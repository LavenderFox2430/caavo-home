"""HDMI/activity control and local IR/macro choices."""

from homeassistant.components.select import SelectEntity
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError

from .automation import activity_options
from .coordinator import current_source, input_options
from .entity import CaavoAutomationEntity, CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CaavoInputSelect(entry.runtime_data)])
    added = False

    @callback
    def discover():
        nonlocal added
        if not added and (entry.runtime_data.data or {}).get("automationAvailable"):
            added = True
            async_add_entities(
                [
                    CaavoActivitySelect(entry.runtime_data),
                    CaavoCommandSelect(entry.runtime_data, "ir_device", "mdi:television"),
                    CaavoCommandSelect(entry.runtime_data, "ir_function", "mdi:remote"),
                    CaavoCommandSelect(entry.runtime_data, "macro", "mdi:format-list-numbered"),
                ]
            )

    discover()
    entry.async_on_unload(entry.runtime_data.async_add_listener(discover))


class CaavoInputSelect(CaavoEntity, SelectEntity):
    _attr_translation_key = "input"
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator):
        super().__init__(coordinator, "input")

    @property
    def options(self):
        return list(input_options(self.coordinator.data))

    @property
    def current_option(self):
        return current_source(self.coordinator.data)

    async def async_select_option(self, option):
        port = input_options(self.coordinator.data).get(option)
        if port is None:
            raise HomeAssistantError("This input name changed; choose one of the current options")
        await self.async_command(self.coordinator.client.async_select_input, port)


class CaavoActivitySelect(CaavoAutomationEntity, SelectEntity):
    _attr_translation_key = "activity"
    _attr_icon = "mdi:movie-open"
    _attr_assumed_state = True

    def __init__(self, coordinator):
        super().__init__(coordinator, "automation_activity")

    @property
    def options(self):
        return list(activity_options(self.automation))

    @property
    def current_option(self):
        if self.automation.get("activityState") != "assumed":
            return None
        active = self.automation.get("activity")
        return next(
            (label for label, key in activity_options(self.automation).items() if key == active),
            None,
        )

    async def async_select_option(self, option):
        options = activity_options(self.automation)
        if not self.can_run or option not in options:
            raise HomeAssistantError(
                "Activity unavailable; refresh Theater or wait for the current job"
            )
        key = options[option]
        request = {"kind": "activity.start", "id": key} if key else {"kind": "activity.stop"}
        await self.async_command(self.coordinator.client.async_run_automation, request)


class CaavoCommandSelect(CaavoAutomationEntity, SelectEntity):
    """Choose locally; only the separate send/run button executes anything."""

    def __init__(self, coordinator, kind, icon):
        super().__init__(coordinator, f"automation_select_{kind}")
        self._kind = kind
        self._attr_translation_key = kind
        self._attr_icon = icon

    @property
    def options(self):
        return list(self.coordinator.selection.options(self.automation, self._kind))

    @property
    def current_option(self):
        return self.coordinator.selection.current_option(self.automation, self._kind)

    @property
    def available(self):
        return super().available and bool(self.options)

    async def async_select_option(self, option):
        if not self.available:
            raise HomeAssistantError("No current choices are available")
        try:
            self.coordinator.selection.select(self.automation, self._kind, option)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
        # Notify the dependent selector and button, without polling or executing.
        self.coordinator.async_update_listeners()
