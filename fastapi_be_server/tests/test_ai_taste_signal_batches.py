import argparse
import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_backfill_module():
    path = ROOT / "dist" / "batch" / "backfill_ai_signal_event_factors.py"
    spec = importlib.util.spec_from_file_location("backfill_ai_signal_event_factors", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AiTasteSignalBatchContractTest(unittest.TestCase):
    def test_backfill_targets_missing_product_detail_exit_factor_rows(self):
        module = _load_backfill_module()

        args = argparse.Namespace(
            event_id_from=None,
            event_id_to=None,
            product_id=None,
            user_id=None,
            limit=500,
        )
        where_sql, params = module.build_where_clause(args)

        self.assertIn("product_detail_exit", module.SUPPORTED_EVENT_TYPES)
        self.assertIn("NOT EXISTS", where_sql)
        self.assertEqual(params["limit"], 500)

    def test_hourly_batch_runs_bounded_factor_backfill_before_aggregation(self):
        script = (ROOT / "dist" / "batch" / "ai_taste_hourly_batch.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn("backfill_ai_signal_event_factors.py", script)
        self.assertIn("AI_TASTE_FACTOR_BACKFILL_LIMIT:-500", script)
        self.assertLess(
            script.index("backfill_ai_signal_event_factors.py"),
            script.index("ai_taste_hourly_batch.sql"),
        )

    def test_manual_replay_counts_factor_table_rows_as_valid_source(self):
        script = (ROOT / "dist" / "batch" / "ai_taste_manual_replay_batch.sh").read_text(
            encoding="utf-8"
        )

        stats_start = script.index("STATS=")
        stats_sql = script[stats_start : script.index("\")", stats_start)]

        self.assertIn("tb_user_ai_signal_event_factor f", stats_sql)
        self.assertIn("COUNT(DISTINCT f.event_id)", stats_sql)
