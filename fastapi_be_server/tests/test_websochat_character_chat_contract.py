import json
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
    _build_websochat_inventory_v3_scope_aliases,
    _build_websochat_rp_lookup_scope_keys,
    _build_websochat_rp_session_list_state,
    _build_websochat_session_contract_payload,
    _is_websochat_character_chat_rp_context_ready,
    _is_websochat_character_chat_session,
    _resolve_websochat_inventory_v3_alias_rows,
    _resolve_websochat_requested_mode_key,
)
from app.services.websochat.websochat_rp_renderer import (
    build_websochat_rp_system_prompt,
)


def _entry_context(
    read_episode_to: int = 14,
    *,
    character_scope_key: str = "character:신미아:dup:be14d6b7",
) -> dict:
    recent_episode_from = max(1, read_episode_to - 1)
    return {
        "schema_version": "character_chat_entry_context_v2",
        "product_id": 1182,
        "character_scope_key": character_scope_key,
        "read_episode_to": read_episode_to,
        "recent_episode_from": recent_episode_from,
        "recent_episode_to": read_episode_to,
        "recent_plot_rows": [
            {
                "episode_no": episode_no,
                "summary_text": f"{episode_no}화의 작품 상태",
            }
            for episode_no in range(recent_episode_from, read_episode_to + 1)
        ],
        "character_anchor_episode_no": read_episode_to,
        "character_scene": {
            "scene_gist": "데시가 직전 사건의 결과를 확인한다.",
            "current_action": "데시가 다음 움직임을 준비한다.",
            "progression_seed": "직전 결과에서 파생된 새 변수를 꺼낸다.",
        },
    }


class WebsochatCharacterChatContractTest(unittest.TestCase):
    def test_inventory_v3_alias_resolution_rejects_ambiguous_source_only_match(self):
        rows = [
            {
                "scopeKey": "character:민준A",
                "summaryText": json.dumps(
                    {
                        "canonical_character_key": "character:민준A",
                        "source_character_keys": ["named:민준"],
                        "display_name": "민준A",
                    },
                    ensure_ascii=False,
                ),
            },
            {
                "scopeKey": "character:민준B",
                "summaryText": json.dumps(
                    {
                        "canonical_character_key": "character:민준B",
                        "source_character_keys": ["named:민준"],
                        "display_name": "민준B",
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        self.assertIsNone(
            _resolve_websochat_inventory_v3_alias_rows(
                rows,
                scope_key="named:민준",
            )
        )
        exact = _resolve_websochat_inventory_v3_alias_rows(
            rows,
            scope_key="character:민준A",
        )
        self.assertEqual(exact["scopeKey"], "character:민준A")

    def test_inventory_v3_aliases_include_locked_protagonist_identity_history(self):
        aliases = _build_websochat_inventory_v3_scope_aliases(
            scope_key="character:조렌테이머",
            payload={
                "canonical_character_key": "character:조렌테이머",
                "source_character_keys": ["named:조렌테이머"],
                "protagonist_identity_scope_keys": ["character:방호영", "character:조렌테이머"],
            },
        )

        self.assertEqual(
            aliases,
            ["character:조렌테이머", "named:조렌테이머", "character:방호영"],
        )

    def test_session_list_state_uses_persisted_character_without_context_load(self):
        state = _build_websochat_rp_session_list_state(
            {
                "active_character": "character:루벤세이린",
                "active_character_label": "루벤",
                "rp_mode": "free",
            }
        )

        self.assertEqual(
            state,
            {
                "rpStage": "chatting",
                "rpActiveCharacterLabel": "루벤",
            },
        )

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
            product_row={
                "title": "테스트 작품",
                "latestEpisodeNo": 30,
                "websochatSetting": "21화 이후에만 드러나는 세계 설정",
            },
            rp_context={
                "display_name": "데시",
                "speech_style": {"tone": ["차분함"], "formality": "반말"},
                "personality_core": ["경계심이 강함"],
                "baseline_attitude": "상대를 쉽게 믿지 않는다",
                "internal_prompt": "[핵심 정체성] 데시는 장면의 동행자에게 쉽게 마음을 열지 않는다.\n[짧은 입력 처리] 사용자가 짧게 답해도 데시는 주변 상황을 살피며 다음 행동을 제안한다.\n\n[금지 사항]\n- 곁에 선 이 같은 표현을 쓰지 않는다.\n\n[응답 감각]\n- 길게 답한다.",
                "inventory": {
                    "first_seen_episode_no": 1,
                    "future_fact": "21화에서 정체가 밝혀진다.",
                },
                "character_relation_lines": ["21화에서 오리온과 동맹이 된다."],
                "character_chat_entry_context": _entry_context(
                    20,
                    character_scope_key="protagonist:named:데시",
                ),
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

        self.assertNotIn("[캐릭터 내부 프롬프트]", prompt)
        self.assertNotIn("[핵심 정체성] 데시는", prompt)
        self.assertNotIn("21화에서 정체가 밝혀진다", prompt)
        self.assertNotIn("21화에서 오리온과 동맹", prompt)
        self.assertNotIn("21화 이후에만 드러나는 세계 설정", prompt)
        self.assertIn("최신 공개 회차: 20화", prompt)
        self.assertIn("[읽은 범위 진입점]", prompt)
        self.assertIn("19~20화", prompt)
        self.assertIn("20화가 끝난 상태", prompt)
        self.assertIn("데시가 직전 사건의 결과를 확인한다.", prompt)
        self.assertIn("직전 결과에서 파생된 새 변수를 꺼낸다.", prompt)
        self.assertNotIn("[캐릭터챗 오프닝 자산]", prompt)
        self.assertNotIn("[캐릭터챗 런타임 전개 공식]", prompt)
        self.assertIn("[대화 운영 상태]", prompt)
        self.assertIn('"schema_version": "runtime_turn_state_v1"', prompt)
        self.assertIn('"next_required_move": "scene_opening"', prompt)
        self.assertIn("[캐릭터챗 하드 렌더링 가드]", prompt)
        self.assertIn("이 블록은 내부 프롬프트와 RP 예시보다 우선한다", prompt)
        self.assertIn("사용자가 방금 입력에서 직접 밝힌 행동, 말, 상태만 이어받을 수 있다", prompt)
        self.assertIn("캐릭터는 자신의 접근, 시선, 접촉, 판단을 먼저 행동할 수 있다", prompt)
        self.assertIn("사용자의 감정, 반응, 성공, 다음 행동은 확정하지 않는다", prompt)
        self.assertIn("협력 요청은 선택 가능하게 남기고", prompt)
        self.assertIn("[캐릭터챗 첫인사 오프닝]", prompt)
        self.assertIn("첫 문단은 300~500자 안팎의 서술형 지문", prompt)
        self.assertIn("서술형 지문 문단, 빈 줄, 큰따옴표 대사 순서", prompt)
        self.assertIn("첫 대사는 외부 사물, 접근하는 인물, 소리, 표식, 선택지", prompt)
        self.assertIn("질문/협력 요청/선택 여지", prompt)
        self.assertIn("이미 장면에 엮인 비네임드 조력자/동행자/관계자", prompt)
        self.assertIn("사용자의 정체를 심문하는 반복 전개", prompt)
        self.assertIn("원작 기존 네임드/짐승/환자/포로로 확정하지 마라", prompt)
        self.assertIn("치료 보조, 기록 담당, 임시 동행자", prompt)
        self.assertNotIn("허가받지 않은 존재", prompt)
        self.assertIn("첫인사에는 아직 사용자가 밝힌 행동이 없으므로", prompt)
        self.assertIn("사용자가 무엇을 했는지는 다음 입력을 기다린다", prompt)
        self.assertIn("[캐릭터챗 응답 계약]", prompt)
        self.assertIn("사용자가 대화와 행동에 참여 가능한 사람이라고 전제하라", prompt)
        self.assertIn("외부 침입자로 몰아가는 대신", prompt)
        self.assertIn("첫 줄 지문은 캐릭터와 환경만 묘사하고 사용자를 직접 지칭하지 마라", prompt)
        self.assertIn("원작 사건 복기가 아니라 원작에서 파생된 새 사이드 사건/새 변수/새 단서", prompt)
        self.assertIn("원작 플롯은 앵커로만 사용하라", prompt)
        self.assertIn("새 사건의 비중을 원작 요약보다 높게 둬라", prompt)
        self.assertIn("장면 압력, 협력 요청, 자연스러운 1~2개 행동 방향", prompt)
        self.assertIn("직접 결과 1개, 관찰 가능한 새 변수 1개", prompt)
        self.assertIn("아직 풀리지 않은 다음 선택 1개", prompt)
        self.assertIn("조사, 개봉, 공격, 이동 중 하나를 선택하지 않았다면", prompt)
        self.assertIn("관찰, 가설, 검증을 서로 다른 턴으로 나눈다", prompt)
        self.assertIn("관계 반응을 최소 하나 포함하라", prompt)
        self.assertIn("첫 줄은 지문", prompt)
        self.assertIn("모든 큰따옴표 대사 앞에 실제 화자명이나 호칭과 콜론", prompt)
        self.assertIn("사용자가 단답", prompt)
        self.assertIn("사용자가 입력에서 직접 묘사한 몸짓이나 위치는 이어받을 수 있지만", prompt)
        self.assertIn("사용자에 관한 서술마다 직전 입력의 근거가 있는지 확인한다", prompt)
        self.assertNotIn("[금지 사항]", prompt)
        self.assertNotIn("곁에 선 이", prompt)
        self.assertNotIn("네가 가리킨", prompt)
        self.assertNotIn("잡아채", prompt)
        self.assertIn("새로운 인사말이나 자기소개로 재시작하지 마라", prompt)
        self.assertIn("매 턴 최소 하나의 물리적 행동, 새 변수, 관계 반응, 장면 변화", prompt)
        self.assertNotIn("지문은 필요할 때만 0~1문장", prompt)

    def test_character_chat_rp_prompt_does_not_repeat_opening_after_first_reply(self):
        prompt = build_websochat_rp_system_prompt(
            product_row={"title": "테스트 작품", "latestEpisodeNo": 20},
            rp_context={
                "display_name": "데시",
                "internal_prompt": "[핵심 정체성] 데시는 이미 사용자를 경계하고 있다.",
                "character_chat_entry_context": _entry_context(
                    20,
                    character_scope_key="protagonist:named:데시",
                ),
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
        self.assertNotIn("[캐릭터챗 런타임 전개 공식]", prompt)
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
            entry_context=_entry_context(),
        )

        self.assertFalse(ready)

    def test_character_chat_context_accepts_locked_protagonist_identity_assets(self):
        canonical_scope_key = "character:조렌테이머"
        previous_identity_scope_key = "character:방호영"
        ready = _is_websochat_character_chat_rp_context_ready(
            product_id=1182,
            read_episode_to=14,
            resolved_active_character=canonical_scope_key,
            compatible_scope_keys=[canonical_scope_key, previous_identity_scope_key],
            profile={
                "character_key": previous_identity_scope_key,
                "display_name": "조렌테이머",
            },
            examples_payload={
                "character_key": previous_identity_scope_key,
                "examples": [{"text": "가자."}],
            },
            internal_prompt_payload=None,
            internal_prompt="",
            inventory_payload={
                "display_name": "조렌테이머",
                "public_chat_eligible": True,
                "display_safety": {"status": "pass"},
            },
            entry_context=_entry_context(
                character_scope_key=canonical_scope_key,
            ),
        )

        self.assertTrue(ready)

    def test_character_chat_context_requires_character_key_on_all_assets(self):
        scope_key = "character:신미아:dup:be14d6b7"
        base_profile = {"character_key": scope_key, "display_name": "신미아"}
        base_examples_payload = {"character_key": scope_key, "examples": [{"text": "가자."}]}
        base_internal_prompt_payload = {
            "character_key": scope_key,
            "internal_prompt": "[핵심 정체성] 신미아",
        }
        base_entry_context = _entry_context()

        for missing_asset in ("profile", "examples_payload"):
            profile = dict(base_profile)
            examples_payload = dict(base_examples_payload)
            internal_prompt_payload = dict(base_internal_prompt_payload)
            if missing_asset == "profile":
                profile.pop("character_key")
            elif missing_asset == "examples_payload":
                examples_payload.pop("character_key")

            with self.subTest(missing_asset=missing_asset):
                ready = _is_websochat_character_chat_rp_context_ready(
                    resolved_active_character=scope_key,
                    profile=profile,
                    examples_payload=examples_payload,
                    internal_prompt_payload=internal_prompt_payload,
                    internal_prompt="[핵심 정체성] 신미아",
                    inventory_payload={
                        "display_name": "신미아",
                        "public_chat_eligible": True,
                        "display_safety": {"status": "pass"},
                    },
                    entry_context=dict(base_entry_context),
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
            entry_context=_entry_context(),
        )

        self.assertFalse(ready)

    def test_character_chat_context_requires_read_boundary_entry_context(self):
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
            entry_context=None,
        )

        self.assertFalse(ready)

    def test_character_chat_context_rejects_wrong_entry_context_identity(self):
        wrong_product = _entry_context()
        wrong_product["product_id"] = 999
        wrong_character = _entry_context()
        wrong_character["character_scope_key"] = "character:다른인물"
        wrong_read_scope = _entry_context()
        wrong_read_scope["read_episode_to"] = 13

        for entry_context in (
            {"schema_version": "character_chat_entry_context_v1"},
            wrong_product,
            wrong_character,
            wrong_read_scope,
        ):
            with self.subTest(entry_context=entry_context):
                ready = _is_websochat_character_chat_rp_context_ready(
                    product_id=1182,
                    read_episode_to=14,
                    resolved_active_character="character:신미아:dup:be14d6b7",
                    profile={
                        "character_key": "character:신미아:dup:be14d6b7",
                        "display_name": "신미아",
                    },
                    examples_payload={
                        "character_key": "character:신미아:dup:be14d6b7",
                        "examples": [{"text": "가자."}],
                    },
                    internal_prompt_payload=None,
                    internal_prompt="",
                    inventory_payload={
                        "display_name": "신미아",
                        "public_chat_eligible": True,
                        "display_safety": {"status": "pass"},
                    },
                    entry_context=entry_context,
                )

                self.assertFalse(ready)

    def test_character_chat_context_accepts_exact_identity_bundle(self):
        ready = _is_websochat_character_chat_rp_context_ready(
            product_id=1182,
            read_episode_to=14,
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
            entry_context=_entry_context(),
        )

        self.assertTrue(ready)


if __name__ == "__main__":
    unittest.main()
