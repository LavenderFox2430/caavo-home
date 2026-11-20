"""Network and minimal framework doubles; these do not claim a live HA install."""

from __future__ import annotations

import asyncio
import importlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace

import probatio

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = "caavo_under_test"
package = ModuleType(PACKAGE)
package.__path__ = [str(ROOT / "custom_components/caavo_home")]
sys.modules.setdefault(PACKAGE, package)


def component(name):
    return importlib.import_module(f"{PACKAGE}.{name}")


INFO = {
    "apiVersion": 1,
    "id": "test-unit-012345",
    "name": "Caavo Home",
    "model": "Caavo HDRX4",
    "version": "1.3",
    "authentication": "bearer",
}
STATE = {
    "id": INFO["id"],
    "name": "Caavo Home",
    "available": True,
    "branchDisabled": True,
    "power": "on",
    "activeInput": 2,
    "inputs": [
        {"port": p, "name": "Player", "signal": "unknown", "configured": True} for p in range(1, 5)
    ],
    "version": "1.3",
}
CAPABILITIES = {
    "apiVersion": 1,
    "inputs": [1, 2, 3, 4],
    "keys": ["up", "down", "caavo", "home", "num_7"],
    "power": ["on", "off", "restart"],
    "events": False,
    "branchDisabled": True,
}


@dataclass
class Reply:
    body: object = None
    status: int = 200
    fragments: list[bytes] | None = None
    error: Exception | None = None
    delay: float = 0


class Stream:
    def __init__(self, fragments):
        self.fragments = list(fragments)

    async def read(self, maximum):
        await asyncio.sleep(0)
        if not self.fragments:
            return b""
        first = self.fragments.pop(0)
        if len(first) > maximum:
            self.fragments.insert(0, first[maximum:])
        return first[:maximum]


class Response:
    def __init__(self, session, method, reply):
        self.session, self.method, self.reply = session, method, reply
        self.status = reply.status
        fragments = (
            reply.fragments if reply.fragments is not None else [json.dumps(reply.body).encode()]
        )
        self.content = Stream(fragments)

    async def __aenter__(self):
        if self.reply.error:
            raise self.reply.error
        if self.method == "POST":
            self.session.active += 1
            self.session.max_active = max(self.session.max_active, self.session.active)
        await asyncio.sleep(self.reply.delay)
        return self

    async def __aexit__(self, *args):
        if self.method == "POST":
            self.session.active -= 1


class Session:
    def __init__(self, replies=(), info=None):
        self.replies = list(replies)
        self.info = dict(INFO if info is None else info)
        self.requests = []
        self.active = self.max_active = 0

    def request(self, method, url, **kwargs):
        self.requests.append({"method": method, "url": url, "at": time.monotonic(), **kwargs})
        if url.endswith("/info"):
            reply = Reply(self.info)
        else:
            if not self.replies:
                raise AssertionError(f"Unexpected request: {method} {url}")
            reply = self.replies.pop(0)
        return Response(self, method, reply)


class FlowAbort(Exception):
    pass


def install_ha_doubles():
    """Only APIs used by flow and pure coordinator/entity logic are simulated."""

    def module(name, **attributes):
        result = sys.modules.setdefault(name, ModuleType(name))
        result.__dict__.update(attributes)
        return result

    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            pass

        async def async_set_unique_id(self, value):
            self.unique_id = value

        def _abort_if_unique_id_configured(self, updates=None):
            if getattr(self, "existing_id", None) == self.unique_id:
                self.updates = updates
                raise FlowAbort("already_configured")

        def async_show_form(self, **kwargs):
            schema = kwargs.get("data_schema")
            if schema is not None and not isinstance(schema, probatio.Schema):
                raise TypeError("Home Assistant 2026.11 expects a probatio schema")
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

        def async_abort(self, **kwargs):
            return {"type": "abort", **kwargs}

        def async_update_reload_and_abort(self, entry, **kwargs):
            self.updated_entry = entry
            return {"type": "abort", **kwargs}

        def _get_reauth_entry(self):
            return self.entry

        def _get_reconfigure_entry(self):
            return self.entry

    class Selector:
        def __init__(self, config):
            self.config = config

        def __call__(self, value):
            return str(value)

    class Coordinator:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, *args, **kwargs):
            self.data = None
            self.last_update_success = True

    class CoordinatorEntity:
        @classmethod
        def __class_getitem__(cls, item):
            return cls

        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.last_update_success

    class HomeAssistantError(Exception):
        pass

    class ConfigEntryAuthFailed(Exception):
        pass

    class UpdateFailed(Exception):
        pass

    module("homeassistant")
    entries = module("homeassistant.config_entries", ConfigFlow=ConfigFlow, ConfigEntry=object)
    sys.modules["homeassistant"].config_entries = entries
    module("homeassistant.core", HomeAssistant=object)
    module(
        "homeassistant.const",
        CONF_HOST="host",
        CONF_PORT="port",
        EntityCategory=SimpleNamespace(DIAGNOSTIC="diagnostic", CONFIG="config"),
        UnitOfTemperature=SimpleNamespace(CELSIUS="°C"),
    )
    module("homeassistant.components")
    # Current Home Assistant deliberately does not re-export this type here.
    # Keeping this module empty catches the removed import that broke 0.1.0.
    module("homeassistant.components.zeroconf")
    module("homeassistant.components.remote", RemoteEntity=type("RemoteEntity", (), {}))
    module(
        "homeassistant.components.sensor",
        SensorEntity=type("SensorEntity", (), {}),
        SensorDeviceClass=SimpleNamespace(ENUM="enum", TEMPERATURE="temperature"),
        SensorStateClass=SimpleNamespace(MEASUREMENT="measurement"),
    )
    module("homeassistant.helpers")
    module("homeassistant.helpers.service_info")
    module("homeassistant.helpers.service_info.zeroconf", ZeroconfServiceInfo=object)
    module(
        "homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: hass.session
    )
    module(
        "homeassistant.helpers.selector",
        TextSelector=Selector,
        TextSelectorConfig=dict,
        TextSelectorType=SimpleNamespace(PASSWORD="password"),
    )
    module("homeassistant.helpers.device_registry", DeviceInfo=dict)
    module(
        "homeassistant.helpers.update_coordinator",
        DataUpdateCoordinator=Coordinator,
        CoordinatorEntity=CoordinatorEntity,
        UpdateFailed=UpdateFailed,
    )
    module(
        "homeassistant.exceptions",
        HomeAssistantError=HomeAssistantError,
        ConfigEntryAuthFailed=ConfigEntryAuthFailed,
    )
    return SimpleNamespace(
        HomeAssistantError=HomeAssistantError,
        ConfigEntryAuthFailed=ConfigEntryAuthFailed,
        UpdateFailed=UpdateFailed,
    )
