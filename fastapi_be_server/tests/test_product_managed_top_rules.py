from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def _product_service_source() -> str:
    return (
        ROOT / "app" / "services" / "product" / "product_service.py"
    ).read_text(encoding="utf-8")


def _managed_area_rules_source() -> str:
    source = _product_service_source()
    start = source.index("TOP_MANAGED_AREA_RULES = {")
    end = source.index("\n}\n\n\ndef convert_product_data", start) + 2
    return source[start:end]


class ProductManagedTopRulesTest(unittest.TestCase):
    def test_serial_top_read_filters_exclude_rest_status(self):
        rules = _managed_area_rules_source()

        self.assertIn('"freeSerialTop"', rules)
        self.assertIn('"paidSerialTop"', rules)
        self.assertIn('p.status_code = "ongoing"', rules)
        self.assertNotIn('p.status_code IN ("ongoing", "rest")', rules)

    def test_paid_main_top_read_filter_excludes_rest_status(self):
        rules = _managed_area_rules_source()

        self.assertIn('"paidMainTop"', rules)
        self.assertIn('p.status_code IN ("ongoing", "end")', rules)
        self.assertNotIn('p.status_code IN ("ongoing", "rest", "end")', rules)
