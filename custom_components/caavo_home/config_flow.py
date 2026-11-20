"""Manual setup, verified Zeroconf discovery, and API-key maintenance."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import probatio as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import (
    CaavoAuthError,
    CaavoClient,
    CaavoError,
    CaavoIdentityError,
    CaavoProtocolError,
    validate_host,
)
from .const import API_PATH, CONF_TOKEN, DEFAULT_PORT, DOMAIN

if TYPE_CHECKING:
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo


def _token_field():
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _discovery_host(discovery_info: ZeroconfServiceInfo) -> str:
    """Use a private IPv4 even when Zeroconf prefers an advertised IPv6 address."""
    candidates = [discovery_info.host, *getattr(discovery_info, "ip_addresses", [])]
    for address in candidates:
        try:
            return validate_host(str(address))
        except ValueError:
            continue
    raise ValueError("The discovered Caavo did not advertise a private IPv4 address")


def _form_error(error: Exception) -> str:
    if isinstance(error, CaavoAuthError):
        return "invalid_auth"
    if isinstance(error, CaavoIdentityError):
        return "identity_mismatch"
    if isinstance(error, CaavoProtocolError):
        return "unsupported_api"
    if isinstance(error, ValueError):
        return "invalid_host"
    return "cannot_connect"


class CaavoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Credentials are sent only after unauthenticated device-ID verification."""

    VERSION = 1

    def __init__(self) -> None:
        self._discovery: dict[str, Any] = {}

    async def _validate(self, data, expected_id=None):
        host = validate_host(data[CONF_HOST])
        token = data[CONF_TOKEN].strip()
        if not token:
            raise CaavoAuthError("An API key is required")
        client = CaavoClient(
            async_get_clientsession(self.hass),
            host,
            token,
            port=data.get(CONF_PORT, DEFAULT_PORT),
            device_id=expected_id,
        )
        # The client checks /info without a token before /capabilities.
        await client.async_get_capabilities()
        return client.info, {CONF_HOST: host, CONF_PORT: client.port, CONF_TOKEN: token}

    async def async_step_user(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                info, data = await self._validate(user_input)
            except (CaavoError, ValueError) as err:
                errors["base"] = _form_error(err)
            else:
                await self.async_set_unique_id(info["id"])
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info.get("name", "Caavo Home"), data=data)
        return self.async_show_form(
            step_id="user",
            errors=errors,
            data_schema=vol.Schema(
                {vol.Required(CONF_HOST): str, vol.Required(CONF_TOKEN): _token_field()}
            ),
        )

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo):
        properties = {
            key.decode("utf-8", "replace") if isinstance(key, bytes) else str(key): value.decode(
                "utf-8", "replace"
            )
            if isinstance(value, bytes)
            else str(value)
            for key, value in discovery_info.properties.items()
        }
        if (
            properties.get("api") != "1"
            or properties.get("path") != API_PATH
            or properties.get("auth") != "bearer"
        ):
            return self.async_abort(reason="unsupported_api")
        claimed_id = properties.get("id")
        if not claimed_id or discovery_info.port != DEFAULT_PORT:
            return self.async_abort(reason="unsupported_api")
        try:
            host = _discovery_host(discovery_info)
            client = CaavoClient(
                async_get_clientsession(self.hass),
                host,
                "",
                port=discovery_info.port,
                device_id=claimed_id,
            )
            info = (
                await client.async_identify()
            )  # Never send a stored token to a discovery address.
        except (CaavoError, ValueError) as err:
            return self.async_abort(reason=_form_error(err))
        await self.async_set_unique_id(info["id"])
        # Only a matching actual /info identity can update an existing unit's IP.
        self._abort_if_unique_id_configured(updates={CONF_HOST: host, CONF_PORT: client.port})
        self._discovery = {
            CONF_HOST: host,
            CONF_PORT: client.port,
            "id": info["id"],
            "name": info.get("name", "Caavo Home"),
        }
        self.context["title_placeholders"] = {"name": self._discovery["name"]}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(self, user_input=None):
        errors = {}
        if user_input is not None:
            try:
                info, data = await self._validate(
                    {
                        CONF_HOST: self._discovery[CONF_HOST],
                        CONF_PORT: self._discovery[CONF_PORT],
                        CONF_TOKEN: user_input[CONF_TOKEN],
                    },
                    self._discovery["id"],
                )
            except (CaavoError, ValueError) as err:
                errors["base"] = _form_error(err)
            else:
                return self.async_create_entry(title=info.get("name", "Caavo Home"), data=data)
        return self.async_show_form(
            step_id="discovery_confirm",
            errors=errors,
            description_placeholders={
                "name": self._discovery["name"],
                "host": self._discovery[CONF_HOST],
            },
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): _token_field()}),
        )

    async def async_step_reauth(self, entry_data):
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        entry = self._get_reauth_entry()
        errors = {}
        if user_input is not None:
            try:
                _, data = await self._validate(
                    {**entry.data, CONF_TOKEN: user_input[CONF_TOKEN]}, entry.unique_id
                )
            except (CaavoError, ValueError) as err:
                errors["base"] = _form_error(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=data, reason="reauth_successful"
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            errors=errors,
            description_placeholders={"host": entry.data[CONF_HOST]},
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): _token_field()}),
        )

    async def async_step_reconfigure(self, user_input=None):
        entry = self._get_reconfigure_entry()
        errors = {}
        if user_input is not None:
            token = user_input.get(CONF_TOKEN, "").strip() or entry.data[CONF_TOKEN]
            try:
                _, data = await self._validate(
                    {**entry.data, CONF_HOST: user_input[CONF_HOST], CONF_TOKEN: token},
                    entry.unique_id,
                )
            except (CaavoError, ValueError) as err:
                errors["base"] = _form_error(err)
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates=data, reason="reconfigure_successful"
                )
        return self.async_show_form(
            step_id="reconfigure",
            errors=errors,
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=entry.data[CONF_HOST]): str,
                    vol.Optional(CONF_TOKEN): _token_field(),
                }
            ),
        )
