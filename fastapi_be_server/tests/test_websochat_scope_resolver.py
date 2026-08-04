import unittest

from app.services.websochat.websochat_scope_resolver import (
    _infer_websochat_read_episode_to_from_prompt,
    _merge_websochat_prompt_read_scope,
    _resolve_websochat_prompt_read_scope_decision,
    _resolve_websochat_scope_read_episode_to,
)


class WebsochatScopeResolverTest(unittest.TestCase):
    def test_numeric_mentions_use_highest_topic_candidate(self):
        for prompt in (
            "49화와 50화의 흐름을 정리해줘",
            "50화와 49화의 흐름을 정리해줘",
        ):
            with self.subTest(prompt=prompt):
                self.assertEqual(self._infer(prompt), 50)

    def test_freeform_sentences_do_not_define_persistent_scope(self):
        for prompt in (
            "49화 기준으로 50화 전개를 예상해줘",
            "49화까지 읽었고 50화는 아직 안 봤어",
            "50화는 아직 안 봤어",
            "49화까지 읽고 싶어",
            "49화 기준은 아직 안 봤어",
        ):
            with self.subTest(prompt=prompt):
                decision = self._decision(prompt)
                persistent_memory, _ = _merge_websochat_prompt_read_scope(
                    session_memory={},
                    decision=decision,
                )

                self.assertEqual(decision["scope_state"], "unknown")
                self.assertEqual(
                    _resolve_websochat_scope_read_episode_to(
                        session_memory={},
                        user_prompt=prompt,
                        latest_episode_no=50,
                    ),
                    0,
                )
                self.assertIsNone(persistent_memory.get("read_episode_to"))

    def test_known_scope_caps_multi_episode_topic_in_both_orders(self):
        for structured_scope, prompt, expected in (
            (50, "49화와 50화의 흐름을 정리해줘", 50),
            (50, "50화와 49화의 흐름을 정리해줘", 50),
            (49, "49화와 50화의 흐름을 정리해줘", 49),
        ):
            with self.subTest(structured_scope=structured_scope, prompt=prompt):
                memory = self._known_memory(structured_scope)
                persistent_memory, turn_memory = _merge_websochat_prompt_read_scope(
                    session_memory=memory,
                    decision=self._decision(prompt),
                )

                self.assertEqual(persistent_memory["read_episode_to"], structured_scope)
                self.assertEqual(persistent_memory["read_scope_source"], "account")
                self.assertEqual(turn_memory["read_episode_to"], expected)

    def test_completion_sentence_uses_structured_scope_not_read_semantics(self):
        prompt = "49화까지 읽었는데 50화 설명해줘"
        for structured_scope, expected in ((49, 49), (50, 50)):
            with self.subTest(structured_scope=structured_scope):
                self.assertEqual(
                    _resolve_websochat_scope_read_episode_to(
                        session_memory=self._known_memory(structured_scope),
                        user_prompt=prompt,
                        latest_episode_no=50,
                    ),
                    expected,
                )

    def test_exact_episode_command_initializes_and_narrows_scope(self):
        for current_scope, command, expected, expected_source in (
            (0, " 49화 \n", 49, "prompt"),
            (50, "49화", 49, "prompt"),
            (49, "50화", 49, "account"),
        ):
            with self.subTest(current_scope=current_scope, command=command):
                memory = self._known_memory(current_scope) if current_scope else {}
                decision = self._decision(command)
                persistent_memory, turn_memory = _merge_websochat_prompt_read_scope(
                    session_memory=memory,
                    decision=decision,
                )

                self.assertEqual(decision["scope_state"], "known")
                self.assertTrue(decision["is_scope_only"])
                self.assertEqual(persistent_memory["read_episode_to"], expected)
                self.assertEqual(
                    persistent_memory["read_scope_source"],
                    expected_source,
                )
                self.assertEqual(turn_memory["read_episode_to"], expected)

    def test_exact_episode_command_is_clamped_to_latest_episode(self):
        self.assertEqual(
            _infer_websochat_read_episode_to_from_prompt(
                "50화",
                latest_episode_no=49,
            ),
            49,
        )

    def test_known_scope_ignores_freeform_without_episode_mentions(self):
        self.assertEqual(
            _resolve_websochat_scope_read_episode_to(
                session_memory=self._known_memory(49),
                user_prompt="아직 안 읽었어",
                latest_episode_no=50,
            ),
            49,
        )

    def _decision(self, prompt):
        return _resolve_websochat_prompt_read_scope_decision(
            user_prompt=prompt,
            inferred_read_episode_to=self._infer(prompt),
        )

    @staticmethod
    def _infer(prompt):
        return _infer_websochat_read_episode_to_from_prompt(
            prompt,
            latest_episode_no=50,
        )

    @staticmethod
    def _known_memory(episode_no):
        return {
            "read_episode_to": episode_no,
            "read_scope_state": "known",
            "read_scope_source": "account",
        }


if __name__ == "__main__":
    unittest.main()
