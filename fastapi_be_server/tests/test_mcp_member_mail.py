import base64
import json
import os
import tempfile
import time
import unittest
from email import policy
from email.parser import BytesParser
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
import jwt
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.services.ai import mcp_member_mail as mail, mcp_store as store


def database(rows):
    result = Mock()
    result.mappings.return_value.all.return_value = rows
    return Mock(execute=AsyncMock(return_value=result))


def sent_message(campaign_id, data):
    message = BytesParser(policy=policy.default).parsebytes(mail._mime(campaign_id, data))
    return {
        "id": "gmail123", "labelIds": ["SENT"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [{"name": key, "value": str(value)} for key, value in message.items()],
            "body": {"data": base64.urlsafe_b64encode(message.get_payload(decode=True)).decode()},
        },
    }


class MemberMailTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = {
            "token_encryption_key": Fernet.generate_key().decode(),
            "member_mail_enabled": True,
            "member_mail_service_account_file": self.temp.name + "/private-key.json",
        }
        self.config_patch = patch.object(mail, "load_config", return_value=self.config)
        self.config_patch.start()
        self.env_patch = patch.dict(os.environ, {
            "LIKENOVEL_MCP_STATE_DB": self.temp.name + "/receipts.sqlite3",
        })
        self.env_patch.start()
        self.addCleanup(self.config_patch.stop)
        self.addCleanup(self.env_patch.stop)
        self.addCleanup(self.temp.cleanup)
        self.rows = [{"user_id": 1, "email": "reader@example.test"}]

    async def campaign(self):
        preview = await mail.preview_members("admin-sub", database(self.rows), {"purpose": "marketing"})
        result = mail.prepare_campaign("admin-sub", preview["receipt_id"], "라이크노벨 안내", "첫째 줄\n둘째 줄")
        mail.record_user_authorization(
            "admin-sub", result["receipt_id"], result["content_hash"],
            source="direct_user_command", evidence_ref="trusted-user-event:1",
        )
        return result

    async def test_parameterized_filters_privacy_and_no_partial_audience(self):
        rows = [
            *self.rows, {"user_id": 2, "email": "READER@example.test"},
            {"user_id": 3, "email": "outed;old@example.test"},
            {"user_id": 4, "email": "bad@example.test\n"},
            {"user_id": 5, "email": "agent@ai-reader.likenovel.net"},
        ]
        db = database(rows)
        preview = await mail.preview_members("admin-sub", db, {
            "purpose": "marketing", "user_ids": [5, 4, 3, 2, 1],
            "joined_from": "2026-10-01T00:00:00", "joined_before": "2026-10-02T00:00:00",
        })
        self.assertEqual(preview["recipient_count"], 1)
        self.assertEqual(preview["excluded_invalid_or_duplicate_count"], 4)
        self.assertEqual(preview["masked_sample"], [{"user_id": 1, "email": "***@example.test"}])
        query, params = db.execute.await_args.args
        sql = str(query)
        self.assertIn("u.use_yn = 'Y'", sql)
        self.assertIn("u.role_type = 'normal'", sql)
        self.assertIn("tb_ai_reader_agent", sql)
        self.assertIn("n.noti_type = 'marketing'", sql)
        self.assertIn("n.updated_date desc, n.id desc", sql)
        self.assertIn(":joined_from", sql)
        self.assertEqual(params["user_ids"], [1, 2, 3, 4, 5])
        record = store.get(preview["receipt_id"], "admin-sub")
        self.assertNotIn("reader@example.test", str(record))
        self.assertNotIn(b"reader@example.test", Path(self.temp.name + "/receipts.sqlite3").read_bytes())
        self.assertIsNone(store.get(preview["receipt_id"], "another-admin"))
        with self.assertRaisesRegex(ValueError, "no partial"):
            await mail.preview_members("admin-sub", database(self.rows * 501), {})

    async def test_invalid_filters_header_injection_and_expiry_are_rejected(self):
        for filters in ({"sql": "drop table tb_user"}, {"user_ids": [True]}, {"user_ids": [1, 1]},
                        {"user_ids": ["1 OR 1=1"]}, {"purpose": "unknown"},
                        {"joined_from": "2026-10-11T00:00:00+09:00"},
                        {"joined_from": "2026-10-12", "joined_before": "2026-10-11"}):
            with self.subTest(filters=filters):
                with self.assertRaises(ValueError):
                    await mail.preview_members("admin-sub", database(self.rows), filters)
        preview = await mail.preview_members("admin-sub", database(self.rows), {})
        with self.assertRaises(ValueError):
            mail.prepare_campaign("admin-sub", preview["receipt_id"], "안내\nBcc: victim@example.test", "내용")
        with patch.object(mail.time, "time", return_value=time.time() + 1000):
            with self.assertRaisesRegex(ValueError, "expired"):
                mail.prepare_campaign("admin-sub", preview["receipt_id"], "제목", "내용")
        empty = await mail.preview_members("admin-sub", database([]), {})
        with self.assertRaisesRegex(ValueError, "No eligible"):
            mail.prepare_campaign("admin-sub", empty["receipt_id"], "제목", "내용")

    async def test_only_matching_user_instruction_authorizes_and_disabled_is_explicit(self):
        campaign = await self.campaign()
        for source, digest in (("autonomous_proposal", campaign["content_hash"]),
                               ("direct_user_command", "0" * 64)):
            with self.assertRaises(ValueError):
                mail.record_user_authorization(
                    "admin-sub", campaign["receipt_id"], digest, source=source, evidence_ref="event:2",
                )
        with self.assertRaises(ValueError):
            mail.prepare_campaign("another-admin", campaign["receipt_id"], "제목", "본문")
        self.config["member_mail_enabled"] = False
        self.assertFalse(mail.capability_status()["enabled"])
        with patch.object(mail, "WorkspaceAdminGmail") as adapter:
            with self.assertRaisesRegex(RuntimeError, "disabled"):
                await mail.send_campaign("admin-sub", campaign["receipt_id"], database(self.rows))
            adapter.assert_not_called()

    async def test_bcc_send_full_readback_and_repeat_do_not_resend(self):
        campaign = await self.campaign()
        data = mail._open(store.get(campaign["receipt_id"], "admin-sub"))
        message = sent_message(campaign["receipt_id"], data)
        request = AsyncMock(side_effect=[{"id": "gmail123"}, message])
        with patch.object(mail.WorkspaceAdminGmail, "request", request):
            result = await mail.send_campaign("admin-sub", campaign["receipt_id"], database(self.rows))
            repeated = await mail.send_campaign("admin-sub", campaign["receipt_id"], database(self.rows))
        self.assertTrue(result["sent_verified"])
        self.assertTrue(repeated["sent_verified"])
        self.assertEqual(request.await_count, 2)
        sent_raw = request.await_args_list[0].kwargs["raw"]
        parsed = BytesParser(policy=policy.default).parsebytes(sent_raw)
        self.assertEqual(parsed["From"], mail.SENDER)
        self.assertEqual(parsed["To"], mail.SENDER)
        self.assertEqual(parsed["Bcc"], "reader@example.test")
        self.assertIsNone(parsed["Cc"])
        self.assertEqual(request.await_args_list[1].kwargs["params"], {"format": "full"})

    async def test_lost_send_response_reconciles_sent_without_resend(self):
        campaign = await self.campaign()
        data = mail._open(store.get(campaign["receipt_id"], "admin-sub"))
        with patch.object(mail.WorkspaceAdminGmail, "request", AsyncMock(side_effect=TimeoutError)) as request:
            with self.assertRaisesRegex(RuntimeError, "uncertain"):
                await mail.send_campaign("admin-sub", campaign["receipt_id"], database(self.rows))
            result = await mail.send_campaign("admin-sub", campaign["receipt_id"], database(self.rows))
            self.assertEqual(result["status"], "uncertain")
            self.assertTrue(result["may_have_sent"])
            self.assertEqual(request.await_count, 1)
        with patch.object(mail.WorkspaceAdminGmail, "request", AsyncMock(side_effect=[
            {"messages": [{"id": "gmail123"}]}, sent_message(campaign["receipt_id"], data),
        ])) as request:
            result = await mail.verify_sent("admin-sub", campaign["receipt_id"])
        self.assertTrue(result["sent_verified"])
        self.assertEqual(request.await_args_list[0].args[0], "/messages")
        self.assertIn("rfc822msgid:", request.await_args_list[0].kwargs["params"]["q"])
        self.assertTrue(all(call.args[0] != "/messages/send" for call in request.await_args_list))

    async def test_fresh_audience_change_blocks_send_and_wrong_sent_bcc_is_unverified(self):
        campaign = await self.campaign()
        with patch.object(mail.WorkspaceAdminGmail, "request", AsyncMock()) as request:
            with self.assertRaisesRegex(ValueError, "audience changed"):
                await mail.send_campaign("admin-sub", campaign["receipt_id"], database([]))
            request.assert_not_awaited()
        data = mail._open(store.get(campaign["receipt_id"], "admin-sub"))
        message = sent_message(campaign["receipt_id"], data)
        for header in message["payload"]["headers"]:
            if header["name"].lower() == "bcc":
                header["value"] = "other@example.test"
        with patch.object(mail.WorkspaceAdminGmail, "request", AsyncMock(side_effect=[
            {"id": "gmail123"}, message,
        ])):
            result = await mail.send_campaign("admin-sub", campaign["receipt_id"], database(self.rows))
        self.assertFalse(result["sent_verified"])
        self.assertEqual(result["status"], "sent_unverified")
        self.assertIn("do not match", result["action_required"])

    async def test_unresolved_search_does_not_infer_unsent_or_retry(self):
        campaign = await self.campaign()
        record = store.get(campaign["receipt_id"], "admin-sub")
        payload = {key: record[key] for key in ("sealed", "recipient_count", "content_hash", "expires_at")}
        store.save(campaign["receipt_id"], "admin-sub", "uncertain", payload)
        with patch.object(mail.WorkspaceAdminGmail, "request", AsyncMock(return_value={"messages": []})) as request:
            result = await mail.verify_sent("admin-sub", campaign["receipt_id"])
        self.assertFalse(result["sent_verified"])
        self.assertTrue(result["may_have_sent"])
        self.assertIn("never resend", result["action_required"])
        self.assertEqual(request.await_count, 1)

    async def test_existing_dwd_jwt_subject_scopes_and_fixed_google_endpoints(self):
        private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = private.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode()
        path = Path(self.config["member_mail_service_account_file"])
        path.write_text(json.dumps({
            "type": "service_account", "client_email": "test@project.iam.gserviceaccount.com",
            "private_key": pem, "token_uri": mail.TOKEN_URL,
        }))
        path.chmod(0o600)
        requests = []

        def respond(request):
            requests.append(request)
            if str(request.url) == mail.TOKEN_URL:
                from urllib.parse import parse_qs
                form = parse_qs(request.content.decode())
                claims = jwt.decode(
                    form["assertion"][0], private.public_key(),
                    algorithms=["RS256"], audience=mail.TOKEN_URL,
                )
                self.assertEqual(claims["sub"], mail.SENDER)
                self.assertEqual(claims["scope"].split(), list(mail.GMAIL_SCOPES))
                return httpx.Response(200, json={"access_token": "synthetic-test-token"})
            self.assertEqual(str(request.url), mail.GMAIL_BASE + "/messages/send")
            self.assertEqual(request.headers["Authorization"], "Bearer synthetic-test-token")
            return httpx.Response(200, json={"id": "synthetic-message-id"})

        client_type = httpx.AsyncClient
        with patch.object(mail, "AsyncClient", side_effect=lambda **kwargs: client_type(
                **kwargs, transport=httpx.MockTransport(respond))):
            result = await mail.WorkspaceAdminGmail(str(path)).request("/messages/send", raw=b"sample")
        self.assertEqual(result["id"], "synthetic-message-id")
        self.assertEqual(len(requests), 2)
        self.assertEqual(json.loads(requests[1].content), {"raw": "c2FtcGxl"})
        path.chmod(0o644)
        async with client_type(transport=httpx.MockTransport(respond)) as client:
            with self.assertRaisesRegex(RuntimeError, "private absolute"):
                await mail.WorkspaceAdminGmail(str(path))._token(client)
        self.assertEqual(len(requests), 2)

    async def test_profile_proof_requires_fixed_admin_and_never_sends(self):
        gmail = mail.WorkspaceAdminGmail(self.config["member_mail_service_account_file"])
        with patch.object(gmail, "request", AsyncMock(return_value={
            "emailAddress": mail.SENDER, "messagesTotal": 123, "threadsTotal": 90,
        })) as request:
            result = await gmail.verify_connection()
        request.assert_awaited_once_with("/profile")
        self.assertTrue(result["profile_verified"])
        self.assertFalse(result["send_runtime_verified"])
        self.assertNotIn("messagesTotal", result)
        with patch.object(gmail, "request", AsyncMock(return_value={
            "emailAddress": "other@example.test",
        })):
            with self.assertRaisesRegex(RuntimeError, "fixed admin"):
                await gmail.verify_connection()


if __name__ == "__main__":
    unittest.main()
