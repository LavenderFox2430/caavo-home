"""Explicit Caavo standby/wake/restart actions and key toggles."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory

from .entity import CaavoEntity

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
