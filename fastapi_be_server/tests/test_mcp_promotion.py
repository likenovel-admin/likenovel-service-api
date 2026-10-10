import copy
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from app.services.ai import mcp_promotion as promotion, mcp_store as store


class PromotionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "LIKENOVEL_MCP_STATE_DB": self.directory.name + "/receipts.db",
        })
        self.environment.start()
        self.actor = {"user_id": 12, "role": "CP"}
        self.before = {
            "product": {"product_id": 45, "user_id": 12, "cp_user_id": 12,
                        "price_type": "paid", "series_regular_price": 100,
                        "status_code": "ongoing", "uci": "test-uci", "title": "preserve",
                        "primary_genre_id": 1, "sub_genre_id": 2},
            "episodes": [{"episode_id": n, "episode_no": n, "price_type": "paid"}
                         for n in range(1, 101)],
            "campaigns": [],
        }
        self.end = datetime.now(promotion.KST) + timedelta(days=7)

    def tearDown(self):
        self.environment.stop()
        self.directory.cleanup()

    def prepare(self):
        return promotion.prepare_hundred_free("owner", self.before, self.actor, self.end)

    def test_cp_impersonation_and_missing_episodes_rejected(self):
        for actor in ({"role": "admin", "user_id": 12}, {"role": "CP", "user_id": 999}):
            with self.assertRaises(ValueError):
                promotion.prepare_hundred_free("owner", self.before, actor, self.end)
        missing = copy.deepcopy(self.before)
        missing["episodes"].pop(24)
        with self.assertRaises(ValueError):
            promotion.prepare_hundred_free("owner", missing, self.actor, self.end)
        with self.assertRaises(ValueError):
            promotion.prepare_hundred_free("owner", self.before, self.actor, self.end.replace(tzinfo=None))

    def test_patch_preserves_non_target_fields_and_timezone(self):
        plan = self.prepare()
        self.assertEqual(set(plan["request"]), {
            "status_code", "hundred_free_campaign_enabled", "hundred_free_campaign_ends_at",
            "primary_genre_id", "sub_genre_id",
        })
        self.assertEqual(plan["request"]["status_code"], "ongoing")
        self.assertEqual(plan["request"]["primary_genre_id"], self.before["product"]["primary_genre_id"])
        self.assertEqual(plan["request"]["sub_genre_id"], self.before["product"]["sub_genre_id"])
        self.assertEqual(plan["before"], self.before)
        self.assertIsNone(datetime.fromisoformat(plan["request"]["hundred_free_campaign_ends_at"]).tzinfo)

    async def test_disabled_missing_intent_scope_owner_and_actor_fail_before_db(self):
        plan = self.prepare()
        db = AsyncMock()
        common = {"approved_plan_id": plan["plan_id"], "writes_enabled": True,
                  "scopes": [promotion.CAMPAIGN_SCOPE]}
        for changes in ({"writes_enabled": False}, {"approved_plan_id": None},
                        {"scopes": ["likenovel.mcp.write"]}):
            with self.assertRaises(ValueError):
                await promotion.apply_plan("owner", plan["plan_id"], db, self.actor,
                                           **{**common, **changes})
        with self.assertRaises(ValueError):
            await promotion.apply_plan("other-owner", plan["plan_id"], db, self.actor, **common)
        with self.assertRaises(ValueError):
            await promotion.apply_plan("owner", plan["plan_id"], db,
                                       {"role": "CP", "user_id": 999}, **common)
        db.execute.assert_not_called()

    async def test_unresolved_receipt_never_reapplies(self):
        plan = self.prepare()
        db = AsyncMock()
        store.claim("promotion-apply:" + plan["plan_id"], "owner", {"kind": "hundred-free"})
        with self.assertRaisesRegex(ValueError, "unresolved"):
            await promotion.apply_plan(
                "owner", plan["plan_id"], db, self.actor, approved_plan_id=plan["plan_id"],
                writes_enabled=True, scopes=[promotion.CAMPAIGN_SCOPE],
            )
        db.execute.assert_not_called()

    async def test_completed_receipt_returns_without_duplicate_write(self):
        plan = self.prepare()
        db = AsyncMock()
        store.save("promotion-apply:" + plan["plan_id"], "owner", "completed", {"kind": "hundred-free"})
        receipt = await promotion.apply_plan(
            "owner", plan["plan_id"], db, self.actor, approved_plan_id=plan["plan_id"],
            writes_enabled=True, scopes=[promotion.CAMPAIGN_SCOPE],
        )
        self.assertEqual(receipt["status"], "completed")
        db.execute.assert_not_called()

    async def test_campaign_calls_existing_cp_service_once_and_checks_readback(self):
        plan = self.prepare()
        after = copy.deepcopy(self.before)
        after["product"]["paid_episode_no"] = 101
        for episode in after["episodes"]:
            episode["price_type"] = "free"
        after["campaigns"] = [{"campaign_free_start_no": 1, "campaign_free_end_no": 100}]
        db = Mock()
        db.begin.return_value.__aenter__ = AsyncMock()
        db.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(promotion, "campaign_snapshot", AsyncMock(side_effect=[self.before, after])), \
                patch("app.services.partner.partner_product_service.get_approved_cp_company_name_by_user_id",
                      AsyncMock(return_value="verified company")), \
                patch("app.services.partner.partner_product_service.put_product", AsyncMock()) as write:
            receipt = await promotion.apply_plan(
                "owner", plan["plan_id"], db, self.actor, approved_plan_id=plan["plan_id"],
                writes_enabled=True, scopes=[promotion.CAMPAIGN_SCOPE],
                expected_cp_company_name="verified company",
            )
        self.assertEqual(receipt["status"], "completed")
        self.assertFalse(receipt["public_verified"])
        write.assert_awaited_once()
        self.assertEqual(write.await_args.kwargs["user_data"]["role"], "CP")

    async def test_changed_snapshot_never_calls_existing_write(self):
        plan = self.prepare()
        changed = copy.deepcopy(self.before)
        changed["product"]["title"] = "concurrent edit"
        db = Mock()
        db.begin.return_value.__aenter__ = AsyncMock()
        db.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        with patch.object(promotion, "campaign_snapshot", AsyncMock(return_value=changed)), \
                patch("app.services.partner.partner_product_service.put_product", AsyncMock()) as write:
            with self.assertRaisesRegex(ValueError, "changed"):
                await promotion.apply_plan(
                    "owner", plan["plan_id"], db, self.actor, approved_plan_id=plan["plan_id"],
                    writes_enabled=True, scopes=[promotion.CAMPAIGN_SCOPE],
                    expected_cp_company_name="verified company",
                )
        write.assert_not_awaited()

    async def test_real_partner_service_accepts_frozen_genres_and_narrow_campaign(self):
        """Execute real validation/query building; only the DB transport is fake."""
        from app.services.partner import partner_product_service
        from app.schemas.partner import PutProductReqBody

        calls = []
        async def execute(query, params):
            sql = str(query).lower()
            calls.append((sql, params))
            result = Mock()
            result.scalar.return_value = 1
            rows = []
            if "tb_standard_keyword" in sql:
                rows = [{"keyword_name": "판타지" if "primary_genre_id" in params else "스릴러"}]
            elif "select uci, isbn" in sql:
                rows = [{**self.before["product"], "isbn": None, "single_regular_price": 0,
                         "single_rental_price": 0, "blind_yn": "N", "open_yn": "Y",
                         "monopoly_yn": "N", "contract_yn": "Y", "paid_apply_status": None}]
            elif "max(episode_no)" in sql:
                rows = [{"max_episode_no": 100}]
            result.mappings.return_value.all.return_value = rows
            result.mappings.return_value.one_or_none.return_value = rows[0] if rows else None
            return result

        db = Mock()
        db.execute = AsyncMock(side_effect=execute)
        plan = self.prepare()
        request = PutProductReqBody.model_validate(plan["request"])
        response = await partner_product_service.put_product(request, 45, db, user_data=self.actor)
        self.assertIs(response["result"], request)
        product_params = next(params for sql, params in calls if sql.startswith("update tb_product set"))
        self.assertEqual(product_params["primary_genre_id"], self.before["product"]["primary_genre_id"])
        self.assertEqual(product_params["sub_genre_id"], self.before["product"]["sub_genre_id"])
        self.assertEqual(product_params["paid_episode_no"], 101)
        self.assertNotIn("title", product_params)
        self.assertNotIn("series_regular_price", product_params)
        campaign_params = next(params for sql, params in calls
                               if "insert into tb_product_free_episode_campaign" in sql)
        self.assertEqual((campaign_params["campaign_free_start_no"],
                          campaign_params["campaign_free_end_no"]), (1, 100))

    def test_approval_keeps_application_separate_from_paid_price_changes(self):
        before = {"application": {"id": 7, "product_id": 45, "status_code": "review", "use_yn": "Y"},
                  "product": {"product_id": 45, "contract_yn": "Y", "cp_user_id": 12, "price_type": "free"}}
        plan = promotion.prepare_paid_approval("owner", before, {"role": "admin", "user_id": 3})
        self.assertEqual(plan["request"], {"apply_id": 7})
        self.assertEqual(before["product"]["price_type"], "free")
        before["application"]["status_code"] = "denied"
        with self.assertRaises(ValueError):
            promotion.prepare_paid_approval("owner", before, {"role": "admin", "user_id": 3})

    async def test_banner_bad_link_and_missing_media_integration_blocked(self):
        payload = {"position": "main", "division": "top", "title": "explicit request",
                   "show_start_date": "2026-10-12", "show_end_date": "2026-10-19",
                   "image_id": 100, "mobile_image_id": 100, "url": "https://likenovel.net/works/45"}
        with self.assertRaises(ValueError):
            promotion.prepare_banner("owner", {**payload, "url": "javascript:alert(1)"}, [],
                                     allowed_link_hosts={"likenovel.net"})
        plan = promotion.prepare_banner("owner", payload, [], allowed_link_hosts={"likenovel.net"})
        with self.assertRaisesRegex(ValueError, "verified media"):
            await promotion.apply_plan("owner", plan["plan_id"], AsyncMock(), {"role": "admin", "user_id": 3},
                                       approved_plan_id=plan["plan_id"], writes_enabled=True,
                                       scopes=[promotion.BANNER_SCOPE])


if __name__ == "__main__":
    unittest.main()
