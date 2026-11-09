"""Offline tests: real plan/store/copy code, fake DB/network boundaries only."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, Mock, patch

from app.services.ai import mcp_policy as policy, mcp_store as store, mcp_single_plan as plan, mcp_episode_evidence


def load_copy_core():
    path = Path(__file__).parents[1] / "app/services/ai/mcp_single_copy.py"
    spec = importlib.util.spec_from_file_location("_offline_copy", path)
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {
        "app.services.common.ai_model_config": types.SimpleNamespace(get_model_binding=Mock()),
        "app.services.common.ai_model_gateway": types.SimpleNamespace(stream_model_chat_completion=Mock()),
    }):
        spec.loader.exec_module(module)
    return module


CORE = load_copy_core()
COPY = "황금 나침반이 가리키는 보물섬\n폭풍 너머 펼쳐지는 해적의 항해"
BODY = "황금 나침반이 가리키는 보물섬. 폭풍 너머 펼쳐지는 해적의 항해"


def proposals():
    return [{"slot_key": key, "product_id": index + 1, "summary_text": COPY,
             "evidence_id": str(index + 1) * 32, "quotes": [BODY],
             "reason": "공개 초반과 최근 본문을 비교해 작품의 항해 갈등을 전달합니다."}
            for index, key in enumerate(policy.SINGLE_KEYS)]


class ValidationTests(unittest.TestCase):
    def test_copy_normalizes_crlf_and_outer_whitespace(self):
        items = proposals()
        items[0]["summary_text"] = "  " + COPY.replace("\n", " \r\n ") + "  "
        self.assertEqual(plan.normalize_proposals(items)[0]["summary_text"], COPY)

    def test_rejects_wrong_count_duplicates_boolean_unknown_slot_and_extra_fields(self):
        variants = [proposals()[:2], proposals() + proposals()[:1]]
        for field, value in [("product_id", True), ("slot_key", "banner"), ("summary_text", COPY+"\nextra"),
                             ("quotes", []), ("evidence_id", ""), ("reason", "짧음")]:
            items = proposals(); items[0][field] = value; variants.append(items)
        items = proposals(); items[1]["product_id"] = 1; variants.append(items)
        items = proposals(); items[1]["slot_key"] = items[0]["slot_key"]; variants.append(items)
        items = proposals(); items[0]["user_approved"] = True; variants.append(items)
        for items in variants:
            with self.subTest(items=items), self.assertRaises(ValueError):
                plan.normalize_proposals(items)

    def test_real_copy_validation_and_body_grounding(self):
        plan.validate_body_grounding(CORE, proposals()[0], {"title": "다른 작품명"}, [{"text": BODY}])

    def test_title_or_synopsis_cannot_substitute_for_episode_body(self):
        with self.assertRaisesRegex(ValueError, "retrieved episode body"):
            plan.validate_body_grounding(CORE, proposals()[0], {"title": "다른 작품명", "synopsis": BODY}, [{"text": "다른 본문"}])

    def test_each_line_must_be_grounded_and_overlong_copy_fails(self):
        item = proposals()[0]; item["summary_text"] = "낯선 도시의 마법 연구\n폭풍 너머 펼쳐지는 해적의 항해"
        with self.assertRaisesRegex(ValueError, "Each copy line"):
            plan.validate_body_grounding(CORE, item, {"title": "다른 작품명"}, [{"text": BODY}])
        item["summary_text"] = "가" * 25 + "\n" + "나" * 10
        with self.assertRaisesRegex(ValueError, "line_too_long"):
            plan.validate_body_grounding(CORE, item, {"title": "다른 작품명"}, [{"text": BODY}])


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LIKENOVEL_MCP_STATE_DB": self.tmp.name + "/receipts.db"})
        self.env.start()
        self.payload = {"kind": "single", "candidates": proposals(), "generated_at": datetime.now(policy.KST).isoformat()}

    def tearDown(self):
        self.env.stop(); self.tmp.cleanup()

    def test_ready_and_rotation_are_saved_atomically_once(self):
        self.assertTrue(plan._insert_ready("owner", "single:2026-11-12", self.payload))
        self.assertFalse(plan._insert_ready("owner", "single:2026-11-12", self.payload))
        self.assertEqual(store.get("single:2026-11-12", "owner")["status"], "ready")
        self.assertEqual(set(store.get("rotation", "owner")["last_proposed_at"]), {"1", "2", "3"})

    def test_existing_failed_applying_completed_generating_are_never_overwritten(self):
        for status in ("failed", "applying", "completed", "generating", "interrupted"):
            job = "single:"+status
            store.save(job, "owner", status, {"marker": "preserve"})
            self.assertFalse(plan._insert_ready("owner", job, self.payload))
            self.assertEqual(store.get(job, "owner")["marker"], "preserve")
        self.assertIsNone(store.get("rotation", "owner"))

    def test_other_owner_and_concurrent_recent_proposal_are_rejected(self):
        store.save("single:other", "other", "ready", {})
        with self.assertRaises(ValueError):
            plan._insert_ready("owner", "single:other", self.payload)
        store.save("rotation", "owner", "state", {"last_proposed_at": {"1": datetime.now(policy.KST).isoformat()}})
        with self.assertRaisesRegex(ValueError, "Concurrent recent"):
            plan._insert_ready("owner", "single:new", self.payload)
        self.assertIsNone(store.get("single:new", "owner"))

    def test_old_proposal_becomes_eligible(self):
        store.save("rotation", "owner", "state", {"last_proposed_at": {"1": (datetime.now(policy.KST)-timedelta(days=8)).isoformat()}})
        self.assertTrue(plan._insert_ready("owner", "single:new", self.payload))

    def test_cooldown_direct_current_proposal_and_same_plan_exception(self):
        import app.services.ai as ai
        ops = types.SimpleNamespace(_direct_cooldown=lambda *args: {"recently_added": []})
        selected = [{"product_id": 1, "last_single_slot_at": None}]
        with patch.dict(sys.modules, {"app.services.ai.mcp_operations":ops,"app.services.ai.mcp_single_copy":CORE}), \
             patch.multiple(ai,mcp_operations=ops,mcp_single_copy=CORE,create=True):
            plan.check_cooldown("owner",selected,[],datetime.now(policy.KST).date())
            ops._direct_cooldown=lambda *args: {"recently_added":[{"product_id":1}]}
            with self.assertRaisesRegex(ValueError,"seven-day"):
                plan.check_cooldown("owner",selected,[],datetime.now(policy.KST).date())
            ops._direct_cooldown=lambda *args: {"recently_added":[]}
            proposed_at=datetime.now(policy.KST).isoformat()
            store.save("rotation","owner","state",{"last_proposed_at":{"1":proposed_at}})
            with self.assertRaisesRegex(ValueError,"seven-day"):
                plan.check_cooldown("owner",selected,[],datetime.now(policy.KST).date())
            same={"candidates":[{"product_id":1}],"generated_at":proposed_at}
            plan.check_cooldown("owner",selected,[],datetime.now(policy.KST).date(),same_plan=same)
            same["generated_at"]="2026-01-01T00:00:00+09:00"
            with self.assertRaisesRegex(ValueError,"seven-day"):
                plan.check_cooldown("owner",selected,[],datetime.now(policy.KST).date(),same_plan=same)

    def test_candidate_sql_preserves_explicit_cms_exclusion(self):
        self.assertIn("m.exclude_from_recommend_yn",CORE.CANDIDATE_SQL)
        self.assertIn("ORDER BY m.id DESC LIMIT 1",CORE.CANDIDATE_SQL)


class _Session:
    def __init__(self, rows): self.rows = rows
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
    def begin(self): return self
    async def execute(self, *args): return types.SimpleNamespace(all=lambda: self.rows)


class WorkflowTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"LIKENOVEL_MCP_STATE_DB": self.tmp.name+"/state.db"}); self.env.start()
        self.before = [{"slot_key": key, "product_id": 20+i} for i,key in enumerate(policy.SINGLE_KEYS)]
        self.candidates = [{"product_id": i+1, "title": "다른 작품명", "cover_image_path": "approved.test/cover"} for i in range(3)]
        self.db = _Session(self.candidates)
        self.ops = types.SimpleNamespace(
            _enabled=Mock(), _snapshot=Mock(return_value={"kind":"direct","single_slots":self.before,"slots":[],"updated_at":2}),
            single_rows=AsyncMock(return_value=self.before), validate_single_layout=Mock(),
            curator=types.SimpleNamespace(_load_slots=AsyncMock(return_value=[])))
        self.core = types.SimpleNamespace(CANDIDATE_SQL="SELECT fixture", rows_to_candidates=lambda rows: rows,
            validate_summary=CORE.validate_summary, summary_is_grounded=CORE.summary_is_grounded,
            inspect_cover=Mock(return_value={"valid":True}), cover_is_eligible=lambda cover:(cover["valid"],None))
        self.modules = patch.dict(sys.modules, {"sqlalchemy":types.SimpleNamespace(text=lambda value:value),
            "app.rdb":types.SimpleNamespace(likenovel_db_session=lambda:self.db),
            "app.services.ai.mcp_operations":self.ops,"app.services.ai.mcp_single_copy":self.core})
        self.modules.start()
        import app.services.ai as ai
        self.attrs = patch.multiple(ai, mcp_operations=self.ops, mcp_single_copy=self.core, create=True); self.attrs.start()
        self.cycle = patch.object(policy,"cycle_key",return_value="single:2026-11-12"); self.cycle.start()
        self.cooldown = patch.object(plan,"check_cooldown"); self.cooldown.start()
        self.evidence = patch.object(mcp_episode_evidence,"validate_evidence", AsyncMock(return_value=[{"text":BODY,"episode_id":101}]))
        self.proof = self.evidence.start()
        self.manifest = patch.object(mcp_episode_evidence,"load_evidence", side_effect=lambda owner,eid,pid: {"kind":mcp_episode_evidence.EVIDENCE_KIND,"product_id":pid,"episodes":[],"updated_at":0})
        self.manifest.start()
        self.live = patch.object(mcp_episode_evidence,"revalidate_evidence", AsyncMock(return_value=[{"text":BODY,"episode_id":101}]))
        self.liveproof = self.live.start()

    def tearDown(self):
        for patcher in (self.live,self.manifest,self.evidence,self.cooldown,self.cycle,self.attrs,self.modules,self.env): patcher.stop()
        self.tmp.cleanup()

    async def test_prepare_records_real_operator_copy_without_generation_or_cms(self):
        result = await plan.prepare_single_plan("owner","snapshot",proposals())
        self.assertEqual(result["status"],"ready")
        self.assertEqual(result["copy_source"],"operator_episode_body")
        self.assertEqual(self.proof.await_count,3)
        self.assertEqual(self.core.inspect_cover.call_count,3)
        self.assertEqual(result["candidates"][0]["read_episode_ids"],[101])

    async def test_existing_job_returned_without_revalidation_or_generation(self):
        store.save("single:2026-11-12","owner","failed",{"error_type":"FileNotFoundError"})
        result = await plan.prepare_single_plan("owner","snapshot",proposals())
        self.assertEqual(result["status"],"failed")
        self.proof.assert_not_awaited()
        self.ops._snapshot.assert_not_called()

    async def test_disabled_writes_and_cms_conflict_block_before_plan(self):
        self.ops._enabled.side_effect=ValueError("disabled")
        with self.assertRaisesRegex(ValueError,"disabled"):
            await plan.prepare_single_plan("owner","snapshot",proposals())
        self.ops._enabled.side_effect=None
        self.ops.single_rows.return_value=[]
        with self.assertRaisesRegex(ValueError,"CMS changed"):
            await plan.prepare_single_plan("owner","snapshot",proposals())
        self.assertIsNone(store.get("single:2026-11-12","owner"))

    async def test_missing_fresh_snapshot_ineligible_work_and_invalid_cover_block(self):
        self.ops._snapshot.return_value={"kind":"direct","slots":[]}
        with self.assertRaisesRegex(ValueError,"fresh snapshot"):
            await plan.prepare_single_plan("owner","snapshot",proposals())
        self.ops._snapshot.return_value={"kind":"direct","slots":[],"single_slots":self.before}
        self.db.rows=[]
        with self.assertRaisesRegex(ValueError,"not eligible"):
            await plan.prepare_single_plan("owner","snapshot",proposals())
        self.db.rows=self.candidates; self.core.inspect_cover.return_value={"valid":False}
        with self.assertRaisesRegex(ValueError,"ineligible cover"):
            await plan.prepare_single_plan("owner","snapshot",proposals())
        self.assertIsNone(store.get("single:2026-11-12","owner"))

    async def test_body_change_prevents_ready_receipt(self):
        self.proof.side_effect=ValueError("Manuscript evidence changed")
        with self.assertRaisesRegex(ValueError,"evidence changed"):
            await plan.prepare_single_plan("owner","snapshot",proposals())
        self.assertIsNone(store.get("single:2026-11-12","owner"))

    async def test_apply_rechecks_body_cover_and_fresh_cms_snapshot(self):
        receipt={"candidates":proposals(),"generated_at":datetime.now(policy.KST).isoformat(),"updated_at":1}
        for item in receipt["candidates"]:
            item["evidence_manifest"]={"kind":mcp_episode_evidence.EVIDENCE_KIND,"product_id":item["product_id"],"episodes":[],"updated_at":0}
        await plan.validate_manual_apply("owner",receipt,"fresh",self.before,self.db,self.candidates)
        self.assertEqual(self.liveproof.await_count,3)
        self.proof.assert_not_awaited()
        self.ops.curator._load_slots.return_value=[{"changed":True}]
        with self.assertRaisesRegex(ValueError,"Direct CMS state changed"):
            await plan.validate_manual_apply("owner",receipt,"fresh",self.before,self.db,self.candidates)

    async def test_prepared_plan_survives_read_ttl_but_rechecks_live_body(self):
        receipt = await plan.prepare_single_plan("owner","snapshot",proposals())
        self.ops._snapshot.return_value["updated_at"] = receipt["updated_at"]+1
        self.proof.side_effect=ValueError("expired read evidence")
        with patch.object(mcp_episode_evidence,"load_evidence",side_effect=ValueError("expired")):
            await plan.validate_manual_apply("owner",receipt,"fresh",self.before,self.db,self.candidates)
        self.assertEqual(self.liveproof.await_count,3)
        self.liveproof.side_effect=ValueError("Manuscript evidence changed")
        with self.assertRaisesRegex(ValueError,"evidence changed"):
            await plan.validate_manual_apply("owner",receipt,"fresh",self.before,self.db,self.candidates)
        self.assertEqual(store.get("single:2026-11-12","owner")["status"],"ready")

    async def test_missing_or_cross_work_prepared_manifest_is_rejected(self):
        receipt={"candidates":proposals(),"updated_at":1}
        with self.assertRaisesRegex(ValueError,"Prepared manuscript evidence"):
            await plan.validate_manual_apply("owner",receipt,"fresh",self.before,self.db,self.candidates)
        receipt["candidates"][0]["evidence_manifest"]={"kind":mcp_episode_evidence.EVIDENCE_KIND,"product_id":999}
        with self.assertRaisesRegex(ValueError,"another work"):
            await plan.validate_manual_apply("owner",receipt,"fresh",self.before,self.db,self.candidates)
        self.liveproof.assert_not_awaited()

    async def test_apply_rejects_snapshot_from_before_plan(self):
        receipt={"candidates":proposals(),"generated_at":datetime.now(policy.KST).isoformat(),"updated_at":3}
        with self.assertRaisesRegex(ValueError,"new snapshot after"):
            await plan.validate_manual_apply("owner",receipt,"old",self.before,self.db,self.candidates)
        self.proof.assert_not_awaited()


if __name__ == "__main__": unittest.main()
