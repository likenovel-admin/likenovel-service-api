import json
import unittest
import pytest
from unittest.mock import AsyncMock, patch

from app.exceptions import CustomResponseException
from app.schemas.websochat import PostWebsochatMessageReqBody, PostWebsochatSessionReqBody
from app.services.websochat import websochat_service
from app.services.websochat.websochat_rp_renderer import _select_rp_examples
from app.services.websochat.character_chat_product_policy import (
    build_character_chat_rp_profile_ready_sql,
    is_character_chat_rp_profile_payload_ready,
    select_character_chat_grounding_v1,
)


@pytest.mark.parametrize("scope", [None, "", "episode:0", "episode:01", "episode:-1", "episode:+1", "episode:１", "Episode:1", "episode:1:extra", "episode:1\n", " episode:1", 1])
@pytest.mark.parametrize("invalid_episode_no, read_to", [(1, None), (60, 5), (1, 60)])
def test_marked_grounding_rejects_invalid_exact_provenance_before_selection(scope, invalid_episode_no, read_to):
    contract = {"version": "v1", "character_key": "character:lead", "generation_hash": "a" * 64}
    profile = {"character_key": "character:lead", "display_name": "주인공", "character_contract": contract, "identity_labels_v1": []}
    evidence = {"episode_no": 2, "episode_scope_key": "episode:101", "character_key": "character:lead", "kind": "narrated_action", "quote": "그는 문을 살폈다.", "source_part": "episode_source", "counterpart_label": ""}
    items = [{**evidence, "episode_no": no} for no in range(2, 15)]
    invalid = {**evidence, "episode_no": invalid_episode_no}
    if scope is None:
        invalid.pop("episode_scope_key")
    else:
        invalid["episode_scope_key"] = scope
    examples = {"character_key": "character:lead", "character_contract": contract, "grounding_v1": items + [invalid]}
    assert select_character_chat_grounding_v1(profile, examples, expected_character_key="character:lead", read_episode_to=read_to) is None


@pytest.mark.parametrize("read_to, expected", [(None, [60, 31]), (31, [31]), (30, [])])
def test_marked_grounding_exact_provenance_preserves_unbounded_episode_numbers(read_to, expected):
    contract = {"version": "v1", "character_key": "character:lead", "generation_hash": "a" * 64}
    profile = {"character_key": "character:lead", "display_name": "주인공", "character_contract": contract, "identity_labels_v1": []}
    examples = {"character_key": "character:lead", "character_contract": contract, "grounding_v1": [
        {"episode_no": no, "episode_scope_key": f"episode:{episode_id}", "character_key": "character:lead", "kind": "narrated_action", "quote": "그는 문을 살폈다.", "source_part": "episode_source", "counterpart_label": ""}
        for episode_id, no in [(101, 31), (104, 60)]
    ]}
    selected = select_character_chat_grounding_v1(profile, examples, expected_character_key="character:lead", read_episode_to=read_to)
    assert [item["episode_no"] for item in selected] == expected


class _Mappings:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _Result:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _Mappings(self._row)


class _Db:
    def __init__(self, row):
        self.row = row
        self.statements = []

    async def execute(self, statement, params=None):
        self.statements.append(str(statement))
        return _Result(self.row)


def _product_row(*, character_chat_eligible: int) -> dict:
    return {
        "productId": 1182,
        "title": "테스트 작품",
        "authorNickname": "작가",
        "statusCode": "ongoing",
        "priceType": "free",
        "contextStatus": "ready",
        "latestEpisodeNo": 15,
        "syncedLatestEpisodeNo": 15,
        "characterChatEligible": character_chat_eligible,
    }


class CharacterChatProductPolicyTest(unittest.IsolatedAsyncioTestCase):
    def test_rp_profile_requires_personality_and_complete_speech_style(self):
        complete = {
            "character_key": "character:adelite",
            "personality_core": ["신중함"],
            "speech_style": {
                "tone": ["차분함"],
                "formality": "존댓말",
                "sentence_length": "보통",
            },
        }

        self.assertTrue(
            is_character_chat_rp_profile_payload_ready(
                complete,
                expected_character_key="character:adelite",
            )
        )
        for field_name in (
            "personality_core",
            "tone",
            "formality",
            "sentence_length",
        ):
            incomplete = json.loads(json.dumps(complete, ensure_ascii=False))
            if field_name == "personality_core":
                incomplete[field_name] = []
            else:
                incomplete["speech_style"][field_name] = [] if field_name == "tone" else ""
            with self.subTest(field_name=field_name):
                self.assertFalse(
                    is_character_chat_rp_profile_payload_ready(
                        incomplete,
                        expected_character_key="character:adelite",
                    )
                )

        self.assertFalse(
            is_character_chat_rp_profile_payload_ready(
                complete,
                expected_character_key="character:other",
            )
        )

        leading_blank = json.loads(json.dumps(complete, ensure_ascii=False))
        leading_blank["personality_core"] = ["", "두 번째 값"]
        self.assertFalse(is_character_chat_rp_profile_payload_ready(leading_blank))

    def test_rp_profile_sql_uses_the_same_required_fields(self):
        query = build_character_chat_rp_profile_ready_sql(
            profile_alias="profile",
            expected_character_key_sql="inventory.scope_key",
        )

        self.assertIn("$.character_key", query)
        self.assertIn("$.personality_core", query)
        self.assertIn("$.speech_style.tone", query)
        self.assertIn("$.speech_style.formality", query)
        self.assertIn("$.speech_style.sentence_length", query)
        self.assertIn("inventory.scope_key", query)

    def test_character_chat_rp_lookup_includes_inventory_source_aliases(self):
        scope_keys = websochat_service._build_websochat_rp_lookup_scope_keys(
            normalized_memory={"session_kind": "character_chat"},
            resolved_active_character="character:조렌테이머",
            resolution={
                "aliasScopeKeys": ["unrelated:alias"],
                "inventoryPayload": {
                    "protagonist_identity_scope_keys": ["character:방호영"],
                    "source_character_keys": [
                        "protagonist:named:방호영",
                        "named:방호영",
                    ],
                },
            },
        )

        self.assertEqual(
            scope_keys,
            [
                "character:조렌테이머",
                "character:방호영",
                "protagonist:named:방호영",
                "named:방호영",
            ],
        )

    async def test_product_lookup_uses_only_public_episode_count_for_character_chat(self):
        db = _Db(_product_row(character_chat_eligible=0))

        product = await websochat_service._get_websochat_product(1182, "N", db)

        self.assertIsNotNone(product)
        self.assertFalse(product["characterChatEligible"])
        query = db.statements[0]
        self.assertIn("COUNT(e.episode_id) >= 15", query)
        self.assertNotIn("p.status_code = 'ongoing'", query)
        self.assertNotIn("e.open_changed_date", query)
        self.assertNotIn("2026-03-01", query)

    async def test_product_session_state_uses_same_public_episode_count_policy(self):
        db = _Db(
            {
                **_product_row(character_chat_eligible=1),
                "openYn": "Y",
                "blindYn": "N",
                "aiContentServiceEnabledYn": "Y",
                "ratingsCode": "all",
            }
        )

        product = await websochat_service._get_websochat_product_session_state(
            1182,
            "N",
            db,
        )

        self.assertTrue(product["characterChatEligible"])
        query = db.statements[0]
        self.assertIn("COUNT(e.episode_id) >= 15", query)
        self.assertNotIn("p.status_code = 'ongoing'", query)
        self.assertNotIn("e.open_changed_date", query)
        self.assertNotIn("2026-03-01", query)

    async def test_character_chat_readiness_requires_usable_turn_examples(self):
        profile = {
            "character_key": "character:adelite",
            "display_name": "아델리트",
            "personality_core": ["신중함"],
            "speech_style": {
                "tone": ["차분함"],
                "formality": "존댓말",
                "sentence_length": "보통",
            },
        }
        inventory = {
            "display_name": "아델리트",
            "public_chat_eligible": True,
            "display_safety": {"status": "pass"},
        }
        entry_context = {
            "schema_version": "character_chat_entry_context_v2",
            "product_id": 1182,
            "character_scope_key": "character:adelite",
            "read_episode_to": 1,
            "recent_episode_from": 1,
            "recent_episode_to": 1,
            "recent_plot_rows": [{"episode_no": 1, "summary_text": "첫 회차의 현재 상태"}],
            "character_anchor_episode_no": 1,
            "character_scene": {"scene_gist": "아델리트가 다음 행동을 준비한다."},
        }

        async def load_context(examples):
            async def get_summary_row(*, summary_type, **_kwargs):
                payloads = {
                    "character_rp_profile": profile,
                    "character_rp_examples": {
                        "character_key": "character:adelite",
                        "examples": examples,
                    },
                    "character_inventory_v3": inventory,
                }
                payload = payloads.get(summary_type)
                return (
                    {"summaryText": json.dumps(payload, ensure_ascii=False)}
                    if payload is not None
                    else None
                )

            with (
                patch.object(
                    websochat_service,
                    "_resolve_websochat_active_character_resolution",
                    new_callable=AsyncMock,
                    return_value={"scopeKey": "character:adelite"},
                ),
                patch.object(
                    websochat_service,
                    "_get_websochat_first_available_summary_row",
                    new_callable=AsyncMock,
                    side_effect=get_summary_row,
                ),
                patch.object(
                    websochat_service,
                    "_build_websochat_rp_trajectory_context",
                    new_callable=AsyncMock,
                    return_value={},
                ),
            ):
                return await websochat_service._load_websochat_rp_context(
                    product_row={
                        "productId": 1182,
                        "latestEpisodeNo": 15,
                    },
                    session_memory={
                        "session_kind": "character_chat",
                        "locked_character_scope_key": "character:adelite",
                        "allowed_modes": ["rp"],
                        "active_mode": "rp",
                        "active_character": "character:adelite",
                        "rp_mode": "free",
                        "read_episode_to": 1,
                        "character_chat_entry_context": entry_context,
                    },
                    db=AsyncMock(),
                )

        future = {"episode_no": 7, "text": "후반부 말투 예시"}
        current = {"episode_no": 1, "text": "첫 화 말투 예시"}
        prologue = {"episode_no": 0, "text": "프롤로그 말투 예시"}
        cases = [
            ("future_only", [future], []),
            ("mixed", [current, future], [current]),
            ("blank", [{"episode_no": 1, "text": "   "}], []),
            ("empty", [], []),
            ("malformed", [{"episode_no": "unknown", "text": "잘못된 회차"}], []),
            ("missing_episode", [{"text": "회차 없음"}], []),
            ("negative_episode", [{"episode_no": -1, "text": "잘못된 회차"}], []),
            ("prologue_zero", [prologue], [prologue]),
        ]
        for label, examples, expected in cases:
            with self.subTest(label=label):
                ready = websochat_service._is_websochat_character_chat_rp_context_ready(
                    product_id=1182,
                    read_episode_to=1,
                    resolved_active_character="character:adelite",
                    profile=profile,
                    examples_payload={"character_key": "character:adelite", "examples": examples},
                    internal_prompt_payload=None,
                    internal_prompt="",
                    inventory_payload=inventory,
                    entry_context=entry_context,
                )
                context = await load_context(examples)
                self.assertEqual(ready, bool(expected))
                if not expected:
                    self.assertIsNone(context)
                    continue
                self.assertIsNotNone(context)
                self.assertEqual(context["examples"], expected)
                selected = _select_rp_examples(
                    examples_payload=context["examples"],
                    anchor_episode_no=1,
                    recent_messages=[],
                    scene_summary_text="",
                    relationship_stage="",
                    read_episode_to=1,
                )
                self.assertEqual(selected, [f"- {item['text']}" for item in expected])

    def test_only_character_chat_uses_product_policy_for_send_permission(self):
        product = {"canSendMessage": True, "characterChatEligible": 0}

        self.assertTrue(
            websochat_service._resolve_websochat_session_can_send_message(
                product_state=product,
                session_memory={"session_kind": "websochat"},
                max_authorized_episode_to=15,
            )
        )
        self.assertFalse(
            websochat_service._resolve_websochat_session_can_send_message(
                product_state=product,
                session_memory={"session_kind": "character_chat"},
                max_authorized_episode_to=15,
            )
        )

    async def test_character_chat_creation_rejects_out_of_cohort_product(self):
        req_body = PostWebsochatSessionReqBody(
            product_id=1182,
            guest_key="guest-1",
            session_kind="character_chat",
            locked_character_scope_key="character:adelite",
        )
        with (
            patch.object(
                websochat_service,
                "_resolve_actor",
                new_callable=AsyncMock,
                return_value=(None, "guest-1"),
            ),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
                return_value="N",
            ),
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
                return_value=_product_row(character_chat_eligible=0),
            ),
            patch.object(
                websochat_service,
                "_get_websochat_authorized_read_scope",
                new_callable=AsyncMock,
                return_value={"maxAuthorizedEpisodeTo": 15},
            ),
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await websochat_service.create_session(
                    req_body=req_body,
                    kc_user_id=None,
                    adult_yn="N",
                    db=AsyncMock(),
                )

        self.assertEqual(raised.exception.code, "CHARACTER_CHAT_PRODUCT_INELIGIBLE")

    async def test_existing_character_chat_is_read_only_outside_cohort(self):
        req_body = PostWebsochatMessageReqBody(
            guest_key="guest-1",
            client_message_id="message-1",
            content="계속 이야기하자.",
        )
        session_row = {
            "product_id": 1182,
            "session_memory_json": json.dumps(
                {
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "character:adelite",
                    "allowed_modes": ["rp"],
                    "active_mode": "rp",
                }
            ),
        }
        with (
            patch.object(
                websochat_service,
                "_resolve_actor",
                new_callable=AsyncMock,
                return_value=(None, "guest-1"),
            ),
            patch.object(
                websochat_service,
                "_get_session_row",
                new_callable=AsyncMock,
                return_value=session_row,
            ),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
                return_value="N",
            ),
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
                return_value=_product_row(character_chat_eligible=0),
            ),
        ):
            with self.assertRaises(CustomResponseException) as raised:
                await websochat_service.post_message(
                    session_id=77,
                    req_body=req_body,
                    kc_user_id=None,
                    db=AsyncMock(),
                )

        self.assertEqual(raised.exception.code, "CHARACTER_CHAT_PRODUCT_INELIGIBLE")
