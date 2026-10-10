import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.ai import mcp_single_copy as core

NOW = datetime(2026, 10, 12, 10, 5, tzinfo=core.KST)


def candidate(product_id, *, last_seen=None, hits=0, bookmarks=0):
    return {
        "product_id": product_id,
        "title": f"작품 {product_id}",
        "cover_image_path": f"cover-{product_id}",
        "history_count": 1 if last_seen else 0,
        "last_single_slot_at": last_seen,
        "paid_open_at": datetime(2026, 10, product_id, tzinfo=core.KST),
        "count_hit": hits,
        "count_bookmark": bookmarks,
    }


class RotationFairnessTests(unittest.TestCase):
    def test_recent_exposure_and_proposal_are_excluded_and_exact_seven_days_allowed(self):
        candidates = [
            candidate(1, last_seen=NOW - timedelta(days=7) + timedelta(microseconds=1)),
            candidate(2, last_seen=NOW - timedelta(days=7)),
            candidate(3, last_seen=NOW - timedelta(days=30)),
            candidate(4, last_seen=NOW + timedelta(days=1)),
        ]
        state = core.empty_state()
        state["last_proposed_at"] = {"3": (NOW - timedelta(days=1)).isoformat()}
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates(candidates, state, now=NOW)
        self.assertEqual([row["product_id"] for row in ranked], [2])

    def test_old_and_unseen_works_can_rotate_in_either_order_despite_popularity(self):
        candidates = [
            candidate(1, last_seen=NOW - timedelta(days=90)),
            candidate(2, hits=1_000_000, bookmarks=100_000),
        ]
        for reverse, expected in [(False, [1, 2]), (True, [2, 1])]:
            with self.subTest(reverse=reverse):
                shuffle = (lambda rows: rows.reverse()) if reverse else (lambda rows: None)
                with patch.object(core.random, "shuffle", side_effect=shuffle):
                    ranked = core.rank_candidates(candidates, core.empty_state(), now=NOW)
                self.assertEqual([row["product_id"] for row in ranked], expected)
        self.assertEqual([row["product_id"] for row in candidates], [1, 2])

    def test_unknown_history_date_is_not_inferred_from_count_or_views(self):
        row = candidate(1, hits=1_000_000)
        row["history_count"] = 100
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates([row], core.empty_state(), now=NOW)
        self.assertEqual(ranked, [row])
        self.assertIsNone(ranked[0]["last_single_slot_at"])

    def test_latest_proposal_or_exposure_controls_cooldown_across_timezones(self):
        candidates = [
            candidate(1, last_seen=NOW - timedelta(days=30)),
            candidate(2, last_seen=NOW - timedelta(days=1)),
        ]
        state = core.empty_state()
        state["last_proposed_at"] = {
            "1": "2026-10-08T16:00:00+00:00",
            "2": "2026-09-01T10:05:00+09:00",
        }
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates(candidates, state, now=NOW)
        self.assertEqual(ranked, [])

    def test_cooldown_shortage_does_not_backfill_with_recent_works(self):
        candidates = [candidate(1), candidate(2), candidate(3, last_seen=NOW)]
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates(candidates, core.empty_state(), now=NOW)
        with patch.object(core, "inspect_cover", return_value={"eligible": True}):
            selected, rejected = core.select_cover_valid_candidates(ranked)
        self.assertEqual([row["product_id"] for row in selected], [1, 2])
        self.assertLess(len(selected), core.REQUIRED_COUNT)
        self.assertEqual(rejected, [])

    def test_cover_rejection_still_selects_three_distinct_eligible_works(self):
        candidates = [candidate(value) for value in range(1, 5)]
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates(candidates, core.empty_state(), now=NOW)
        def cover(path):
            return {"eligible": path != "cover-1", "reason": "invalid"}
        with patch.object(core, "inspect_cover", side_effect=cover):
            selected, rejected = core.select_cover_valid_candidates(ranked)
        self.assertEqual([row["product_id"] for row in selected], [2, 3, 4])
        self.assertEqual(len({row["product_id"] for row in selected}), 3)
        self.assertEqual(rejected[0]["product_id"], 1)


if __name__ == "__main__":
    unittest.main()
