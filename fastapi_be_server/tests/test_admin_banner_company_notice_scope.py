import ast
import unittest
from pathlib import Path

SERVICE_SOURCE_PATH = (
    Path(__file__).resolve().parents[1]
    / "app"
    / "services"
    / "admin"
    / "admin_event_service.py"
)
SCHEMA_SOURCE_PATH = (
    Path(__file__).resolve().parents[1] / "app" / "schemas" / "admin.py"
)


def _read_service_source() -> str:
    return SERVICE_SOURCE_PATH.read_text(encoding="utf-8")


def _literal_assignment(name: str):
    tree = ast.parse(_read_service_source())
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if any(
            isinstance(target, ast.Name) and target.id == name
            for target in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} assignment not found")


class AdminBannerCompanyNoticeScopeTest(unittest.TestCase):
    def test_company_notice_position_is_available_to_cms_banner_management(self):
        allowed_banner_positions = _literal_assignment("ALLOWED_BANNER_POSITIONS")
        banner_list_position_map = _literal_assignment("BANNER_LIST_POSITION_MAP")

        self.assertIn("companyNotice", allowed_banner_positions)
        self.assertEqual(
            banner_list_position_map["companyNotice"],
            ("companyNotice", None),
        )

    def test_reorder_validation_uses_the_shared_allowed_banner_positions(self):
        service_source = _read_service_source()

        self.assertIn(
            "if req_body.position not in ALLOWED_BANNER_POSITIONS:",
            service_source,
        )

    def test_banner_request_schema_documents_company_notice_position(self):
        schema_source = SCHEMA_SOURCE_PATH.read_text(encoding="utf-8")

        self.assertIn("companyNotice (메인: 미니캐러셀)", schema_source)
        self.assertIn("main | companyNotice | paid", schema_source)


if __name__ == "__main__":
    unittest.main()
