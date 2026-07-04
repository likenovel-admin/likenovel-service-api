import unittest

from fastapi import status

from app.exceptions import CustomResponseException
from app.services.websochat.websochat_game_memory import (
    _merge_websochat_session_memory,
    _normalize_websochat_session_memory,
    _serialize_websochat_session_memory,
)
from app.services.websochat.websochat_service import (
    _assert_websochat_session_allows_mode,
    _build_websochat_rp_lookup_scope_keys,
    _build_websochat_session_contract_payload,
    _is_websochat_character_chat_rp_context_ready,
    _is_websochat_character_chat_session,
    _resolve_websochat_requested_mode_key,
)
from app.services.websochat.websochat_rp_renderer import (
    build_websochat_rp_system_prompt,
)


class WebsochatCharacterChatContractTest(unittest.TestCase):
    def test_character_chat_memory_locks_to_rp_and_scope_key(self):
        normalized = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "entry_source": "home_character_slot",
                "locked_character_scope_key": "protagonist:named:데시",
                "active_character": "supporting:named:오리온",
                "allowed_modes": ["qa", "rp", "ideal_worldcup"],
                "game_context": {"mode": "ideal_worldcup"},
            }
        )

        self.assertEqual(normalized["session_kind"], "character_chat")
        self.assertEqual(normalized["entry_source"], "home_character_slot")
        self.assertEqual(normalized["locked_character_scope_key"], "protagonist:named:데시")
        self.assertEqual(normalized["allowed_modes"], ["rp"])
        self.assertEqual(normalized["active_character"], "protagonist:named:데시")
        self.assertEqual(normalized["rp_mode"], "free")
        self.assertEqual(normalized["active_mode"], "rp")
        self.assertIsNone(normalized["game_context"]["mode"])

    def test_default_websochat_memory_keeps_all_modes_and_can_be_empty(self):
        normalized = _normalize_websochat_session_memory({})

        self.assertEqual(normalized["session_kind"], "websochat")
        self.assertEqual(normalized["allowed_modes"], ["qa", "rp", "ideal_worldcup"])
        self.assertIsNone(_serialize_websochat_session_memory(normalized))

    def test_character_chat_contract_is_serialized_even_without_messages(self):
        serialized = _serialize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "entry_source": "home_character_slot",
                "locked_character_scope_key": "protagonist:named:데시",
                "allowed_modes": ["rp"],
            }
        )

        self.assertIsNotNone(serialized)

    def test_character_chat_merge_keeps_locked_character(self):
        merged = _merge_websochat_session_memory(
            base_memory={
                "session_kind": "character_chat",
                "locked_character_scope_key": "protagonist:named:데시",
                "allowed_modes": ["rp"],
            },
            rp_mode="free",
            active_character="supporting:named:오리온",
            active_character_label="오리온",
            scene_episode_no=None,
        )

        self.assertEqual(merged["active_character"], "protagonist:named:데시")
        self.assertIsNone(merged["active_character_label"])
        self.assertEqual(merged["active_mode"], "rp")

    def test_character_chat_session_allows_only_rp_mode(self):
        memory = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "locked_character_scope_key": "protagonist:named:데시",
                "allowed_modes": ["rp"],
            }
        )

        _assert_websochat_session_allows_mode(memory, "rp")
        for blocked_mode in ["qa", "ideal_worldcup"]:
            with self.subTest(blocked_mode=blocked_mode):
                with self.assertRaises(CustomResponseException) as captured:
                    _assert_websochat_session_allows_mode(memory, blocked_mode)
                self.assertEqual(captured.exception.status_code, status.HTTP_400_BAD_REQUEST)

    def test_character_chat_session_kind_helper_detects_locked_session(self):
        memory = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "locked_character_scope_key": "protagonist:named:데시",
            }
        )

        self.assertTrue(_is_websochat_character_chat_session(memory))

    def test_qa_action_wins_over_rp_starter_for_mode_gate(self):
        memory = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "locked_character_scope_key": "protagonist:named:데시",
                "allowed_modes": ["rp"],
            }
        )

        requested_mode = _resolve_websochat_requested_mode_key(
            starter_mode_key="rp",
            qa_action_key="predict",
            game_mode=None,
            session_memory=memory,
        )

        self.assertEqual(requested_mode, "qa")
        with self.assertRaises(CustomResponseException):
            _assert_websochat_session_allows_mode(memory, requested_mode)

    def test_session_contract_payload_uses_camel_case_api_fields(self):
        payload = _build_websochat_session_contract_payload(
            {
                "session_kind": "character_chat",
                "entry_source": "home_character_slot",
                "locked_character_scope_key": "protagonist:named:데시",
                "allowed_modes": ["rp"],
            }
        )

        self.assertEqual(
            payload,
            {
                "sessionKind": "character_chat",
                "entrySource": "home_character_slot",
                "lockedCharacterScopeKey": "protagonist:named:데시",
                "allowedModes": ["rp"],
            },
        )

    def test_character_chat_rp_prompt_requires_immersive_scene_reply(self):
        prompt = build_websochat_rp_system_prompt(
            product_row={"title": "테스트 작품", "latestEpisodeNo": 20},
            rp_context={
                "display_name": "데시",
                "speech_style": {"tone": ["차분함"], "formality": "반말"},
                "personality_core": ["경계심이 강함"],
                "baseline_attitude": "상대를 쉽게 믿지 않는다",
                "internal_prompt": "[핵심 정체성] 데시는 장면의 동행자에게 쉽게 마음을 열지 않는다.\n[짧은 입력 처리] 사용자가 짧게 답해도 데시는 주변 상황을 살피며 다음 행동을 제안한다.",
                "character_chat_opening": {
                    "opening_message": {
                        "narration": "복도 끝의 등이 낮게 흔들리고, 데시는 문고리 위에 얹은 손을 멈춘다. 바닥의 먼지 위로 새로 생긴 긁힌 자국이 안쪽으로 이어지고, 문틈 아래에서는 차갑게 식은 공기가 밀려 나온다. 데시는 먼저 숨을 낮추고 등불의 그림자를 벽 쪽으로 돌린다. 금속 손잡이는 안쪽에서 아주 작게 떨리고, 가까워지던 발소리는 문 하나를 사이에 둔 듯 갑자기 멈춘다. 지금 흔적을 확인하지 않으면 다음 방의 움직임을 놓치고, 곧바로 열면 안쪽의 누군가가 먼저 반응할 수 있다.",
                        "dialogue": "\"발소리가 가까워지고 있어. 저 흔적이 안쪽으로 이어지는지 먼저 확인해야 해.\"",
                        "opening_text": "복도 끝의 등이 낮게 흔들리고, 데시는 문고리 위에 얹은 손을 멈춘다. 바닥의 먼지 위로 새로 생긴 긁힌 자국이 안쪽으로 이어지고, 문틈 아래에서는 차갑게 식은 공기가 밀려 나온다. 데시는 먼저 숨을 낮추고 등불의 그림자를 벽 쪽으로 돌린다. 금속 손잡이는 안쪽에서 아주 작게 떨리고, 가까워지던 발소리는 문 하나를 사이에 둔 듯 갑자기 멈춘다. 지금 흔적을 확인하지 않으면 다음 방의 움직임을 놓치고, 곧바로 열면 안쪽의 누군가가 먼저 반응할 수 있다.\n\n\"발소리가 가까워지고 있어. 저 흔적이 안쪽으로 이어지는지 먼저 확인해야 해.\"",
                        "user_objective": "문틈 아래 흔적을 확인할지 발소리의 방향을 먼저 들을지 선택한다.",
                    },
                    "opening_scene": {
                        "situation": "데시가 복도 끝 소리를 확인한다.",
                        "immediate_conflict": "발소리가 가까워진다.",
                    },
                    "user_role": {
                        "role_type": "임시 동행자",
                        "first_turn_affordance": "문틈 아래 흔적을 확인할 수 있다.",
                    },
                    "agency_contract": {
                        "character_moves_first": True,
                        "non_user_dependent_action": "데시가 먼저 문고리를 확인한다.",
                    },
                    "progression_engine": {
                        "scene_exit_condition": "흔적을 확인하고 다음 방으로 이동한다.",
                        "event_injection_rules": [{"inject": "발소리가 한 칸 가까워진다."}],
                    },
                    "canon_safe_expansion": {
                        "safe_new_event_pattern": "복도에서 파생된 작은 방해",
                    },
                },
                "session_memory": {
                    "session_kind": "character_chat",
                    "entry_source": "home_character_slot",
                    "locked_character_scope_key": "protagonist:named:데시",
                    "allowed_modes": ["rp"],
                    "read_episode_to": 20,
                },
            },
            recent_messages=[],
        )

        self.assertIn("[캐릭터 내부 프롬프트]", prompt)
        self.assertIn("[핵심 정체성] 데시는", prompt)
        self.assertIn("[캐릭터챗 오프닝 자산]", prompt)
        self.assertIn("opening_message", prompt)
        self.assertIn("발소리가 가까워지고 있어", prompt)
        self.assertIn("첫 assistant 응답 초안", prompt)
        self.assertIn("데시가 복도 끝 소리를 확인한다.", prompt)
        self.assertIn("character_moves_first", prompt)
        self.assertIn("scene_exit_condition", prompt)
        self.assertIn("canon_safe_expansion", prompt)
        self.assertIn("캐릭터 운용 원칙", prompt)
        self.assertIn("[대화 운영 상태]", prompt)
        self.assertIn('"schema_version": "runtime_turn_state_v1"', prompt)
        self.assertIn('"next_required_move": "scene_opening"', prompt)
        self.assertIn("하드 렌더링 가드/첫인사 오프닝/응답 계약이 내부 프롬프트와 RP 예시보다 우선", prompt)
        self.assertIn("[캐릭터챗 하드 렌더링 가드]", prompt)
        self.assertIn("이 블록은 내부 프롬프트와 RP 예시보다 우선한다", prompt)
        self.assertIn("지문은 캐릭터, 환경, 사물, 사건만 묘사한다", prompt)
        self.assertIn("`너/네/당신/상대/보조자/사용자`", prompt)
        self.assertIn("`곁에 선 이`, `옆의 사람`, `너를 향해`, `너에게`", prompt)
        self.assertIn("시선, 턱짓, 속삭임, 대답, 명령의 대상이 사용자인 표현도 금지", prompt)
        self.assertIn("`기록판을 들고 있다`, `약재를 가리켰다`, `레지던트 때처럼`", prompt)
        self.assertIn("[캐릭터챗 첫인사 오프닝]", prompt)
        self.assertIn("opening_message.opening_text", prompt)
        self.assertIn("첫 문단은 300~500자 안팎의 서술형 지문", prompt)
        self.assertIn("서술형 지문 문단, 빈 줄, 큰따옴표 대사 순서", prompt)
        self.assertIn("대사에서도 사용자의 자세, 은신, 침입, 허가 여부, 멍함, 목적 은폐를 단정하지 마라", prompt)
        self.assertIn("질문/협력 요청/선택 여지", prompt)
        self.assertIn("이미 장면에 엮인 비네임드 조력자/동행자/관계자", prompt)
        self.assertIn("사용자의 정체를 추궁하지 마라", prompt)
        self.assertIn("'너 누구냐', '왜 여기 있지', '수상한 놈', '침입자냐'", prompt)
        self.assertIn("정체 미스터리/심문 루프", prompt)
        self.assertIn("원작 기존 네임드/짐승/환자/포로로 확정하지 마라", prompt)
        self.assertIn("치료 보조, 기록 담당, 임시 동행자", prompt)
        self.assertNotIn("허가받지 않은 존재", prompt)
        self.assertIn("지문에서는 2인칭 대명사 전체를 쓰지 마라", prompt)
        self.assertIn("`너/네/당신/상대/보조자`", prompt)
        self.assertIn("`곁에 선 이`, `옆의 사람`, `너를 향해`, `너에게`", prompt)
        self.assertIn("`저 약재`, `밖 소리`, `저쪽 통로`", prompt)
        self.assertIn("`네가 가리킨`, `네가 들고 있는`, `너를 향해`, `너를 돌아보며`", prompt)
        self.assertIn("협력 요청은 대사 속 선택형으로만 하라", prompt)
        self.assertIn("밀거나 이동시키거나 환부를 닦게 하거나 증거를 쥐여 주었다고", prompt)
        self.assertIn("사용자의 표정, 떨림, 긴장, 행동, 감정, 숨소리, 소지품, 서 있는 자세는 확정하지 마라", prompt)
        self.assertIn("얼굴/발끝/몸을 훑는 묘사는 쓰지 마라", prompt)
        self.assertIn("2인칭 호명은 캐릭터 대사 안에서만 사용하라", prompt)
        self.assertIn("'곁에 선 너', '멍하니 서서', '네가 멈춰 선', '네가 가리킨', '네 발치'", prompt)
        self.assertIn("'상대의 어깨/눈/손/발치/몸'", prompt)
        self.assertIn("사용자를 잡아채거나 끌어당기거나 짓누르거나 몸을 낮추게", prompt)
        self.assertIn("'너를 쏘아보았다', '너를 힐끗 보았다', '너를 쳐다보지도 않았다'", prompt)
        self.assertIn("관계 반응은 대사, 말투, 판단, 주변 사물에 대한 반응으로 드러내라", prompt)
        self.assertIn("[캐릭터챗 응답 계약]", prompt)
        self.assertIn("사용자가 대화와 행동에 참여 가능한 사람이라고 전제하라", prompt)
        self.assertIn("외부 침입자로 몰아가는 대신", prompt)
        self.assertIn("첫 줄 지문은 캐릭터와 환경만 묘사하고 사용자를 직접 지칭하지 마라", prompt)
        self.assertIn("원작 사건 복기가 아니라 원작에서 파생된 새 사이드 사건/새 변수/새 단서", prompt)
        self.assertIn("원작 플롯은 앵커로만 사용하라", prompt)
        self.assertIn("새 사건의 비중을 원작 요약보다 높게 둬라", prompt)
        self.assertIn("장면 압력, 협력 요청, 자연스러운 1~2개 행동 방향", prompt)
        self.assertIn("관계 반응을 최소 하나 포함하라", prompt)
        self.assertIn("첫 줄은 지문", prompt)
        self.assertIn("사용자가 단답", prompt)
        self.assertIn("사용자의 신체 반응, 내면, 위치, 움직임, 소지품을 관찰했다고 단정하지 마라", prompt)
        self.assertIn("얼굴/발끝/몸을 훑었다는 지문도 쓰지 마라", prompt)
        self.assertIn("상대의 어깨를 잡아끈다", prompt)
        self.assertIn("상대의 눈을 본다", prompt)
        self.assertIn("상대의 귓가에 속삭인다", prompt)
        self.assertIn("잡아채/끌어당겨/짓눌러/몸을 낮추게", prompt)
        self.assertIn("문 앞을 지키고 서서", prompt)
        self.assertIn("뒤에 숨어서", prompt)
        self.assertIn("너를 향해/돌아보며/쏘아보/힐끗 보/쳐다보", prompt)
        self.assertIn("사용자의 자세, 위치, 손짓, 시선을 새로 만든 표현도 쓰지 마라", prompt)
        self.assertIn("최종 출력 전에 지문을 자체검수하라", prompt)
        self.assertIn("캐릭터의 시선이 출입구/복도/주변 사물로 향하거나 캐릭터 자신만 움직이는 묘사로 고쳐라", prompt)
        self.assertIn("`너/네/당신/상대/보조자/곁에 선 이/옆의 사람/너에게`", prompt)
        self.assertIn("`밀어 넣/떠밀/잡아채/끌어당겨/짓눌러/몸을 낮추게`", prompt)
        self.assertIn("새로운 인사말이나 자기소개로 재시작하지 마라", prompt)
        self.assertIn("매 턴 최소 하나의 물리적 행동, 새 변수, 관계 반응, 장면 변화", prompt)
        self.assertNotIn("지문은 필요할 때만 0~1문장", prompt)

    def test_character_chat_rp_prompt_does_not_repeat_opening_after_first_reply(self):
        prompt = build_websochat_rp_system_prompt(
            product_row={"title": "테스트 작품", "latestEpisodeNo": 20},
            rp_context={
                "display_name": "데시",
                "internal_prompt": "[핵심 정체성] 데시는 이미 사용자를 경계하고 있다.",
                "session_memory": {
                    "session_kind": "character_chat",
                    "entry_source": "home_character_slot",
                    "locked_character_scope_key": "protagonist:named:데시",
                    "allowed_modes": ["rp"],
                    "read_episode_to": 20,
                },
            },
            recent_messages=[
                {
                    "role": "user",
                    "content": "응",
                },
                {
                    "role": "assistant",
                    "content": "복도 끝에서 데시가 먼저 말을 걸었다.",
                }
            ],
            current_user_prompt="그래",
        )

        self.assertNotIn("[캐릭터챗 첫인사 오프닝]", prompt)
        self.assertIn("[캐릭터챗 응답 계약]", prompt)
        self.assertIn("이미 시작된 장면의 다음 순간처럼 이어가라", prompt)
        self.assertIn('"stall_count": 2', prompt)
        self.assertIn('"latest_user_intent": "short_or_ambiguous"', prompt)
        self.assertIn('"next_required_move": "state_change"', prompt)

    def test_default_websochat_rp_prompt_keeps_lightweight_reply_contract(self):
        prompt = build_websochat_rp_system_prompt(
            product_row={"title": "테스트 작품", "latestEpisodeNo": 20},
            rp_context={
                "display_name": "데시",
                "session_memory": {
                    "session_kind": "websochat",
                    "allowed_modes": ["qa", "rp", "ideal_worldcup"],
                    "read_episode_to": 20,
                },
            },
            recent_messages=[],
        )

        self.assertNotIn("[캐릭터챗 응답 계약]", prompt)
        self.assertNotIn("[대화 운영 상태]", prompt)
        self.assertIn("지문은 필요할 때만 0~1문장", prompt)

    def test_character_chat_lookup_uses_exact_resolved_scope_only(self):
        memory = _normalize_websochat_session_memory(
            {
                "session_kind": "character_chat",
                "locked_character_scope_key": "character:신미아:dup:be14d6b7",
                "allowed_modes": ["rp"],
            }
        )

        scope_keys = _build_websochat_rp_lookup_scope_keys(
            normalized_memory=memory,
            resolved_active_character="character:신미아:dup:be14d6b7",
            resolution={
                "aliasScopeKeys": [
                    "character:신미아:dup:be14d6b7",
                    "protagonist:first_person",
                    "named:신미아",
                ],
            },
        )

        self.assertEqual(scope_keys, ["character:신미아:dup:be14d6b7"])

    def test_default_rp_lookup_keeps_alias_scope_keys_for_legacy_sessions(self):
        memory = _normalize_websochat_session_memory(
            {
                "session_kind": "websochat",
                "allowed_modes": ["qa", "rp", "ideal_worldcup"],
            }
        )

        scope_keys = _build_websochat_rp_lookup_scope_keys(
            normalized_memory=memory,
            resolved_active_character="character:신미아:dup:be14d6b7",
            resolution={
                "aliasScopeKeys": [
                    "character:신미아:dup:be14d6b7",
                    "protagonist:first_person",
                    "named:신미아",
                ],
            },
        )

        self.assertEqual(
            scope_keys,
            [
                "character:신미아:dup:be14d6b7",
                "protagonist:first_person",
                "named:신미아",
            ],
        )

    def test_character_chat_context_rejects_mismatched_profile_identity(self):
        ready = _is_websochat_character_chat_rp_context_ready(
            resolved_active_character="character:신미아:dup:be14d6b7",
            profile={
                "character_key": "protagonist:first_person",
                "display_name": "추종자",
            },
            examples_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "examples": [{"text": "가자."}],
            },
            internal_prompt_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "internal_prompt": "[핵심 정체성] 신미아",
            },
            internal_prompt="[핵심 정체성] 신미아",
            inventory_payload={
                "display_name": "신미아",
                "public_chat_eligible": True,
                "display_safety": {"status": "pass"},
            },
            opening_payload={
                "chat_target": {"scope_key": "character:신미아:dup:be14d6b7"},
                "readiness": {"status": "ready"},
            },
        )

        self.assertFalse(ready)

    def test_character_chat_context_requires_v3_public_gate(self):
        ready = _is_websochat_character_chat_rp_context_ready(
            resolved_active_character="character:신미아:dup:be14d6b7",
            profile={
                "character_key": "character:신미아:dup:be14d6b7",
                "display_name": "신미아",
            },
            examples_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "examples": [{"text": "가자."}],
            },
            internal_prompt_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "internal_prompt": "[핵심 정체성] 신미아",
            },
            internal_prompt="[핵심 정체성] 신미아",
            inventory_payload={
                "display_name": "신미아",
                "distinct_episode_count": 10,
            },
            opening_payload={
                "chat_target": {"scope_key": "character:신미아:dup:be14d6b7"},
                "readiness": {"status": "ready"},
            },
        )

        self.assertFalse(ready)

    def test_character_chat_context_requires_opening_asset(self):
        ready = _is_websochat_character_chat_rp_context_ready(
            resolved_active_character="character:신미아:dup:be14d6b7",
            profile={
                "character_key": "character:신미아:dup:be14d6b7",
                "display_name": "신미아",
            },
            examples_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "examples": [{"text": "가자."}],
            },
            internal_prompt_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "internal_prompt": "[핵심 정체성] 신미아",
            },
            internal_prompt="[핵심 정체성] 신미아",
            inventory_payload={
                "display_name": "신미아",
                "public_chat_eligible": True,
                "display_safety": {"status": "pass"},
            },
            opening_payload=None,
        )

        self.assertFalse(ready)

    def test_character_chat_context_accepts_exact_identity_bundle(self):
        ready = _is_websochat_character_chat_rp_context_ready(
            resolved_active_character="character:신미아:dup:be14d6b7",
            profile={
                "character_key": "character:신미아:dup:be14d6b7",
                "display_name": "신미아",
            },
            examples_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "examples": [{"text": "가자."}],
            },
            internal_prompt_payload={
                "character_key": "character:신미아:dup:be14d6b7",
                "internal_prompt": "[핵심 정체성] 신미아",
            },
            internal_prompt="[핵심 정체성] 신미아",
            inventory_payload={
                "display_name": "신미아",
                "public_chat_eligible": True,
                "display_safety": {"status": "pass"},
            },
            opening_payload={
                "chat_target": {"scope_key": "character:신미아:dup:be14d6b7"},
                "readiness": {"status": "ready"},
                "opening_scene": {"situation": "신미아가 먼저 움직인다."},
                "opening_message": {
                    "narration": "어두운 통로의 기척이 한순간 끊기고, 신미아는 손끝에 걸린 작은 표식을 확인한다. 닫힌 문 안쪽에서 낮은 마찰음이 이어지고, 천장 틈으로 떨어진 먼지가 등불 가장자리에서 희미하게 흩어진다. 신미아는 먼저 문턱 앞에 무릎을 낮추지 않고, 벽에 남은 표식의 방향만 천천히 맞춘다. 표식은 안쪽이 아니라 옆 통로의 낮은 배수구 쪽으로 이어져 있고, 그 아래에서 누군가 금속을 긁는 듯한 소리가 끊긴다. 지금 문을 열면 소리의 주인을 놓치고, 배수구를 확인하면 안쪽의 움직임이 먼저 반응할 수 있다.",
                    "dialogue": "\"지금 열면 안 돼. 저 표식이 어느 쪽으로 이어지는지 먼저 확인해야 해.\"",
                    "opening_text": "어두운 통로의 기척이 한순간 끊기고, 신미아는 손끝에 걸린 작은 표식을 확인한다. 닫힌 문 안쪽에서 낮은 마찰음이 이어지고, 천장 틈으로 떨어진 먼지가 등불 가장자리에서 희미하게 흩어진다. 신미아는 먼저 문턱 앞에 무릎을 낮추지 않고, 벽에 남은 표식의 방향만 천천히 맞춘다. 표식은 안쪽이 아니라 옆 통로의 낮은 배수구 쪽으로 이어져 있고, 그 아래에서 누군가 금속을 긁는 듯한 소리가 끊긴다. 지금 문을 열면 소리의 주인을 놓치고, 배수구를 확인하면 안쪽의 움직임이 먼저 반응할 수 있다.\n\n\"지금 열면 안 돼. 저 표식이 어느 쪽으로 이어지는지 먼저 확인해야 해.\"",
                    "user_objective": "표식의 방향을 확인할지 문 안쪽 소리를 먼저 들을지 선택한다.",
                },
            },
        )

        self.assertTrue(ready)


if __name__ == "__main__":
    unittest.main()
