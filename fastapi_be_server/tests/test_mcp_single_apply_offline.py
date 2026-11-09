"""Execute the unchanged apply function with isolated CMS/DB boundaries.

This supplements, not replaces, full SQLAlchemy/MySQL/transport integration tests.
"""
import ast
import copy
from datetime import datetime
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.services.ai import mcp_policy as policy


class _DB:
    def __init__(self): self.committed=False; self.rolled_back=False
    async def __aenter__(self): return self
    async def __aexit__(self, kind, exc, tb):
        if kind: self.rolled_back=True
        else: self.committed=True
    def begin(self): return self
    async def execute(self, *args): return types.SimpleNamespace(all=lambda:[]) 


class ApplyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.before=[{"single_slot_id":i+1,"slot_key":key,"slot_name":key,"slot_order":i,
                      "product_id":20+i,"summary_text":"old","publish_start_at":"2026-01-01T00:00:00",
                      "publish_end_at":None} for i,key in enumerate(policy.SINGLE_KEYS)]
        self.proposals=[{"product_id":i+1,"slot_key":key,"summary_text":"new copy\nsecond line","title":"title"}
                        for i,key in enumerate(policy.SINGLE_KEYS)]
        self.receipt={"status":"ready","kind":"single","before":self.before,"candidates":self.proposals,
                      "generated_at":"2026-11-12T10:05:00+09:00","model":"operator","copy_source":"operator_episode_body"}
        self.after=[{**row,"product_id":i+1,"summary_text":"new copy\nsecond line"} for i,row in enumerate(self.before)]
        self.db=_DB()
        self.store=types.SimpleNamespace(get=Mock(side_effect=lambda key,owner:self.receipt if key.startswith("single:") else None),save=Mock())
        self.core=types.SimpleNamespace(CANDIDATE_SQL="query",rows_to_candidates=lambda rows:[{"product_id":i} for i in (1,2,3)],
                                        validate_summary=lambda text,title:(True,None,[]))
        self.cms=types.SimpleNamespace(publish_admin_main_single_slot_now=AsyncMock())
        self.guard=AsyncMock()
        self.single_rows=AsyncMock(side_effect=[copy.deepcopy(self.before),copy.deepcopy(self.after)])
        source=Path(__file__).parents[1]/"app/services/ai/mcp_operations.py"
        tree=ast.parse(source.read_text())
        functions=[node for node in tree.body if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))
                   and node.name in ("apply_single","validate_single_layout")]
        self.ns={"policy":policy,"store":self.store,"datetime":datetime,"text":lambda x:x,
                 "_enabled":Mock(),"likenovel_db_session":lambda:self.db,"single_rows":self.single_rows,
                 "PostMainSingleSlotPublishNowReqBody":lambda **kwargs:kwargs}
        exec(compile(ast.Module(body=functions,type_ignores=[]),str(source),"exec"),self.ns)
        import app.services.ai as ai
        self.mods=patch.dict(sys.modules,{
            "app.services.ai.mcp_single_copy":self.core,
            "app.services.product":types.SimpleNamespace(main_single_slot_service=self.cms),
            "app.services.ai.mcp_single_plan":types.SimpleNamespace(validate_manual_apply=self.guard)})
        self.mods.start()
        self.attrs=patch.object(ai,"mcp_single_copy",self.core,create=True);self.attrs.start()
        self.cycle=patch.object(policy,"cycle_key",return_value="single:2026-11-12");self.cycle.start()

    def tearDown(self):
        self.cycle.stop();self.attrs.stop();self.mods.stop()

    async def call(self,snapshot="fresh"):
        return await self.ns["apply_single"]("owner",42,"single:2026-11-12",snapshot)

    async def test_three_slot_apply_after_manual_guard_and_one_completed_receipt(self):
        await self.call()
        self.guard.assert_awaited_once()
        self.assertEqual(self.cms.publish_admin_main_single_slot_now.await_count,3)
        self.assertEqual(self.store.save.call_args_list[0].args[2],"applying")
        self.assertEqual(self.store.save.call_args_list[1].args[2],"completed")
        self.assertTrue(self.db.committed)

    async def test_completed_job_never_reapplies(self):
        self.receipt["status"]="completed"
        self.assertEqual(await self.call(),self.receipt)
        self.cms.publish_admin_main_single_slot_now.assert_not_awaited()
        self.guard.assert_not_awaited()

    async def test_failed_job_and_missing_snapshot_never_write(self):
        self.receipt["status"]="failed"
        with self.assertRaisesRegex(ValueError,"not ready"): await self.call()
        self.receipt["status"]="ready";self.single_rows.side_effect=None;self.single_rows.return_value=self.before
        with self.assertRaisesRegex(ValueError,"fresh snapshot"): await self.call(None)
        self.cms.publish_admin_main_single_slot_now.assert_not_awaited()

    async def test_duplicate_slot_keys_or_cms_changed_never_write(self):
        self.proposals[1]["slot_key"]=self.proposals[0]["slot_key"]
        with self.assertRaisesRegex(ValueError,"each authorized"): await self.call()
        self.single_rows.side_effect=None; self.single_rows.return_value=[]
        with self.assertRaisesRegex(ValueError,"CMS changed"): await self.call()
        self.cms.publish_admin_main_single_slot_now.assert_not_awaited()

    async def test_manual_body_or_cover_guard_failure_precedes_intent(self):
        self.guard.side_effect=ValueError("body changed")
        with self.assertRaisesRegex(ValueError,"body changed"): await self.call()
        self.store.save.assert_not_called()
        self.cms.publish_admin_main_single_slot_now.assert_not_awaited()

    async def test_cms_failure_never_records_completed_or_automatically_retries(self):
        self.cms.publish_admin_main_single_slot_now.side_effect=RuntimeError("write failed")
        with self.assertRaisesRegex(RuntimeError,"write failed"): await self.call()
        self.assertEqual(self.cms.publish_admin_main_single_slot_now.await_count,1)
        self.assertEqual([call.args[2] for call in self.store.save.call_args_list],["applying"])
        self.assertTrue(self.db.rolled_back)

    async def test_uncertain_state_mismatch_blocks_without_cms_write(self):
        self.receipt={"status":"applying","expected":{key:[1,"different"] for key in policy.SINGLE_KEYS}}
        with self.assertRaisesRegex(ValueError,"Uncertain"): await self.call()
        self.store.save.assert_not_called()
        self.cms.publish_admin_main_single_slot_now.assert_not_awaited()

    async def test_committed_readback_recovers_without_reapplying(self):
        self.receipt={"status":"applying","expected":{row["slot_key"]:[row["product_id"],row["summary_text"]] for row in self.before},
                      "result":{"kind":"single"}}
        await self.call()
        self.assertEqual(self.store.save.call_args.args[2],"completed")
        self.assertTrue(self.store.save.call_args.args[3]["recovered_after_commit"])
        self.cms.publish_admin_main_single_slot_now.assert_not_awaited()


if __name__=="__main__":unittest.main()
