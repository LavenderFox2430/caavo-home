"""Useful schema/availability diagnostics with credentials and identifiers removed."""

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_HOST, CONF_PORT

from .const import CONF_TOKEN

REDACT = {
    CONF_TOKEN,
    CONF_HOST,
    "id",
    "unique_id",
    "name",
    "address",
    "ip",
    "Authorization",
    "token",
}


async def async_get_config_entry_diagnostics(hass, entry):
    coordinator = entry.runtime_data
    # Whitelist the contract fields before redaction, so a future API field cannot
    # accidentally introduce another spelling of a credential or personal name.
    state = coordinator.data or {}
    public_state = {
        key: state.get(key)
        for key in (
            "available",
            "branchDisabled",
            "power",
            "activeInput",
            "version",
            "temperatureCelsius",
        )
    }
    public_state["inputs"] = [
        {key: item.get(key) for key in ("port", "signal", "configured")}
        for item in state.get("inputs", [])
    ]
    return async_redact_data(
        {
            "entry": {
                "data": {key: entry.data.get(key) for key in (CONF_HOST, CONF_PORT, CONF_TOKEN)},
                "unique_id": entry.unique_id,
            },
            "last_update_success": coordinator.last_update_success,
            "info": {
                key: coordinator.client.info.get(key)
                for key in ("apiVersion", "model", "version", "authentication")
            },
            "capabilities": {
                key: coordinator.client.capabilities.get(key)
                for key in ("apiVersion", "inputs", "keys", "power", "events", "branchDisabled")
            },
            "state": public_state,
        },
        REDACT,
    )
