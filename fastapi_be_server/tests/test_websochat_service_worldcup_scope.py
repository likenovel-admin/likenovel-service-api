import unittest
from unittest.mock import AsyncMock, patch

from app.services.websochat import websochat_service


class WebsochatWorldcupScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_worldcup_unknown_scope_does_not_initialize_from_freeform_prompt(self):
        session_memory = {
            "active_mode": "ideal_worldcup",
            "read_scope_state": "unknown",
            "read_scope_source": "unknown",
            "game_context": {
                "mode": "ideal_worldcup",
                "gender_scope": "mixed",
                "category": "romance",
            },
            "games": {
                "ideal_worldcup": {
                    "mixed": {
                        "romance": {"read_episode_to": 50},
                    },
                    "male": {
                        "romance": {"read_episode_to": 50},
                    },
                },
            },
        }
        product_row = {
            "productId": 777,
            "title": "테스트 작품",
            "contextStatus": "ready",
            "latestEpisodeNo": 50,
            "syncedLatestEpisodeNo": 50,
        }

        with (
            patch.object(
                websochat_service,
                "_build_websochat_read_scope_label",
                new_callable=AsyncMock,
                return_value="50화",
            ),
            patch.object(
                websochat_service,
                "get_websochat_game_candidate_profiles",
                new_callable=AsyncMock,
                return_value=[],
            ) as get_candidates,
        ):
            reply, next_memory = await websochat_service._generate_websochat_worldcup_reply(
                session_memory=session_memory,
                product_row=product_row,
                user_prompt="남성으로 계속해줘",
                db=AsyncMock(),
            )

        self.assertEqual(next_memory["game_context"]["gender_scope"], "male")
        state = websochat_service._get_websochat_game_state(
            next_memory,
            game_mode="ideal_worldcup",
            gender_scope="male",
            category="romance",
        )
        self.assertIsNone(state["read_episode_to"])
        self.assertIn("예: 3화", reply)
        get_candidates.assert_not_awaited()

    async def test_worldcup_preserves_top_level_turn_scope_ceiling(self):
        session_memory = {
            "active_mode": "ideal_worldcup",
            "read_episode_to": 49,
            "read_scope_state": "known",
            "read_scope_source": "account",
            "game_context": {
                "mode": "ideal_worldcup",
                "gender_scope": "mixed",
                "category": "romance",
            },
            "games": {
                "ideal_worldcup": {
                    "mixed": {
                        "romance": {"read_episode_to": 49},
                    },
                    "male": {
                        "romance": {"read_episode_to": 50},
                    },
                },
            },
        }
        product_row = {
            "productId": 777,
            "title": "테스트 작품",
            "contextStatus": "ready",
            "latestEpisodeNo": 50,
            "syncedLatestEpisodeNo": 50,
        }

        with (
            patch.object(
                websochat_service,
                "_build_websochat_read_scope_label",
                new_callable=AsyncMock,
                return_value="49화",
            ),
            patch.object(
                websochat_service,
                "get_websochat_game_candidate_profiles",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            reply, next_memory = await websochat_service._generate_websochat_worldcup_reply(
                session_memory=session_memory,
                product_row=product_row,
                user_prompt="남성으로 계속해줘",
                db=AsyncMock(),
            )

        self.assertEqual(next_memory["game_context"]["gender_scope"], "male")
        state = websochat_service._get_websochat_game_state(
            next_memory,
            game_mode="ideal_worldcup",
            gender_scope="male",
            category="romance",
        )
        self.assertEqual(state["read_episode_to"], 49)
        self.assertIn("49화", reply)

    async def test_worldcup_clamps_existing_game_read_scope_to_synced_latest(self):
        session_memory = {
            "active_mode": "ideal_worldcup",
            "read_episode_to": 10,
            "read_scope_state": "known",
            "read_scope_source": "account",
            "game_context": {
                "mode": "ideal_worldcup",
                "gender_scope": "mixed",
                "category": "romance",
            },
            "games": {
                "ideal_worldcup": {
                    "mixed": {
                        "romance": {
                            "read_episode_to": 10,
                        },
                    },
                },
            },
        }
        product_row = {
            "productId": 777,
            "title": "테스트 작품",
            "contextStatus": "ready",
            "latestEpisodeNo": 10,
            "syncedLatestEpisodeNo": 3,
        }
        candidates = [
            {
                "scope_key": "named:early-a",
                "display_name": "초반A",
                "first_seen_episode_no": 1,
                "example_items": [{"episode_no": 1, "text": "초반A 대사"}],
                "evidence_count": 3,
            },
            {
                "scope_key": "named:early-b",
                "display_name": "초반B",
                "first_seen_episode_no": 2,
                "example_items": [{"episode_no": 2, "text": "초반B 대사"}],
                "evidence_count": 3,
            },
            {
                "scope_key": "named:late-c",
                "display_name": "후반C",
                "first_seen_episode_no": 8,
                "example_items": [{"episode_no": 8, "text": "후반C 대사"}],
                "evidence_count": 99,
            },
        ]

        async def build_label(*, product_id, read_episode_to, db):
            return f"{int(read_episode_to)}화" if read_episode_to else None

        with (
            patch.object(
                websochat_service,
                "_resolve_websochat_prompt_read_episode_to",
                new_callable=AsyncMock,
            ) as resolve_prompt_scope,
            patch.object(
                websochat_service,
                "_build_websochat_read_scope_label",
                side_effect=build_label,
            ),
            patch.object(
                websochat_service,
                "get_websochat_game_candidate_profiles",
                new_callable=AsyncMock,
            ) as get_candidates,
        ):
            resolve_prompt_scope.return_value = None
            get_candidates.return_value = candidates

            reply, next_memory = await websochat_service._generate_websochat_worldcup_reply(
                session_memory=session_memory,
                product_row=product_row,
                user_prompt="시작",
                db=AsyncMock(),
            )

        state = websochat_service._get_websochat_game_state(
            next_memory,
            game_mode="ideal_worldcup",
            gender_scope="mixed",
            category="romance",
        )

        self.assertEqual(state["read_episode_to"], 3)
        self.assertIn("3화", reply)
        self.assertNotIn("후반C", state.get("current_candidates") or [])


if __name__ == "__main__":
    unittest.main()
