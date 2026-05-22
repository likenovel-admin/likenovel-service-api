import unittest
import sys
from types import ModuleType, SimpleNamespace

_STUBBED_MODULE_NAMES = (
    "pandas",
    "bs4",
    "app.const",
    "app.services.common",
    "app.utils.query",
    "sqlalchemy",
    "sqlalchemy.ext",
    "sqlalchemy.ext.asyncio",
)
_MISSING = object()
_ORIGINAL_MODULES = {
    name: sys.modules.get(name, _MISSING) for name in _STUBBED_MODULE_NAMES
}


def _restore_stubbed_modules():
    for name, module in _ORIGINAL_MODULES.items():
        if module is _MISSING:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = module


sys.modules["pandas"] = ModuleType("pandas")

bs4_stub = ModuleType("bs4")
bs4_stub.BeautifulSoup = object
sys.modules["bs4"] = bs4_stub

const_stub = ModuleType("app.const")
const_stub.settings = SimpleNamespace()
sys.modules["app.const"] = const_stub

common_stub = ModuleType("app.services.common")
common_stub.comm_service = SimpleNamespace()
sys.modules["app.services.common"] = common_stub

query_stub = ModuleType("app.utils.query")
query_stub.get_file_path_sub_query = lambda *args, **kwargs: None
sys.modules["app.utils.query"] = query_stub

sqlalchemy_stub = ModuleType("sqlalchemy")
sqlalchemy_stub.text = lambda *args, **kwargs: None
sys.modules["sqlalchemy"] = sqlalchemy_stub

sqlalchemy_ext_stub = ModuleType("sqlalchemy.ext")
sys.modules["sqlalchemy.ext"] = sqlalchemy_ext_stub

sqlalchemy_asyncio_stub = ModuleType("sqlalchemy.ext.asyncio")
sqlalchemy_asyncio_stub.AsyncSession = object
sys.modules["sqlalchemy.ext.asyncio"] = sqlalchemy_asyncio_stub

try:
    from app.services.admin.admin_bulk_upload_service import (
        _normalize_episode_no_map,
        _txt_to_html,
    )
finally:
    _restore_stubbed_modules()


class AdminBulkUploadServiceUnitTest(unittest.TestCase):
    def test_txt_to_html_maps_single_newline_to_new_paragraph(self):
        html = _txt_to_html("첫 줄\n둘째 줄")
        self.assertEqual(html, "<p>첫 줄</p><p>둘째 줄</p>")

    def test_txt_to_html_preserves_blank_line_count(self):
        html = _txt_to_html("A\n\nB\n\n\nC")
        self.assertEqual(
            html,
            "<p>A</p><p><br/></p><p>B</p><p><br/></p><p><br/></p><p>C</p>",
        )

    def test_txt_to_html_ignores_single_terminal_newline(self):
        html = _txt_to_html("A\n")
        self.assertEqual(html, "<p>A</p>")

    def test_txt_to_html_preserves_intentional_trailing_blank_line(self):
        html = _txt_to_html("A\n\n")
        self.assertEqual(html, "<p>A</p><p><br/></p>")

    def test_normalize_episode_no_map_keeps_one_based_numbers(self):
        episodes = {1: "one", 2: "two", 10: "ten"}
        self.assertEqual(_normalize_episode_no_map(episodes), episodes)

    def test_normalize_episode_no_map_remaps_zero_based_numbers(self):
        episodes = {0: "prologue", 1: "one", 2: "two"}
        self.assertEqual(
            _normalize_episode_no_map(episodes),
            {1: "prologue", 2: "one", 3: "two"},
        )


if __name__ == "__main__":
    unittest.main()
