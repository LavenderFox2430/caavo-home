"""HDMI input selection."""

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError

from .coordinator import current_source, input_options
from .entity import CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CaavoInputSelect(entry.runtime_data)])


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
