import os
import tempfile
import unittest
from datetime import date, datetime
from unittest.mock import AsyncMock, Mock, patch

from app.services.ai import mcp_operations as ops, mcp_policy as policy, mcp_store as store


def slots(product_ids):
    return [{"slot_id": 1, "name": "slot", "product_ids": product_ids}]


def receipt(before, after):
    return {"kind": "direct", "before": slots(before), "after": slots(after), "changes": []}


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def begin(self):
        return self

    async def execute(self, *args):
        pass


class _GenerationSession(_Session):
    async def execute(self, *args):
        if "FROM tb_ai_model_config" in str(args[0]):
            result = Mock()
            result.mappings.return_value.all.return_value = []
            return result
        return Mock(all=Mock(return_value=[
            (2, 1, "chapter"), (3, 1, "chapter"), (4, 1, "chapter"),
        ]))


class CooldownTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {
            "LIKENOVEL_MCP_STATE_DB": self.directory.name + "/receipts.sqlite3",
        })
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.directory.cleanup()

    def test_seven_day_boundary_owner_status_and_auth_separation(self):
        store.save("direct:2026-10-05", "owner", "completed", receipt([1], [2]))
        store.save("direct:2026-10-06", "owner", "completed", receipt([1], [3]))
        store.save("direct:2026-10-07", "other", "completed", receipt([1], [4]))
        store.save("direct:2026-10-08", "owner", "applying", receipt([1], [5]))
        # Auth payload is intentionally not valid JSON: any accidental read fails.
        with store.connection() as db:
            db.execute("INSERT INTO receipts VALUES (?, ?, ?, ?, ?)",
                       ("oauth:private", "owner", "completed", "private invalid payload", 0))
            db.commit()
        result = ops._direct_cooldown("owner", slots([1]), date(2026, 10, 12))
        self.assertEqual(result["avoid_reproposal_product_ids"], [3])
        self.assertEqual(result["recently_added"], [{
            "product_id": 3, "last_added_date": "2026-10-06", "eligible_again_on": "2026-10-13",
        }])
        self.assertEqual(result["cooldown_days"], 7)
        self.assertIn("unknown", result["legacy_local_proposal_history"])

    def test_current_retention_and_no_change_are_not_reproposals(self):
        store.save("direct:2026-10-10", "owner", "completed", receipt([1], [2]))
        store.save("direct:2026-10-11", "owner", "completed", receipt([2], [2]))
        result = ops._direct_cooldown("owner", slots([2]), date(2026, 10, 12))
        self.assertEqual(result["avoid_reproposal_product_ids"], [])
        self.assertEqual(result["recently_added"][0]["last_added_date"], "2026-10-10")

    def test_invalid_recent_receipt_fails_closed(self):
        invalid = receipt([1], [2])
        invalid["after"][0]["name"] = "altered"
        store.save("direct:2026-10-10", "owner", "completed", invalid)
        with self.assertRaisesRegex(ValueError, "history is invalid"):
            ops._direct_cooldown("owner", slots([1]), date(2026, 10, 12))

    def test_initial_empty_slot_is_valid_history(self):
        store.save("direct:2026-10-10", "owner", "completed", receipt([], [2]))
        result = ops._direct_cooldown("owner", slots([1]), date(2026, 10, 12))
        self.assertEqual(result["avoid_reproposal_product_ids"], [2])

    async def test_snapshot_returns_real_rotation_metadata(self):
        store.save("direct:2026-10-10", "owner", "completed", receipt([1], [2]))
        with patch.object(ops, "likenovel_db_session", return_value=_Session()), \
             patch.object(ops.curator, "build_scheduled_snapshot", AsyncMock(return_value={
                 "slots": slots([1]), "slot_snapshot_stable": True, "objective_checks_error": None,
             })), \
             patch.object(ops.curator, "_load_candidates", AsyncMock(return_value=[])), \
             patch.object(ops, "load_config", return_value={"writes_enabled": False}), \
             patch.object(ops, "datetime") as clock:
            clock.now.return_value = datetime(2026, 10, 12, 10, 0, tzinfo=policy.KST)
            result = await ops.direct_snapshot("owner")
        self.assertEqual(result["rotation_policy"]["avoid_reproposal_product_ids"], [2])

    async def test_fresh_history_guard_blocks_before_intent_or_cms_mutation(self):
        from app.services.admin import admin_recommend_service as cms
        current = slots([1])
        store.save("snapshot:example", "owner", "snapshot", {"kind": "direct", "slots": current})
        # The completed history arrives after the snapshot was saved.
        store.save("direct:2026-10-11", "owner", "completed", receipt([1], [2]))
        update = [{"slot_id": 1, "product_ids": [2], "reason": "새 작품에게 기회를 제공합니다"}]
        with patch.object(ops, "_enabled"), \
             patch.object(policy, "cycle_key", return_value="direct:2026-10-12"), \
             patch.object(policy, "validate_direct_updates"), \
             patch.object(ops, "likenovel_db_session", return_value=_Session()), \
             patch.object(ops.curator, "_load_slots", AsyncMock(return_value=current)), \
             patch.object(ops.curator, "_load_candidates", AsyncMock(return_value=[])), \
             patch.object(cms, "put_direct_recommend", AsyncMock()) as put:
            with self.assertRaisesRegex(ValueError, "7-day cooldown"):
                await ops.apply_direct("owner", "example", update)
        put.assert_not_awaited()
        self.assertIsNone(store.get("direct:2026-10-12", "owner"))

    async def test_unchanged_and_current_work_can_complete(self):
        from app.services.admin import admin_recommend_service as cms

        for retained_update in (False, True):
            with self.subTest(retained_update=retained_update):
                current = slots([2])
                store.save("snapshot:example", "owner", "snapshot", {"kind": "direct", "slots": current})
                store.save("direct:2026-10-11", "owner", "completed", receipt([1], [2]))
                updates = ([{"slot_id": 1, "product_ids": [2], "reason": "현재 편성을 그대로 유지합니다"}]
                           if retained_update else [])
                with patch.object(ops, "_enabled"), \
                     patch.object(policy, "cycle_key", return_value="direct:2026-10-12"), \
                     patch.object(policy, "validate_direct_updates"), \
                     patch.object(ops, "likenovel_db_session", return_value=_Session()), \
                     patch.object(ops.curator, "_load_slots", AsyncMock(return_value=current)), \
                     patch.object(ops.curator, "_load_candidates", AsyncMock(return_value=[])), \
                     patch.object(cms, "put_direct_recommend", AsyncMock()):
                    result = await ops.apply_direct("owner", "example", updates)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["after"], current)
                with store.connection() as db:
                    db.execute("DELETE FROM receipts WHERE job_id=?", ("direct:2026-10-12",))
                    db.commit()

    async def test_validated_single_proposal_records_rotation_before_ready(self):
        from app.services.ai import mcp_single_copy as core

        selected = [{"product_id": product_id} for product_id in (2, 3, 4)]
        generated_at = datetime(2026, 10, 12, 10, 5, tzinfo=policy.KST)
        store.save("rotation", "owner", "state", {"last_proposed_at": {"1": "2026-09-01"}})
        with patch.object(ops, "likenovel_db_session", return_value=_GenerationSession()), \
             patch.object(ops, "single_rows", AsyncMock(return_value=[])), \
             patch.object(core, "rows_to_candidates", return_value=selected), \
             patch.object(core, "rank_candidates", return_value=selected), \
             patch.object(core, "select_cover_valid_candidates", return_value=(selected, [])), \
             patch.object(core, "_decode_hex", return_value="첫 회차"), \
             patch.object(core, "build_gemini_prompt", return_value="source evidence"), \
             patch.object(core, "run_openrouter", return_value={}), \
             patch.object(core, "choose_proposals", return_value=selected), \
             patch.object(ops, "datetime") as clock, \
             patch.object(store, "save", wraps=store.save) as save:
            clock.now.return_value = generated_at
            await ops._generate_single_inner("single:2026-10-12", "owner")
        expected = {"1": "2026-09-01", **{
            str(product_id): generated_at.isoformat() for product_id in (2, 3, 4)
        }}
        self.assertEqual(store.get("rotation", "owner")["last_proposed_at"], expected)
        self.assertEqual(store.get("single:2026-10-12", "owner")["generated_at"],
                         generated_at.isoformat())
        statuses = [(call.args[0], call.args[2]) for call in save.call_args_list]
        self.assertEqual(statuses, [
            ("single:2026-10-12", "generating"),
            ("rotation", "state"),
            ("single:2026-10-12", "ready"),
        ])
        self.assertIn("model_snapshot", save.call_args_list[0].args[3])

    async def test_failed_single_copy_does_not_record_proposals(self):
        from app.services.ai import mcp_single_copy as core

        selected = [{"product_id": product_id} for product_id in (2, 3, 4)]
        original = {"1": "2026-09-01"}
        store.save("rotation", "owner", "state", {"last_proposed_at": original})
        with patch.object(ops, "likenovel_db_session", return_value=_GenerationSession()), \
             patch.object(ops, "single_rows", AsyncMock(return_value=[])), \
             patch.object(core, "rows_to_candidates", return_value=selected), \
             patch.object(core, "rank_candidates", return_value=selected), \
             patch.object(core, "select_cover_valid_candidates", return_value=(selected, [])), \
             patch.object(core, "_decode_hex", return_value="첫 회차"), \
             patch.object(core, "build_gemini_prompt", return_value="source evidence"), \
             patch.object(core, "run_openrouter", return_value={}), \
             patch.object(core, "choose_proposals", side_effect=core.CopyValidationError("invalid")) as choose, \
             patch.object(ops.logger, "exception"), \
             patch.object(store, "save", wraps=store.save) as save:
            await ops._generate_single_inner("single:2026-10-12", "owner")
        self.assertEqual(store.get("rotation", "owner")["last_proposed_at"], original)
        self.assertEqual(store.get("single:2026-10-12", "owner")["status"], "failed")
        self.assertEqual(store.get("single:2026-10-12", "owner")["error_type"], "CopyValidationError")
        self.assertEqual(choose.call_count, 2)
        self.assertEqual([(call.args[0], call.args[2]) for call in save.call_args_list],
                         [("single:2026-10-12", "generating"), ("single:2026-10-12", "failed")])


if __name__ == "__main__":
    unittest.main()
