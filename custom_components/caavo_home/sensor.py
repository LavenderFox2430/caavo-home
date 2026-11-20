"""Reported power, HDMI signal, and optional CPU temperature diagnostics."""

from math import isfinite

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature

from .const import POWER_STATES, SIGNAL_STATES
from .entity import CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            CaavoPowerSensor(coordinator),
            CaavoTemperatureSensor(coordinator),
            *(CaavoSignalSensor(coordinator, port) for port in range(1, 5)),
        ]
    )


class CaavoPowerSensor(CaavoEntity, SensorEntity):
    _attr_translation_key = "power_state"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(POWER_STATES)
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "power_state")

    @property
    def available(self):
        return self.coordinator.last_update_success

    @property
    def native_value(self):
        return (self.coordinator.data or {}).get("power", "unknown")


class CaavoSignalSensor(CaavoEntity, SensorEntity):
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(SIGNAL_STATES)
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator, port):
        super().__init__(coordinator, f"input_{port}_signal")
        self._port = port
        self._attr_translation_key = "input_signal"
        self._attr_translation_placeholders = {"port": str(port)}

    @property
    def native_value(self):
        for item in (self.coordinator.data or {}).get("inputs", []):
            if item["port"] == self._port:
                return item["signal"]
        return "unknown"


class CaavoTemperatureSensor(CaavoEntity, SensorEntity):
    """Read the CPU0–CPU3 average when the optional API telemetry is present."""

    _attr_translation_key = "cpu_temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
    _attr_suggested_display_precision = 1
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator):
        super().__init__(coordinator, "cpu_temperature")

    @property
    def available(self):
        # This read-only measurement can remain useful while HDMI is unready.
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def native_value(self):
        value = (self.coordinator.data or {}).get("temperatureCelsius")
        if type(value) not in (int, float):
            return None
        try:
            return float(value) if isfinite(value) else None
        except OverflowError:
            return None
