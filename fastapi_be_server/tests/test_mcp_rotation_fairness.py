import unittest
from datetime import datetime
from unittest.mock import patch

from app.services.ai import mcp_single_copy as core


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
    def test_unseen_and_older_opportunities_precede_recent_popular_work(self):
        candidates = [
            candidate(3, hits=1_000_000, bookmarks=100_000),
            candidate(2, last_seen=datetime(2026, 9, 1, tzinfo=core.KST)),
            candidate(1),
        ]
        state = core.empty_state()
        state["last_proposed_at"] = {"3": "2026-10-10T10:05:00+09:00"}
        with patch.object(core.random, "shuffle", side_effect=lambda rows: rows.reverse()):
            ranked = core.rank_candidates(candidates, state)
        self.assertEqual([row["product_id"] for row in ranked], [1, 2, 3])

    def test_same_kst_opportunity_day_uses_shuffle_not_views_or_microseconds(self):
        candidates = [
            candidate(1, last_seen=datetime(2026, 10, 8, 0, 0, tzinfo=core.KST),
                      hits=1_000_000, bookmarks=100_000),
            candidate(2, last_seen=datetime(2026, 10, 8, 23, 59, tzinfo=core.KST)),
        ]
        with patch.object(core.random, "shuffle", side_effect=lambda rows: rows.reverse()):
            ranked = core.rank_candidates(candidates, core.empty_state())
        self.assertEqual([row["product_id"] for row in ranked], [2, 1])
        self.assertEqual([row["product_id"] for row in candidates], [1, 2])

    def test_unseen_tier_can_rotate_in_either_order_despite_popularity(self):
        candidates = [candidate(1), candidate(2, hits=1_000_000, bookmarks=100_000)]
        for reverse, expected in [(False, [1, 2]), (True, [2, 1])]:
            with self.subTest(reverse=reverse):
                shuffle = (lambda rows: rows.reverse()) if reverse else (lambda rows: None)
                with patch.object(core.random, "shuffle", side_effect=shuffle):
                    ranked = core.rank_candidates(candidates, core.empty_state())
                self.assertEqual([row["product_id"] for row in ranked], expected)

    def test_proposal_and_exposure_history_use_latest_kst_day(self):
        candidates = [
            candidate(1, last_seen=datetime(2026, 10, 1, tzinfo=core.KST)),
            candidate(2, last_seen=datetime(2026, 10, 8, tzinfo=core.KST)),
        ]
        state = core.empty_state()
        # UTC evening is the next calendar day in KST.
        state["last_proposed_at"] = {"1": "2026-10-08T16:00:00+00:00"}
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates(candidates, state)
        self.assertEqual([row["product_id"] for row in ranked], [2, 1])

    def test_cover_rejection_still_selects_three_distinct_eligible_works(self):
        candidates = [candidate(value) for value in range(1, 5)]
        with patch.object(core.random, "shuffle", side_effect=lambda rows: None):
            ranked = core.rank_candidates(candidates, core.empty_state())
        def cover(path):
            return {"eligible": path != "cover-1", "reason": "invalid"}
        with patch.object(core, "inspect_cover", side_effect=cover):
            selected, rejected = core.select_cover_valid_candidates(ranked)
        self.assertEqual([row["product_id"] for row in selected], [2, 3, 4])
        self.assertEqual(len({row["product_id"] for row in selected}), 3)
        self.assertEqual(rejected[0]["product_id"], 1)


if __name__ == "__main__":
    unittest.main()
