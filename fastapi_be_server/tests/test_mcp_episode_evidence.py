import os
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import AsyncMock, patch

from app.services.ai import mcp_episode_evidence as evidence
from app.services.ai import mcp_store as store


class _Session:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _rows():
    return [{"episode_id": 101, "episode_no": 1, "episode_title": "첫 출항",
             "episode_content": "<p>해적 선장은 황금 나침반을 펼쳤다.</p><p>폭풍 너머 보물섬으로!</p>"}]


class BodyTextTests(unittest.TestCase):
    def test_reads_body_not_title_and_decodes_entities(self):
        self.assertEqual(evidence.plain_text("<p>바다 &amp; 항해</p><p>두 번째</p>"),
                         "바다 & 항해\n\n두 번째")

    def test_strips_script_style_and_does_not_follow_urls(self):
        self.assertEqual(evidence.plain_text(
            '<script>send_secret()</script><style>hide</style><p>본문</p>'
            '<img src="http://invalid.test/secret">'), "본문")

    def test_missing_or_empty_body_is_not_title_fallback(self):
        for body in (None, "", " ", "<script>not a body</script>", 5):
            with self.subTest(body=body), self.assertRaises(ValueError):
                evidence.plain_text(body)

    def test_rejects_oversize_without_silent_truncation(self):
        with patch.object(evidence, "MAX_EPISODE_CHARACTERS", 3):
            with self.assertRaisesRegex(ValueError, "no truncated"):
                evidence._materialize(_rows())
        with patch.object(evidence, "MAX_TOTAL_CHARACTERS", 3):
            with self.assertRaisesRegex(ValueError, "request fewer"):
                evidence._materialize(_rows())

    def test_ids_reject_bool_duplicates_strings_and_unbounded_requests(self):
        for value in ([True], [], [1, 1], ["1"], list(range(1, 10)), "1"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                evidence._episode_ids(value)

    def test_public_selection_has_deleted_hidden_future_guards_and_bounded_sample(self):
        for query in (evidence.EPISODES_SQL, evidence.DEFAULT_EPISODES_SQL):
            self.assertIn("e.use_yn = 'Y'", query)
            self.assertIn("e.open_yn = 'Y'", query)
            self.assertIn("e.publish_reserve_date <= NOW()", query)
            self.assertIn("e.product_id = :product_id", query)
        self.assertIn("first_rank <= 5 OR ranked.last_rank <= 3", evidence.DEFAULT_EPISODES_SQL)


class QueryBoundaryTests(unittest.IsolatedAsyncioTestCase):
    async def _query(self, rows, ids):
        class _SQL:
            def __init__(self, value):
                self.value = value

            def bindparams(self, *args):
                return self

        result = types.SimpleNamespace(mappings=lambda: types.SimpleNamespace(all=lambda: rows))
        db = types.SimpleNamespace(execute=AsyncMock(return_value=result))
        with patch.dict(sys.modules, {"sqlalchemy": types.SimpleNamespace(
            text=_SQL, bindparam=lambda *args, **kwargs: (args, kwargs),
        )}):
            actual = await evidence._load_public_episodes(db, 10, ids)
        return actual, db.execute.call_args

    async def test_query_binds_product_and_episode_ids(self):
        actual, call = await self._query(_rows(), [101])
        self.assertEqual(actual, _rows())
        self.assertEqual(call.args[1], {"product_id": 10, "episode_ids": [101]})
        self.assertIn("IN :episode_ids", call.args[0].value)

    async def test_default_query_has_no_unbounded_input(self):
        _, call = await self._query(_rows(), None)
        self.assertEqual(call.args[1], {"product_id": 10})
        self.assertIn("first_rank <= 5", call.args[0].value)

    async def test_missing_requested_episode_is_not_partial_success(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            await self._query(_rows(), [101, 102])

    async def test_empty_duplicate_or_excess_result_is_rejected(self):
        for rows in ([], _rows() * 2, _rows() * 9):
            with self.subTest(rows=len(rows)), self.assertRaises(ValueError):
                await self._query(rows, None)


class EvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.environment = patch.dict(os.environ, {
            "LIKENOVEL_MCP_STATE_DB": self.directory.name + "/state.db",
        })
        self.environment.start()
        self.rdb = patch.dict(sys.modules, {
            "app.rdb": types.SimpleNamespace(likenovel_db_session=lambda: _Session()),
        })
        self.rdb.start()
        self.eligible = patch.object(evidence, "_eligible_product", AsyncMock(return_value={
            "product_id": 10, "title": "바다의 왕",
        }))
        self.eligible_mock = self.eligible.start()
        self.rows = patch.object(evidence, "_load_public_episodes", AsyncMock(return_value=_rows()))
        self.rows_mock = self.rows.start()

    async def asyncTearDown(self):
        self.rows.stop()
        self.eligible.stop()
        self.rdb.stop()
        self.environment.stop()
        self.directory.cleanup()

    async def test_read_returns_exact_full_body_and_owner_scoped_hash_receipt(self):
        result = await evidence.read_episode_evidence("owner", 10)
        episode = result["episodes"][0]
        self.assertIn("해적 선장은", episode["text"])
        self.assertNotEqual(episode["text"], episode["title"])
        self.assertTrue(episode["full_text"])
        self.assertEqual(episode["range_end"], len(episode["text"]))
        self.assertEqual(len(episode["text_sha256"]), 64)
        receipt = evidence.load_evidence("owner", result["evidence_id"], 10)
        self.assertNotIn("text", receipt["episodes"][0])
        self.assertEqual(result["selection"], "first_five_and_latest_three")
        with self.assertRaisesRegex(ValueError, "another operator"):
            evidence.load_evidence("other", result["evidence_id"], 10)

    async def test_invalid_product_or_episode_ids_never_query(self):
        for product_id, ids in ((True, None), (0, None), (10, [False]), (10, [1, 1])):
            with self.subTest(product_id=product_id, ids=ids), self.assertRaises(ValueError):
                await evidence.read_episode_evidence("owner", product_id, ids)
        self.eligible_mock.assert_not_awaited()
        self.rows_mock.assert_not_awaited()

    async def test_ineligible_work_does_not_read_or_save_evidence(self):
        self.eligible_mock.side_effect = ValueError("not eligible")
        with patch.object(store, "save") as save, self.assertRaises(ValueError):
            await evidence.read_episode_evidence("owner", 10)
        self.rows_mock.assert_not_awaited()
        save.assert_not_called()

    async def test_missing_body_does_not_save_receipt(self):
        rows = _rows()
        rows[0]["episode_content"] = ""
        self.rows_mock.return_value = rows
        with patch.object(store, "save") as save, self.assertRaises(ValueError):
            await evidence.read_episode_evidence("owner", 10)
        save.assert_not_called()

    async def test_other_product_expired_and_invalid_evidence_are_rejected(self):
        result = await evidence.read_episode_evidence("owner", 10)
        with self.assertRaisesRegex(ValueError, "another work"):
            evidence.load_evidence("owner", result["evidence_id"], 11)
        with self.assertRaisesRegex(ValueError, "Invalid"):
            evidence.load_evidence("owner", "../../state", 10)
        now = time.time()
        with patch.object(evidence.time, "time", return_value=now + 1801):
            with self.assertRaisesRegex(ValueError, "expired"):
                evidence.load_evidence("owner", result["evidence_id"], 10)

    async def test_fresh_recheck_accepts_identical_body(self):
        result = await evidence.read_episode_evidence("owner", 10, [101])
        fresh = await evidence.validate_evidence("owner", 10, result["evidence_id"], db=_Session())
        self.assertEqual(fresh, result["episodes"])

    async def test_body_changed_after_read_blocks_plan(self):
        result = await evidence.read_episode_evidence("owner", 10)
        changed = _rows()
        changed[0]["episode_content"] += "<p>다른 결말</p>"
        self.rows_mock.return_value = changed
        with self.assertRaisesRegex(ValueError, "changed"):
            await evidence.validate_evidence("owner", 10, result["evidence_id"], db=_Session())

    async def test_title_or_publication_changed_blocks_plan(self):
        result = await evidence.read_episode_evidence("owner", 10)
        changed = _rows()
        changed[0]["episode_title"] = "새 제목"
        self.rows_mock.return_value = changed
        with self.assertRaisesRegex(ValueError, "changed"):
            await evidence.validate_evidence("owner", 10, result["evidence_id"], db=_Session())
        self.rows_mock.side_effect = ValueError("unpublished")
        with self.assertRaisesRegex(ValueError, "unpublished"):
            await evidence.validate_evidence("owner", 10, result["evidence_id"], db=_Session())


if __name__ == "__main__":
    unittest.main()
