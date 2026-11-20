"""Exercise actual client behavior against controlled asynchronous HTTP responses."""

import asyncio
import copy
import json
import unittest

from support import CAPABILITIES, INFO, STATE, Reply, Session, component

api = component("api")
const = component("const")
TOKEN = "test-only-secret-do-not-log"
HOST = "192.168.1.50"


class ClientTests(unittest.IsolatedAsyncioTestCase):
    def client(self, session, identifier=INFO["id"]):
        return api.CaavoClient(session, HOST, TOKEN, device_id=identifier)

    async def test_identity_mismatch_prevents_token_transmission(self):
        session = Session(info={**INFO, "id": "another-unit"})
        with self.assertRaises(api.CaavoIdentityError):
            await self.client(session).async_get_capabilities()
        self.assertEqual(len(session.requests), 1)
        self.assertEqual(session.requests[0]["headers"], {})

    async def test_identity_is_checked_again_before_mutation(self):
        session = Session([Reply(CAPABILITIES)])
        client = self.client(session)
        await client.async_get_capabilities()
        session.info["id"] = "different-unit-now-at-this-ip"
        with self.assertRaises(api.CaavoIdentityError):
            await client.async_send_key("up")
        self.assertFalse(any(request["method"] == "POST" for request in session.requests))
        self.assertEqual(session.requests[-1]["headers"], {})

    async def test_fragmented_response_is_read_to_eof(self):
        raw = json.dumps(STATE).encode()
        session = Session([Reply(fragments=[raw[:2], raw[2:19], raw[19:70], raw[70:]])])
        self.assertEqual(await self.client(session).async_get_state(), STATE)

    async def test_oversize_response_is_rejected(self):
        session = Session([Reply(fragments=[b" " * 20000] * 4)])
        with self.assertRaises(api.CaavoProtocolError):
            await self.client(session).async_get_state()

    async def test_error_body_is_not_exposed(self):
        session = Session([Reply(fragments=[TOKEN.encode()])])
        with self.assertRaises(api.CaavoProtocolError) as error:
            await self.client(session).async_get_state()
        self.assertNotIn(TOKEN, str(error.exception))

    async def test_http_auth_and_backend_errors(self):
        for status, expected in (
            (401, api.CaavoAuthError),
            (403, api.CaavoError),
            (409, api.CaavoError),
            (429, api.CaavoError),
            (502, api.CaavoConnectionError),
        ):
            with self.subTest(status=status):
                session = Session([Reply({"error": {"message": TOKEN}}, status=status)])
                with self.assertRaises(expected) as error:
                    await self.client(session).async_get_capabilities()
                self.assertNotIn(TOKEN, str(error.exception))

    async def test_post_timeout_is_uncertain_and_never_retried(self):
        session = Session([Reply(error=TimeoutError())])
        with self.assertRaises(api.CaavoConnectionError) as error:
            await self.client(session).async_select_input(2)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(sum(r["method"] == "POST" for r in session.requests), 1)

    async def test_502_after_post_is_uncertain(self):
        session = Session([Reply(status=502)])
        with self.assertRaises(api.CaavoConnectionError) as error:
            await self.client(session).async_power("off")
        self.assertTrue(error.exception.uncertain)

    async def test_command_result_must_be_confirmed(self):
        session = Session([Reply({"ok": False, "error": TOKEN})])
        with self.assertRaises(api.CaavoProtocolError) as error:
            await self.client(session).async_send_key("up")
        self.assertTrue(error.exception.uncertain)

    async def test_commands_are_serialized_and_rate_spaced(self):
        session = Session([Reply({"ok": True, "result": {}}, delay=0.015) for _ in range(3)])
        client = self.client(session)
        await asyncio.gather(*(client.async_send_key("up") for _ in range(3)))
        commands = [r for r in session.requests if r["method"] == "POST"]
        self.assertEqual(session.max_active, 1)
        self.assertEqual(len(commands), 3)
        self.assertTrue(
            all(b["at"] - a["at"] >= 0.085 for a, b in zip(commands, commands[1:], strict=False))
        )

    async def test_timeouts_headers_redirects_and_numeric_key(self):
        session = Session([Reply({"ok": True, "result": {}})])
        await self.client(session).async_send_key("num_7")
        info, command = session.requests
        self.assertEqual(info["timeout"].total, 10)
        self.assertEqual(command["timeout"].total, 25)
        self.assertEqual(info["headers"], {})
        self.assertEqual(command["headers"], {"Authorization": f"Bearer {TOKEN}"})
        self.assertEqual(command["json"], {"key": "num_7"})
        self.assertFalse(command["allow_redirects"])
        self.assertNotIn(TOKEN, command["url"])

    async def test_restart_has_explicit_confirmation(self):
        session = Session([Reply({"ok": True, "result": {}})])
        await self.client(session).async_power("restart")
        self.assertEqual(session.requests[-1]["json"], {"action": "restart", "confirm": True})

    async def test_backend_unready_is_valid_state(self):
        state = {**STATE, "available": False, "branchDisabled": False, "power": "unknown"}
        self.assertEqual(await self.client(Session([Reply(state)])).async_get_state(), state)

    async def test_invalid_or_wrong_unit_state_is_rejected(self):
        cases = [
            {**STATE, "power": "playing"},
            {**STATE, "activeInput": True},
            {**STATE, "id": "other"},
        ]
        duplicate = copy.deepcopy(STATE)
        duplicate["inputs"].append(duplicate["inputs"][0])
        cases.append(duplicate)
        for state in cases:
            with self.subTest(state=state.get("power")):
                with self.assertRaises(api.CaavoError):
                    await self.client(Session([Reply(state)])).async_get_state()

    async def test_invalid_command_never_reaches_network(self):
        session = Session()
        client = self.client(session)
        for value in (0, 5, True, "1"):
            with self.assertRaises(ValueError):
                await client.async_select_input(value)
        with self.assertRaises(ValueError):
            await client.async_send_key("factory_reset")
        self.assertEqual(session.requests, [])


class HostTests(unittest.TestCase):
    def test_private_ipv4_only(self):
        for address in ("10.1.2.3", "172.16.0.2", "192.168.1.50", "169.254.1.9"):
            self.assertEqual(api.validate_host(address), address)
        for address in (
            "8.8.8.8",
            "127.0.0.1",
            "0.0.0.0",
            "192.0.2.1",
            "224.0.0.1",
            "::1",
            "caavo.local",
            "http://192.168.1.50",
            "192.168.1.50:8090",
            "user:secret@192.168.1.50",
            "172.32.0.1",
        ):
            with self.subTest(address=address), self.assertRaises(ValueError):
                api.validate_host(address)
