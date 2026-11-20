"""Dependent choices and explicit dispatch, including stale-library boundaries."""

import asyncio
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import test_automation
from support import component, install_ha_doubles
from test_automation import library_state

errors = install_ha_doubles()
automation = component("automation")
selection = component("selection")
select = component("select")
button = component("button")
coordinators = component("coordinator")


def populated_state():
    state = library_state()
    state["library"]["devices"].append(
        {"id": "second", "name": "Other screen", "commands": [{"id": "down", "name": "Lower"}]}
    )
    return automation.summarize(state)


class ChoiceTests(unittest.TestCase):
    def test_duplicate_names_and_literal_suffixes_are_unambiguous(self):
        options = selection.named_options({"a": "Screen", "b": "Screen", "c": "Screen (a)"})
        self.assertEqual(len(options), 3)
        self.assertEqual(set(options.values()), {"a", "b", "c"})
        self.assertEqual(options["Screen (a)"], "a")
        self.assertEqual(options["Screen (a) (c)"], "c")

    def test_device_change_clears_function_even_with_same_command_id(self):
        choices = selection.AutomationSelection()
        state = populated_state()
        choices.select(state, "ir_device", "Screen")
        choices.select(state, "ir_function", "Lower")
        choices.select(state, "ir_device", "Other screen")
        self.assertIsNone(choices.ir_function)
        self.assertIsNone(choices.request(state, "ir"))
        choices.select(state, "ir_function", "Lower")
        self.assertEqual(choices.request(state, "ir")["device"], "second")

    def test_same_device_keeps_choice_and_rename_tracks_id(self):
        choices = selection.AutomationSelection("screen", "down", "movie")
        state = populated_state()
        choices.select(state, "ir_device", "Screen")
        self.assertEqual(choices.ir_function, "down")
        state["devices"]["screen"]["name"] = "Renamed display"
        state["devices"]["screen"]["commands"]["down"] = "Close"
        state["macros"]["movie"] = "Cinema"
        choices.reconcile(state)
        self.assertEqual(choices.current_option(state, "ir_device"), "Renamed display")
        self.assertEqual(choices.current_option(state, "ir_function"), "Close")
        self.assertEqual(choices.current_option(state, "macro"), "Cinema")
        self.assertEqual(choices.request(state, "macro"), {"kind": "macro", "id": "movie"})

    def test_deleted_items_clear_without_selecting_replacements(self):
        choices = selection.AutomationSelection("screen", "down", "movie")
        state = populated_state()
        del state["devices"]["screen"]["commands"]["down"]
        del state["macros"]["movie"]
        choices.reconcile(state)
        self.assertEqual(choices.ir_device, "screen")
        self.assertIsNone(choices.ir_function)
        self.assertIsNone(choices.macro)
        del state["devices"]["screen"]
        choices.reconcile(state)
        self.assertIsNone(choices.ir_device)

    def test_invalid_old_label_rejected_and_empty_library_is_valid(self):
        choices = selection.AutomationSelection()
        with self.assertRaises(ValueError):
            choices.select(populated_state(), "ir_device", "Deleted name")
        for kind in ("ir_device", "ir_function", "macro"):
            self.assertEqual(choices.options({}, kind), {})
            self.assertIsNone(choices.current_option({}, kind))
        self.assertIsNone(choices.request({}, "ir"))

    def test_choices_are_isolated_and_reset_for_a_new_entry_instance(self):
        first = selection.AutomationSelection("screen", "down", "movie")
        second = selection.AutomationSelection()
        self.assertIsNone(second.ir_device)
        self.assertIsNone(second.macro)
        self.assertEqual(first.ir_device, "screen")


class SelectorEntityTests(unittest.IsolatedAsyncioTestCase):
    def coordinator(self):
        c = test_automation.TheaterEntityTests().coordinator()
        c.data["automation"] = populated_state()
        c.selection = selection.AutomationSelection()
        c.async_update_listeners = Mock(
            side_effect=lambda: [callback() for callback in c.callbacks]
        )
        return c

    async def choose_ir(self, c):
        await select.CaavoCommandSelect(c, "ir_device", "mdi:television").async_select_option(
            "Screen"
        )
        await select.CaavoCommandSelect(c, "ir_function", "mdi:remote").async_select_option("Lower")

    async def test_choosing_only_updates_local_state_and_dependent_availability(self):
        c = self.coordinator()
        function = select.CaavoCommandSelect(c, "ir_function", "mdi:remote")
        send = button.CaavoSelectedButton(c, "ir", "ir_send", "mdi:remote")
        self.assertFalse(function.available)
        self.assertFalse(send.available)
        await self.choose_ir(c)
        self.assertTrue(function.available)
        self.assertTrue(send.available)
        self.assertEqual(c.async_update_listeners.call_count, 2)
        c.async_request_refresh.assert_not_awaited()
        c.client.async_run_automation.assert_not_awaited()

    async def test_send_and_run_submit_exactly_selected_ids(self):
        c = self.coordinator()
        await self.choose_ir(c)
        await button.CaavoSelectedButton(c, "ir", "ir_send", "mdi:remote").async_press()
        c.client.async_run_automation.assert_awaited_once_with(
            {"kind": "command", "device": "screen", "command": "down"}
        )
        c.client.async_run_automation.reset_mock()
        await select.CaavoCommandSelect(c, "macro", "mdi:format-list-numbered").async_select_option(
            "Movie"
        )
        c.client.async_run_automation.assert_not_awaited()
        await button.CaavoSelectedButton(c, "macro", "run_macro", "mdi:playlist-play").async_press()
        c.client.async_run_automation.assert_awaited_once_with({"kind": "macro", "id": "movie"})

    async def test_unselected_stale_busy_learning_and_offline_actions_are_rejected(self):
        c = self.coordinator()
        send = button.CaavoSelectedButton(c, "ir", "ir_send", "mdi:remote")
        with self.assertRaises(errors.HomeAssistantError):
            await send.async_press()
        await self.choose_ir(c)
        for key in ("busy", "learning"):
            c.data["automation"][key] = True
            self.assertFalse(send.available)
            with self.assertRaises(errors.HomeAssistantError):
                await send.async_press()
            c.data["automation"][key] = False
        c.data["automationAvailable"] = False
        with self.assertRaises(errors.HomeAssistantError):
            await send.async_press()
        c.data["automationAvailable"] = True
        c.last_update_success = False
        self.assertFalse(send.available)
        c.last_update_success = True
        del c.data["automation"]["buttons"][("command", "screen", "down")]
        with self.assertRaises(errors.HomeAssistantError):
            await send.async_press()
        c.client.async_run_automation.assert_not_awaited()

    async def test_in_flight_send_does_not_change_when_next_choice_changes(self):
        c = self.coordinator()
        await self.choose_ir(c)
        started, release = asyncio.Event(), asyncio.Event()
        sent = []

        async def execute(request):
            started.set()
            await release.wait()
            sent.append(request)

        c.client.async_run_automation = execute
        pending = asyncio.create_task(
            button.CaavoSelectedButton(c, "ir", "ir_send", "mdi:remote").async_press()
        )
        await started.wait()
        await select.CaavoCommandSelect(c, "ir_device", "mdi:television").async_select_option(
            "Other screen"
        )
        release.set()
        await pending
        self.assertEqual(sent, [{"kind": "command", "device": "screen", "command": "down"}])
        self.assertIsNone(c.selection.ir_function)

    async def test_discovery_once_after_late_capability_and_listener_cleanup(self):
        c = self.coordinator()
        c.data["automationAvailable"] = False
        unload, entities = [], []
        entry = SimpleNamespace(runtime_data=c, async_on_unload=unload.append)
        await select.async_setup_entry(None, entry, entities.extend)
        self.assertEqual(len(entities), 1)
        c.data["automationAvailable"] = True
        c.async_update_listeners()
        c.async_update_listeners()
        self.assertEqual(len(entities), 5)
        self.assertEqual(len({e._attr_unique_id for e in entities}), 5)
        unload[0]()
        self.assertEqual(c.callbacks, [])

    async def test_successful_poll_reconciles_removed_choices(self):
        c = self.coordinator()
        client = c.client
        client.async_get_state = AsyncMock(return_value={"available": True})
        client.supports_automation = True
        client.async_get_automation = AsyncMock(return_value=automation.summarize(library_state()))
        actual = coordinators.CaavoCoordinator(None, None, client)
        actual._update_device = lambda state: None
        actual.selection = selection.AutomationSelection("second", "down", "deleted")
        await actual._async_update_data()
        self.assertEqual(actual.selection, selection.AutomationSelection())

    async def test_failed_library_poll_retains_choices_but_disables_actions(self):
        c = self.coordinator()
        client = c.client
        client.async_get_state = AsyncMock(return_value={"available": True})
        client.supports_automation = True
        client.async_get_automation = AsyncMock(side_effect=component("api").CaavoError("offline"))
        actual = coordinators.CaavoCoordinator(None, None, client)
        actual._update_device = lambda state: None
        actual.data = copy.deepcopy(c.data)
        actual.selection = selection.AutomationSelection("screen", "down", "movie")
        actual.data = await actual._async_update_data()
        self.assertEqual(actual.selection.ir_function, "down")
        self.assertFalse(
            button.CaavoSelectedButton(actual, "ir", "ir_send", "mdi:remote").available
        )

    async def test_restart_category_and_optional_shortcuts(self):
        restart = next(row for row in button.BUTTONS if row[0] == "restart")
        self.assertEqual(restart[-1], "diagnostic")
        shortcut = button.CaavoLibraryButton(self.coordinator(), ("macro", "movie"))
        self.assertFalse(shortcut._attr_entity_registry_enabled_default)


if __name__ == "__main__":
    unittest.main()
