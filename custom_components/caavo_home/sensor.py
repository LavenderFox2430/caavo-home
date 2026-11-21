"""Reported power, HDMI signal, network, and temperature diagnostics."""

from math import isfinite

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import callback

from .api import network_connection
from .const import POWER_STATES, SIGNAL_STATES
from .entity import CaavoAutomationEntity, CaavoEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities(
        [
            CaavoPowerSensor(coordinator),
            CaavoTemperatureSensor(coordinator),
            CaavoAddressSensor(coordinator, "ip_address"),
            CaavoAddressSensor(coordinator, "mac_address"),
            CaavoNetworkConnectionSensor(coordinator),
            CaavoSignalSensor(coordinator),
            *(CaavoSignalSensor(coordinator, port) for port in range(1, 5)),
        ]
    )
    added = False

    @callback
    def discover():
        nonlocal added
        if not added and (coordinator.data or {}).get("automationAvailable"):
            added = True
            async_add_entities([CaavoJobSensor(coordinator)])

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class CaavoAddressSensor(CaavoEntity, SensorEntity):
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:network-outline"

    def __init__(self, coordinator, kind):
        super().__init__(coordinator, kind)
        self._kind = kind
        self._attr_translation_key = kind

    @property
    def available(self):
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def native_value(self):
        if self._kind == "ip_address":
            return self.coordinator.client.host
        return (self.coordinator.data or {}).get("macAddress")


class CaavoNetworkConnectionSensor(CaavoEntity, SensorEntity):
    _attr_translation_key = "network_connection"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = ["ethernet", "wifi", "other"]
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:network-outline"

    def __init__(self, coordinator):
        super().__init__(coordinator, "network_connection")

    @property
    def available(self):
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def native_value(self):
        return network_connection(self.coordinator.data or {}, self.coordinator.client.host)


class CaavoJobSensor(CaavoAutomationEntity, SensorEntity):
    _attr_translation_key = "automation_job"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:progress-clock"

    def __init__(self, coordinator):
        super().__init__(coordinator, "automation_job")

    @property
    def native_value(self):
        return (self.automation.get("job") or {}).get("status", "idle")

    @property
    def extra_state_attributes(self):
        job = self.automation.get("job") or {}
        return {
            "request_id": job.get("requestId"),
            "completed_steps": job.get("nextStep"),
            "total_steps": job.get("stepCount"),
            "library_revision": self.automation.get("revision"),
            "activity_state": self.automation.get("activityState", "unknown"),
            "last_submitted_request": self.coordinator.client.last_automation_request,
        }


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
    _attr_icon = "mdi:video-input-hdmi"

    def __init__(self, coordinator, port=None):
        key = "active_input_signal" if port is None else f"input_{port}_signal"
        super().__init__(coordinator, key)
        self._port = port
        self._attr_translation_key = "active_input_signal"
        if port is not None:
            self._attr_entity_registry_enabled_default = False
            self._attr_translation_key = "input_signal"
            self._attr_translation_placeholders = {"port": str(port)}

    @property
    def native_value(self):
        state = self.coordinator.data or {}
        port = self._port if self._port is not None else state.get("activeInput")
        for item in state.get("inputs", []):
            if item["port"] == port:
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
