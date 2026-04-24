import unittest
import sys
from types import ModuleType, SimpleNamespace

sys.modules.setdefault("pandas", ModuleType("pandas"))

bs4_stub = ModuleType("bs4")
bs4_stub.BeautifulSoup = object
sys.modules.setdefault("bs4", bs4_stub)

const_stub = ModuleType("app.const")
const_stub.settings = SimpleNamespace()
sys.modules.setdefault("app.const", const_stub)

common_stub = ModuleType("app.services.common")
common_stub.comm_service = SimpleNamespace()
sys.modules.setdefault("app.services.common", common_stub)

query_stub = ModuleType("app.utils.query")
query_stub.get_file_path_sub_query = lambda *args, **kwargs: None
sys.modules.setdefault("app.utils.query", query_stub)

sqlalchemy_stub = ModuleType("sqlalchemy")
sqlalchemy_stub.text = lambda *args, **kwargs: None
sys.modules.setdefault("sqlalchemy", sqlalchemy_stub)

sqlalchemy_ext_stub = ModuleType("sqlalchemy.ext")
sys.modules.setdefault("sqlalchemy.ext", sqlalchemy_ext_stub)

sqlalchemy_asyncio_stub = ModuleType("sqlalchemy.ext.asyncio")
sqlalchemy_asyncio_stub.AsyncSession = object
sys.modules.setdefault("sqlalchemy.ext.asyncio", sqlalchemy_asyncio_stub)

from app.services.admin.admin_bulk_upload_service import _txt_to_html


class AdminBulkUploadServiceUnitTest(unittest.TestCase):
    def test_txt_to_html_joins_adjacent_lines_with_br(self):
        html = _txt_to_html("첫 줄\n둘째 줄")
        self.assertEqual(html, "<p>첫 줄<br/>둘째 줄</p>")

    def test_txt_to_html_preserves_blank_line_count(self):
        html = _txt_to_html("A\n\nB\n\n\nC")
        self.assertEqual(
            html,
            "<p>A</p><p><br/></p><p>B</p><p><br/></p><p><br/></p><p>C</p>",
        )

    def test_txt_to_html_ignores_single_terminal_newline(self):
        html = _txt_to_html("A\n")
        self.assertEqual(html, "<p>A</p>")


if __name__ == "__main__":
    unittest.main()
