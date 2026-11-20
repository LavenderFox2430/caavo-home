"""Optional temperature telemetry must not break older API v1 devices."""

import unittest
from types import SimpleNamespace

from support import INFO, STATE, component, install_ha_doubles

install_ha_doubles()
sensor_module = component("sensor")


def coordinator(data):
    return SimpleNamespace(
        data=data,
        last_update_success=True,
        client=SimpleNamespace(device_id=INFO["id"], info=INFO),
        async_add_listener=lambda callback: lambda: None,
    )


class TemperatureTests(unittest.TestCase):
    def test_numeric_cpu_average_is_celsius_measurement(self):
        state = {**STATE, "temperatureCelsius": 55.875, "available": False}
        sensor = sensor_module.CaavoTemperatureSensor(coordinator(state))
        self.assertTrue(sensor.available)
        self.assertEqual(sensor.native_value, 55.875)
        self.assertEqual(sensor._attr_device_class, "temperature")
        self.assertEqual(sensor._attr_state_class, "measurement")
        self.assertEqual(sensor._attr_native_unit_of_measurement, "°C")
        self.assertEqual(sensor._attr_unique_id, INFO["id"] + "_cpu_temperature")

    def test_absent_null_or_invalid_value_leaves_old_state_usable(self):
        source = coordinator(dict(STATE))
        sensor = sensor_module.CaavoTemperatureSensor(source)
        power = sensor_module.CaavoPowerSensor(source)
        for state in (
            dict(STATE),
            *(
                {**STATE, "temperatureCelsius": value}
                for value in (
                    None,
                    True,
                    "55.0",
                    float("nan"),
                    float("inf"),
                    -float("inf"),
                    10**1000,
                )
            ),
        ):
            source.data = state
            self.assertFalse(sensor.available)
            self.assertIsNone(sensor.native_value)
            self.assertTrue(power.available)
            self.assertEqual(power.native_value, "on")

    def test_failed_poll_marks_last_temperature_unavailable(self):
        source = coordinator({**STATE, "temperatureCelsius": 56})
        sensor = sensor_module.CaavoTemperatureSensor(source)
        self.assertEqual(sensor.native_value, 56.0)
        source.last_update_success = False
        self.assertFalse(sensor.available)


class TemperatureSetupTests(unittest.IsolatedAsyncioTestCase):
    async def test_sensor_is_registered_without_extra_api_calls(self):
        entities = []
        entry = SimpleNamespace(
            runtime_data=coordinator(dict(STATE)), async_on_unload=lambda callback: None
        )
        await sensor_module.async_setup_entry(None, entry, entities.extend)
        temperatures = [
            entity
            for entity in entities
            if isinstance(entity, sensor_module.CaavoTemperatureSensor)
        ]
        self.assertEqual(len(temperatures), 1)
        self.assertFalse(temperatures[0].available)
