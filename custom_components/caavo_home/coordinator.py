"""Polling and shared device metadata for Caavo Home."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import CaavoAuthError, CaavoClient, CaavoError
from .const import DOMAIN, POLL_INTERVAL

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

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.async_get_state()
        except CaavoAuthError as err:
            raise ConfigEntryAuthFailed("The Caavo API key was rejected") from err
        except CaavoError as err:
            raise UpdateFailed(str(err)) from err


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
