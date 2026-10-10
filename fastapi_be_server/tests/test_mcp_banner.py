import io
import base64
import os
import tempfile
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, Mock, patch

from PIL import Image

from app.services.ai import mcp_banner as banner


def pixels(size=(364, 414)):
    body = io.BytesIO()
    Image.new("RGB", size, "blue").save(body, format="PNG")
    return body.getvalue()


class BannerAssetTests(unittest.TestCase):
    def test_real_pixels_and_dimensions_are_verified(self):
        result = banner.validate_image(pixels(), (364, 414))
        self.assertEqual(result["format"], "PNG")
        self.assertEqual(result["size"], [364, 414])
        for value in (b"not an image", pixels((414, 364)), b"x" * (banner.MAX_BYTES + 1)):
            with self.subTest(size=len(value)):
                with self.assertRaises(ValueError):
                    banner.validate_image(value, (364, 414))

    def test_cms_dimensions_and_explicit_unmapped_dimensions(self):
        self.assertEqual(banner._spec("main", "top")[2][0], (364, 414))
        self.assertEqual(banner._spec("viewer", None)[2], ((839, 122), (375, 122)))
        with self.assertRaises(ValueError):
            banner._spec("promotion", None)
        self.assertEqual(banner._spec("promotion", None, 1200, 600)[2][0], (1200, 600))
        with self.assertRaises(ValueError):
            banner._spec("paid", None, 1200, 600)

    def test_file_metadata_has_complete_official_schema(self):
        self.assertEqual(set(banner.FILE_PROPERTIES), {"download_url", "file_id", "mime_type", "file_name"})
        self.assertEqual(banner.FILE_SCHEMA["required"], ["download_url", "file_id"])
        self.assertEqual(banner.FILE_META["openai/fileParams"], ["file", "mobile_file"])

    def test_ssrf_hosts_credentials_ports_private_dns_and_redirects_are_rejected(self):
        public = [(2, 1, 6, "", ("104.18.1.1", 443))]
        private = [(2, 1, 6, "", ("127.0.0.1", 443))]
        with patch.object(banner.socket, "getaddrinfo", return_value=public):
            banner._safe_host("https://files.oaiusercontent.com/file-test?sig=private", {"files.oaiusercontent.com"})
            for url in ("http://files.oaiusercontent.com/x", "https://127.0.0.1/x",
                        "https://files.oaiusercontent.com.evil.test/x",
                        "https://user@files.oaiusercontent.com/x", "https://files.oaiusercontent.com:444/x"):
                with self.subTest(url=url):
                    with self.assertRaises(ValueError):
                        banner._safe_host(url, {"files.oaiusercontent.com"})
        with patch.object(banner.socket, "getaddrinfo", return_value=private):
            with self.assertRaises(ValueError):
                banner._safe_host("https://files.oaiusercontent.com/x", {"files.oaiusercontent.com"})
        with self.assertRaises(ValueError):
            banner._NoRedirect().redirect_request(None, None, 302, "redirect", None, "https://127.0.0.1")


class _Transaction:
    async def __aenter__(self):
        return self
    async def __aexit__(self, *args):
        return False


class _DB:
    def begin(self):
        return _Transaction()


class BannerPlanTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LIKENOVEL_MCP_STATE_DB": self.directory.name + "/receipts.db"})
        self.env.start()
        self.db = _DB()
        self.request = {"position": "paid", "title": "100화 무료 안내", "url": "https://likenovel.net/product/1",
                        "show_start_date": "2026-10-01", "show_end_date": "2027-01-01"}
        self.file = {"download_url": "https://files.oaiusercontent.com/file-test", "file_id": "file-test"}

    async def asyncTearDown(self):
        self.env.stop()
        self.directory.cleanup()

    async def prepare(self, before=None):
        with patch.object(banner, "scope_snapshot", AsyncMock(return_value=before or [])), \
             patch.object(banner, "_download_file", return_value=pixels()), \
             patch.object(banner, "load_config", return_value={"resource": "https://api.likenovel.net/mcp"}):
            return await banner.prepare_asset("owner", self.request, self.file, self.db)

    async def test_preparation_stages_private_local_bytes_without_upload_or_publication(self):
        with patch.object(banner.storage_service, "get_presigned_upload_url", AsyncMock()) as upload, \
             patch.object(banner.service, "post_banner", AsyncMock()) as publish:
            plan = await self.prepare()
        upload.assert_not_awaited()
        publish.assert_not_awaited()
        self.assertFalse(plan["published"])
        self.assertNotIn("download_url", str(plan))
        self.assertEqual(banner._asset_path(plan["plan_id"], "primary").stat().st_mode & 0o777, 0o600)
        self.assertEqual(banner.store.get("banner-plan:" + plan["plan_id"], "other"), None)

    async def test_private_previews_are_bounded_and_bind_unchanged_original(self):
        plan = await self.prepare()
        original = banner._asset_path(plan["plan_id"], "primary").read_bytes()
        previews = banner.get_previews("owner", plan["plan_id"])
        self.assertEqual(len(previews), 1)
        self.assertTrue(previews[0].startswith("data:image/webp;base64,"))
        decoded = base64.b64decode(previews[0].split(",", 1)[1])
        self.assertLessEqual(len(decoded), 300_000)
        with Image.open(io.BytesIO(decoded)) as image:
            self.assertLessEqual(image.width, 800)
            self.assertLessEqual(image.height, 600)
        self.assertEqual(banner._asset_path(plan["plan_id"], "primary").read_bytes(), original)
        with self.assertRaises(ValueError):
            banner.get_previews("other", plan["plan_id"])

    async def test_slot_scope_or_missing_approval_cannot_publish(self):
        plan = await self.prepare()
        for kwargs in ({"approved_plan_id": plan["plan_id"], "scopes": ["likenovel.mcp.write"], "writes_enabled": True},
                       {"scopes": [banner.BANNER_SCOPE], "writes_enabled": True},
                       {"approved_plan_id": plan["plan_id"], "scopes": [banner.BANNER_SCOPE]}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    await banner.publish_prepared("owner", plan["plan_id"], self.db,
                                                  {"role": "admin", "user_id": 1}, **kwargs)

    async def test_concurrent_banner_edit_blocks_before_any_external_upload(self):
        plan = await self.prepare()
        with patch.object(banner, "scope_snapshot", AsyncMock(return_value=[{"id": 9, "show_order": 1}])), \
             patch.object(banner.storage_service, "get_presigned_upload_url", AsyncMock()) as upload:
            with self.assertRaisesRegex(ValueError, "scope changed"):
                await banner.publish_prepared("owner", plan["plan_id"], self.db, {"role": "admin", "user_id": 1},
                                              approved_plan_id=plan["plan_id"], scopes=[banner.BANNER_SCOPE], writes_enabled=True)
        upload.assert_not_awaited()

    async def test_approved_publication_reuses_storage_and_cms_and_is_not_repeated(self):
        plan = await self.prepare()
        row = {**plan["request"], "image_id": 22, "mobile_image_id": 22, "id": 88}
        with patch.object(banner, "scope_snapshot", AsyncMock(side_effect=[[], [], [row]])), \
             patch.object(banner, "_safe_host"), \
             patch.object(banner, "_put_upload") as put_upload, \
             patch.object(banner.storage_service, "get_presigned_upload_url", AsyncMock(return_value={"data": {"fileId": 22, "uploadPath": "https://r2.test/signed"}})) as upload, \
             patch.object(banner.service, "post_banner", AsyncMock()) as publish:
            kwargs = {"approved_plan_id": plan["plan_id"], "scopes": [banner.BANNER_SCOPE], "writes_enabled": True}
            first = await banner.publish_prepared("owner", plan["plan_id"], self.db, {"role": "admin", "user_id": 1}, **kwargs)
            second = await banner.publish_prepared("owner", plan["plan_id"], self.db, {"role": "admin", "user_id": 1}, **kwargs)
        upload.assert_awaited_once()
        publish.assert_awaited_once()
        put_upload.assert_called_once()
        self.assertEqual(first["banner_id"], 88)
        self.assertFalse(first["public_verified"])
        self.assertEqual(second["banner_id"], 88)

    async def test_unresolved_publication_receipt_blocks_repeat_upload(self):
        plan = await self.prepare()
        banner.store.claim("banner-publish:" + plan["plan_id"], "owner", {"kind": "banner"})
        with patch.object(banner.storage_service, "get_presigned_upload_url", AsyncMock()) as upload:
            with self.assertRaisesRegex(ValueError, "Unresolved"):
                await banner.publish_prepared("owner", plan["plan_id"], self.db, {"role": "admin", "user_id": 1},
                                              approved_plan_id=plan["plan_id"], scopes=[banner.BANNER_SCOPE], writes_enabled=True)
        upload.assert_not_awaited()

    async def test_public_verification_matches_link_and_actual_cdn_pixels(self):
        plan = await self.prepare()
        receipt = {"kind": "banner", "plan_id": plan["plan_id"], "banner_id": 88,
                   "request": plan["request"], "public_verified": False}
        banner.store.save("banner-publish:" + plan["plan_id"], "owner", "completed", receipt)
        client = AsyncMock()
        client.get.return_value = Mock(status_code=200, json=Mock(return_value={"data": [{
            "id": 88, "linkPath": plan["request"]["url"], "pcImgPath": "https://cdn.likenovel.net/user/test.png"}]}))
        context = AsyncMock()
        context.__aenter__.return_value = client
        clock = Mock(wraps=datetime)
        clock.now.return_value = datetime(2026, 10, 12, 12, tzinfo=banner.KST)
        with patch.object(banner, "AsyncClient", return_value=context), \
             patch.object(banner, "load_config", return_value={"resource": "https://api.likenovel.net/mcp"}), \
             patch.object(banner, "datetime", clock), \
             patch.object(banner, "_download", return_value=pixels()):
            result = await banner.verify_public("owner", plan["plan_id"])
        self.assertTrue(result["public_verified"])
        self.assertEqual(result["exposure_status"], "visible")
        client.get.assert_awaited_once_with("https://api.likenovel.net/v1/query/banners/paid")
        with patch.object(banner, "AsyncClient", return_value=context), \
             patch.object(banner, "load_config", return_value={"resource": "https://api.likenovel.net/mcp"}), \
             patch.object(banner, "datetime", clock), \
             patch.object(banner, "_download", return_value=pixels((414, 364))):
            with self.assertRaises(ValueError):
                await banner.verify_public("owner", plan["plan_id"])

    async def test_future_scheduled_banner_is_not_reported_publicly_visible(self):
        plan = await self.prepare()
        receipt = {"kind": "banner", "plan_id": plan["plan_id"], "banner_id": 88,
                   "request": plan["request"], "public_verified": False}
        banner.store.save("banner-publish:" + plan["plan_id"], "owner", "completed", receipt)
        clock = Mock(wraps=datetime)
        clock.now.return_value = datetime(2026, 9, 1, tzinfo=banner.KST)
        with patch.object(banner, "datetime", clock), patch.object(banner, "AsyncClient") as client:
            result = await banner.verify_public("owner", plan["plan_id"])
        self.assertFalse(result["public_verified"])
        self.assertEqual(result["exposure_status"], "outside_scheduled_window")
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
