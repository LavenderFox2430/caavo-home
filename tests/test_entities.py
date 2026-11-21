"""Availability, ambiguous source names, and explicit command sequence semantics."""

import unittest
from types import SimpleNamespace

from support import INFO, STATE, component, install_ha_doubles

errors = install_ha_doubles()
coordinator_module = component("coordinator")
entity_module = component("entity")
remote_module = component("remote")
sensor_module = component("sensor")
api = component("api")


class EntityTests(unittest.TestCase):
    def test_duplicate_input_names_have_distinct_options(self):
        options = coordinator_module.input_options(STATE)
        self.assertEqual(len(options), 4)
        self.assertEqual(options["HDMI 1 · Player"], 1)
        self.assertEqual(options["HDMI 2 · Player"], 2)
        self.assertEqual(coordinator_module.current_source(STATE), "HDMI 2 · Player")

    def test_availability_requires_ready_backend_and_disabled_branch(self):
        coordinator = SimpleNamespace(
            data=dict(STATE),
            last_update_success=True,
            client=SimpleNamespace(device_id=INFO["id"], info=INFO),
        )
        entity = entity_module.CaavoEntity(coordinator, "test")
        self.assertTrue(entity.available)
        coordinator.data["available"] = False
        self.assertFalse(entity.available)
        coordinator.data["available"] = True
        coordinator.data["branchDisabled"] = False
        self.assertFalse(entity.available)
        coordinator.data["branchDisabled"] = True
        coordinator.last_update_success = False
        self.assertFalse(entity.available)
        self.assertEqual(entity._attr_unique_id, INFO["id"] + "_test")

    def test_active_signal_follows_selected_port_without_changing_per_port_entity(self):
        coordinator = SimpleNamespace(
            data={
                **STATE,
                "inputs": [
                    {"port": 1, "signal": "connected"},
                    {"port": 2, "signal": "standby"},
                ],
            },
            last_update_success=True,
            client=SimpleNamespace(device_id=INFO["id"], info=INFO),
        )
        active = sensor_module.CaavoSignalSensor(coordinator)
        first = sensor_module.CaavoSignalSensor(coordinator, 1)
        self.assertEqual(first._attr_unique_id, INFO["id"] + "_input_1_signal")
        self.assertFalse(first._attr_entity_registry_enabled_default)
        self.assertEqual(first.native_value, "connected")
        self.assertEqual(active.native_value, "standby")
        coordinator.data["activeInput"] = 1
        self.assertEqual(active.native_value, "connected")
        for missing in (4, None):
            coordinator.data["activeInput"] = missing
            self.assertEqual(active.native_value, "unknown")
        coordinator.last_update_success = False
        self.assertFalse(active.available)

    def test_network_connection_uses_interface_for_configured_ipv4(self):
        eth = {"interface": "eth0", "addresses": ["192.168.1.40"], "mac": None}
        wifi = {"interface": "wlan0", "addresses": ["192.168.1.41"], "mac": None}
        network = {"interfaces": [eth, wifi, {"addresses": "192.168.1.40"}]}
        coordinator = SimpleNamespace(
            data={**STATE, "network": network, "available": False},
            last_update_success=True,
            client=SimpleNamespace(device_id=INFO["id"], info=INFO, host="192.168.1.40"),
        )
        connection = sensor_module.CaavoNetworkConnectionSensor(coordinator)
        self.assertTrue(connection.available)
        self.assertEqual(connection.native_value, "ethernet")
        coordinator.client.host = "192.168.1.41"
        self.assertEqual(connection.native_value, "wifi")
        wifi["interface"] = "br0"
        self.assertEqual(connection.native_value, "other")
        network["interfaces"].append({"interface": "eth1", "addresses": ["192.168.1.41"]})
        self.assertFalse(connection.available)
        coordinator.data.pop("network")
        self.assertFalse(connection.available)
        coordinator.data["network"] = network
        coordinator.client.host = "192.168.1.40"
        coordinator.last_update_success = False
        self.assertFalse(connection.available)


class SequenceTests(unittest.IsolatedAsyncioTestCase):
    def remote(self, failure_at=None):
        sent = []

        async def key(command):
            sent.append(command)
            if len(sent) == failure_at:
                raise api.CaavoConnectionError("uncertain", uncertain=True)
            return {}

        async def refresh():
            pass

        coordinator = SimpleNamespace(
            data=dict(STATE),
            last_update_success=True,
            client=SimpleNamespace(
                device_id=INFO["id"],
                info=INFO,
                capabilities={"keys": ["up", "down"]},
                async_send_key=key,
            ),
            async_request_refresh=refresh,
        )
        return remote_module.CaavoRemote(coordinator), sent

    async def test_failed_sequence_stops_without_retries(self):
        remote, sent = self.remote(failure_at=2)
        with self.assertRaises(errors.HomeAssistantError):
            await remote.async_send_command(["up", "down"], num_repeats=3, delay_secs=0)
        self.assertEqual(sent, ["up", "down"])

    async def test_explicit_repetitions_are_in_order(self):
        remote, sent = self.remote()
        await remote.async_send_command(["up", "down"], num_repeats=2, delay_secs=0)
        self.assertEqual(sent, ["up", "down", "up", "down"])

    async def test_unsupported_hold_is_rejected_before_any_action(self):
        remote, sent = self.remote()
        with self.assertRaises(errors.HomeAssistantError):
            await remote.async_send_command(["up"], hold_secs=1)
        self.assertEqual(sent, [])
