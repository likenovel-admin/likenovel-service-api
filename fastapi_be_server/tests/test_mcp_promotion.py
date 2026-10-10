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

    def conversion_before(self):
        return {
            "application": {"id": 7, "product_id": 45, "status_code": "accepted", "use_yn": "Y"},
            "product": {"product_id": 45, "product_type": "normal", "price_type": "free",
                        "paid_episode_no": None, "paid_open_date": None, "title": "preserve"},
            "episodes": [{"episode_id": n, "episode_no": n, "price_type": "free"}
                         for n in range(1, 51)],
            "campaigns": [],
        }

    def test_paid_conversion_requires_accepted_request_and_explicit_episode_bounds(self):
        before = self.conversion_before()
        actor = {"role": "admin", "user_id": 3}
        plan = promotion.prepare_paid_conversion("owner", before, actor, 26)
        self.assertEqual(plan["request"]["paid_episode_no"], 26)
        self.assertFalse(plan["request"]["waiting_for_free_enabled"])
        self.assertIsNone(plan["request"]["waiting_for_free_period_months"])
        for episode_no in (True, 0, -1, 52):
            with self.assertRaises(ValueError):
                promotion.prepare_paid_conversion("owner", before, actor, episode_no)
        for field, value in (("price_type", "paid"), ("paid_episode_no", 26),
                             ("paid_open_date", "2026-10-11T10:00:00")):
            changed = copy.deepcopy(before)
            changed["product"][field] = value
            with self.assertRaises(ValueError):
                promotion.prepare_paid_conversion("owner", changed, actor, 26)
        before["application"]["status_code"] = "review"
        with self.assertRaises(ValueError):
            promotion.prepare_paid_conversion("owner", before, actor, 26)

    async def test_real_paid_conversion_service_saves_settings_and_defers_effect(self):
        from app.services.admin import admin_user_service
        from app.schemas.admin import PostApplyPaidConversionReqBody

        calls = []
        async def execute(query, params):
            sql = str(query).lower()
            calls.append((sql, params))
            result = Mock()
            result.rowcount = 1
            result.mappings.return_value.one_or_none.return_value = {
                "id": 7, "product_id": 45, "status_code": "accepted", "product_type": "normal",
                "price_type": "free", "paid_open_date": None, "paid_episode_no": None,
                "episode_count": 50,
            }
            return result

        plan = promotion.prepare_paid_conversion(
            "owner", self.conversion_before(), {"role": "admin", "user_id": 3}, 26,
        )
        db = Mock()
        db.execute = AsyncMock(side_effect=execute)
        result = await admin_user_service.apply_paid_conversion_by_admin(
            7, PostApplyPaidConversionReqBody.model_validate(plan["request"]), 3, db,
        )
        self.assertEqual(result["data"]["paidEpisodeNo"], 26)
        self.assertFalse(result["data"]["waitingForFreeEnabled"])
        updates = [(sql, params) for sql, params in calls if "update tb_product p" in sql]
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0][1]["updated_id"], 3)
        self.assertIn("p.paid_open_date = now()", updates[0][0])
        self.assertNotIn("set e.price_type", updates[0][0])
        self.assertNotIn("p.price_type = 'paid'", updates[0][0])
        self.assertFalse(any("tb_applied_promotion" in sql for sql, _ in calls))

    async def test_conversion_apply_requires_separate_scope_and_returns_transition_pending(self):
        actor = {"role": "admin", "user_id": 3}
        before = self.conversion_before()
        plan = promotion.prepare_paid_conversion("owner", before, actor, 26)
        after = copy.deepcopy(before)
        after["product"]["paid_episode_no"] = 26
        after["product"]["paid_open_date"] = "2026-10-11T10:00:00"
        db = Mock()
        db.begin.return_value.__aenter__ = AsyncMock()
        db.begin.return_value.__aexit__ = AsyncMock(return_value=False)
        with self.assertRaisesRegex(ValueError, "separate"):
            await promotion.apply_plan(
                "owner", plan["plan_id"], db, actor, approved_plan_id=plan["plan_id"],
                writes_enabled=True, scopes=[promotion.PAID_APPROVAL_SCOPE],
            )
        with patch.object(promotion, "paid_conversion_snapshot", AsyncMock(side_effect=[before, after])), \
                patch("app.services.admin.admin_user_service.apply_paid_conversion_by_admin", AsyncMock()) as write:
            receipt = await promotion.apply_plan(
                "owner", plan["plan_id"], db, actor, approved_plan_id=plan["plan_id"],
                writes_enabled=True, scopes=[promotion.PAID_CONVERSION_SCOPE],
            )
        write.assert_awaited_once()
        self.assertEqual(receipt["status"], "completed")
        self.assertTrue(receipt["transition_pending"])
        self.assertFalse(receipt["effective_conversion_verified"])
        self.assertFalse(receipt["public_verified"])
        self.assertFalse(receipt["approval_only"])

    async def test_conversion_cas_and_unrelated_field_mutation_are_rejected(self):
        actor = {"role": "admin", "user_id": 3}
        before = self.conversion_before()
        for snapshot_change in ("before", "after"):
            with self.subTest(snapshot_change=snapshot_change):
                plan = promotion.prepare_paid_conversion("owner", before, actor, 26)
                changed = copy.deepcopy(before)
                changed["product"]["title"] = "unexpected edit"
                if snapshot_change == "after":
                    changed["product"]["paid_episode_no"] = 26
                    changed["product"]["paid_open_date"] = "2026-10-11T10:00:00"
                    snapshots = [before, changed]
                else:
                    snapshots = [changed]
                db = Mock()
                db.begin.return_value.__aenter__ = AsyncMock()
                db.begin.return_value.__aexit__ = AsyncMock(return_value=False)
                with patch.object(promotion, "paid_conversion_snapshot", AsyncMock(side_effect=snapshots)), \
                        patch("app.services.admin.admin_user_service.apply_paid_conversion_by_admin", AsyncMock()) as write:
                    with self.assertRaises(ValueError):
                        await promotion.apply_plan(
                            "owner", plan["plan_id"], db, actor, approved_plan_id=plan["plan_id"],
                            writes_enabled=True, scopes=[promotion.PAID_CONVERSION_SCOPE],
                        )
                if snapshot_change == "before":
                    write.assert_not_awaited()
                self.assertNotEqual(store.get("promotion-apply:" + plan["plan_id"], "owner")["status"],
                                    "completed")

    def public_conversion_fixture(self):
        before = self.conversion_before()
        for row in before["episodes"]:
            row["open_yn"] = "Y"
        plan = promotion.prepare_paid_conversion("owner", before, {"role": "admin", "user_id": 3}, 26)
        current = copy.deepcopy(before)
        current["product"].update({"paid_episode_no": 26, "paid_open_date": "2026-10-11T10:00:00",
                                   "price_type": "paid"})
        for row in current["episodes"]:
            if row["episode_no"] >= 26:
                row["price_type"] = "paid"
        store.save("promotion-apply:" + plan["plan_id"], "owner", "completed",
                   {"kind": "paid-conversion", "after": current})
        public = {
            "product": {"productId": 45, "priceType": "paid", "paidEpisodeNo": 26},
            "episodes": {row["episode_id"]: {"episode_no": row["episode_no"],
                                           "price_type": row["price_type"]}
                         for row in current["episodes"]},
            "complete": True, "urls": ["https://api.example.test/public"],
        }
        return plan, current, public

    def db_context(self):
        context = Mock()
        context.__aenter__ = AsyncMock(return_value=Mock())
        context.__aexit__ = AsyncMock(return_value=False)
        return context

    async def test_verification_requires_owned_receipt_and_never_mutates_it(self):
        plan, current, public = self.public_conversion_fixture()
        with self.assertRaises(ValueError):
            await promotion.verify_public("other-owner", plan["plan_id"])
        receipt = store.get("promotion-apply:" + plan["plan_id"], "owner")
        with patch.object(promotion, "likenovel_db_session", return_value=self.db_context()), \
                patch.object(promotion, "paid_conversion_snapshot", AsyncMock(return_value=current)), \
                patch.object(promotion, "_public_prices", AsyncMock(return_value=public)), \
                patch.object(promotion, "load_config", return_value={"resource": "https://api.example.test/mcp"}):
            proof = await promotion.verify_public("owner", plan["plan_id"])
        self.assertTrue(proof["effective_conversion_verified"])
        self.assertTrue(proof["public_verified"])
        self.assertFalse(proof["transition_pending"])
        self.assertEqual(store.get("promotion-apply:" + plan["plan_id"], "owner"), receipt)

    async def test_db_conversion_does_not_claim_public_success_on_failure_or_partial_pages(self):
        plan, current, public = self.public_conversion_fixture()
        for result in ("network-error", "partial-page", "wrong-public-price"):
            with self.subTest(result=result):
                response = copy.deepcopy(public)
                if result == "partial-page":
                    response["complete"] = False
                if result == "wrong-public-price":
                    response["episodes"][26]["price_type"] = "free"
                fetch = AsyncMock(side_effect=RuntimeError("network unavailable")) if result == "network-error" \
                    else AsyncMock(return_value=response)
                with patch.object(promotion, "likenovel_db_session", return_value=self.db_context()), \
                        patch.object(promotion, "paid_conversion_snapshot", AsyncMock(return_value=current)), \
                        patch.object(promotion, "_public_prices", fetch), \
                        patch.object(promotion, "load_config", return_value={"resource": "https://api.example.test/mcp"}):
                    proof = await promotion.verify_public("owner", plan["plan_id"])
                self.assertTrue(proof["effective_conversion_verified"])
                self.assertFalse(proof["public_verified"])

    async def test_paid_approval_verification_reports_public_unneeded(self):
        before = {"application": {"id": 7, "product_id": 45, "status_code": "review", "use_yn": "Y"},
                  "product": {"product_id": 45, "contract_yn": "Y", "cp_user_id": 12}}
        plan = promotion.prepare_paid_approval("owner", before, {"role": "admin", "user_id": 3})
        current = copy.deepcopy(before)
        current["application"]["status_code"] = "accepted"
        store.save("promotion-apply:" + plan["plan_id"], "owner", "completed",
                   {"kind": "paid-approval", "after": current})
        with patch.object(promotion, "likenovel_db_session", return_value=self.db_context()), \
                patch.object(promotion, "_paid_snapshot", AsyncMock(return_value=current)), \
                patch.object(promotion, "_public_prices", AsyncMock()) as public:
            proof = await promotion.verify_public("owner", plan["plan_id"])
        self.assertTrue(proof["db_verified"])
        self.assertIsNone(proof["public_verified"])
        self.assertFalse(proof["public_verification_required"])
        public.assert_not_awaited()

    async def test_hundred_free_public_price_and_period_verification(self):
        plan = self.prepare()
        current = copy.deepcopy(self.before)
        current["product"]["paid_episode_no"] = 101
        for row in current["episodes"]:
            row.update({"price_type": "free", "open_yn": "Y"})
        current["episodes"].append({"episode_id": 101, "episode_no": 101, "price_type": "paid", "open_yn": "Y"})
        current["campaigns"] = [{"campaign_free_start_no": 1, "campaign_free_end_no": 100,
                                 "restore_free_start_no": 1, "restore_free_end_no": 25,
                                 "ends_at": plan["request"]["hundred_free_campaign_ends_at"]}]
        store.save("promotion-apply:" + plan["plan_id"], "owner", "completed",
                   {"kind": "hundred-free", "after": current})
        public = {
            "product": {"productId": 45, "priceType": "paid", "paidEpisodeNo": 101},
            "episodes": {row["episode_id"]: {"episode_no": row["episode_no"], "price_type": row["price_type"]}
                         for row in current["episodes"]}, "complete": True, "urls": [],
        }
        for valid in (True, False):
            response = copy.deepcopy(public)
            if not valid:
                response["episodes"][101]["price_type"] = "free"
            with patch.object(promotion, "likenovel_db_session", return_value=self.db_context()), \
                    patch.object(promotion, "campaign_snapshot", AsyncMock(return_value=current)), \
                    patch.object(promotion, "_public_prices", AsyncMock(return_value=response)), \
                    patch.object(promotion, "load_config", return_value={"resource": "https://api.example.test/mcp"}):
                proof = await promotion.verify_public("owner", plan["plan_id"])
            self.assertTrue(proof["campaign_period_active"])
            self.assertEqual(proof["public_verified"], valid)

    async def test_actual_public_client_paginates_anonymously_and_bounds_payload(self):
        from httpx import AsyncClient, MockTransport, Response

        requests = []
        def handle(request):
            requests.append(request)
            self.assertNotIn("Authorization", request.headers)
            if request.url.path.endswith("detail-shell"):
                return Response(200, json={"data": {"productId": 45, "priceType": "paid", "paidEpisodeNo": 26}})
            page = int(request.url.params["page"])
            rows = [{"episodeId": n, "productId": 45, "episodeNo": n, "priceType": "paid"}
                    for n in (range(1, 101) if page == 1 else [101])]
            return Response(200, json={"data": {"episodes": rows, "pagination": {"totalCount": 101}}})

        with patch.object(promotion, "AsyncClient",
                          side_effect=lambda **kwargs: AsyncClient(transport=MockTransport(handle), **kwargs)):
            proof = await promotion._public_prices("https://api.example.test", 45)
        self.assertTrue(proof["complete"])
        self.assertEqual(len(proof["episodes"]), 101)
        self.assertEqual(len(requests), 3)
        async with AsyncClient(transport=MockTransport(lambda request: Response(200, content=b"x" * (2 * 1024 * 1024 + 1)))) as client:
            with self.assertRaisesRegex(ValueError, "size bound"):
                await promotion._public_json(client, "https://api.example.test/large")

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
