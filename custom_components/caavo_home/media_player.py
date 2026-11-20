"""A switch/standby media entity; no invented playback or volume-level state."""

from homeassistant.components.media_player import (
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.exceptions import HomeAssistantError

from .coordinator import current_source, input_options
from .entity import CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CaavoMediaPlayer(entry.runtime_data)])


class CaavoMediaPlayer(CaavoEntity, MediaPlayerEntity):
    _attr_name = None
    _attr_icon = "mdi:video-input-hdmi"
    _attr_supported_features = (
        MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_STEP
    )

    def __init__(self, coordinator):
        super().__init__(coordinator, "media_player")

    @property
    def state(self):
        return {"on": MediaPlayerState.ON, "off": MediaPlayerState.OFF}.get(
            (self.coordinator.data or {}).get("power")
        )

    @property
    def source(self):
        return current_source(self.coordinator.data)

    @property
    def source_list(self):
        return list(input_options(self.coordinator.data))

    async def async_select_source(self, source):
        port = input_options(self.coordinator.data).get(source)
        if port is None:
            raise HomeAssistantError("This input name changed; choose a current source")
        await self.async_command(self.coordinator.client.async_select_input, port)

    async def async_turn_on(self, **kwargs):
        await self.async_command(self.coordinator.client.async_power, "on")

    async def async_turn_off(self, **kwargs):
        await self.async_command(self.coordinator.client.async_power, "off")

    async def async_volume_up(self):
        await self.async_command(self.coordinator.client.async_send_key, "volume_up")

    async def async_volume_down(self):
        await self.async_command(self.coordinator.client.async_send_key, "volume_down")
