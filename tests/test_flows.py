"""Flow safety using small HA API doubles, not a running Home Assistant instance."""

import sys
import unittest
from ipaddress import ip_address
from types import SimpleNamespace

import probatio
from support import CAPABILITIES, INFO, FlowAbort, Reply, Session, component, install_ha_doubles

install_ha_doubles()
flow_module = component("config_flow")


class FlowTests(unittest.IsolatedAsyncioTestCase):
    def flow(self, session):
        flow = flow_module.CaavoConfigFlow()
        flow.hass = SimpleNamespace(session=session)
        flow.context = {}
        return flow

    def discovery(self, identifier=INFO["id"], host="192.168.1.50"):
        return SimpleNamespace(
            host=host,
            port=8090,
            properties={"id": identifier, "api": "1", "path": "/api/v1", "auth": "bearer"},
        )

    async def test_forms_use_real_probatio_with_no_legacy_zeroconf_export(self):
        self.assertFalse(
            hasattr(sys.modules["homeassistant.components.zeroconf"], "ZeroconfServiceInfo")
        )
        flow = self.flow(Session())
        flow.entry = SimpleNamespace(
            unique_id=INFO["id"],
            data={"host": "192.168.1.50", "port": 8090, "token": "saved-secret"},
        )
        user = await flow.async_step_user()
        discovery = await flow.async_step_zeroconf(self.discovery())
        reconfigure = await flow.async_step_reconfigure()
        reauth = await flow.async_step_reauth_confirm()
        for form in (user, discovery, reconfigure, reauth):
            self.assertIsInstance(form["data_schema"], probatio.Schema)
        self.assertEqual(
            user["data_schema"]({"host": "192.168.1.50", "token": "key"}),
            {"host": "192.168.1.50", "token": "key"},
        )
        for form in (discovery, reauth):
            self.assertEqual(form["data_schema"]({"token": "key"}), {"token": "key"})
            with self.assertRaises(probatio.Invalid):
                form["data_schema"]({})
        self.assertEqual(reconfigure["data_schema"]({}), {"host": "192.168.1.50"})

    async def test_user_flow_stable_id_and_data(self):
        session = Session([Reply(CAPABILITIES)])
        flow = self.flow(session)
        result = await flow.async_step_user({"host": "192.168.1.50", "token": "example-token"})
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(flow.unique_id, INFO["id"])
        self.assertEqual(
            result["data"], {"host": "192.168.1.50", "port": 8090, "token": "example-token"}
        )
        self.assertEqual(session.requests[0]["headers"], {})

    async def test_invalid_token_does_not_create_entry(self):
        result = await self.flow(Session([Reply(status=401)])).async_step_user(
            {"host": "192.168.1.50", "token": "bad"}
        )
        self.assertEqual(result["errors"], {"base": "invalid_auth"})

    async def test_discovery_needs_token_and_never_sends_one_first(self):
        session = Session()
        flow = self.flow(session)
        result = await flow.async_step_zeroconf(self.discovery())
        self.assertEqual(result["step_id"], "discovery_confirm")
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(session.requests[0]["headers"], {})
        session.replies.append(Reply(CAPABILITIES))
        result = await flow.async_step_discovery_confirm({"token": "example-token"})
        self.assertEqual(result["type"], "create_entry")

    async def test_discovery_mismatch_does_not_update_existing_entry(self):
        session = Session(info={**INFO, "id": "other-unit"})
        flow = self.flow(session)
        flow.existing_id = INFO["id"]
        result = await flow.async_step_zeroconf(self.discovery())
        self.assertEqual(result["reason"], "identity_mismatch")
        self.assertFalse(hasattr(flow, "updates"))
        self.assertTrue(all(not request["headers"] for request in session.requests))

    async def test_discovery_ipv6_preferred_uses_advertised_private_ipv4(self):
        session = Session()
        flow = self.flow(session)
        discovery = self.discovery(host="fe80::1234")
        discovery.ip_addresses = [
            ip_address("fe80::1234"),
            ip_address("203.0.113.20"),
            ip_address("192.168.1.51"),
        ]
        result = await flow.async_step_zeroconf(discovery)
        self.assertEqual(result["step_id"], "discovery_confirm")
        self.assertEqual(flow._discovery["host"], "192.168.1.51")
        self.assertEqual(session.requests[0]["url"], "http://192.168.1.51:8090/api/v1/info")
        self.assertEqual(session.requests[0]["headers"], {})
        session.replies.append(Reply(CAPABILITIES))
        result = await flow.async_step_discovery_confirm({"token": "example-token"})
        self.assertEqual(result["data"]["host"], "192.168.1.51")

    async def test_discovery_without_private_ipv4_is_rejected_before_network(self):
        session = Session()
        flow = self.flow(session)
        discovery = self.discovery(host="fe80::1234")
        discovery.ip_addresses = [ip_address("fe80::1234"), ip_address("203.0.113.20")]
        result = await flow.async_step_zeroconf(discovery)
        self.assertEqual(result["reason"], "invalid_host")
        self.assertEqual(session.requests, [])

    async def test_matching_discovery_updates_address_without_token(self):
        session = Session()
        flow = self.flow(session)
        flow.existing_id = INFO["id"]
        with self.assertRaises(FlowAbort):
            await flow.async_step_zeroconf(self.discovery(host="192.168.1.51"))
        self.assertEqual(flow.updates, {"host": "192.168.1.51", "port": 8090})
        self.assertTrue(all(not request["headers"] for request in session.requests))

    async def test_reconfigure_wrong_unit_prevents_saved_token_transmission(self):
        session = Session(info={**INFO, "id": "wrong-unit"})
        flow = self.flow(session)
        flow.entry = SimpleNamespace(
            unique_id=INFO["id"],
            data={"host": "192.168.1.50", "port": 8090, "token": "saved-secret"},
        )
        result = await flow.async_step_reconfigure({"host": "192.168.1.51"})
        self.assertEqual(result["errors"], {"base": "identity_mismatch"})
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(session.requests[0]["headers"], {})

    async def test_reconfigure_blank_token_keeps_current_key(self):
        flow = self.flow(Session([Reply(CAPABILITIES)]))
        flow.entry = SimpleNamespace(
            unique_id=INFO["id"],
            data={"host": "192.168.1.50", "port": 8090, "token": "saved-secret"},
        )
        result = await flow.async_step_reconfigure({"host": "192.168.1.51", "token": ""})
        self.assertEqual(result["reason"], "reconfigure_successful")
        self.assertEqual(result["data_updates"]["token"], "saved-secret")

    async def test_reauth_changes_key_for_same_identity(self):
        flow = self.flow(Session([Reply(CAPABILITIES)]))
        flow.entry = SimpleNamespace(
            unique_id=INFO["id"], data={"host": "192.168.1.50", "port": 8090, "token": "old-secret"}
        )
        result = await flow.async_step_reauth_confirm({"token": "new-secret"})
        self.assertEqual(result["reason"], "reauth_successful")
        self.assertEqual(result["data_updates"]["token"], "new-secret")

    async def test_invalid_discovery_service_is_rejected_before_network(self):
        session = Session()
        flow = self.flow(session)
        discovery = self.discovery()
        discovery.properties["api"] = "2"
        self.assertEqual((await flow.async_step_zeroconf(discovery))["reason"], "unsupported_api")
        self.assertEqual(session.requests, [])
