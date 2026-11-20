"""Explicit Caavo standby/wake/restart actions and key toggles."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_registry import async_get

from .automation import entity_key
from .entity import CaavoAutomationEntity, CaavoEntity

BUTTONS = (
    ("wake", "power", "on", "mdi:power", None),
    ("standby", "power", "off", "mdi:power-standby", None),
    ("restart", "power", "restart", "mdi:restart", EntityCategory.CONFIG),
    ("launcher", "key", "caavo", "mdi:home", None),
    ("play_pause", "key", "play_pause", "mdi:play-pause", None),
    ("mute", "key", "mute", "mdi:volume-mute", None),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    keys = coordinator.client.capabilities.get("keys", [])
    async_add_entities(
        [
            CaavoButton(coordinator, *button)
            for button in BUTTONS
            if button[1] != "key" or button[2] in keys
        ]
    )
    known = set()
    controls_added = False

    @callback
    def discover():
        nonlocal controls_added
        if not (coordinator.data or {}).get("automationAvailable"):
            return
        entities = []
        if not controls_added:
            entities += [CaavoStopActivity(coordinator), CaavoCancelJob(coordinator)]
            controls_added = True
        for key in coordinator.data["automation"]["buttons"]:
            if key not in known:
                entities.append(CaavoLibraryButton(coordinator, key))
                known.add(key)
        if entities:
            async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class CaavoButton(CaavoEntity, ButtonEntity):
    def __init__(self, coordinator, key, kind, command, icon, category):
        super().__init__(coordinator, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._attr_entity_category = category
        self._kind = kind
        self._command = command

    async def async_press(self):
        operation = (
            self.coordinator.client.async_power
            if self._kind == "power"
            else self.coordinator.client.async_send_key
        )
        await self.async_command(operation, self._command)


class CaavoLibraryButton(CaavoAutomationEntity, ButtonEntity):
    """Stable IDs preserve dashboard references across renames and reloads."""

    def __init__(self, coordinator, key):
        super().__init__(coordinator, entity_key(key))
        self._key = key
        self._last_name = self.name
        self._attr_icon = {
            "command": "mdi:remote",
            "macro": "mdi:format-list-numbered",
            "activity.start": "mdi:movie-open",
        }[key[0]]

    @property
    def row(self):
        return self.automation.get("buttons", {}).get(self._key)

    @property
    def name(self):
        return (
            self.row["name"] if self.row else getattr(self, "_last_name", "Removed theater control")
        )

    @property
    def available(self):
        return (
            super().available
            and self.row is not None
            and not self.automation.get("busy")
            and not self.automation.get("learning")
        )

    @callback
    def _handle_coordinator_update(self):
        if self.row and self.name != self._last_name:
            self._last_name = self.name
            registry = async_get(self.hass)
            if registry.async_get(self.entity_id):
                # Update the integration's name, retaining any user's name override.
                registry.async_update_entity(self.entity_id, original_name=self.name)
        super()._handle_coordinator_update()

    async def async_press(self):
        if not self.available:
            raise HomeAssistantError("This theater control is unavailable or Caavo is busy")
        await self.async_command(self.coordinator.client.async_run_automation, self.row["request"])


class CaavoStopActivity(CaavoAutomationEntity, ButtonEntity):
    _attr_translation_key = "stop_activity"
    _attr_icon = "mdi:stop-circle-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "automation_stop_activity")

    async def async_press(self):
        if not self.can_run:
            raise HomeAssistantError("Wait for or cancel the current theater job")
        await self.async_command(
            self.coordinator.client.async_run_automation, {"kind": "activity.stop"}
        )


class CaavoCancelJob(CaavoAutomationEntity, ButtonEntity):
    _attr_translation_key = "cancel_automation"
    _attr_icon = "mdi:cancel"

    def __init__(self, coordinator):
        super().__init__(coordinator, "automation_cancel_job")

    async def async_press(self):
        job = self.automation.get("job")
        if not self.available or not self.automation.get("busy") or not job:
            raise HomeAssistantError("There is no active theater job to cancel")
        await self.async_command(self.coordinator.client.async_cancel_automation, job["requestId"])
