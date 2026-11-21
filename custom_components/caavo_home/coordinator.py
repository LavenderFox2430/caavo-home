"""Polling and shared device metadata for Caavo Home."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo, async_get
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CaavoAuthError, CaavoClient, CaavoError, network_mac
from .const import DOMAIN, POLL_INTERVAL
from .selection import AutomationSelection

_LOGGER = logging.getLogger(__name__)


class CaavoCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """One poll and one serialized command client per physical unit."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: CaavoClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(seconds=POLL_INTERVAL),
            always_update=False,
        )
        self.client = client
        self.entry = entry
        self.selection = AutomationSelection()
        self._capability_version = client.info.get("version")

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            state = await self.client.async_get_state()
            version = self.client.info.get("version")
            if version != self._capability_version:
                await self.client.async_get_capabilities()
                self._capability_version = version
            state["macAddress"] = network_mac(state, self.client.host)
            state["automationAvailable"] = False
            state["automation"] = (self.data or {}).get("automation", {})
            if self.client.supports_automation:
                try:
                    state["automation"] = await self.client.async_get_automation()
                    self.selection.reconcile(state["automation"])
                    state["automationAvailable"] = True
                except CaavoAuthError:
                    raise
                except CaavoError:
                    # Keep normal HDMI/power controls usable during an IR issue.
                    # Retained entity definitions are unavailable, never actionable.
                    pass
            self._update_device(state)
            return state
        except CaavoAuthError as err:
            raise ConfigEntryAuthFailed("The Caavo API key was rejected") from err
        except CaavoError as err:
            raise UpdateFailed(str(err)) from err

    def _update_device(self, state: dict[str, Any]) -> None:
        registry = async_get(self.hass)
        device = registry.async_get_device_by_identifier(
            (DOMAIN, str(self.client.device_id)), self.entry.entry_id
        )
        if device:
            values = {
                "configuration_url": self.client.configuration_url,
                "sw_version": self.client.info.get("version"),
            }
            if state.get("macAddress"):
                values["new_connections"] = device.connections | {
                    (CONNECTION_NETWORK_MAC, state["macAddress"])
                }
            registry.async_update_device(device.id, **values)


def device_info(coordinator: CaavoCoordinator) -> DeviceInfo:
    client = coordinator.client
    info = client.info
    values = {
        "identifiers": {(DOMAIN, str(client.device_id))},
        "name": info.get("name", "Caavo Home"),
        "manufacturer": "Caavo",
        "model": info.get("model", "HDRX4"),
        "sw_version": info.get("version"),
    }
    if url := getattr(client, "configuration_url", None):
        values["configuration_url"] = url
    if mac := (coordinator.data or {}).get("macAddress"):
        values["connections"] = {(CONNECTION_NETWORK_MAC, mac)}
    return DeviceInfo(**values)


def input_options(state: dict[str, Any] | None) -> dict[str, int]:
    """Include the port in every label so duplicate owner names stay unambiguous."""
    rows = {row["port"]: row for row in (state or {}).get("inputs", [])}
    options = {}
    for port in range(1, 5):
        name = str(rows.get(port, {}).get("name", "")).strip()
        label = f"HDMI {port}"
        if name and name.lower() != label.lower():
            label += f" · {name}"
        options[label] = port
    return options


def current_source(state: dict[str, Any] | None) -> str | None:
    active = (state or {}).get("activeInput")
    return next((label for label, port in input_options(state).items() if port == active), None)
