import unittest

from app.services.websochat.websochat_scope_resolver import (
    _infer_websochat_read_episode_to_from_prompt,
    _resolve_websochat_prompt_read_scope_decision,
)


class WebsochatScopeResolverTest(unittest.TestCase):
    def test_multi_episode_query_uses_highest_referenced_episode(self):
        for prompt in (
            "49화와 50화의 흐름을 정리해줘",
            "50화와 49화의 흐름을 정리해줘",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    _infer_websochat_read_episode_to_from_prompt(
                        prompt,
                        latest_episode_no=50,
                    ),
                    50,
                )

    def test_explicit_read_declaration_beats_later_unread_episode(self):
        for prompt in (
            "49화까지 읽었고 50화는 아직 안 봤어",
            "50화까지 안 봤고 49화는 읽었어",
            "49화까지만 읽었고 50화는 아직 안 봤어",
            "49화까진 읽었고 50화는 아직 안 봤어",
            "49화까지 다 읽었고 50화는 아직 안 봤어",
            "49화까지 읽었고 그 뒤는 하나도 안 봤어",
            "49화까지 읽었고 50화는 하나도 안 봤어",
            "49화까지 읽었고 50화는 아직 못 봤어",
            "49화까지 읽었고 50화는 아직 안 본 상태야",
            "49화까지 읽었고 그 이후는 안 봤어",
            "49화까지 읽었고 이후는 안 봤어",
        ):
            with self.subTest(prompt=prompt):
                inferred_episode_to = _infer_websochat_read_episode_to_from_prompt(
                    prompt,
                    latest_episode_no=50,
                )
                decision = _resolve_websochat_prompt_read_scope_decision(
                    user_prompt=prompt,
                    inferred_read_episode_to=inferred_episode_to,
                )

                self.assertEqual(inferred_episode_to, 49)
                self.assertEqual(decision["read_episode_to"], 49)
                self.assertEqual(decision["scope_state"], "known")

    def test_unread_episode_without_positive_scope_stays_unread(self):
        for prompt in (
            "50화는 아직 안 봤어",
            "50화까지 안 봤어",
            "50화는 아직 못 봤어",
            "50화는 아직 못 읽었어",
            "50화는 아직 읽지 못했어",
            "50화는 보지 않았어",
            "50화는 아직 읽지는 않았어",
            "50화는 아직 읽진 않았어",
            "50화는 아직 보지는 못했어",
            "50화는 아직 보진 못했어",
            "50화는 아직 안 본 상태야",
            "50화는 아직 못 본 상태야",
            "50화는 아직 안 읽은 상태야",
            "50화는 아직 못 읽은 상태야",
        ):
            with self.subTest(prompt=prompt):
                inferred_episode_to = _infer_websochat_read_episode_to_from_prompt(
                    prompt,
                    latest_episode_no=50,
                )
                decision = _resolve_websochat_prompt_read_scope_decision(
                    user_prompt=prompt,
                    inferred_read_episode_to=inferred_episode_to,
                )

                self.assertEqual(inferred_episode_to, 0)
                self.assertEqual(decision["read_episode_to"], 0)
                self.assertEqual(decision["scope_state"], "none")

    def test_uncertain_or_global_unread_is_not_positive_scope(self):
        for prompt in (
            "49화는 읽었는지 모르겠고 아직 하나도 안 봤어",
            "49화 기준은 아직 안 봤어",
            "49화까지 읽었어? 난 아직 안 읽었는데",
            "49화 기준으로는 아직 안 봤어",
            "49화까지 읽었고 사실 아직 안 봤어",
            "49화까지 읽었지만 사실 아직 안 읽었어",
            "50화까지 읽었어. 아니, 50화는 아직 안 봤어",
            "50화까지 읽었지만 50화는 아직 안 봤어",
        ):
            with self.subTest(prompt=prompt):
                inferred_episode_to = _infer_websochat_read_episode_to_from_prompt(
                    prompt,
                    latest_episode_no=50,
                )
                decision = _resolve_websochat_prompt_read_scope_decision(
                    user_prompt=prompt,
                    inferred_read_episode_to=inferred_episode_to,
                )

                self.assertEqual(inferred_episode_to, 0)
                self.assertEqual(decision["read_episode_to"], 0)
                self.assertEqual(decision["scope_state"], "none")

    def test_later_positive_scope_supersedes_earlier_same_episode_unread(self):
        prompt = "50화는 아직 안 봤지만 방금 50화까지 읽었어"

        inferred_episode_to = _infer_websochat_read_episode_to_from_prompt(
            prompt,
            latest_episode_no=50,
        )
        decision = _resolve_websochat_prompt_read_scope_decision(
            user_prompt=prompt,
            inferred_read_episode_to=inferred_episode_to,
        )

        self.assertEqual(inferred_episode_to, 50)
        self.assertEqual(decision["read_episode_to"], 50)
        self.assertEqual(decision["scope_state"], "known")

    def test_explicit_basis_wins_over_later_prediction_episode(self):
        for prompt in (
            "49화 기준으로 50화 전개를 예상해줘",
            "49화 기준으로는 50화 전개를 예상해줘",
            "49화 기준으론 50화 전개를 예상해줘",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(
                    _infer_websochat_read_episode_to_from_prompt(
                        prompt,
                        latest_episode_no=50,
                    ),
                    49,
                )

    def test_multiple_episode_scope_is_clamped_to_latest_episode(self):
        self.assertEqual(
            _infer_websochat_read_episode_to_from_prompt(
                "49화와 50화의 흐름을 정리해줘",
                latest_episode_no=49,
            ),
            49,
        )


if __name__ == "__main__":
    unittest.main()
