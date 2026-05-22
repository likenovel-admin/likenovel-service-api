import asyncio
import sys
import unittest
from html.parser import HTMLParser
from types import ModuleType, SimpleNamespace

_STUBBED_MODULE_NAMES = (
    "fastapi.responses",
    "sqlalchemy",
    "sqlalchemy.ext",
    "sqlalchemy.ext.asyncio",
    "app.const",
    "app.utils.response",
    "bs4",
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


class _StreamingResponse:
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


fastapi_responses_stub = ModuleType("fastapi.responses")
fastapi_responses_stub.StreamingResponse = _StreamingResponse
sys.modules["fastapi.responses"] = fastapi_responses_stub

class _SqlText:
    def __init__(self, sql: str):
        self.sql = sql

    def bindparams(self, *args, **kwargs):
        return self


sqlalchemy_stub = ModuleType("sqlalchemy")
sqlalchemy_stub.RowMapping = object
sqlalchemy_stub.text = lambda value, *args, **kwargs: _SqlText(value)
sqlalchemy_stub.bindparam = lambda *args, **kwargs: None
sys.modules["sqlalchemy"] = sqlalchemy_stub

sqlalchemy_ext_stub = ModuleType("sqlalchemy.ext")
sys.modules["sqlalchemy.ext"] = sqlalchemy_ext_stub

sqlalchemy_asyncio_stub = ModuleType("sqlalchemy.ext.asyncio")
sqlalchemy_asyncio_stub.AsyncSession = object
sys.modules["sqlalchemy.ext.asyncio"] = sqlalchemy_asyncio_stub

const_stub = ModuleType("app.const")
const_stub.CommonConstants = SimpleNamespace(COMPANY_LIKENOVEL="라이크노벨")
const_stub.ErrorMessages = SimpleNamespace(NOT_FOUND_PRODUCT="NOT_FOUND_PRODUCT")
const_stub.LOGGER_TYPE = SimpleNamespace(LOGGER_FILE_NAME_FOR_SERVICE_ERROR="test.log")
const_stub.settings = SimpleNamespace(DB_DML_DEFAULT_ID=0)
sys.modules["app.const"] = const_stub

response_stub = ModuleType("app.utils.response")
response_stub.CustomResponseException = type(
    "CustomResponseException", (Exception,), {}
)
response_stub.check_exists_or_404 = lambda *args, **kwargs: None
response_stub.build_list_response = lambda *args, **kwargs: {}
response_stub.build_paginated_response = lambda *args, **kwargs: {}
sys.modules["app.utils.response"] = response_stub


class _NavigableString(str):
    pass


class _Tag:
    def __init__(self, name: str, attrs: dict | None = None):
        self.name = name
        self.attrs = attrs or {}
        self.children: list[object] = []

    def append(self, child):
        self.children.append(child)

    def find_all(self, name, recursive=False):
        results = []
        for child in self.children:
            if isinstance(child, _Tag) and child.name == name:
                results.append(child)
            if recursive and isinstance(child, _Tag):
                results.extend(child.find_all(name, recursive=True))
        return results


class _Soup(_Tag):
    def __init__(self):
        super().__init__("[document]")

    @property
    def body(self):
        for child in self.children:
            if isinstance(child, _Tag) and child.name == "body":
                return child
        return None


class _SoupBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.root = _Soup()
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Tag(tag, dict(attrs))
        self.stack[-1].append(node)
        if tag not in {"br", "img", "hr", "meta", "link", "input"}:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            node = self.stack[index]
            if isinstance(node, _Tag) and node.name == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].append(_NavigableString(data))


def _beautiful_soup(value: str, parser: str):
    del parser
    builder = _SoupBuilder()
    builder.feed(value)
    return builder.root


bs4_stub = ModuleType("bs4")
bs4_stub.BeautifulSoup = _beautiful_soup
bs4_stub.NavigableString = _NavigableString
bs4_stub.Tag = _Tag
sys.modules["bs4"] = bs4_stub

try:
    from app.services.admin.admin_blind_service import _html_to_plain_text, batch_monopoly
finally:
    _restore_stubbed_modules()


class _FakeExecuteResult:
    rowcount = 2


class _FakeDb:
    def __init__(self):
        self.calls = []

    async def execute(self, query, params):
        self.calls.append((query, params))
        return _FakeExecuteResult()


class AdminBlindServiceUnitTest(unittest.TestCase):
    def test_html_to_plain_text_preserves_blank_paragraph_count(self):
        text = _html_to_plain_text("<p>A</p><p><br/></p><p><br/></p><p>B</p>")
        self.assertEqual(text, "A\n\n\nB")

    def test_html_to_plain_text_preserves_internal_breaks(self):
        text = _html_to_plain_text("<p>A<br/>B<br/><br/>C</p>")
        self.assertEqual(text, "A\nB\n\nC")

    def test_html_to_plain_text_keeps_block_separator_without_collapsing(self):
        text = _html_to_plain_text("<p>첫 줄</p><p><br/></p><p>둘째 줄</p>")
        self.assertEqual(text, "첫 줄\n\n둘째 줄")

    def test_batch_monopoly_updates_only_monopoly_column(self):
        db = _FakeDb()

        result = asyncio.run(batch_monopoly([1, 2], "n", db))

        self.assertEqual(result, {"result": True, "updated_count": 2})
        self.assertEqual(len(db.calls), 1)
        query, params = db.calls[0]
        self.assertIn("monopoly_yn = :monopoly_yn", query.sql)
        self.assertNotIn("contract_yn", query.sql)
        self.assertNotIn("cp_user_id", query.sql)
        self.assertEqual(params, {"ids": [1, 2], "monopoly_yn": "N"})


if __name__ == "__main__":
    unittest.main()
