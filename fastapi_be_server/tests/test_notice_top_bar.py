import unittest
from datetime import datetime
from unittest.mock import patch

from app.exceptions import CustomResponseException
import app.schemas.admin as admin_schema
from app.routers.content import notice_query
from app.services.admin import admin_system_service
from app.services.content import notice_top_bar


class _Result:
    def __init__(self, row=None):
        self._row = row

    def mappings(self):
        return self

    def one_or_none(self):
        return self._row


class _RecordingDb:
    def __init__(self, row=None):
        self.queries = []
        self.params = []
        self._row = row

    async def execute(self, statement, params=None):
        self.queries.append(" ".join(str(statement).split()))
        self.params.append(params or {})
        return _Result(self._row)


def _put_body(**overrides):
    values = {"subject": "제목", "content": "본문"}
    values.update(overrides)
    return admin_schema.PutNoticeReqBody(**values)


class NoticeTopBarValidationTests(unittest.TestCase):
    def test_omitted_top_bar_leaves_columns_untouched(self):
        body = _put_body()
        self.assertIsNone(notice_top_bar.resolve_notice_top_bar_columns(body))

    def test_turning_off_clears_text_and_period(self):
        body = _put_body(top_bar_yn="N", top_bar_text="남은 문구")
        self.assertEqual(
            notice_top_bar.resolve_notice_top_bar_columns(body),
            {"top_bar_yn": "N", "top_bar_text": None, "top_bar_start_date": None, "top_bar_end_date": None},
        )

    def test_turning_on_normalizes_text_and_parses_period(self):
        body = _put_body(
            top_bar_yn="y",
            top_bar_text="  웹소챗  장애 보상 안내 ",
            top_bar_start_date="2026-09-30 18:00",
            top_bar_end_date="2026-10-07T23:59",
        )
        self.assertEqual(
            notice_top_bar.resolve_notice_top_bar_columns(body),
            {
                "top_bar_yn": "Y",
                "top_bar_text": "웹소챗 장애 보상 안내",
                "top_bar_start_date": datetime(2026, 9, 30, 18, 0),
                "top_bar_end_date": datetime(2026, 10, 7, 23, 59),
            },
        )

    def test_invalid_top_bar_requests_are_rejected(self):
        invalid_bodies = [
            _put_body(top_bar_yn="Y", top_bar_text="   "),
            _put_body(top_bar_yn="Y", top_bar_text="가" * 81),
            _put_body(
                top_bar_yn="Y",
                top_bar_text="문구",
                top_bar_start_date="2026-10-01 10:00",
                top_bar_end_date="2026-10-01 10:00",
            ),
            _put_body(top_bar_yn="Y", top_bar_text="문구", top_bar_end_date="내일"),
            _put_body(top_bar_yn="X"),
        ]
        for body in invalid_bodies:
            with self.subTest(body=body), self.assertRaises(CustomResponseException) as raised:
                notice_top_bar.resolve_notice_top_bar_columns(body)
            self.assertEqual(raised.exception.status_code, 400)


class NoticeTopBarStartDefaultTests(unittest.TestCase):
    def test_empty_start_records_the_save_time_in_kst(self):
        with patch.object(notice_top_bar, "_now_kst", return_value=datetime(2026, 9, 30, 18, 30)):
            columns = notice_top_bar.resolve_notice_top_bar_columns(
                _put_body(top_bar_yn="Y", top_bar_text="안내")
            )
        self.assertEqual(columns["top_bar_start_date"], datetime(2026, 9, 30, 18, 30))
        self.assertIsNone(columns["top_bar_end_date"])

    def test_end_before_now_is_rejected_when_start_is_empty(self):
        with patch.object(notice_top_bar, "_now_kst", return_value=datetime(2026, 9, 30, 18, 30)):
            with self.assertRaises(CustomResponseException) as raised:
                notice_top_bar.resolve_notice_top_bar_columns(
                    _put_body(top_bar_yn="Y", top_bar_text="안내", top_bar_end_date="2026-09-30 18:00")
                )
        self.assertIn("지금보다", raised.exception.message)

    def test_kst_now_is_naive_seconds_precision(self):
        now = notice_top_bar._now_kst()
        self.assertIsNone(now.tzinfo)
        self.assertEqual(now.microsecond, 0)


class NoticeTopBarPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def test_edit_sets_all_top_bar_columns_explicitly(self):
        db = _RecordingDb()
        await admin_system_service.put_general_notice(
            89,
            _put_body(top_bar_yn="N"),
            db=db,
        )
        query = db.queries[0]
        for column in ("top_bar_yn", "top_bar_text", "top_bar_start_date", "top_bar_end_date"):
            self.assertIn(f"{column} = :{column}", query)
        self.assertIsNone(db.params[0]["top_bar_text"])
        self.assertEqual(db.params[0]["id"], 89)

    async def test_edit_without_top_bar_fields_keeps_existing_bar(self):
        db = _RecordingDb()
        await admin_system_service.put_general_notice(
            89, _put_body(subject="제목만 수정"), db=db
        )
        self.assertNotIn("top_bar", db.queries[0])

    async def test_create_can_publish_a_bar_with_the_notice(self):
        db = _RecordingDb()
        await admin_system_service.post_general_notice(
            admin_schema.PostNoticeReqBody(
                subject="제목", content="본문", top_bar_yn="Y", top_bar_text="상단 띠"
            ),
            db=db,
        )
        self.assertIn("top_bar_text", db.queries[0])
        self.assertEqual(db.params[0]["top_bar_text"], "상단 띠")

    async def test_active_bar_query_returns_null_without_a_row(self):
        self.assertEqual(await notice_top_bar.get_active_notice_top_bar(_RecordingDb()), {"data": None})
        row = {"noticeId": 89, "text": "안내"}
        self.assertEqual(
            await notice_top_bar.get_active_notice_top_bar(_RecordingDb(row)),
            {"data": row},
        )


class NoticeTopBarRouteTests(unittest.TestCase):
    def test_top_bar_route_is_registered_before_notice_detail(self):
        paths = [route.path for route in notice_query.router.routes]
        self.assertLess(paths.index("/notices/top-bar"), paths.index("/notices/{notice_id}"))


if __name__ == "__main__":
    unittest.main()
