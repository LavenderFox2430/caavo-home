"""Home Assistant integration for the independently implemented Caavo Home API."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT, Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import CaavoAuthError, CaavoClient, CaavoError
from .const import CONF_TOKEN, DEFAULT_PORT
from .coordinator import CaavoCoordinator

PLATFORMS = [
    Platform.SELECT,
    Platform.MEDIA_PLAYER,
    Platform.REMOTE,
    Platform.BUTTON,
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if not entry.unique_id:
        raise ConfigEntryNotReady(
            "Missing verified Caavo identity; remove and add this entry again"
        )
    client = CaavoClient(
        async_get_clientsession(hass),
        entry.data[CONF_HOST],
        entry.data[CONF_TOKEN],
        port=entry.data.get(CONF_PORT, DEFAULT_PORT),
        device_id=entry.unique_id,
    )
    try:
        await client.async_get_capabilities()
    except CaavoAuthError as err:
        raise ConfigEntryAuthFailed("The Caavo API key was rejected") from err
    except CaavoError as err:
        raise ConfigEntryNotReady(str(err)) from err
    coordinator = CaavoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    # Unloading/removing the integration never changes power, source, keys, or token.
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
