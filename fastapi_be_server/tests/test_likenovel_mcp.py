import importlib
import json
import os
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import base64
import hashlib
import re
import time
from urllib.parse import urlsplit, parse_qs
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from app.const import settings
from app.services.ai import mcp_policy as policy, mcp_store as store


class PolicyTests(unittest.TestCase):
    def test_single_cadence_and_before_due_are_rejected(self):
        for day, hour, minute in [(11, 11, 0), (12, 10, 4), (13, 11, 0)]:
            with self.subTest(day=day):
                with self.assertRaises(ValueError):
                    policy.cycle_key("single", datetime(2026, 10, day, hour, minute, tzinfo=policy.KST))
        self.assertEqual(
            policy.cycle_key("single", datetime(2026, 10, 12, 10, 5, tzinfo=policy.KST)),
            "single:2026-10-12",
        )
        self.assertEqual(
            policy.cycle_key("single", datetime(2026, 10, 15, 10, 5, tzinfo=policy.KST)),
            "single:2026-10-15",
        )

    def test_unknown_duplicate_bool_and_empty_ids_are_rejected(self):
        for values in ([], [True], [0], [1, 1], "1", [1.5]):
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    policy.validate_ids(values)


class StoreTests(unittest.TestCase):
    def test_receipts_survive_connections_and_cannot_be_stolen_by_another_admin(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"LIKENOVEL_MCP_STATE_DB": directory + "/state.db"}):
                self.assertTrue(store.claim("single:2026-10-12", "owner", {"kind": "single"}))
                self.assertFalse(store.claim("single:2026-10-12", "owner", {}))
                self.assertFalse(store.claim("single:2026-10-12", "other", {}))
                with self.assertRaises(RuntimeError):
                    store.save("single:2026-10-12", "other", "completed", {"wrong": True})
                self.assertEqual(store.get("single:2026-10-12", "owner")["status"], "generating")
                self.assertIsNone(store.get("single:2026-10-12", "other"))
                store.save("single:2026-10-12", "owner", "ready", {"candidates": [1, 2, 3]})
                self.assertEqual(store.get("single:2026-10-12", "owner")["candidates"], [1, 2, 3])


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def begin(self):
        return self

    async def execute(self, *args):
        pass


class GuardedWriteTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_edit_blocks_before_intent_or_cms_write(self):
        from app.services.ai import mcp_operations as ops
        from app.services.admin import admin_recommend_service as cms
        current = [{"slot_id": 1, "name": "changed", "product_ids": [99]}]
        with patch.object(ops, "_enabled"), \
             patch.object(policy, "cycle_key", return_value="direct:2026-10-12"), \
             patch.object(ops, "_snapshot", return_value={"kind": "direct", "slots": []}), \
             patch.object(ops, "likenovel_db_session", return_value=_Session()), \
             patch.object(ops.curator, "_load_slots", AsyncMock(return_value=current)), \
             patch.object(store, "get", return_value=None), \
             patch.object(store, "save") as save, \
             patch.object(cms, "put_direct_recommend", AsyncMock()) as put:
            with self.assertRaisesRegex(ValueError, "CMS state changed"):
                await ops.apply_direct("owner", "snapshot", [])
            save.assert_not_called()
            put.assert_not_awaited()

    async def test_lost_response_after_commit_is_reconciled_without_repeating_write(self):
        from app.services.ai import mcp_operations as ops
        from app.services.admin import admin_recommend_service as cms
        after = [{"slot_id": 1, "name": "slot", "product_ids": [2]}]
        applying = {"status": "applying", "after": after, "result": {"kind": "direct", "after": after}}
        completed = {"status": "completed", "recovered_after_commit": True}
        with patch.object(ops, "_enabled"), \
             patch.object(policy, "cycle_key", return_value="direct:2026-10-12"), \
             patch.object(ops, "_snapshot", return_value={"kind": "direct", "slots": []}), \
             patch.object(ops, "likenovel_db_session", return_value=_Session()), \
             patch.object(ops.curator, "_load_slots", AsyncMock(return_value=after)), \
             patch.object(store, "get", side_effect=[applying, completed]), \
             patch.object(store, "save") as save, \
             patch.object(cms, "put_direct_recommend", AsyncMock()) as put:
            result = await ops.apply_direct("owner", "snapshot", [])
            self.assertTrue(result["recovered_after_commit"])
            save.assert_called_once()
            put.assert_not_awaited()


class SDKTransportTests(unittest.TestCase):
    def test_real_code_pkce_flow_refresh_revocation_and_tool_surface(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            issuer = "https://auth.example.test/realms/likenovel"
            resource = "https://api.likenovel.net/mcp"
            callback = "https://chatgpt.com/connector/oauth/test-exact"
            config_path.write_text(json.dumps({
                "issuer": issuer, "resource": resource, "allowed_subject": "authorized-admin",
                "state_db": directory + "/state.db", "writes_enabled": False,
                "environment_db_host": settings.DB_IP,
                "oauth_callback": callback,
                "token_encryption_key": Fernet.generate_key().decode(),
            }))
            config_path.chmod(0o600)
            with patch.dict(os.environ, {"LIKENOVEL_MCP_CONFIG_FILE": str(config_path)}), \
                 patch.object(settings, "KC_ISSUER_BASE_URL", issuer):
                from app import mcp_server
                from app.services.ai import mcp_oauth as oauth
                server = importlib.reload(mcp_server)
                fake_kc = {"access_token": "private-upstream-access", "refresh_token": "private-upstream-refresh",
                           "expires_in": 3600, "refresh_expires_in": 0}
                with patch.object(oauth, "_keycloak", AsyncMock(return_value=fake_kc)), \
                     patch.object(oauth, "_verify_admin", AsyncMock(return_value=("authorized-admin", 42))), \
                     TestClient(server.http_app, base_url="https://api.likenovel.net", follow_redirects=False) as client:
                    headers = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}
                    initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}}
                    rejected = client.post("/mcp", headers=headers, json=initialize)
                    self.assertEqual(rejected.status_code, 401)
                    self.assertIn("resource_metadata=", rejected.headers["www-authenticate"])
                    metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
                    self.assertEqual(metadata["resource"], resource)
                    auth_metadata = client.get("/.well-known/oauth-authorization-server").json()
                    self.assertEqual(auth_metadata["token_endpoint_auth_methods_supported"], ["none"])
                    self.assertEqual(auth_metadata["code_challenge_methods_supported"], ["S256"])
                    verifier = "a" * 64
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
                    params = {"client_id": policy.CLIENT_ID, "redirect_uri": callback, "response_type": "code",
                              "scope": " ".join(oauth.SCOPES), "state": "bound-client-state",
                              "code_challenge": challenge, "code_challenge_method": "S256", "resource": resource}
                    denied_callback = client.get("/authorize", params={**params, "redirect_uri": "https://evil.test/"})
                    self.assertEqual(denied_callback.status_code, 400)
                    auth = client.get("/authorize", params=params)
                    self.assertEqual(auth.status_code, 302)
                    page = client.get(auth.headers["location"])
                    self.assertEqual(page.status_code, 200)
                    # Preserve same-site POST Origin; cross-site navigation still has no referrer.
                    self.assertEqual(page.headers["referrer-policy"], "same-origin")
                    csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
                    flow = parse_qs(urlsplit(auth.headers["location"]).query)["flow"][0]
                    form = {"flow": flow, "csrf": csrf, "username": "admin@example.test", "password": "test-only"}
                    cross_site = client.post("/oauth/login", data=form, headers={"Origin": "https://evil.test"})
                    self.assertEqual(cross_site.status_code, 403)
                    login = client.post("/oauth/login", data=form, headers={"Origin": "https://api.likenovel.net"})
                    self.assertEqual(login.status_code, 303)
                    query = parse_qs(urlsplit(login.headers["location"]).query)
                    self.assertEqual(query["state"], ["bound-client-state"])
                    code = query["code"][0]
                    token_request = {"grant_type": "authorization_code", "client_id": policy.CLIENT_ID,
                                     "code": code, "redirect_uri": callback, "code_verifier": verifier}
                    bad_pkce = client.post("/token", data={**token_request, "code_verifier": "wrong"})
                    self.assertEqual(bad_pkce.status_code, 400)
                    exchange = client.post("/token", data=token_request)
                    self.assertEqual(exchange.status_code, 200, exchange.text)
                    tokens = exchange.json()
                    self.assertNotIn("private-upstream", exchange.text)
                    self.assertEqual(client.post("/token", data=token_request).status_code, 400)
                    headers["Authorization"] = "Bearer " + tokens["access_token"]
                    self.assertEqual(client.post("/mcp", headers=headers, json=initialize).status_code, 200)
                    result = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
                    names = {tool["name"] for tool in result.json()["result"]["tools"]}
                    self.assertEqual(names, {"likenovel_direct_snapshot", "likenovel_apply_direct",
                        "likenovel_start_single_generation", "likenovel_job_status", "likenovel_apply_single",
                        "likenovel_operator_status", "likenovel_verify_public"})
                    status_result = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 3,
                        "method": "tools/call", "params": {"name": "likenovel_operator_status", "arguments": {}}}).json()["result"]
                    self.assertFalse(status_result.get("isError", False), status_result)
                    status_data = json.loads(status_result["content"][0]["text"])
                    self.assertFalse(status_data["writes_enabled"])
                    self.assertEqual(status_data["receipts"], [])
                    private_lookup = client.post("/mcp", headers=headers, json={"jsonrpc": "2.0", "id": 4,
                        "method": "tools/call", "params": {"name": "likenovel_job_status", "arguments": {"job_id": "oauth:grant:private"}}}).json()["result"]
                    self.assertTrue(private_lookup["isError"])
                    refresh_request = {"grant_type": "refresh_token", "client_id": policy.CLIENT_ID, "refresh_token": tokens["refresh_token"]}
                    refreshed = client.post("/token", data=refresh_request)
                    self.assertEqual(refreshed.status_code, 200, refreshed.text)
                    self.assertNotEqual(refreshed.json()["refresh_token"], tokens["refresh_token"])
                    self.assertEqual(client.post("/token", data=refresh_request).status_code, 400)
                    self.assertEqual(client.post("/mcp", headers=headers, json=initialize).status_code, 401)
                    headers["Authorization"] = "Bearer " + refreshed.json()["access_token"]
                    self.assertEqual(client.post("/mcp", headers=headers, json=initialize).status_code, 200)
                    access_key = oauth._key("access", refreshed.json()["access_token"])
                    access_record = store.get(access_key, "authorized-admin")
                    for override in ({"resource": "wrong-resource"}, {"subject": "another-admin"}, {"client_id": "other"}, {"expires_at": 1}):
                        store.save(access_key, "authorized-admin", "active", {**access_record, **override})
                        self.assertEqual(client.post("/mcp", headers=headers, json=initialize).status_code, 401)
                    store.save(access_key, "authorized-admin", "active", access_record)
                    with patch.object(oauth, "_verify_admin", AsyncMock(side_effect=ValueError("not admin"))):
                        self.assertEqual(client.post("/mcp", headers=headers, json=initialize).status_code, 401)
                    # Revocation removes the encrypted identity credentials and invalidates the entire grant.
                    with patch.object(oauth, "AsyncClient") as http:
                        session = http.return_value.__aenter__.return_value
                        session.post = AsyncMock(return_value=Mock())
                        revoke = client.post("/revoke", data={"client_id": policy.CLIENT_ID,
                            "token": refreshed.json()["refresh_token"], "token_type_hint": "refresh_token"})
                        self.assertEqual(revoke.status_code, 200, revoke.text)
                    self.assertEqual(client.post("/mcp", headers=headers, json=initialize).status_code, 401)


if __name__ == "__main__":
    unittest.main()
