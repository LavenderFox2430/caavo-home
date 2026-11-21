"""Authenticated local HTTP client. No automatic command retries."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import re
import time
import uuid
from collections.abc import Iterator
from typing import Any

import aiohttp

from .automation import identifier, job_summary, summarize
from .const import (
    API_PATH,
    COMMAND_INTERVAL,
    DEFAULT_PORT,
    GET_TIMEOUT,
    KEYS,
    MAX_RESPONSE_BYTES,
    POST_TIMEOUT,
    POWER_STATES,
    SIGNAL_STATES,
)


class CaavoError(Exception):
    """An error safe to show without revealing the API token or response body."""

    def __init__(self, message: str, *, uncertain: bool = False) -> None:
        super().__init__(message)
        self.uncertain = uncertain


class CaavoAuthError(CaavoError):
    """The unit rejected the API key."""


class CaavoIdentityError(CaavoError):
    """An address belongs to a different unit."""


class CaavoConnectionError(CaavoError):
    """The endpoint could not be reached."""


class CaavoProtocolError(CaavoError):
    """The endpoint did not satisfy this API version's contract."""


def validate_host(host: str) -> str:
    """Accept an IPv4 address, never a URL, hostname, credential, or path."""
    try:
        address = ipaddress.IPv4Address(host.strip())
    except (ValueError, AttributeError) as err:
        raise ValueError("Enter the Caavo's IPv4 address") from err
    allowed = ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16")
    if not any(address in ipaddress.IPv4Network(network) for network in allowed):
        raise ValueError("Enter a private or link-local LAN IPv4 address")
    return str(address)


class CaavoClient:
    """Use Home Assistant's shared session without owning or closing it."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        token: str,
        *,
        port: int = DEFAULT_PORT,
        device_id: str | None = None,
    ) -> None:
        self._session = session
        self.host = validate_host(host)
        if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
            raise ValueError("Invalid API port")
        self.port = port
        self._token = token
        self.device_id = device_id
        self.info: dict[str, Any] = {}
        self.capabilities: dict[str, Any] = {}
        self._base = f"http://{self.host}:{port}{API_PATH}"
        self._command_lock = asyncio.Lock()
        self._last_command = 0.0
        self.last_automation_request: str | None = None

    @property
    def supports_automation(self) -> bool:
        return (
            self.capabilities.get("irAutomation") is True
            and self.capabilities.get("automationVersion") == 1
        )

    @property
    def configuration_url(self) -> str:
        path = "/automation" if self.supports_automation else "/"
        return f"http://{self.host}:{self.port}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        authenticated: bool,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        is_command = method == "POST"
        headers = {"Authorization": f"Bearer {self._token}"} if authenticated else {}
        timeout = aiohttp.ClientTimeout(total=POST_TIMEOUT if is_command else GET_TIMEOUT)
        try:
            async with self._session.request(
                method,
                self._base + path,
                headers=headers,
                json=payload,
                timeout=timeout,
                allow_redirects=False,
            ) as response:
                # Never follow a redirect with credentials; never include a response body
                # in exceptions or diagnostics (it may contain information from hardware).
                if response.status == 401:
                    raise CaavoAuthError("The Caavo API key was rejected")
                if response.status == 403:
                    raise CaavoError("Caavo refused access from this network")
                if response.status == 409:
                    raise CaavoError(
                        "Caavo rejected the automation request; check its current job, learning session and library"
                        if path.startswith("/automation")
                        else "The Caavo hardware backend is not ready"
                    )
                if response.status == 429:
                    raise CaavoError("Caavo is receiving commands too quickly")
                if response.status != 200:
                    raise CaavoConnectionError(
                        f"Caavo returned HTTP {response.status}",
                        uncertain=is_command and response.status >= 500,
                    )
                chunks = bytearray()
                while chunk := await response.content.read(16384):
                    chunks.extend(chunk)
                    limit = 2097152 if path.startswith("/automation") else MAX_RESPONSE_BYTES
                    if len(chunks) > limit:
                        raise CaavoProtocolError(
                            "Caavo response was too large", uncertain=is_command
                        )
                try:
                    data = json.loads(chunks)
                except (ValueError, UnicodeError) as err:
                    raise CaavoProtocolError(
                        "Caavo returned invalid JSON", uncertain=is_command
                    ) from err
                if not isinstance(data, dict):
                    raise CaavoProtocolError(
                        "Caavo returned an invalid response", uncertain=is_command
                    )
                return data
        except (aiohttp.ClientError, TimeoutError) as err:
            raise CaavoConnectionError(
                "Cannot communicate with Caavo"
                if not is_command
                else "The command outcome is unknown; check Caavo before trying again",
                uncertain=is_command,
            ) from err

    async def async_identify(self) -> dict[str, Any]:
        """Verify identity without a token, including before authenticated requests."""
        info = await self._request("GET", "/info", authenticated=False)
        identifier = info.get("id")
        if not isinstance(identifier, str) or not identifier or len(identifier) > 128:
            raise CaavoProtocolError("The endpoint did not return a valid device identity")
        if info.get("apiVersion") != 1 or info.get("authentication") != "bearer":
            raise CaavoProtocolError("The endpoint does not support Caavo Home API v1")
        if self.device_id is not None and identifier != self.device_id:
            raise CaavoIdentityError("This address identifies a different Caavo")
        self.device_id = identifier
        self.info = info
        return info

    async def async_get_capabilities(self) -> dict[str, Any]:
        await self.async_identify()
        capabilities = await self._request("GET", "/capabilities", authenticated=True)
        if capabilities.get("apiVersion") != 1:
            raise CaavoProtocolError("Caavo capabilities use an unsupported API version")
        keys = capabilities.get("keys")
        if not isinstance(keys, list) or not all(isinstance(key, str) for key in keys):
            raise CaavoProtocolError("Caavo did not return its supported commands")
        self.capabilities = capabilities
        return capabilities

    async def async_get_state(self) -> dict[str, Any]:
        await self.async_identify()
        state = await self._request("GET", "/state", authenticated=True)
        if state.get("id") != self.device_id:
            raise CaavoIdentityError("Caavo state identifies a different unit")
        if not isinstance(state.get("available"), bool) or not isinstance(
            state.get("branchDisabled"), bool
        ):
            raise CaavoProtocolError("Caavo did not report backend availability")
        if state.get("power") not in POWER_STATES:
            raise CaavoProtocolError("Caavo returned an invalid power state")
        active = state.get("activeInput")
        if active is not None and (type(active) is not int or active not in range(1, 5)):
            raise CaavoProtocolError("Caavo returned an invalid active input")
        inputs = state.get("inputs")
        if not isinstance(inputs, list):
            raise CaavoProtocolError("Caavo did not return input status")
        seen: set[int] = set()
        for item in inputs:
            if (
                not isinstance(item, dict)
                or type(item.get("port")) is not int
                or item["port"] not in range(1, 5)
            ):
                raise CaavoProtocolError("Caavo returned an invalid HDMI input")
            if item["port"] in seen or item.get("signal") not in SIGNAL_STATES:
                raise CaavoProtocolError("Caavo returned inconsistent HDMI input status")
            if not isinstance(item.get("name"), str) or not isinstance(
                item.get("configured"), bool
            ):
                raise CaavoProtocolError("Caavo returned invalid HDMI input details")
            seen.add(item["port"])
        return state

    async def _command(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        async with self._command_lock:
            # Identity is checked without Authorization before each authenticated
            # request, including when a DHCP address has been reused by another unit.
            await self.async_identify()
            delay = COMMAND_INTERVAL - (time.monotonic() - self._last_command)
            if delay > 0:
                await asyncio.sleep(delay)
            self._last_command = time.monotonic()
            response = await self._request("POST", path, authenticated=True, payload=payload)
            if response.get("ok") is not True or not isinstance(response.get("result"), dict):
                raise CaavoProtocolError("The command result was not confirmed", uncertain=True)
            return response["result"]

    async def async_select_input(self, port: int) -> dict[str, Any]:
        if type(port) is not int or port not in range(1, 5):
            raise ValueError("HDMI input must be 1 through 4")
        return await self._command("/inputs/select", {"port": port})

    async def async_send_key(self, key: str) -> dict[str, Any]:
        if key not in KEYS:
            raise ValueError("Unsupported Caavo remote command")
        supported = self.capabilities.get("keys")
        if supported is not None and key not in supported:
            raise ValueError("This Caavo does not support that remote command")
        return await self._command("/keys", {"key": key})

    async def async_power(self, action: str) -> dict[str, Any]:
        if action not in {"on", "off", "restart"}:
            raise ValueError("Unsupported Caavo power action")
        payload: dict[str, Any] = {"action": action}
        if action == "restart":
            payload["confirm"] = True
        return await self._command("/power", payload)

    async def async_get_automation(self) -> dict[str, Any]:
        if not self.supports_automation:
            raise CaavoError("Update Caavo Home to enable theater automation")
        await self.async_identify()
        response = await self._request("GET", "/automation", authenticated=True)
        try:
            if response.get("ok") is not True:
                raise ValueError("Missing result")
            return summarize(response.get("result"))
        except (ValueError, TypeError, KeyError, AttributeError) as err:
            raise CaavoProtocolError("Caavo returned invalid automation state") from err

    async def async_get_job(self, request_id: str) -> dict[str, Any]:
        identifier(request_id)
        result = await self._command(
            "/automation", {"action": "job", "args": {"requestId": request_id}}
        )
        return self._validate_job(result, request_id)

    @staticmethod
    def _validate_job(result: dict[str, Any], request_id: str) -> dict[str, Any]:
        try:
            job = job_summary(result)
            if job is None or job["requestId"] != request_id:
                raise ValueError("Wrong receipt")
        except (ValueError, TypeError) as err:
            raise CaavoProtocolError(
                "Caavo did not confirm the job receipt", uncertain=True
            ) from err
        return job

    async def async_run_automation(self, request: dict[str, Any]) -> dict[str, Any]:
        if not self.supports_automation:
            raise CaavoError("This Caavo does not support theater automation")
        kind = request.get("kind")
        fields = {"kind"}
        if kind == "command":
            fields |= {"device", "command"}
            identifier(request.get("device"))
            identifier(request.get("command"))
        elif kind in {"macro", "activity.start"}:
            fields.add("id")
            identifier(request.get("id"))
        elif kind != "activity.stop":
            raise ValueError("Unsupported theater action")
        if set(request) != fields:
            raise ValueError("Unsupported theater action fields")
        request_id = uuid.uuid4().hex
        self.last_automation_request = request_id
        try:
            result = await self._command(
                "/automation", {"action": "run", "args": {**request, "requestId": request_id}}
            )
            job = self._validate_job(result, request_id)
        except CaavoError as err:
            if not err.uncertain:
                raise
            # Read the durable receipt once. Never resend 'run', even with the
            # same ID, and never create a replacement job after an uncertain send.
            try:
                job = await self.async_get_job(request_id)
            except CaavoError as lookup_error:
                raise CaavoError(
                    f"Automation outcome unknown. Inspect request {request_id} in Theater before running it again",
                    uncertain=True,
                ) from lookup_error
        if job["status"] in {"failed", "cancelled", "interrupted"}:
            raise CaavoError(f"Automation {job['status']}; inspect request {request_id} in Theater")
        return job

    async def async_cancel_automation(self, request_id: str) -> dict[str, Any]:
        identifier(request_id)
        return await self._command(
            "/automation", {"action": "cancel", "args": {"requestId": request_id}}
        )


def _matching_network_interfaces(state: dict[str, Any], host: str) -> Iterator[dict[str, Any]]:
    network = state.get("network")
    rows = network.get("interfaces") if isinstance(network, dict) else None
    if not isinstance(rows, list):
        return
    for row in rows:
        if isinstance(row, dict) and isinstance(row.get("addresses"), list):
            if host in row["addresses"]:
                yield row


def network_mac(state: dict[str, Any], host: str) -> str | None:
    """Use only a MAC reported for the interface serving the configured IP."""
    for row in _matching_network_interfaces(state, host):
        mac = row.get("mac")
        if not isinstance(mac, str):
            continue
        if not re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", mac):
            continue
        if mac.lower() in {"00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff", "02:00:00:00:00:00"}:
            continue
        if int(mac[:2], 16) & 1:
            continue
        return mac.lower()
    return None


def network_connection(state: dict[str, Any], host: str) -> str | None:
    """Describe the host's reported interface without guessing the default route."""
    names = {
        name
        for row in _matching_network_interfaces(state, host)
        if isinstance(name := row.get("interface"), str) and name.strip()
    }
    if len(names) != 1:
        return None
    name = names.pop()
    if re.fullmatch(r"eth[0-9]+", name):
        return "ethernet"
    if re.fullmatch(r"wlan[0-9]+", name):
        return "wifi"
    return "other"
