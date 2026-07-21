import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.schemas.websochat import PostWebsochatCharacterChoicesReqBody
from app.services.websochat import websochat_service
from app.services.websochat.websochat_service import (
    _build_websochat_character_chat_choice_anchor_candidates,
    _build_websochat_character_chat_choices_cache_key,
    _build_websochat_character_chat_choice_prompt,
    _parse_and_validate_websochat_character_chat_choices,
)


class WebsochatCharacterChatChoicesTest(unittest.TestCase):
    def setUp(self):
        websochat_service._WEBSOCHAT_CHARACTER_CHAT_CHOICES_CACHE.clear()
        websochat_service._WEBSOCHAT_CHARACTER_CHAT_CHOICES_RATE_BUCKETS.clear()

    def test_choice_prompt_is_for_user_input_not_character_reply(self):
        prompt = _build_websochat_character_chat_choice_prompt(
            product_row={"title": "테스트 작품"},
            rp_context={
                "display_name": "데시",
                "active_character": "protagonist:named:데시",
                "character_chat_entry_context": {
                    "schema_version": "character_chat_entry_context_v2",
                    "product_id": 1182,
                    "character_scope_key": "protagonist:named:데시",
                    "read_episode_to": 14,
                    "recent_episode_from": 13,
                    "recent_episode_to": 14,
                    "character_anchor_episode_no": 14,
                    "character_scene": {
                        "scene_gist": "데시가 문틈 아래 흔적과 발소리를 확인한다.",
                    },
                },
                "session_memory": {
                    "recent_rp_facts": ["문틈 아래 금속음이 들렸다."],
                },
            },
            recent_messages=[
                {"role": "assistant", "content": "데시는 낮게 숨을 죽였다."},
            ],
            source_assistant_message={
                "messageId": 77,
                "content": "데시는 문 아래 흔적을 가리키며 선택을 기다렸다.",
            },
        )

        self.assertIn("캐릭터챗 composer 선택지 생성기", prompt["system"])
        self.assertIn("캐릭터의 다음 답변을 쓰지 않는다", prompt["system"])
        self.assertIn("사용자가 다음에 보낼 수 있는 입력 후보", prompt["user"])
        self.assertIn("source_assistant_message_id", prompt["user"])
        self.assertIn("문틈 아래 흔적", prompt["user"])
        self.assertIn("character_anchor_episode_no", prompt["user"])
        self.assertIn("choices는 반드시 3개", prompt["user"])
        self.assertIn("intentKind", prompt["user"])
        self.assertIn("targetAnchorId", prompt["user"])
        self.assertIn("target_anchor_candidates", prompt["user"])
        self.assertIn("후보의 id 중 하나", prompt["user"])
        self.assertNotIn("문맥이 부족하면", prompt["user"])

    def test_choice_cache_key_is_bound_to_product_character_and_read_boundary(self):
        base = {
            "session_id": 10,
            "source_assistant_message_id": 88,
            "product_id": 123,
            "character_scope_key": "protagonist:named:데시",
        }

        key_r14 = _build_websochat_character_chat_choices_cache_key(
            **base,
            read_episode_to=14,
        )
        key_r15 = _build_websochat_character_chat_choices_cache_key(
            **base,
            read_episode_to=15,
        )
        key_other_character = _build_websochat_character_chat_choices_cache_key(
            **{
                **base,
                "character_scope_key": "character:신미아",
            },
            read_episode_to=14,
        )

        self.assertNotEqual(key_r14, key_r15)
        self.assertNotEqual(key_r14, key_other_character)

    def test_choice_anchor_candidates_are_short_exact_source_phrases(self):
        source = "데시는 문 아래 흔적을 가리켰다. 문 안쪽에서 금속음이 울렸다."

        candidates = _build_websochat_character_chat_choice_anchor_candidates(source)

        self.assertIn("아래 흔적을", candidates)
        self.assertIn("금속음이 울렸다", candidates)
        self.assertNotIn("금속음이", candidates)
        self.assertNotIn("문 아래 흔적을", candidates)
        self.assertTrue(all(candidate in source for candidate in candidates))
        self.assertTrue(all(2 <= len(candidate) <= 24 for candidate in candidates))
        self.assertTrue(all("." not in candidate for candidate in candidates))

    def test_choice_anchor_candidates_preserve_the_latest_scene_targets(self):
        source = " ".join(f"초반단서{index}" for index in range(70)) + " 마지막 가방 부품"

        candidates = _build_websochat_character_chat_choice_anchor_candidates(source)

        self.assertIn("초반단서0 초반단서1", candidates)
        self.assertIn("가방 부품", candidates)
        self.assertNotIn("초반단서0", candidates)

    def test_choice_anchor_id_mapping_is_stable_for_long_assistant_text(self):
        source = " ".join(f"단서{index}" for index in range(400))
        prompt_candidates = _build_websochat_character_chat_choice_anchor_candidates(
            source[:1600]
        )
        expected_anchor = prompt_candidates[-1]
        target_anchor_id = f"a{len(prompt_candidates)}"

        choices = _parse_and_validate_websochat_character_chat_choices(
            {
                "choices": [
                    {
                        "label": "마지막 단서 확인",
                        "dialogue": "마지막으로 언급한 단서를 확인할게요.",
                        "narration": "단서가 나온 대목을 다시 살핀다.",
                        "intentKind": "observe",
                        "targetAnchorId": target_anchor_id,
                    }
                ]
            },
            active_character_scope_key="protagonist:named:데시",
            active_character_label="데시",
            source_assistant_text=source,
        )

        self.assertEqual(choices[0]["targetAnchor"], expected_anchor)

    def test_choice_validator_keeps_only_user_side_advancing_choices(self):
        choices = _parse_and_validate_websochat_character_chat_choices(
            {
                "choices": [
                    {
                        "label": "흔적 확인",
                        "dialogue": "제가 문틈 아래 흔적을 먼저 볼게요.",
                        "narration": "등불을 낮춰 바닥을 비춘다.",
                    },
                    {
                        "label": "캐릭터 대사",
                        "dialogue": "데시는 문고리를 붙잡고 말했다.",
                        "narration": "",
                    },
                    {
                        "label": "데시에게 확인",
                        "dialogue": "데시, 저쪽 발소리부터 확인해도 될까요?",
                        "narration": "나는 데시가 가리킨 복도 쪽으로 몸을 낮춘다.",
                    },
                    {
                        "label": "정체 묻기",
                        "dialogue": "넌 누구야? 내가 왜 여기 있지?",
                        "narration": "",
                    },
                    {
                        "label": "흔적 확인",
                        "dialogue": "제가 문틈 아래 흔적을 먼저 볼게요.",
                        "narration": "등불을 낮춰 바닥을 비춘다.",
                    },
                    {
                        "label": "세계 해결",
                        "dialogue": "내가 모든 흑막과 원작 결말을 알고 있으니 지금 끝내죠.",
                        "narration": "",
                    },
                ]
            },
            active_character_scope_key="protagonist:named:데시",
            active_character_label="데시",
        )

        self.assertEqual(
            choices,
            [
                {
                    "label": "흔적 확인",
                    "dialogue": "제가 문틈 아래 흔적을 먼저 볼게요.",
                    "narration": "등불을 낮춰 바닥을 비춘다.",
                },
                {
                    "label": "데시에게 확인",
                    "dialogue": "데시, 저쪽 발소리부터 확인해도 될까요?",
                    "narration": "나는 데시가 가리킨 복도 쪽으로 몸을 낮춘다.",
                }
            ],
        )

    def test_choice_validator_caps_lengths_and_result_count(self):
        parsed = {
            "choices": [
                {
                    "label": f"선택지 {idx} 라벨이 너무 길어서 잘려야 합니다",
                    "dialogue": "제가 확인해보겠습니다. " * 20,
                    "narration": "조심스럽게 움직인다. " * 20,
                }
                for idx in range(5)
            ]
        }

        choices = _parse_and_validate_websochat_character_chat_choices(
            parsed,
            active_character_scope_key="protagonist:named:데시",
            active_character_label="데시",
        )

        self.assertEqual(len(choices), 3)
        for choice in choices:
            self.assertLessEqual(len(choice["label"]), 28)
            self.assertLessEqual(len(choice["dialogue"]), 120)
            self.assertLessEqual(len(choice["narration"]), 120)

    def test_choice_validator_rejects_resolved_outcome_choices(self):
        choices = _parse_and_validate_websochat_character_chat_choices(
            {
                "choices": [
                    {
                        "label": "투표 용지가 아님을 보고",
                        "dialogue": "이건 투표 용지가 아니라고 바로 말할게요.",
                        "narration": "종이를 확인한 뒤 결과를 전한다.",
                    },
                    {
                        "label": "증거물 강제 확보",
                        "dialogue": "제가 증거를 확보하겠습니다.",
                        "narration": "상대의 손에서 종이를 빼앗는다.",
                    },
                    {
                        "label": "종이 정체 확인",
                        "dialogue": "제가 이 종이가 뭔지 먼저 확인해 볼게요.",
                        "narration": "바닥에 떨어진 종이를 조심스럽게 펼친다.",
                    },
                ]
            },
            active_character_scope_key="protagonist:named:데시",
            active_character_label="데시",
        )

        self.assertEqual(
            choices,
            [
                {
                    "label": "종이 정체 확인",
                    "dialogue": "제가 이 종이가 뭔지 먼저 확인해 볼게요.",
                    "narration": "바닥에 떨어진 종이를 조심스럽게 펼친다.",
                }
            ],
        )

    def test_choice_validator_exposes_only_grounded_structured_intent(self):
        source_assistant_text = (
            "데시는 문 아래 흔적을 가리키며 선택을 기다렸다. "
            "그리고 문 안쪽의 금속음도 오래 확인했다."
        )
        anchor_candidates = _build_websochat_character_chat_choice_anchor_candidates(
            source_assistant_text
        )
        valid_anchor_id = f"a{anchor_candidates.index('아래 흔적을') + 1}"
        choices = _parse_and_validate_websochat_character_chat_choices(
            {
                "choices": [
                    {
                        "label": "흔적 확인",
                        "dialogue": "제가 문 아래 흔적을 먼저 볼게요.",
                        "narration": "등불을 낮춰 바닥을 살핀다.",
                        "intentKind": "observe",
                        "targetAnchorId": valid_anchor_id,
                    },
                    {
                        "label": "넓은 구절 확인",
                        "dialogue": "문 아래 흔적을 확인해 볼게요.",
                        "narration": "등불을 낮춰 살핀다.",
                        "intentKind": "interact",
                        "targetAnchorId": "a999",
                    },
                    {
                        "label": "긴 명령 확인",
                        "dialogue": "방금 말한 지시를 확인해 볼게요.",
                        "narration": "지시 대상을 다시 살핀다.",
                        "intentKind": "observe",
                        "targetAnchorId": "not-an-anchor-id",
                    },
                ]
            },
            active_character_scope_key="protagonist:named:데시",
            active_character_label="데시",
            source_assistant_text=source_assistant_text,
        )

        self.assertEqual(choices[0]["intentKind"], "observe")
        self.assertEqual(choices[0]["targetAnchor"], "아래 흔적을")
        self.assertNotIn("intentKind", choices[1])
        self.assertNotIn("targetAnchor", choices[1])
        self.assertNotIn("intentKind", choices[2])
        self.assertNotIn("targetAnchor", choices[2])


class WebsochatCharacterChatChoicesServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        websochat_service._WEBSOCHAT_CHARACTER_CHAT_CHOICES_CACHE.clear()
        websochat_service._WEBSOCHAT_CHARACTER_CHAT_CHOICES_RATE_BUCKETS.clear()

    async def test_post_choices_rejects_non_character_chat_session(self):
        req_body = PostWebsochatCharacterChoicesReqBody(
            guest_key="guest-1",
            source_assistant_message_id=77,
        )

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
        ):
            resolve_actor.return_value = (None, "guest-1")
            get_session_row.return_value = {
                "product_id": 123,
                "session_memory_json": {"session_kind": "websochat"},
            }

            with self.assertRaises(CustomResponseException) as captured:
                await websochat_service.post_character_chat_choices(
                    session_id=10,
                    req_body=req_body,
                    kc_user_id=None,
                    db=object(),
                )

        self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(captured.exception.code, "NOT_CHARACTER_CHAT_SESSION")

    async def test_cached_choices_still_require_current_authorization(self):
        req_body = PostWebsochatCharacterChoicesReqBody(
            guest_key="guest-1",
            source_assistant_message_id=88,
        )
        session_memory = {
            "session_kind": "character_chat",
            "locked_character_scope_key": "protagonist:named:데시",
            "allowed_modes": ["rp"],
            "read_episode_to": 14,
            "read_scope_state": "known",
        }
        cache_key = _build_websochat_character_chat_choices_cache_key(
            session_id=10,
            source_assistant_message_id=88,
            product_id=123,
            character_scope_key="protagonist:named:데시",
            read_episode_to=14,
        )
        websochat_service._set_websochat_character_chat_choices_cache(
            cache_key,
            choices=[
                {
                    "label": "흔적 확인",
                    "dialogue": "제가 흔적을 확인할게요.",
                    "narration": "바닥을 살핀다.",
                }
            ],
            generation_source="generated",
        )

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
                return_value=object(),
            ),
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages_with_ids",
                new_callable=AsyncMock,
                return_value=[
                    {"messageId": 77, "role": "user", "content": "어떻게 할까요?"},
                    {"messageId": 88, "role": "assistant", "content": "데시는 흔적을 가리켰다."},
                ],
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
                return_value={
                    "productId": 123,
                    "title": "테스트 작품",
                    "latestEpisodeNo": 14,
                    "syncedLatestEpisodeNo": 14,
                    "characterChatEligible": True,
                },
            ),
            patch.object(websochat_service, "_assert_websochat_product_context_available"),
            patch.object(
                websochat_service,
                "_clamp_websochat_session_read_scope_to_authorized",
                new_callable=AsyncMock,
                return_value=(dict(session_memory), {"maxAuthorizedEpisodeTo": 0}),
            ) as clamp_scope,
            patch.object(
                websochat_service,
                "_ensure_websochat_character_chat_entry_context",
                new_callable=AsyncMock,
            ) as ensure_entry,
            patch.object(
                websochat_service,
                "call_websochat_model",
                new_callable=AsyncMock,
            ) as call_model,
        ):
            resolve_actor.return_value = (None, "guest-1")
            get_session_row.return_value = {
                "product_id": 123,
                "session_memory_json": dict(session_memory),
            }

            result = await websochat_service.post_character_chat_choices(
                session_id=10,
                req_body=req_body,
                kc_user_id=None,
                db=object(),
            )

        self.assertEqual(result["data"]["choices"], [])
        clamp_scope.assert_awaited_once()
        ensure_entry.assert_not_awaited()
        call_model.assert_not_awaited()

    async def test_post_choices_returns_empty_on_stale_source_without_llm(self):
        req_body = PostWebsochatCharacterChoicesReqBody(
            guest_key="guest-1",
            source_assistant_message_id=77,
        )
        session_lock = object()

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
            ) as acquire_lock,
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ) as release_lock,
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages_with_ids",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(
                websochat_service,
                "call_websochat_model",
                new_callable=AsyncMock,
            ) as call_model,
        ):
            resolve_actor.return_value = (None, "guest-1")
            get_session_row.return_value = {
                "product_id": 123,
                "session_memory_json": {
                    "session_kind": "character_chat",
                    "locked_character_scope_key": "protagonist:named:데시",
                    "allowed_modes": ["rp"],
                },
            }
            acquire_lock.return_value = session_lock
            get_recent_messages.return_value = [
                {"messageId": 76, "role": "user", "content": "어떻게 할까요?"},
                {"messageId": 88, "role": "assistant", "content": "데시는 흔적을 가리켰다."},
            ]

            result = await websochat_service.post_character_chat_choices(
                session_id=10,
                req_body=req_body,
                kc_user_id=None,
                db=object(),
            )

        self.assertEqual(
            result,
            {"data": {"choices": [], "sourceAssistantMessageId": 88, "generationSource": "none"}},
        )
        release_lock.assert_awaited_once_with(session_id=10, conn=session_lock)
        call_model.assert_not_awaited()

    async def test_post_choices_retries_when_first_generation_only_has_outcomes(self):
        req_body = PostWebsochatCharacterChoicesReqBody(
            guest_key="guest-1",
            source_assistant_message_id=88,
        )
        session_lock = object()
        session_memory = {
            "session_kind": "character_chat",
            "locked_character_scope_key": "protagonist:named:데시",
            "allowed_modes": ["rp"],
            "read_scope_state": "known",
        }

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
            ) as acquire_lock,
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages_with_ids",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(websochat_service, "_enforce_websochat_character_chat_choice_rate_limit"),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
            ) as get_product,
            patch.object(websochat_service, "_assert_websochat_product_context_available"),
            patch.object(
                websochat_service,
                "_clamp_websochat_session_read_scope_to_authorized",
                new_callable=AsyncMock,
            ) as clamp_scope,
            patch.object(
                websochat_service,
                "_resolve_websochat_synced_latest_episode_no",
                return_value=10,
            ),
            patch.object(
                websochat_service,
                "_resolve_websochat_read_scope_state",
                return_value="known",
            ),
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
            patch.object(
                websochat_service,
                "_ensure_websochat_character_chat_entry_context",
                new_callable=AsyncMock,
            ) as ensure_entry,
            patch.object(
                websochat_service,
                "_load_websochat_rp_context",
                new_callable=AsyncMock,
            ) as load_rp_context,
            patch.object(
                websochat_service,
                "call_websochat_model",
                new_callable=AsyncMock,
            ) as call_model,
        ):
            resolve_actor.return_value = (None, "guest-1")
            get_session_row.return_value = {
                "product_id": 123,
                "session_memory_json": dict(session_memory),
            }
            acquire_lock.return_value = session_lock
            get_recent_messages.return_value = [
                {"messageId": 77, "role": "user", "content": "저는 뭘 하면 되죠?"},
                {
                    "messageId": 88,
                    "role": "assistant",
                    "content": "데시는 바닥에 떨어진 종이를 가리켰다.",
                },
            ]
            resolve_adult.return_value = "N"
            get_product.return_value = {
                "product_id": 123,
                "title": "테스트 작품",
                "synced_latest_episode_no": 10,
                "characterChatEligible": True,
            }
            clamp_scope.return_value = (dict(session_memory), {"maxAuthorizedEpisodeTo": 10})
            resolve_character.return_value = {
                "scopeKey": "protagonist:named:데시",
                "inventoryPayload": {},
            }
            ensure_entry.return_value = dict(session_memory)
            load_rp_context.return_value = {
                "display_name": "데시",
                "active_character": "protagonist:named:데시",
                "session_memory": {},
            }
            call_model.side_effect = [
                json.dumps(
                    {
                        "choices": [
                            {
                                "label": "투표 용지가 아님을 보고",
                                "dialogue": "이건 투표 용지가 아니라고 말할게요.",
                                "narration": "",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "choices": [
                            {
                                "label": "종이 정체 확인",
                                "dialogue": "제가 이 종이가 뭔지 먼저 확인해 볼게요.",
                                "narration": "바닥에 떨어진 종이를 조심스럽게 펼친다.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            ]

            result = await websochat_service.post_character_chat_choices(
                session_id=10,
                req_body=req_body,
                kc_user_id=None,
                db=object(),
            )

        self.assertEqual(len(result["data"]["choices"]), 3)
        self.assertEqual(result["data"]["generationSource"], "floor")
        self.assertEqual(
            result["data"]["choices"][0],
            {
                "label": "종이 정체 확인",
                "dialogue": "제가 이 종이가 뭔지 먼저 확인해 볼게요.",
                "narration": "바닥에 떨어진 종이를 조심스럽게 펼친다.",
            },
        )
        self.assertEqual(call_model.await_count, 2)
        ensure_entry.assert_awaited_once()

    async def test_post_choices_returns_safe_floor_when_both_generations_are_invalid(self):
        req_body = PostWebsochatCharacterChoicesReqBody(
            guest_key="guest-1",
            source_assistant_message_id=88,
        )
        session_lock = object()
        session_memory = {
            "session_kind": "character_chat",
            "locked_character_scope_key": "protagonist:named:데시",
            "allowed_modes": ["rp"],
            "read_scope_state": "known",
        }

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
            ) as acquire_lock,
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages_with_ids",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(websochat_service, "_enforce_websochat_character_chat_choice_rate_limit"),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
            ) as get_product,
            patch.object(websochat_service, "_assert_websochat_product_context_available"),
            patch.object(
                websochat_service,
                "_clamp_websochat_session_read_scope_to_authorized",
                new_callable=AsyncMock,
            ) as clamp_scope,
            patch.object(
                websochat_service,
                "_resolve_websochat_synced_latest_episode_no",
                return_value=10,
            ),
            patch.object(
                websochat_service,
                "_resolve_websochat_read_scope_state",
                return_value="known",
            ),
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
            patch.object(
                websochat_service,
                "_ensure_websochat_character_chat_entry_context",
                new_callable=AsyncMock,
            ) as ensure_entry,
            patch.object(
                websochat_service,
                "_load_websochat_rp_context",
                new_callable=AsyncMock,
            ) as load_rp_context,
            patch.object(
                websochat_service,
                "call_websochat_model",
                new_callable=AsyncMock,
            ) as call_model,
        ):
            resolve_actor.return_value = (None, "guest-1")
            get_session_row.return_value = {
                "product_id": 123,
                "session_memory_json": dict(session_memory),
            }
            acquire_lock.return_value = session_lock
            get_recent_messages.return_value = [
                {"messageId": 77, "role": "user", "content": "저는 뭘 하면 되죠?"},
                {
                    "messageId": 88,
                    "role": "assistant",
                    "content": "데시는 바닥에 떨어진 종이를 가리켰다.",
                },
            ]
            resolve_adult.return_value = "N"
            get_product.return_value = {
                "product_id": 123,
                "title": "테스트 작품",
                "synced_latest_episode_no": 10,
                "characterChatEligible": True,
            }
            clamp_scope.return_value = (dict(session_memory), {"maxAuthorizedEpisodeTo": 10})
            resolve_character.return_value = {
                "scopeKey": "protagonist:named:데시",
                "inventoryPayload": {},
            }
            ensure_entry.return_value = dict(session_memory)
            load_rp_context.return_value = {
                "display_name": "데시",
                "active_character": "protagonist:named:데시",
                "session_memory": {},
            }
            invalid_choices = json.dumps(
                {
                    "choices": [
                        {
                            "label": "자백시키기",
                            "dialogue": "제가 범인을 자백시키겠습니다.",
                            "narration": "",
                        }
                    ]
                },
                ensure_ascii=False,
            )
            call_model.side_effect = [invalid_choices, invalid_choices]

            result = await websochat_service.post_character_chat_choices(
                session_id=10,
                req_body=req_body,
                kc_user_id=None,
                db=object(),
            )

        self.assertEqual(len(result["data"]["choices"]), 3)
        self.assertEqual(result["data"]["generationSource"], "floor")
        self.assertEqual(
            [choice["label"] for choice in result["data"]["choices"]],
            ["상황 확인", "직접 확인", "단서 비교"],
        )
        joined = "\n".join(choice["label"] for choice in result["data"]["choices"])
        self.assertNotIn("자백", joined)
        self.assertEqual(call_model.await_count, 2)
        self.assertEqual(websochat_service._WEBSOCHAT_CHARACTER_CHAT_CHOICES_CACHE, {})

    async def test_post_choices_retries_when_first_generation_has_less_than_three_choices(self):
        req_body = PostWebsochatCharacterChoicesReqBody(
            guest_key="guest-1",
            source_assistant_message_id=88,
        )
        session_lock = object()
        session_memory = {
            "session_kind": "character_chat",
            "locked_character_scope_key": "protagonist:named:데시",
            "allowed_modes": ["rp"],
            "read_scope_state": "known",
        }

        with (
            patch.object(websochat_service, "_resolve_actor", new_callable=AsyncMock) as resolve_actor,
            patch.object(websochat_service, "_get_session_row", new_callable=AsyncMock) as get_session_row,
            patch.object(
                websochat_service,
                "_acquire_websochat_session_lock",
                new_callable=AsyncMock,
            ) as acquire_lock,
            patch.object(
                websochat_service,
                "_release_websochat_session_lock",
                new_callable=AsyncMock,
            ),
            patch.object(
                websochat_service,
                "_get_websochat_recent_messages_with_ids",
                new_callable=AsyncMock,
            ) as get_recent_messages,
            patch.object(websochat_service, "_enforce_websochat_character_chat_choice_rate_limit"),
            patch.object(
                websochat_service,
                "_resolve_effective_adult_yn",
                new_callable=AsyncMock,
            ) as resolve_adult,
            patch.object(
                websochat_service,
                "_get_websochat_product",
                new_callable=AsyncMock,
            ) as get_product,
            patch.object(websochat_service, "_assert_websochat_product_context_available"),
            patch.object(
                websochat_service,
                "_clamp_websochat_session_read_scope_to_authorized",
                new_callable=AsyncMock,
            ) as clamp_scope,
            patch.object(
                websochat_service,
                "_resolve_websochat_synced_latest_episode_no",
                return_value=10,
            ),
            patch.object(
                websochat_service,
                "_resolve_websochat_read_scope_state",
                return_value="known",
            ),
            patch.object(
                websochat_service,
                "_resolve_websochat_active_character_resolution",
                new_callable=AsyncMock,
            ) as resolve_character,
            patch.object(
                websochat_service,
                "_ensure_websochat_character_chat_entry_context",
                new_callable=AsyncMock,
            ) as ensure_entry,
            patch.object(
                websochat_service,
                "_load_websochat_rp_context",
                new_callable=AsyncMock,
            ) as load_rp_context,
            patch.object(
                websochat_service,
                "call_websochat_model",
                new_callable=AsyncMock,
            ) as call_model,
        ):
            resolve_actor.return_value = (None, "guest-1")
            get_session_row.return_value = {
                "product_id": 123,
                "session_memory_json": dict(session_memory),
            }
            acquire_lock.return_value = session_lock
            get_recent_messages.return_value = [
                {"messageId": 77, "role": "user", "content": "저는 뭘 하면 되죠?"},
                {
                    "messageId": 88,
                    "role": "assistant",
                    "content": "데시는 바닥에 떨어진 종이를 가리켰다.",
                },
            ]
            resolve_adult.return_value = "N"
            get_product.return_value = {
                "product_id": 123,
                "title": "테스트 작품",
                "synced_latest_episode_no": 10,
                "characterChatEligible": True,
            }
            clamp_scope.return_value = (dict(session_memory), {"maxAuthorizedEpisodeTo": 10})
            resolve_character.return_value = {
                "scopeKey": "protagonist:named:데시",
                "inventoryPayload": {},
            }
            ensure_entry.return_value = dict(session_memory)
            load_rp_context.return_value = {
                "display_name": "데시",
                "active_character": "protagonist:named:데시",
                "session_memory": {},
            }
            call_model.side_effect = [
                json.dumps(
                    {
                        "choices": [
                            {
                                "label": "종이 정체 확인",
                                "dialogue": "제가 이 종이가 뭔지 먼저 확인해 볼게요.",
                                "narration": "바닥에 떨어진 종이를 조심스럽게 펼친다.",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "choices": [
                            {
                                "label": "종이 정체 확인",
                                "dialogue": "제가 이 종이가 뭔지 먼저 확인해 볼게요.",
                                "narration": "바닥에 떨어진 종이를 조심스럽게 펼친다.",
                                "intentKind": "observe",
                                "targetAnchorId": "a3",
                            },
                            {
                                "label": "사진 촬영 제안",
                                "dialogue": "건드리기 전에 이 종이를 사진으로 남겨도 될까요?",
                                "narration": "나는 손을 멈추고 데시의 반응을 기다린다.",
                                "intentKind": "assist",
                                "targetAnchorId": "a2",
                            },
                            {
                                "label": "발소리 확인",
                                "dialogue": "저쪽 발소리부터 확인하면 단서가 이어질 것 같아요.",
                                "narration": "복도 쪽으로 몸을 낮춘다.",
                                "intentKind": "move",
                                "targetAnchorId": "a4",
                            },
                        ]
                    },
                    ensure_ascii=False,
                ),
            ]

            result = await websochat_service.post_character_chat_choices(
                session_id=10,
                req_body=req_body,
                kc_user_id=None,
                db=object(),
            )

        self.assertEqual(len(result["data"]["choices"]), 3)
        self.assertEqual(result["data"]["generationSource"], "generated")
        self.assertEqual(
            [choice["label"] for choice in result["data"]["choices"]],
            ["종이 정체 확인", "사진 촬영 제안", "발소리 확인"],
        )
        self.assertEqual(result["data"]["choices"][0]["targetAnchor"], "떨어진 종이를")
        self.assertTrue(
            all("targetAnchorId" not in choice for choice in result["data"]["choices"])
        )
        self.assertEqual(call_model.await_count, 2)
        self.assertEqual(
            list(websochat_service._WEBSOCHAT_CHARACTER_CHAT_CHOICES_CACHE.values())[0][1]["generationSource"],
            "generated",
        )


if __name__ == "__main__":
    unittest.main()
