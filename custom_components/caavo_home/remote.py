"""Explicit key clicks through the authenticated local API."""

import asyncio

from homeassistant.components.remote import RemoteEntity
from homeassistant.exceptions import HomeAssistantError

from .const import KEYS
from .entity import CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CaavoRemote(entry.runtime_data)])


class CaavoRemote(CaavoEntity, RemoteEntity):
    _attr_translation_key = "remote"

    def __init__(self, coordinator):
        super().__init__(coordinator, "remote")

    @property
    def is_on(self):
        return {"on": True, "off": False}.get((self.coordinator.data or {}).get("power"))

    @property
    def extra_state_attributes(self):
        supported = self.coordinator.client.capabilities.get("keys", [])
        return {"supported_commands": sorted(KEYS.intersection(supported))}

    async def async_turn_on(self, **kwargs):
        await self.async_command(self.coordinator.client.async_power, "on")

    async def async_turn_off(self, **kwargs):
        await self.async_command(self.coordinator.client.async_power, "off")

    async def async_send_command(self, command, **kwargs):
        commands = [command] if isinstance(command, str) else list(command)
        repeats = kwargs.get("num_repeats", 1)
        delay = kwargs.get("delay_secs", 0.1)
        if kwargs.get("hold_secs", 0):
            raise HomeAssistantError("Caavo Home supports key clicks, not held-key requests")
        if type(repeats) is not int or not 1 <= repeats <= 20:
            raise HomeAssistantError("Use between 1 and 20 explicit repetitions")
        if not isinstance(delay, (int, float)) or not 0 <= delay <= 60:
            raise HomeAssistantError("Delay must be between 0 and 60 seconds")
        supported = set(self.coordinator.client.capabilities.get("keys", KEYS))
        if (
            not commands
            or len(commands) > 100
            or any(
                not isinstance(key, str) or key not in KEYS or key not in supported
                for key in commands
            )
        ):
            raise HomeAssistantError("Use the command names listed in supported_commands")
        # Repetitions are explicit user instructions, never recovery retries.
        # Any failed/uncertain command stops the rest of the sequence immediately.
        sequence = commands * repeats
        for index, key in enumerate(sequence):
            if index:
                await asyncio.sleep(delay)
            await self.async_command(self.coordinator.client.async_send_key, key, refresh=False)
        await self.coordinator.async_request_refresh()
