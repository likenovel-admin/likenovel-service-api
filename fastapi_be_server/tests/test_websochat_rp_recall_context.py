import unittest
from unittest.mock import AsyncMock, patch

from app.services.websochat import websochat_service


_FILLER = "주인공은 조용히 아무 일도 일어나지 않는 하루를 보내고 있었다. "


def _long_episode_text(match_offset: int, passage: str) -> str:
    head = "UNIQUE_EPISODE_HEAD_MARKER 서두의 잔잔한 나레이션이 이어진다. "
    filler = _FILLER * 80
    prefix = (head + filler)[:match_offset]
    return f"{prefix}{passage}{_FILLER * 20}"


class WebsochatRpRecallContextExcerptTests(unittest.IsolatedAsyncioTestCase):
    async def _build_context(self, *, episode_content: str):
        with (
            patch.object(
                websochat_service,
                "_resolve_websochat_rp_recall_need",
                new_callable=AsyncMock,
            ) as resolve_recall_need,
            patch.object(
                websochat_service,
                "_get_websochat_summary_candidates",
                new_callable=AsyncMock,
            ) as get_summary_candidates,
            patch.object(
                websochat_service,
                "_get_websochat_episode_contents",
                new_callable=AsyncMock,
            ) as get_episode_contents,
            patch.object(
                websochat_service,
                "_search_websochat_episode_contents",
                new_callable=AsyncMock,
            ) as search_episode_contents,
        ):
            resolve_recall_need.return_value = (True, "크리스탈 검")
            get_summary_candidates.return_value = []
            get_episode_contents.return_value = [
                {"episodeNo": 2, "content": episode_content}
            ]
            search_episode_contents.return_value = []

            context = await websochat_service._build_websochat_rp_exact_recall_context(
                product_row={"productId": 1, "title": "테스트", "latestEpisodeNo": 5},
                user_prompt="그때 뭐가 빛났지?",
                recent_messages=[],
                rp_context={
                    "display_name": "테스트",
                    "anchor_episode_no": 2,
                    "trajectory_history": [],
                    "session_memory": {"read_episode_to": 3},
                },
                db=AsyncMock(),
            )
        return context, search_episode_contents

    async def test_prioritized_recall_excerpt_centers_on_deep_match(self):
        passage = "그 순간 크리스탈 검이 빛났고, 모두가 그 빛을 기억했다."
        content = _long_episode_text(match_offset=2400, passage=passage)

        context, search_episode_contents = await self._build_context(
            episode_content=content
        )

        self.assertIn("raw_recall_context", context)
        self.assertIn("크리스탈 검이 빛났고", context["raw_recall_context"])
        self.assertNotIn("UNIQUE_EPISODE_HEAD_MARKER", context["raw_recall_context"])
        search_episode_contents.assert_not_awaited()

    async def test_prioritized_recall_keeps_opening_when_match_is_near_head(self):
        passage = "크리스탈 검을 처음으로 꺼내 들었다."
        content = _long_episode_text(match_offset=60, passage=passage)

        context, _ = await self._build_context(episode_content=content)

        self.assertIn("raw_recall_context", context)
        self.assertIn("크리스탈 검을 처음으로", context["raw_recall_context"])
        self.assertIn("UNIQUE_EPISODE_HEAD_MARKER", context["raw_recall_context"])

    async def test_prioritized_recall_preserves_match_at_episode_end(self):
        passage = "크리스탈 검이 빛났고 모두가 그 빛을 기억했다."
        for suffix in ("", "장면 종료. " * 80):
            with self.subTest(suffix_length=len(suffix)):
                content = "배경 설명. " * 500 + passage + suffix
                context, search = await self._build_context(episode_content=content)
                excerpt = context["raw_recall_context"].split("[2화 원문 일부]\n", 1)[1]
                self.assertIn(passage, excerpt)
                self.assertGreater(len(excerpt), 500)
                self.assertLessEqual(len(excerpt), 1200)
                search.assert_not_awaited()

    async def test_recall_keeps_four_complete_excerpts_within_read_scope(self):
        fetched = []

        async def get_contents(**kwargs):
            fetched.append(kwargs)
            episode_no = kwargs["episode_from"]
            return [{"episodeNo": episode_no, "content": "가" * 1500 + "크리스탈 검"}]

        with (
            patch.object(websochat_service, "_resolve_websochat_rp_recall_need", AsyncMock(return_value=(True, "크리스탈 검"))),
            patch.object(websochat_service, "_get_websochat_summary_candidates", AsyncMock(return_value=[])),
            patch.object(websochat_service, "_get_websochat_episode_contents", side_effect=get_contents),
        ):
            context = await websochat_service._build_websochat_rp_exact_recall_context(
                product_row={"productId": 1, "latestEpisodeNo": 10},
                user_prompt="크리스탈 검", recent_messages=[], db=AsyncMock(),
                rp_context={"anchor_episode_no": 1, "trajectory_history": [{"episode_no": n} for n in (2, 3, 4, 5, 7)], "session_memory": {"read_episode_to": 5}},
            )
        recall = context["raw_recall_context"]
        self.assertEqual(recall.count("화 원문 일부]"), 4)
        self.assertEqual(recall.count("크리스탈 검"), 4)
        for episode_no in range(1, 5):
            self.assertIn(f"[{episode_no}화 원문 일부]", recall)
        self.assertNotIn("[5화 원문 일부]", recall)
        self.assertNotIn("[7화 원문 일부]", recall)
        self.assertEqual([row["episode_from"] for row in fetched], [1, 2, 3, 4, 5])
        self.assertTrue(all(row["latest_episode_no"] == 5 for row in fetched))


if __name__ == "__main__":
    unittest.main()
