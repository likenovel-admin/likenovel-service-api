import asyncio
import json
import os
import re
import tempfile
import time
import unittest
from unittest.mock import AsyncMock, patch
from urllib.parse import parse_qs, urlsplit

from cryptography.fernet import Fernet
from starlette.applications import Starlette
from starlette.testclient import TestClient

from app.services.ai import mcp_cp_auth as cp, mcp_oauth as oauth, mcp_store as store


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class CPAuthTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = {
            "allowed_subject": "admin-owner", "cp_company_name": "라이크노벨",
            "resource": "https://api.likenovel.net/mcp",
            "token_encryption_key": Fernet.generate_key().decode(),
        }
        self.patches = [
            patch.dict(os.environ, {"LIKENOVEL_MCP_STATE_DB": self.directory.name + "/state.db"}),
            patch.object(cp, "load_config", return_value=self.config),
            patch.object(oauth, "load_config", return_value=self.config),
            patch.object(cp, "likenovel_db_session", return_value=_Session()),
            patch.object(cp, "chk_jwt_token", AsyncMock(return_value={"sub": "cp-subject"})),
            patch.object(cp, "check_user", AsyncMock(return_value={"user_id": 17, "role": "CP"})),
            patch.object(cp, "get_approved_cp_company_name_by_user_id",
                         AsyncMock(return_value="라이크노벨")),
            patch.object(oauth, "_keycloak", AsyncMock(return_value={
                "access_token": "private-cp-access", "refresh_token": "private-cp-refresh",
                "expires_in": 3600, "refresh_expires_in": 0,
            })),
        ]
        for item in self.patches:
            item.start()
        self.client = TestClient(Starlette(routes=cp.CP_AUTH_ROUTES),
                                 base_url="https://api.likenovel.net", follow_redirects=False)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        for item in reversed(self.patches):
            item.stop()
        self.directory.cleanup()

    def _form(self):
        begun = cp.begin_connection("admin-owner")
        self.assertEqual(begun["expires_in"], 600)
        self.assertNotIn("password", begun)
        page = self.client.get(begun["login_url"])
        self.assertEqual(page.status_code, 200)
        self.assertIn("관리자 계정은 연결할 수 없습니다", page.text)
        self.assertIn("frame-ancestors 'none'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["referrer-policy"], "same-origin")
        flow = parse_qs(urlsplit(begun["login_url"]).query)["flow"][0]
        csrf = re.search(r'name="csrf" value="([^"]+)"', page.text).group(1)
        return {"flow": flow, "csrf": csrf, "username": "cp@example.test", "password": "test-only"}

    def _login(self, form):
        return self.client.post(cp.LOGIN_PATH, data=form,
                                headers={"Origin": "https://api.likenovel.net"})

    def test_first_party_login_encrypted_grant_and_live_cp_actor(self):
        form = self._form()
        response = self._login(form)
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/oauth/cp/connected")
        record = store.get(cp.GRANT_KEY, "admin-owner")
        self.assertEqual(record["cp_subject"], "cp-subject")
        raw = json.dumps(record)
        self.assertNotIn("private-cp-access", raw)
        self.assertNotIn("private-cp-refresh", raw)
        self.assertNotIn("test-only", raw)
        self.assertEqual(oauth._decrypt(record["kc_access"]), "private-cp-access")
        actor = asyncio.run(cp.get_actor("admin-owner"))
        self.assertEqual(actor, {"user_id": 17, "role": "CP", "company_name": "라이크노벨"})
        self.assertEqual(asyncio.run(cp.connection_status("admin-owner"))["connected"], True)
        cp.check_user.assert_awaited_with("cp-subject", unittest.mock.ANY, role="partner")
        # A used browser flow cannot issue another grant.
        self.assertEqual(self._login(form).status_code, 403)
        oauth._keycloak.assert_awaited_once()

    def test_owner_company_and_real_cp_role_are_required(self):
        with self.assertRaises(ValueError):
            cp.begin_connection("other-admin")
        form = self._form()
        cp.check_user.return_value = {"user_id": 17, "role": "admin"}
        self.assertEqual(self._login(form).status_code, 401)
        self.assertIsNone(store.get(cp.GRANT_KEY, "admin-owner"))
        cp.get_approved_cp_company_name_by_user_id.assert_not_awaited()
        cp.check_user.return_value = {"user_id": 17, "role": "CP"}
        cp.get_approved_cp_company_name_by_user_id.return_value = "다른 회사"
        self.assertEqual(self._login(form).status_code, 401)
        self.assertIsNone(store.get(cp.GRANT_KEY, "admin-owner"))
        self.config["cp_company_name"] = ""
        with self.assertRaises(ValueError):
            cp.begin_connection("admin-owner")

    def test_csrf_origin_expiration_and_bounded_form_block_before_authentication(self):
        form = self._form()
        self.assertEqual(self.client.post(cp.LOGIN_PATH, data=form,
                         headers={"Origin": "https://other.example.test"}).status_code, 403)
        self.assertEqual(self._login({**form, "csrf": "wrong"}).status_code, 403)
        self.assertEqual(self.client.post(cp.LOGIN_PATH, content="password=" + "x" * 8192,
                         headers={"Origin": "https://api.likenovel.net"}).status_code, 400)
        record = store.get(cp._flow_key(form["flow"]), "admin-owner")
        record["expires_at"] = time.time() - 1
        store.save(cp._flow_key(form["flow"]), "admin-owner", "pending", record)
        self.assertEqual(self._login(form).status_code, 403)
        oauth._keycloak.assert_not_awaited()

    def test_non_offline_grant_is_rejected(self):
        form = self._form()
        oauth._keycloak.return_value["refresh_expires_in"] = 3600
        self.assertEqual(self._login(form).status_code, 401)
        self.assertIsNone(store.get(cp.GRANT_KEY, "admin-owner"))

    def test_refresh_revalidates_identity_role_and_company(self):
        self.assertEqual(self._login(self._form()).status_code, 303)
        record = store.get(cp.GRANT_KEY, "admin-owner")
        record["kc_expires_at"] = 0
        store.save(cp.GRANT_KEY, "admin-owner", "active", record)
        oauth._keycloak.return_value = {
            "access_token": "next-private-access", "refresh_token": "next-private-refresh",
            "expires_in": 3600,
        }
        actor = asyncio.run(cp.get_actor("admin-owner"))
        self.assertEqual(actor["role"], "CP")
        oauth._keycloak.assert_awaited_with({
            "grant_type": "refresh_token", "refresh_token": "private-cp-refresh",
        })
        saved = store.get(cp.GRANT_KEY, "admin-owner")
        self.assertEqual(saved["status"], "active")
        self.assertEqual(oauth._decrypt(saved["kc_refresh"]), "next-private-refresh")
        # A changed identity on renewal is denied and stored encrypted tokens erased.
        saved["kc_expires_at"] = 0
        store.save(cp.GRANT_KEY, "admin-owner", "active", saved)
        cp.chk_jwt_token.return_value = {"sub": "different-cp"}
        with self.assertRaisesRegex(ValueError, "must be renewed"):
            asyncio.run(cp.get_actor("admin-owner"))
        self.assertNotIn("kc_access", store.get(cp.GRANT_KEY, "admin-owner"))
        self.assertEqual(store.get(cp.GRANT_KEY, "admin-owner")["status"], "revoked")

    def test_existing_grant_never_skips_live_role_and_company_check(self):
        self.assertEqual(self._login(self._form()).status_code, 303)
        cp.check_user.return_value = {"user_id": 17, "role": "admin"}
        with self.assertRaisesRegex(ValueError, "real CP"):
            asyncio.run(cp.get_actor("admin-owner"))
        self.assertFalse(asyncio.run(cp.connection_status("admin-owner"))["connected"])
        cp.check_user.return_value = {"user_id": 17, "role": "CP"}
        cp.get_approved_cp_company_name_by_user_id.return_value = "다른 회사"
        with self.assertRaisesRegex(ValueError, "configured company"):
            asyncio.run(cp.get_actor("admin-owner"))

    def test_private_server_setup_reuses_cp_verification_without_credential_output(self):
        actor = asyncio.run(cp.connect_credentials("admin-owner", "cp@example.test", "test-only"))
        self.assertEqual(actor, {"user_id": 17, "role": "CP", "company_name": "라이크노벨"})
        self.assertNotIn("kc_access", actor)
        oauth._keycloak.assert_awaited_once_with({
            "grant_type": "password", "username": "cp@example.test", "password": "test-only",
            "scope": "openid offline_access",
        })
        raw = json.dumps(store.get(cp.GRANT_KEY, "admin-owner"))
        self.assertNotIn("test-only", raw)
        self.assertNotIn("private-cp-access", raw)
        cp.check_user.return_value = {"user_id": 17, "role": "admin"}
        with self.assertRaisesRegex(ValueError, "real CP"):
            asyncio.run(cp.connect_credentials("admin-owner", "cp@example.test", "test-only"))


if __name__ == "__main__":
    unittest.main()
