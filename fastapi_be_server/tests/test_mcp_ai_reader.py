import os
import tempfile
import unittest
from datetime import date
from unittest.mock import AsyncMock, Mock, patch

from app.services.ai import mcp_ai_reader as ops, mcp_store as store


class _Context:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def begin(self):
        return self


class AiReaderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "LIKENOVEL_MCP_STATE_DB": self.directory.name + "/state.db",
        })
        self.environment.start()
        self.today = patch.object(ops, "_today", return_value=date(2026, 10, 11))
        self.today.start()
        self.preview = {
            "applied": False, "schedule_date": "2026-10-12",
            "schedule_duration_days": 2, "schedule_end_date": "2026-10-13",
            "requested_count": 1, "dry_run_token": "cms-token",
            "preview": [{"agent_key": "reader-1", "ai_reader_agent_id": 1,
                         "activity_pattern": {"auto_pause_schedule_end_date": "2026-10-13"}}],
        }
        self.state = [{"ai_reader_agent_id": 1, "status": "paused"}]
        self.session = patch.object(ops, "likenovel_db_session", return_value=_Context())
        self.session.start()
        self.state_patch = patch.object(ops, "_state", AsyncMock(return_value=self.state))
        self.state_mock = self.state_patch.start()
        self.service_patch = patch.object(ops.cms, "resume_paused_ai_reader_agents",
                                         AsyncMock(return_value=self.preview))
        self.service = self.service_patch.start()

    def tearDown(self):
        self.service_patch.stop()
        self.state_patch.stop()
        self.session.stop()
        self.today.stop()
        self.environment.stop()
        self.directory.cleanup()

    async def make_plan(self):
        return await ops.plan("admin", 1, "2026-10-12", 2)

    def test_exact_inputs_kst_dates_and_existing_schema_limits(self):
        for count, start, days, mode in [
            (True, "2026-10-12", 2, "resume"),
            (1, "2026-10-12", True, "resume"),
            (0, "2026-10-12", 2, "resume"),
            (1001, "2026-10-12", 2, "resume"),
            (1, "2026-10-12", 91, "resume"),
            (1, "2026-10-10", 2, "resume"),
            (1, "2026-10-12T00:00", 2, "resume"),
            (1, "2026-10-12", 2, "unknown"),
        ]:
            with self.subTest(count=count, start=start, days=days, mode=mode):
                with self.assertRaises(ValueError):
                    ops._request(count, start, days, mode, None)
        req = ops._request(1000, "2026-10-11", 90, "bootstrap", "ai-reader-")
        self.assertFalse(req.allow_partial)
        self.assertFalse(req.auto_provision_missing_users)
        self.assertFalse(req.start_immediately)

    async def test_plan_persists_owned_exact_period_without_write(self):
        public = await self.make_plan()
        self.assertEqual(public["starts_on"], "2026-10-12")
        self.assertEqual(public["ends_on"], "2026-10-13")
        self.assertEqual(public["duration_days"], 2)
        self.assertTrue(public["exact_count_available"])
        self.assertFalse(self.service.await_args.kwargs["req_body"].apply)
        stored = ops._read_plan("admin", public["plan_id"])
        self.assertEqual(stored["plan_hash"], public["plan_hash"])
        with self.assertRaises(ValueError):
            ops._read_plan("different-admin", public["plan_id"])
        with store.connection() as db:
            row = db.execute("SELECT payload FROM receipts WHERE job_id=?", (public["plan_id"],)).fetchone()
            altered = row[0].replace('"schedule_duration_days": 2', '"schedule_duration_days": 3')
            db.execute("UPDATE receipts SET payload=? WHERE job_id=?", (altered, public["plan_id"]))
            db.commit()
        with self.assertRaisesRegex(ValueError, "payload changed"):
            ops._read_plan("admin", public["plan_id"])

    async def test_authorization_separate_gate_and_unavailable_count(self):
        public = await self.make_plan()
        with self.assertRaises(PermissionError):
            await ops.apply("admin", public["plan_id"])
        with patch.object(ops, "load_config", return_value={"writes_enabled": True}):
            with self.assertRaisesRegex(PermissionError, "independently"):
                await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
        self.preview["preview"] = []
        public = await self.make_plan()
        with patch.object(ops, "load_config", return_value={"ai_reader_writes_enabled": True}):
            with self.assertRaisesRegex(ValueError, "exact requested"):
                await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
        self.assertTrue(all(not call.kwargs["req_body"].apply for call in self.service.await_args_list))

    async def test_expired_or_past_start_never_applies(self):
        public = await self.make_plan()
        with patch.object(ops, "load_config", return_value={"ai_reader_writes_enabled": True}):
            stored = ops._read_plan("admin", public["plan_id"])
            with patch.object(ops.time, "time", return_value=stored["created_at"] + 1801):
                with self.assertRaisesRegex(ValueError, "expired"):
                    await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
            with patch.object(ops, "_today", return_value=date(2026, 10, 13)):
                with self.assertRaisesRegex(ValueError, "start date has passed"):
                    await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])

    async def test_concurrent_change_rejected_before_consuming_or_service_write(self):
        public = await self.make_plan()
        self.state_mock.return_value = [{"ai_reader_agent_id": 1, "status": "active"}]
        engine = Mock()
        engine.connect.return_value = _Context()
        with patch.object(ops, "load_config", return_value={"ai_reader_writes_enabled": True}), \
             patch.object(ops, "likenovel_db_engine", engine), \
             patch.object(ops, "AsyncSession", return_value=_Context()):
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
        self.assertEqual(ops._read_plan("admin", public["plan_id"])["status"], "planned")
        self.assertEqual(self.service.await_count, 1)

    async def test_uncertain_commit_intent_blocks_repeated_effects(self):
        public = await self.make_plan()
        engine = Mock()
        engine.connect.return_value = _Context()
        self.service.side_effect = RuntimeError("connection lost")
        with patch.object(ops, "load_config", return_value={"ai_reader_writes_enabled": True}), \
             patch.object(ops, "likenovel_db_engine", engine), \
             patch.object(ops, "AsyncSession", return_value=_Context()) as session_factory:
            with self.assertRaisesRegex(RuntimeError, "connection lost"):
                await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
            receipt = await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
            self.assertEqual(receipt["status"], "applying")
            self.assertEqual(self.service.await_count, 2)  # one preview + one apply
            self.assertTrue(self.service.await_args.kwargs["req_body"].apply)
            self.assertEqual(self.service.await_args.kwargs["req_body"].dry_run_token, "cms-token")
            self.assertEqual(session_factory.call_args.kwargs["join_transaction_mode"], "create_savepoint")

    async def test_readback_mismatch_fails_in_outer_transaction(self):
        public = await self.make_plan()
        record = ops._read_plan("admin", public["plan_id"])
        result = Mock()
        result.mappings.return_value.all.return_value = [{
            "agent_key": "reader-1", "status": "active",
            "activity_pattern_json": '{"auto_pause_schedule_end_date":"2026-10-15"}',
        }]
        db = Mock(execute=AsyncMock(return_value=result))
        with self.assertRaisesRegex(ValueError, "period readback"):
            await ops._verify_applied(db, record)

    async def test_schedule_days_readback_and_changed_budget(self):
        self.preview["preview"][0]["daily_llm_budget"] = 8
        public = await self.make_plan()
        record = ops._read_plan("admin", public["plan_id"])
        agent = Mock()
        agent.mappings.return_value.all.return_value = [{
            "agent_key": "reader-1", "status": "active", "daily_llm_budget": 8,
            "activity_pattern_json": '{"auto_pause_schedule_end_date":"2026-10-13"}',
        }]
        schedules = Mock()
        schedules.mappings.return_value.all.return_value = [{
            "agent_key": "reader-1", "scheduled_days": 2,
            "starts_on": date(2026, 10, 12), "ends_on": date(2026, 10, 13),
        }]
        db = Mock(execute=AsyncMock(side_effect=[agent, schedules]))
        self.assertEqual((await ops._verify_applied(db, record))["active_count"], 1)
        schedules.mappings.return_value.all.return_value[0]["scheduled_days"] = 1
        db.execute.side_effect = [agent, schedules]
        with self.assertRaisesRegex(ValueError, "scheduled dates"):
            await ops._verify_applied(db, record)
        agent.mappings.return_value.all.return_value[0]["daily_llm_budget"] = 20
        db.execute.side_effect = [agent]
        with self.assertRaisesRegex(ValueError, "LLM budget"):
            await ops._verify_applied(db, record)

    async def test_inconsistent_cms_preview_period_never_saved(self):
        self.preview["schedule_end_date"] = "2026-10-15"
        with self.assertRaisesRegex(ValueError, "period does not match"):
            await self.make_plan()

    async def test_completed_receipt_is_durable_and_not_reapplied(self):
        public = await self.make_plan()
        operation_id = "ai-reader-apply:" + public["plan_id"].split(":")[1]
        store.save(operation_id, "admin", "completed", {
            "kind": "ai-reader", "plan_hash": public["plan_hash"],
            "readback": {"active_count": 1},
        })
        with patch.object(ops, "load_config", return_value={"ai_reader_writes_enabled": True}):
            result = await ops.apply("admin", public["plan_id"], authorized_plan_hash=public["plan_hash"])
        self.assertEqual(result["status"], "completed")
        self.assertEqual(self.service.await_count, 1)
