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


if __name__ == "__main__":
    unittest.main()
