"""Diagnostics must not expose API credentials or future unrecognized fields."""

import json
import sys
import unittest
from types import ModuleType, SimpleNamespace

from support import CAPABILITIES, INFO, STATE, component, install_ha_doubles

install_ha_doubles()


def redact(data, keys):
    if isinstance(data, dict):
        return {
            key: "**REDACTED**" if key in keys else redact(value, keys)
            for key, value in data.items()
        }
    if isinstance(data, list):
        return [redact(item, keys) for item in data]
    return data


stub = ModuleType("homeassistant.components.diagnostics")
stub.async_redact_data = redact
sys.modules[stub.__name__] = stub
diagnostics = component("diagnostics")


class DiagnosticsTests(unittest.IsolatedAsyncioTestCase):
    async def test_only_whitelisted_fields_survive(self):
        entry = SimpleNamespace(
            unique_id="private-unit-id",
            data={
                "host": "192.168.20.50",
                "port": 8090,
                "token": "entry-secret",
                "future_secret": "another-secret",
            },
            runtime_data=SimpleNamespace(
                last_update_success=True,
                client=SimpleNamespace(
                    info={**INFO, "name": "Owner's room", "future_credential": "api-secret"},
                    capabilities={**CAPABILITIES, "future_credential": "cap-secret"},
                ),
                data={
                    **STATE,
                    "future_credential": "state-secret",
                    "inputs": [
                        {
                            "port": 1,
                            "name": "Private player",
                            "signal": "connected",
                            "configured": True,
                            "credential": "input-secret",
                        }
                    ],
                },
            ),
        )
        result = await diagnostics.async_get_config_entry_diagnostics(None, entry)
        serialized = json.dumps(result)
        for private in (
            "private-unit-id",
            "192.168.20.50",
            "entry-secret",
            "another-secret",
            "Owner's room",
            "api-secret",
            "cap-secret",
            "state-secret",
            "Private player",
            "input-secret",
            INFO["id"],
        ):
            self.assertNotIn(private, serialized)
        self.assertEqual(
            result["state"]["inputs"], [{"port": 1, "signal": "connected", "configured": True}]
        )
        self.assertTrue(result["last_update_success"])
