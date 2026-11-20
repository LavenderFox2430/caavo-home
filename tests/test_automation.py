"""Theater discovery, identity, uncertainty, metadata and entity behavior."""

import copy
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from support import CAPABILITIES, INFO, STATE, Reply, Session, component, install_ha_doubles

errors = install_ha_doubles()
api = component("api")
automation = component("automation")
buttons = component("button")
select = component("select")
sensors = component("sensor")
coordinators = component("coordinator")


def library_state():
    return {
        "library": {
            "schema": 1,
            "revision": 2,
            "devices": [
                {
                    "id": "screen",
                    "name": "Screen",
                    "commands": [
                        {"id": "down", "name": "Lower", "kind": "raw", "timings": [10, 20, 30]}
                    ],
                }
            ],
            "macros": [{"id": "movie", "name": "Movie", "steps": []}],
            "activities": [{"id": "watch", "name": "Watch", "start": "movie", "stop": "movie"}],
        },
        "runtime": {
            "variables": {"private": "do not expose"},
            "activity": "",
            "activityState": "assumed",
        },
        "learning": {"active": False},
        "job": None,
        "recentJobs": [],
    }


def receipt(status="queued"):
    return {"requestId": "job-123", "status": status, "nextStep": 0, "stepCount": 2}


class AutomationClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, session):
        client = api.CaavoClient(session, "192.168.1.50", "test-only", device_id=INFO["id"])
        client.capabilities = {**CAPABILITIES, "irAutomation": True, "automationVersion": 1}
        return client

    async def test_large_library_is_summarized_without_ir_payloads(self):
        state = library_state()
        state["library"]["devices"][0]["commands"][0]["padding"] = "x" * 100000
        session = Session([Reply({"ok": True, "result": state})])
        summary = await self.client(session).async_get_automation()
        self.assertEqual(len(summary["buttons"]), 3)
        self.assertNotIn("timings", repr(summary))
        self.assertNotIn("do not expose", repr(summary))
        self.assertNotIn("padding", repr(summary))
        self.assertEqual(session.requests[0]["headers"], {})

    async def test_automation_response_is_still_bounded(self):
        session = Session([Reply(fragments=[b" " * 1048576] * 3)])
        with self.assertRaises(api.CaavoProtocolError):
            await self.client(session).async_get_automation()

    async def test_identity_mismatch_prevents_theater_token_use(self):
        session = Session(info={**INFO, "id": "wrong-unit"})
        with self.assertRaises(api.CaavoIdentityError):
            await self.client(session).async_get_automation()
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(session.requests[0]["headers"], {})

    async def test_lost_run_response_reads_receipt_without_resending(self):
        session = Session(
            [Reply(error=TimeoutError()), Reply({"ok": True, "result": receipt("running")})]
        )
        client = self.client(session)
        with patch.object(api.uuid, "uuid4", return_value=SimpleNamespace(hex="job-123")):
            job = await client.async_run_automation({"kind": "macro", "id": "movie"})
        commands = [row["json"] for row in session.requests if row["method"] == "POST"]
        self.assertEqual([row["action"] for row in commands], ["run", "job"])
        self.assertEqual(commands[0]["args"]["requestId"], commands[1]["args"]["requestId"])
        self.assertEqual(job["status"], "running")

    async def test_unresolved_run_exposes_only_recovery_id(self):
        session = Session([Reply(error=TimeoutError()), Reply(status=409)])
        client = self.client(session)
        with patch.object(api.uuid, "uuid4", return_value=SimpleNamespace(hex="job-123")):
            with self.assertRaises(api.CaavoError) as caught:
                await client.async_run_automation(
                    {"kind": "command", "device": "screen", "command": "down"}
                )
        self.assertTrue(caught.exception.uncertain)
        self.assertIn("job-123", str(caught.exception))
        self.assertEqual(
            sum(
                row["json"].get("action") == "run"
                for row in session.requests
                if row["method"] == "POST"
            ),
            1,
        )

    async def test_conflict_is_not_retried_or_reconciled(self):
        session = Session([Reply(status=409)])
        with self.assertRaises(api.CaavoError):
            await self.client(session).async_run_automation(
                {"kind": "activity.start", "id": "watch"}
            )
        self.assertEqual(sum(row["method"] == "POST" for row in session.requests), 1)

    async def test_failed_receipt_does_not_report_success(self):
        session = Session([Reply({"ok": True, "result": receipt("failed")})])
        with patch.object(api.uuid, "uuid4", return_value=SimpleNamespace(hex="job-123")):
            with self.assertRaises(api.CaavoError):
                await self.client(session).async_run_automation({"kind": "activity.stop"})

    async def test_invalid_requests_do_not_reach_network(self):
        session = Session()
        for request in [
            {"kind": "shell"},
            {"kind": "macro", "id": "bad id"},
            {"kind": "activity.stop", "force": True},
        ]:
            with self.assertRaises(ValueError):
                await self.client(session).async_run_automation(request)
        self.assertEqual(session.requests, [])

    async def test_older_api_keeps_remote_link_and_rejects_theater_locally(self):
        session = Session()
        client = self.client(session)
        client.capabilities = CAPABILITIES
        self.assertEqual(client.configuration_url, "http://192.168.1.50:8090/")
        with self.assertRaises(api.CaavoError):
            await client.async_run_automation({"kind": "activity.stop"})
        self.assertEqual(session.requests, [])

    async def test_partial_automation_failure_keeps_legacy_state_available(self):
        client = self.client(Session([Reply(STATE), Reply(status=502)]))
        client.info = INFO
        coordinator = coordinators.CaavoCoordinator(None, None, client)
        coordinator._update_device = lambda state: None
        state = await coordinator._async_update_data()
        self.assertTrue(state["available"])
        self.assertFalse(state["automationAvailable"])

    async def test_automation_auth_failure_requires_reauthentication(self):
        client = self.client(Session([Reply(STATE), Reply(status=401)]))
        client.info = INFO
        coordinator = coordinators.CaavoCoordinator(None, None, client)
        with self.assertRaises(errors.ConfigEntryAuthFailed):
            await coordinator._async_update_data()


class SummaryTests(unittest.TestCase):
    def test_raw_data_is_omitted_and_ids_do_not_collide(self):
        result = automation.summarize(library_state())
        self.assertEqual(
            result["buttons"][("command", "screen", "down")]["request"],
            {"kind": "command", "device": "screen", "command": "down"},
        )
        self.assertNotEqual(
            automation.entity_key(("command", "a_b", "c")),
            automation.entity_key(("command", "a", "b_c")),
        )

    def test_malformed_and_duplicate_libraries_are_rejected(self):
        state = library_state()
        state["library"]["devices"].append(copy.deepcopy(state["library"]["devices"][0]))
        with self.assertRaises(ValueError):
            automation.summarize(state)
        with self.assertRaises(ValueError):
            automation.summarize({"library": {}, "runtime": {}, "learning": {}})

    def test_recent_receipt_after_backend_restart(self):
        state = library_state()
        state["recentJobs"] = [
            {**receipt("interrupted"), "createdAt": 2},
            {**receipt("completed"), "createdAt": 1},
        ]
        self.assertEqual(automation.summarize(state)["job"]["status"], "interrupted")

    def test_network_mac_must_match_configured_address(self):
        state = {
            "network": {"interfaces": [{"addresses": ["192.168.1.50"], "mac": "00:11:22:AA:BB:CC"}]}
        }
        self.assertEqual(api.network_mac(state, "192.168.1.50"), "00:11:22:aa:bb:cc")
        self.assertIsNone(api.network_mac(state, "192.168.1.51"))
        for mac in [None, "secret", "ff:ff:ff:ff:ff:ff", "00:00:00:00:00:00", "02:00:00:00:00:00"]:
            state["network"]["interfaces"][0]["mac"] = mac
            self.assertIsNone(api.network_mac(state, "192.168.1.50"))
        self.assertIsNone(api.network_mac({}, "192.168.1.50"))


class TheaterEntityTests(unittest.IsolatedAsyncioTestCase):
    def coordinator(self):
        callbacks = []

        def listen(callback):
            callbacks.append(callback)
            return lambda: callbacks.remove(callback)

        client = SimpleNamespace(
            device_id=INFO["id"],
            info=INFO,
            capabilities=CAPABILITIES,
            host="192.168.1.50",
            configuration_url="http://192.168.1.50:8090/automation",
            async_run_automation=AsyncMock(return_value=receipt()),
            async_cancel_automation=AsyncMock(return_value=receipt("cancelled")),
            last_automation_request=None,
        )
        return SimpleNamespace(
            client=client,
            data={
                **STATE,
                "automationAvailable": True,
                "automation": automation.summarize(library_state()),
                "macAddress": "00:11:22:aa:bb:cc",
            },
            last_update_success=True,
            async_request_refresh=AsyncMock(),
            async_add_listener=listen,
            callbacks=callbacks,
        )

    async def test_dynamic_add_remove_rename_preserves_unique_id(self):
        c = self.coordinator()
        unload = []
        entry = SimpleNamespace(runtime_data=c, async_on_unload=unload.append)
        entities = []
        await buttons.async_setup_entry(None, entry, entities.extend)
        button = next(
            e
            for e in entities
            if isinstance(e, buttons.CaavoLibraryButton) and e._key[0] == "command"
        )
        uid = button._attr_unique_id
        await button.async_press()
        c.client.async_run_automation.assert_awaited_once_with(
            {"kind": "command", "device": "screen", "command": "down"}
        )
        c.data["automation"]["buttons"][button._key]["name"] = "Renamed custom button"
        self.assertEqual(button.name, "Renamed custom button")
        self.assertEqual(button._attr_unique_id, uid)
        count = len(entities)
        c.data["automation"]["buttons"][("macro", "new")] = {
            "name": "New macro",
            "request": {"kind": "macro", "id": "new"},
        }
        c.callbacks[0]()
        c.callbacks[0]()
        self.assertEqual(len(entities), count + 1)
        del c.data["automation"]["buttons"][button._key]
        self.assertFalse(button.available)
        with self.assertRaises(errors.HomeAssistantError):
            await button.async_press()
        unload[0]()
        self.assertEqual(c.callbacks, [])

    async def test_busy_and_failed_poll_disable_custom_commands(self):
        c = self.coordinator()
        entity = buttons.CaavoLibraryButton(c, ("macro", "movie"))
        c.data["automation"]["busy"] = True
        self.assertFalse(entity.available)
        c.data["automation"]["busy"] = False
        c.data["automationAvailable"] = False
        with self.assertRaises(errors.HomeAssistantError):
            await entity.async_press()
        c.client.async_run_automation.assert_not_awaited()

    async def test_activity_options_and_stop_are_explicit(self):
        c = self.coordinator()
        c.data["automation"]["activities"]["second"] = "Watch"
        entity = select.CaavoActivitySelect(c)
        self.assertEqual(entity.options, ["Off", "Watch (watch)", "Watch (second)"])
        self.assertEqual(entity.current_option, "Off")
        await entity.async_select_option("Watch (watch)")
        c.client.async_run_automation.assert_awaited_with({"kind": "activity.start", "id": "watch"})
        await entity.async_select_option("Off")
        c.client.async_run_automation.assert_awaited_with({"kind": "activity.stop"})
        c.data["automation"]["activityState"] = "unknown"
        self.assertIsNone(entity.current_option)

    async def test_cancel_uses_running_job_id(self):
        c = self.coordinator()
        entity = buttons.CaavoCancelJob(c)
        with self.assertRaises(errors.HomeAssistantError):
            await entity.async_press()
        c.data["automation"].update(busy=True, job=receipt("running"))
        await entity.async_press()
        c.client.async_cancel_automation.assert_awaited_once_with("job-123")

    async def test_device_link_network_sensors_and_job_summary(self):
        c = self.coordinator()
        info = coordinators.device_info(c)
        self.assertEqual(info["configuration_url"], c.client.configuration_url)
        self.assertEqual(info["connections"], {("mac", "00:11:22:aa:bb:cc")})
        self.assertEqual(sensors.CaavoAddressSensor(c, "ip_address").native_value, "192.168.1.50")
        self.assertEqual(
            sensors.CaavoAddressSensor(c, "mac_address").native_value, "00:11:22:aa:bb:cc"
        )
        c.data["automation"]["job"] = receipt("running")
        job = sensors.CaavoJobSensor(c)
        self.assertEqual(job.native_value, "running")
        self.assertEqual(job.extra_state_attributes["request_id"], "job-123")
        self.assertNotIn("library", job.extra_state_attributes)
