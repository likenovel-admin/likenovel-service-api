import unittest

try:
    from app.services.admin.banner_order_service import _build_banner_reorder_plan
except ImportError:
    _build_banner_reorder_plan = None


class AdminBannerOrderServiceUnitTest(unittest.TestCase):
    def test_reorder_plan_normalizes_duplicate_orders_with_stable_id_tiebreak(self):
        self.assertIsNotNone(_build_banner_reorder_plan)
        rows = [
            {"id": 12, "show_order": 1},
            {"id": 10, "show_order": 1},
            {"id": 11, "show_order": 1},
        ]

        plan = _build_banner_reorder_plan(rows, target_id=12, target_position=2)

        self.assertEqual(plan, [(10, 1), (12, 2), (11, 3)])

    def test_reorder_plan_preserves_stable_order_when_target_position_is_omitted(self):
        self.assertIsNotNone(_build_banner_reorder_plan)
        rows = [
            {"id": 7, "show_order": 3},
            {"id": 5, "show_order": 1},
            {"id": 6, "show_order": 1},
        ]

        plan = _build_banner_reorder_plan(rows, target_id=7, target_position=None)

        self.assertEqual(plan, [(5, 1), (6, 2), (7, 3)])

    def test_reorder_plan_rejects_out_of_range_position(self):
        self.assertIsNotNone(_build_banner_reorder_plan)
        rows = [
            {"id": 1, "show_order": 1},
            {"id": 2, "show_order": 2},
        ]

        with self.assertRaises(ValueError):
            _build_banner_reorder_plan(rows, target_id=1, target_position=0)

        with self.assertRaises(ValueError):
            _build_banner_reorder_plan(rows, target_id=1, target_position=3)

    def test_reorder_plan_rejects_missing_target_id_even_without_target_position(self):
        self.assertIsNotNone(_build_banner_reorder_plan)
        rows = [
            {"id": 1, "show_order": 1},
            {"id": 2, "show_order": 2},
        ]

        with self.assertRaises(ValueError):
            _build_banner_reorder_plan(rows, target_id=99, target_position=None)


if __name__ == "__main__":
    unittest.main()
