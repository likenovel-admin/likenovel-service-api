import json
import unittest

from tests.test_story_agent_context_cost_guard import load_module

SOURCE_PARTS = {
    "episode_summary": "주인공 아델리트가 검을 뽑았다. 레이븐은 뒤에서 지켜봤다.",
    "episode_source": "「물러서라」라고 아델리트가 말했다. 레이븐은 고개를 끄덕였다. 노인이 소리쳤다.",
}


def _evidence(quote: str, kind: str = "dialogue", source_part: str = "episode_source") -> dict:
    return {"quote": quote, "kind": kind, "source_part": source_part, "counterpart_label": ""}


def _character(display_name: str, evidence: list[dict], *, voice_mode: str = "dialogue", claims: list[dict] | None = None) -> dict:
    return {
        "display_name": display_name,
        "aliases": [],
        "is_protagonist": False,
        "is_work_protagonist": False,
        "is_episode_focal": False,
        "is_first_person": False,
        "narration_names": [],
        "social_call_names": [],
        "persona_names": [],
        "real_names": [],
        "entity_kind": "person",
        "scene_weight": "high",
        "role_in_episode": "lead",
        "voice_mode": voice_mode,
        "evidence": evidence,
        "identity_claims": claims or [],
        "relation_edges": [],
        "action_tags": [],
        "affect_tags": [],
    }


def _payload(characters: list[dict], episode_no: int = 7) -> dict:
    return {"episode_no": episode_no, "mentioned_characters": characters, "cliffhanger_hooks": ["절벽 끝"]}


class SignalsQuarantineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_invalid_npc_quote_quarantines_npc_keeps_protagonist(self):
        payload = _payload([
            _character("아델리트", [_evidence("물러서라", "dialogue")]),
            _character("노인", [_evidence("원문에 없는 대사", "dialogue")]),
        ])

        sanitized, records = self.module.sanitize_episode_character_signals_grounding(
            payload, source_parts=SOURCE_PARTS
        )

        names = [c["display_name"] for c in sanitized["mentioned_characters"]]
        self.assertEqual(names, ["아델리트"])
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["display_name"], "노인")
        self.assertIn("no_valid_evidence", records[0]["reasons"])

    def test_invalid_protagonist_voice_mode_quarantines_protagonist_keeps_npc(self):
        payload = _payload([
            _character(
                "아델리트",
                [_evidence("아델리트가 검을 뽑았다", "narrated_action", source_part="episode_summary")],
                voice_mode="dialogue",
            ),
            _character("레이븐", [_evidence("레이븐은 고개를 끄덕였다", "narrated_action")], voice_mode="narration_only"),
        ])

        sanitized, records = self.module.sanitize_episode_character_signals_grounding(
            payload, source_parts=SOURCE_PARTS
        )

        names = [c["display_name"] for c in sanitized["mentioned_characters"]]
        self.assertEqual(names, ["레이븐"])
        reasons = {r["display_name"]: r["reasons"] for r in records}
        self.assertIn("voice_mode_unsupported", reasons["아델리트"])

    def test_failed_identity_claim_quarantines_whole_character(self):
        payload = _payload([
            _character(
                "레이븐",
                [_evidence("레이븐은 고개를 끄덕였다", "narrated_action")],
                voice_mode="narration_only",
                claims=[{"claim_type": "possessed_as", "target_label": "레이븐", "evidence": "원문에 없는 주장 근거"}],
            ),
        ])

        sanitized, records = self.module.sanitize_episode_character_signals_grounding(
            payload, source_parts=SOURCE_PARTS
        )

        self.assertEqual(sanitized["mentioned_characters"], [])
        self.assertIn("identity_claim_evidence", records[0]["reasons"])

    def test_partial_evidence_drop_keeps_character(self):
        payload = _payload([
            _character(
                "아델리트",
                [
                    _evidence("물러서라", "dialogue"),
                    _evidence("원문에 없는 대사", "dialogue"),
                ],
            ),
        ])

        sanitized, records = self.module.sanitize_episode_character_signals_grounding(
            payload, source_parts=SOURCE_PARTS
        )

        self.assertEqual(len(sanitized["mentioned_characters"]), 1)
        quotes = [e["quote"] for e in sanitized["mentioned_characters"][0]["evidence"]]
        self.assertEqual(quotes, ["물러서라"])
        self.assertEqual(records, [])

    def test_validator_raises_when_all_characters_quarantined(self):
        payload = _payload([
            _character("노인", [_evidence("원문에 없는 대사", "dialogue")]),
        ])

        with self.assertRaises(ValueError) as ctx:
            self.module.validate_episode_character_signals_provider_payload(
                payload, episode_no=7, source_parts=SOURCE_PARTS
            )
        self.assertIn("quarantined_all", str(ctx.exception))

    def test_validator_raises_on_envelope_mismatch_unchanged(self):
        payload = _payload([_character("아델리트", [_evidence("물러서라", "dialogue")])], episode_no=6)

        with self.assertRaises(ValueError):
            self.module.validate_episode_character_signals_provider_payload(
                payload, episode_no=7, source_parts=SOURCE_PARTS
            )

    def test_empty_character_list_is_valid_not_quarantined_all(self):
        payload = _payload([])

        result = self.module.validate_episode_character_signals_provider_payload(
            payload, episode_no=7, source_parts=SOURCE_PARTS
        )

        self.assertEqual(result["mentioned_characters"], [])

    def test_clean_payload_returns_identical_object_and_records(self):
        payload = _payload([_character("아델리트", [_evidence("물러서라", "dialogue")])])

        sanitized, records = self.module.sanitize_episode_character_signals_grounding(
            payload, source_parts=SOURCE_PARTS
        )

        self.assertIs(sanitized, payload)
        self.assertEqual(records, [])

    def test_sanitize_is_canonically_stable_on_replay(self):
        payload = _payload([
            _character("아델리트", [_evidence("물러서라", "dialogue")]),
            _character("노인", [_evidence("원문에 없는 대사", "dialogue")]),
        ])

        first, records = self.module.sanitize_episode_character_signals_grounding(
            payload, source_parts=SOURCE_PARTS
        )
        second, replay_records = self.module.sanitize_episode_character_signals_grounding(
            first, source_parts=SOURCE_PARTS
        )

        self.assertEqual(
            json.dumps(first, ensure_ascii=False, sort_keys=True),
            json.dumps(second, ensure_ascii=False, sort_keys=True),
        )
        self.assertEqual(replay_records, [])

    def test_sanitized_payload_passes_strict_grounding_validator(self):
        payload = _payload([
            _character("아델리트", [_evidence("물러서라", "dialogue")]),
            _character(
                "노인",
                [
                    _evidence("노인이 소리쳤다", "narrated_action"),
                    _evidence("원문에 없는 대사", "dialogue"),
                ],
                voice_mode="narration_only",
                claims=[{"claim_type": "possessed_as", "target_label": "노인", "evidence": "원문에 없는 주장 근거"}],
            ),
        ])

        result = self.module.validate_episode_character_signals_provider_payload(
            payload, episode_no=7, source_parts=SOURCE_PARTS
        )

        self.assertIsNone(
            self.module.get_episode_character_signals_grounding_error(result, source_parts=SOURCE_PARTS)
        )
        names = [c["display_name"] for c in result["mentioned_characters"]]
        self.assertEqual(names, ["아델리트"])


if __name__ == "__main__":
    unittest.main()
