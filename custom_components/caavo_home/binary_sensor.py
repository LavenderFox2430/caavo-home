"""Diagnostic readiness remains visible when hardware control is unavailable."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.const import EntityCategory

from .entity import CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([CaavoBackendSensor(entry.runtime_data)])


class CaavoBackendSensor(CaavoEntity, BinarySensorEntity):
    _attr_translation_key = "backend_ready"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:check-network-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "backend_ready")

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def is_on(self):
        state = self.coordinator.data or {}
        return state.get("available") is True and state.get("branchDisabled") is True
