import inspect
import json
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.services.admin import admin_ai_metadata_service
from app.services.common.openrouter_background_credit_guard import (
    OpenRouterBackgroundCreditReserveError,
)


class _MappingsResult:
    def __init__(self, rows):
        self.rows = rows

    def mappings(self):
        return self

    def one(self):
        return self.rows[0]

    def all(self):
        return self.rows

    def one_or_none(self):
        return self.rows[0] if self.rows else None


class AdminAiMetadataPromptTest(unittest.TestCase):
    def test_prompt_and_schema_require_librarian_copy(self):
        prompt = admin_ai_metadata_service.DNA_SYSTEM_PROMPT
        template = admin_ai_metadata_service.DNA_USER_TEMPLATE
        allowed = {
            axis: {f"{axis}-label"}
            for axis in admin_ai_metadata_service.AXIS_ORDER
        }
        response_format = admin_ai_metadata_service._build_openrouter_dna_response_format(allowed)
        summary_schema = response_format["json_schema"]["schema"]["properties"]["summary"]

        self.assertIn("summary.librarian", prompt)
        self.assertIn("금칙어", prompt)
        self.assertIn('"librarian"', template)
        self.assertIn("librarian", summary_schema["properties"])
        self.assertIn("librarian", summary_schema["required"])
        self.assertEqual(
            summary_schema["properties"]["librarian"]["required"],
            ["intro", "points", "chips"],
        )

    def test_reanalyze_upsert_persists_librarian_columns(self):
        source = inspect.getsource(admin_ai_metadata_service.reanalyze_ai_product_metadata)

        for column in ("librarian_intro", "librarian_points", "librarian_chips"):
            self.assertIn(f":{column}", source)
            self.assertIn(f"{column} = VALUES({column})", source)

    def test_normalize_payload_keeps_librarian_copy(self):
        normalized = admin_ai_metadata_service._normalize_ai_payload(
            {
                "summary": {
                    "librarian": {
                        "intro": "해고된 날 대문호가 깃들었어요. 유쾌한 이야기를 좋아하면 잘 맞아요.",
                        "points": [
                            "출발점은 게임 개발이에요.",
                            "주인공은 개발자예요.",
                            "코미디를 좋아하면 어울려요.",
                        ],
                        "chips": ["먼치킨", "게임개발", "코미디"],
                    }
                }
            },
            enforce_axis_minimum=False,
            enforce_legacy_required=False,
        )

        self.assertTrue(normalized["librarian_intro"].startswith("해고된 날"))
        self.assertEqual(len(normalized["librarian_points"]), 3)
        self.assertEqual(normalized["librarian_chips"], ["먼치킨", "게임개발", "코미디"])

    def test_prompt_separates_ai_librarian_public_tone_from_internal_summary_style(self):
        prompt = admin_ai_metadata_service.DNA_SYSTEM_PROMPT

        self.assertIn("summary.premise", prompt)
        self.assertIn("summary.hook", prompt)
        self.assertIn("핵심 설정", prompt)
        self.assertIn("초반 진입 포인트", prompt)
        self.assertIn("AI 사서 공개 소개", prompt)
        self.assertIn("해요체", prompt)
        self.assertIn('"다", "합니다", "입니다" 종결을 쓰지 않는다', prompt)
        self.assertIn("summary.protagonist_desc와 summary.episode_summary_text", prompt)
        self.assertIn("존댓말 없이 간결한 서술체", prompt)

    def test_prompt_treats_axis_labels_as_recommendation_graph_signals(self):
        prompt = admin_ai_metadata_service.DNA_SYSTEM_PROMPT

        self.assertIn("상호배타 장르 분류가 아니라", prompt)
        self.assertIn("작품을 엮는 작품 신호", prompt)
        self.assertIn("여러 라벨을 동시에 부여", prompt)
        self.assertIn("조합 라벨을 새로 만들지 않는다", prompt)
        self.assertIn("강한 근거 순서로 정렬", prompt)
        self.assertIn("최대 개수를 채우려 하지 않는다", prompt)
        self.assertIn("시대 배경 라벨과 기관", prompt)
        self.assertIn("중세와 아카데미를 함께 선택", prompt)
        self.assertIn("단순 언급이나 스쳐 지나가는 배경만으로는 선택하지 않는다", prompt)
        self.assertIn("내부 그룹 키 의미", prompt)
        self.assertIn("상태창은 스탯, 스킬, 업적을 보여주는 정보 창", prompt)
        self.assertIn("회귀는 과거 특정 시점", prompt)
        self.assertIn("아카데미는 특수능력 교육기관", prompt)
        self.assertIn("직업을 추정하지 않는다", prompt)
        self.assertIn("아카데미 입학", prompt)
        self.assertIn("조력자는 단순 도움 제공이 아니라", prompt)
        self.assertIn("axis_* 이름은 저장용 내부 키", prompt)
        self.assertNotIn("/", prompt)
        self.assertIn("회귀, 빙의, 환생, 귀환자는 서로 독립적인 추천 신호", prompt)
        self.assertIn("긴 시간 단절 뒤 같은 세계의 후대에 다시 등장", prompt)

    def test_prompt_defines_hook_as_entry_point_not_marketing_copy(self):
        prompt = admin_ai_metadata_service.DNA_SYSTEM_PROMPT

        self.assertIn("초반 1~3화", prompt)
        self.assertIn("광고 카피가 아니라", prompt)
        self.assertIn("구체적 사건, 위기, 목표, 반전, 보상 약속", prompt)
        self.assertIn("추상 홍보문구", prompt)
        self.assertIn("본문에 없는 기대감 생성", prompt)

    def test_normalizer_uses_source_evidence_guards_for_axis_labels(self):
        payload = {
            "summary": {
                "protagonist_type": "회귀자",
                "protagonist_desc": "과거로 돌아와 전생의 실패를 고치려는 마법사다.",
                "heroine_type": "없음",
                "heroine_weight": "none",
                "mood": "후회",
                "pacing": "fast",
                "premise": "대마법사가 회귀해 전사 아카데미 입학을 목표로 한다.",
                "hook": "전사 아카데미 입학 과제를 해결하며 새 인생을 시작한다.",
                "themes": ["성장"],
                "taste_tags": ["중세"],
            },
            "axis_labels": {
                "세": ["중세"],
                "직": ["마법사", "소방관"],
                "능": ["마법", "소드마스터"],
                "연": [],
                "작": ["후회"],
                "타": ["회귀", "성장형"],
                "목": ["성장"],
            },
            "axis_confidence": {
                "세": 0.9,
                "직": 0.8,
                "능": 0.9,
                "연": 0.0,
                "작": 0.8,
                "타": 0.9,
                "목": 0.9,
            },
            "axis_label_scores": {
                "직": [
                    {"label": "마법사", "score": 0.8},
                    {"label": "소방관", "score": 0.7},
                ],
            },
            "overall_confidence": 0.86,
        }

        normalized = admin_ai_metadata_service._normalize_ai_payload(
            payload,
            enforce_axis_minimum=True,
            enforce_legacy_required=True,
            drop_unsupported_axis_labels=True,
            source_text="중세 제국의 전사 아카데미 입학 시험을 통과해야 한다.",
        )

        self.assertEqual(normalized["worldview_tags"], ["중세", "아카데미"])
        self.assertEqual(normalized["protagonist_job_tags"], ["마법사"])
        self.assertEqual(normalized["axis_label_scores"]["직"], [{"label": "마법사", "score": 0.8}])

    def test_normalizer_replaces_status_window_with_buff_when_evidence_says_no_status_window(self):
        payload = {
            "summary": {
                "protagonist_type": "성장형",
                "protagonist_desc": "다크엘프와 계약해 괴물 사냥을 시작하는 소년이다.",
                "heroine_type": "다크엘프",
                "heroine_weight": "low",
                "mood": "비장",
                "pacing": "fast",
                "premise": "계약을 통해 버프를 받고 괴물을 사냥한다.",
                "hook": "다크엘프와의 계약으로 힘을 얻고 복수 여정을 시작한다.",
                "themes": ["복수"],
                "taste_tags": ["이종족"],
            },
            "axis_labels": {
                "세": ["이종족", "중세"],
                "직": ["헌터"],
                "능": ["상태창"],
                "연": [],
                "작": ["비장"],
                "타": ["성장형"],
                "목": ["복수"],
            },
            "axis_confidence": {
                "세": 0.8,
                "직": 0.7,
                "능": 0.7,
                "연": 0.0,
                "작": 0.8,
                "타": 0.8,
                "목": 0.9,
            },
            "evidence": {"능": ["상태창이나 시스템은 없지만 계약으로 버프를 받는다."]},
            "overall_confidence": 0.8,
        }

        normalized = admin_ai_metadata_service._normalize_ai_payload(
            payload,
            enforce_axis_minimum=True,
            enforce_legacy_required=True,
            drop_unsupported_axis_labels=True,
            source_text="다크엘프에게 버프를 받고 계약을 통해 힘을 얻는다.",
        )

        self.assertEqual(normalized["protagonist_material_tags"], ["버프"])
        self.assertEqual(normalized["axis_label_scores"]["능"], [{"label": "버프", "score": 0.7}])

    def test_normalizer_removes_explicit_false_possession_without_synthesizing_growth_type(self):
        payload = {
            "summary": {
                "protagonist_type": "빙의적 상황",
                "protagonist_desc": "재벌가 유언 때문에 트로트 가수 데뷔를 강제받는 손자다.",
                "heroine_type": "없음",
                "heroine_weight": "none",
                "mood": "코미디",
                "pacing": "fast",
                "premise": "재벌집 손자가 시스템 퀘스트로 트로트 가수 데뷔를 목표로 한다.",
                "hook": "AI 시스템이 데뷔 퀘스트와 페널티를 주며 성장을 압박한다.",
                "themes": ["성장"],
                "taste_tags": ["재벌"],
            },
            "axis_labels": {
                "세": ["현대", "재벌", "연예계"],
                "직": ["가수"],
                "능": ["시스템", "상태창"],
                "연": [],
                "작": ["코미디"],
                "타": ["빙의"],
                "목": ["성장"],
            },
            "axis_confidence": {
                "세": 0.9,
                "직": 0.8,
                "능": 0.9,
                "연": 0.0,
                "작": 0.8,
                "타": 0.7,
                "목": 0.9,
            },
            "evidence": {"타": ["시스템이 빙의한 형태로 작동하지만 주인공은 원래 자신의 몸과 신분이다."]},
            "overall_confidence": 0.85,
        }

        normalized = admin_ai_metadata_service._normalize_ai_payload(
            payload,
            enforce_axis_minimum=True,
            enforce_legacy_required=True,
            drop_unsupported_axis_labels=True,
            source_text="주인공은 원래 자신의 몸과 신분 그대로다. 몸이나 영혼의 이동은 없다.",
        )

        self.assertEqual(normalized["protagonist_type_tags"], [])
        self.assertEqual(normalized["axis_label_scores"]["타"], [])

    def test_possession_contradiction_does_not_match_valid_transfer_contexts(self):
        valid_contexts = (
            "그 몸은 원래 자신의 몸이 아니었다.",
            "원래 자신의 몸으로 돌아가기 위해 타인의 육체에서 살아간다.",
            "시스템이 빙의시킨 소설 속 악역의 몸에서 깨어났다.",
            "타인의 몸에 빙의한 뒤 별도의 프로그램이 설치되었다.",
        )

        for source_text in valid_contexts:
            with self.subTest(source_text=source_text):
                self.assertFalse(admin_ai_metadata_service._has_possession_contradiction(source_text))


    def test_normalizer_replaces_non_protagonist_knight_with_hunter(self):
        payload = {
            "summary": {
                "protagonist_type": "성장형",
                "protagonist_desc": "다크엘프와 계약해 괴물 사냥을 시작하는 소년이다.",
                "heroine_type": "다크엘프",
                "heroine_weight": "low",
                "mood": "비장",
                "pacing": "fast",
                "premise": "괴물사냥꾼이 되어 복수를 시작한다.",
                "hook": "아버지가 기사로 언급되지만 주인공은 괴물사냥꾼의 길을 걷는다.",
                "themes": ["복수"],
                "taste_tags": ["이종족"],
            },
            "axis_labels": {
                "세": ["이종족", "중세"],
                "직": ["기사"],
                "능": ["버프"],
                "연": [],
                "작": ["비장"],
                "타": ["성장형"],
                "목": ["복수"],
            },
            "axis_confidence": {
                "세": 0.8,
                "직": 0.7,
                "능": 0.8,
                "연": 0.0,
                "작": 0.8,
                "타": 0.8,
                "목": 0.9,
            },
            "evidence": {"직": ["주인공의 아버지가 기사이며, 주인공도 검술을 사용한다."]},
            "overall_confidence": 0.82,
        }

        normalized = admin_ai_metadata_service._normalize_ai_payload(
            payload,
            enforce_axis_minimum=True,
            enforce_legacy_required=True,
            drop_unsupported_axis_labels=True,
            source_text="괴물사냥꾼이 되어 괴물을 사냥한다. 주인공의 아버지가 기사다.",
        )

        self.assertEqual(normalized["protagonist_job_tags"], ["헌터"])
        self.assertEqual(normalized["axis_label_scores"]["직"], [{"label": "헌터", "score": 0.7}])


class AdminAiMetadataOpenRouterTest(unittest.IsolatedAsyncioTestCase):
    async def test_dna_request_uses_openrouter_auto_routing_and_strict_schema(self):
        allowed = {axis: {f"{axis}-label"} for axis in admin_ai_metadata_service.AXIS_ORDER}
        response = unittest.mock.MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "model": "routed/provider-model",
            "choices": [{"finish_reason": "stop", "message": {"content": "{}"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cost": "0.00125",
                "untrusted_extra": "drop-me",
            },
        }
        post = AsyncMock(return_value=response)

        with (
            patch.object(admin_ai_metadata_service.settings, "OPENROUTER_API_KEY", "test-key"),
            patch.object(admin_ai_metadata_service.settings, "AI_DNA_OPENROUTER_MODEL", "deepseek/test-model"),
            patch.object(admin_ai_metadata_service.settings, "AI_DNA_OPENROUTER_TIMEOUT_SECONDS", 120.0),
            patch.object(admin_ai_metadata_service.settings, "AI_DNA_MAX_OUTPUT_TOKENS", 8192),
            patch.object(admin_ai_metadata_service, "post_openrouter_background_chat_completion_async", post),
        ):
            raw, call_meta = await admin_ai_metadata_service._call_openrouter_dna(
                "system", "user", allowed
            )

        self.assertEqual(raw, "{}")
        request = post.await_args.kwargs["json"]
        self.assertEqual(request["response_format"]["type"], "json_schema")
        self.assertTrue(request["response_format"]["json_schema"]["strict"])
        self.assertEqual(request.get("provider"), {"require_parameters": True})
        self.assertNotIn("only", request.get("provider") or {})
        serialized_request = json.dumps(request, ensure_ascii=False).lower()
        self.assertNotIn("anthropic", serialized_request)
        self.assertNotIn("friendli", serialized_request)
        self.assertEqual(call_meta["routing"], "auto")
        self.assertEqual(
            call_meta["usage"],
            {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "cost": "0.00125",
            },
        )

    def test_dna_admin_module_has_no_anthropic_execution_or_model_persistence(self):
        module_source = inspect.getsource(admin_ai_metadata_service)
        reanalyze_source = inspect.getsource(admin_ai_metadata_service.reanalyze_ai_product_metadata)

        self.assertNotIn("_call_claude", reanalyze_source)
        self.assertNotIn("settings.ANTHROPIC_MODEL", module_source)
        self.assertIn("_call_openrouter_dna", reanalyze_source)

    async def test_dna_http_402_becomes_non_retryable_reserve_error(self):
        allowed = {axis: {f"{axis}-label"} for axis in admin_ai_metadata_service.AXIS_ORDER}
        response = unittest.mock.MagicMock()
        response.status_code = status.HTTP_402_PAYMENT_REQUIRED
        post = AsyncMock(return_value=response)

        with (
            patch.object(admin_ai_metadata_service.settings, "OPENROUTER_API_KEY", "test-key"),
            patch.object(admin_ai_metadata_service.settings, "AI_DNA_OPENROUTER_MODEL", "deepseek/test-model"),
            patch.object(admin_ai_metadata_service, "post_openrouter_background_chat_completion_async", post),
            self.assertRaises(OpenRouterBackgroundCreditReserveError),
        ):
            await admin_ai_metadata_service._call_openrouter_dna("system", "user", allowed)

        self.assertEqual(post.await_count, 1)


class AdminAiMetadataReadTest(unittest.IsolatedAsyncioTestCase):
    async def test_product_analysis_uses_first_public_episode_and_500_chars(self):
        db = AsyncMock()

        async def execute(query, params):
            sql = str(query)
            self.assertNotIn("e.episode_no = 1", sql)
            self.assertIn("ORDER BY e.episode_no ASC, e.episode_id ASC", sql)
            return _MappingsResult(
                [
                    {
                        "product_id": 1225,
                        "title": "아저씨의 요술램프",
                        "author_nickname": "작가",
                        "author_role_type": "normal",
                        "first_episode_text_count": 500,
                        "episode_count": 23,
                    }
                ]
            )

        db.execute.side_effect = execute

        product = await admin_ai_metadata_service._get_product_for_analysis(1225, db)

        self.assertEqual(admin_ai_metadata_service.MIN_FIRST_EPISODE_TEXT_COUNT, 500)
        self.assertEqual(product["product_id"], 1225)

    async def test_product_analysis_rejects_zero_public_episodes(self):
        db = AsyncMock()
        db.execute.return_value = _MappingsResult(
            [
                {
                    "product_id": 1226,
                    "title": "공개 전 작품",
                    "author_nickname": "작가",
                    "author_role_type": "normal",
                    "first_episode_text_count": None,
                    "episode_count": 0,
                }
            ]
        )

        with self.assertRaisesRegex(Exception, "첫 공개회차 500자 미만"):
            await admin_ai_metadata_service._get_product_for_analysis(1226, db)

    async def test_product_analysis_rejects_fewer_than_three_public_episodes(self):
        db = AsyncMock()
        db.execute.return_value = _MappingsResult(
            [
                {
                    "product_id": 1227,
                    "title": "공개 2화 작품",
                    "author_nickname": "작가",
                    "author_role_type": "normal",
                    "first_episode_text_count": 700,
                    "episode_count": 2,
                }
            ]
        )

        with self.assertRaisesRegex(Exception, "3화 미만"):
            await admin_ai_metadata_service._get_product_for_analysis(1227, db)

    async def test_list_exposes_dna_status_and_storyctx_episode_progress(self):
        db = AsyncMock()

        async def execute(query, params):
            sql = str(query)
            if "COUNT(*) AS total_count" in sql:
                self.assertNotIn("fe.episode_no = 1", sql)
                self.assertIn("ORDER BY fe.episode_no ASC, fe.episode_id ASC", sql)
                self.assertIn("), 0) >= 500", sql)
                self.assertRegex(sql, r"COUNT\(\*\)[\s\S]+>= 3")
                return _MappingsResult([{"total_count": 1}])
            self.assertIn("tb_story_agent_context_product", sql)
            self.assertIn("story_context_status", sql)
            self.assertIn("story_ready_episode_no", sql)
            self.assertIn("story_total_episode_count", sql)
            return _MappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "analysis_status": "success",
                        "story_context_status": "processing",
                        "story_ready_episode_no": 8,
                        "story_total_episode_count": 12,
                    }
                ]
            )

        db.execute.side_effect = execute

        result = await admin_ai_metadata_service.ai_product_metadata_list(
            search_target="",
            search_word="",
            analysis_status="all",
            exclude_from_recommend_yn="all",
            page=1,
            count_per_page=20,
            db=db,
        )

        row = result["results"][0]
        self.assertEqual(row["analysis_status"], "success")
        self.assertEqual(row["story_context_status"], "processing")
        self.assertEqual(row["story_ready_episode_no"], 8)
        self.assertEqual(row["story_total_episode_count"], 12)

    async def test_detail_exposes_storyctx_episode_progress(self):
        db = AsyncMock()

        async def execute(query, params):
            sql = str(query)
            self.assertIn("tb_story_agent_context_product", sql)
            self.assertIn("story_context_status", sql)
            self.assertIn("story_ready_episode_no", sql)
            self.assertIn("story_total_episode_count", sql)
            return _MappingsResult(
                [
                    {
                        "product_id": 200,
                        "title": "테스트 작품",
                        "analysis_status": "success",
                        "story_context_status": "ready",
                        "story_ready_episode_no": 12,
                        "story_total_episode_count": 12,
                        "protagonist_goal_primary": None,
                    }
                ]
            )

        db.execute.side_effect = execute

        result = await admin_ai_metadata_service.ai_product_metadata_detail(200, db)

        detail = result["data"]
        self.assertEqual(detail["story_context_status"], "ready")
        self.assertEqual(detail["story_ready_episode_no"], 12)
        self.assertEqual(detail["story_total_episode_count"], 12)


class FakeAsyncSession:
    def __init__(self):
        self.sql = ""
        self.params = None
        self.committed = False

    async def execute(self, statement, params=None):
        self.sql = str(statement)
        self.params = params

    async def commit(self):
        self.committed = True


class AdminAiMetadataFailureGuardTest(unittest.IsolatedAsyncioTestCase):
    async def test_mark_analysis_failed_does_not_overwrite_existing_success(self):
        db = FakeAsyncSession()

        await admin_ai_metadata_service._mark_analysis_failed(
            product_id=1162,
            analysis_attempt_count=3,
            error_message="provider failed",
            analysis_version="dna-test|or|test-model|auto|schema",
            raw_analysis={
                "_llm_meta": {
                    "calls": [{"usage": {"completion_tokens": 8192, "cost": "0.002"}}],
                    "total_cost": 0.002,
                }
            },
            db=db,
        )

        for column in (
            "analysis_status",
            "analysis_attempt_count",
            "analysis_error_message",
            "model_version",
            "raw_analysis",
        ):
            self.assertRegex(
                db.sql,
                rf"{column}\s*=\s*IF\(\s*analysis_status\s*=\s*'success',\s*{column},\s*VALUES\({column}\)\s*\)",
            )
        self.assertEqual(db.params["model_version"], "dna-test|or|test-model|auto|schema")
        stored = json.loads(db.params["raw_analysis"])
        self.assertEqual(stored["_llm_meta"]["calls"][0]["usage"]["completion_tokens"], 8192)
        self.assertTrue(db.committed)
