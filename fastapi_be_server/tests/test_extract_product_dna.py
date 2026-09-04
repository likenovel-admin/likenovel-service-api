import importlib.util
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

from app.services.common.openrouter_background_credit_guard import (
    OpenRouterBackgroundCreditReserveError,
)


MODULE_PATH = Path(__file__).resolve().parents[1] / "dist" / "batch" / "extract_product_dna.py"
LEGACY_MODULE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "extract_product_dna.py"
FASTAPI_ROOT = MODULE_PATH.parents[2]
CODEBOOK_DIRS = [
    FASTAPI_ROOT / "dist" / "ai",
    FASTAPI_ROOT / "dist" / "batch",
]
PILOT_LABELS_BY_AXIS = {
    "세": ("마탑", "튜토리얼"),
    "직": ("교관",),
    "능": ("원작지식", "미래지식", "레벨업", "퀘스트", "상점", "소환", "카피", "버프"),
    "타": ("추방",),
    "목": ("수련", "육성", "재건"),
}


def load_module():
    spec = importlib.util.spec_from_file_location("extract_product_dna_batch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_legacy_module():
    spec = importlib.util.spec_from_file_location("extract_product_dna_legacy", LEGACY_MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class AiDnaCodebookContractTest(TestCase):
    def test_codebook_copies_stay_in_sync(self):
        docs_dir = CODEBOOK_DIRS[0]

        for filename in ("allowed-labels-by-axis.json", "label-definitions-by-axis.json"):
            expected = (docs_dir / filename).read_bytes()
            for codebook_dir in CODEBOOK_DIRS[1:]:
                self.assertEqual(
                    (codebook_dir / filename).read_bytes(),
                    expected,
                    f"{codebook_dir / filename} must match {docs_dir / filename}",
                )

    def test_secret_manual_label_is_not_b_grade(self):
        for codebook_dir in CODEBOOK_DIRS:
            allowed = json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8"))
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            self.assertNotIn("B급", json.dumps(allowed, ensure_ascii=False))
            self.assertIn("비급", allowed["능"])
            self.assertNotIn("비급", allowed["타"])
            self.assertIn("비급", definitions.get("능", {}))

    def test_every_allowed_label_has_definition(self):
        for codebook_dir in CODEBOOK_DIRS:
            allowed = json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8"))
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            missing = {
                axis: [label for label in labels if label not in definitions.get(axis, {})]
                for axis, labels in allowed.items()
            }
            missing = {axis: labels for axis, labels in missing.items() if labels}

            extra = {
                axis: [label for label in defs if label not in allowed.get(axis, [])]
                for axis, defs in definitions.items()
            }
            extra = {axis: labels for axis, labels in extra.items() if labels}

            self.assertEqual(missing, {})
            self.assertEqual(extra, {})

    def test_allowed_label_keys_do_not_use_slash_compounds(self):
        for codebook_dir in CODEBOOK_DIRS:
            allowed = json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8"))
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            compound_allowed = {
                axis: [label for label in labels if "/" in label]
                for axis, labels in allowed.items()
            }
            compound_allowed = {axis: labels for axis, labels in compound_allowed.items() if labels}
            compound_definitions = {
                axis: [label for label in defs if "/" in label]
                for axis, defs in definitions.items()
            }
            compound_definitions = {axis: labels for axis, labels in compound_definitions.items() if labels}

            self.assertEqual(compound_allowed, {})
            self.assertEqual(compound_definitions, {})

    def test_label_definitions_do_not_use_slash_shortcuts(self):
        for codebook_dir in CODEBOOK_DIRS:
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            slash_values = {
                axis: [label for label, desc in defs.items() if isinstance(desc, str) and "/" in desc]
                for axis, defs in definitions.items()
            }
            slash_values = {axis: labels for axis, labels in slash_values.items() if labels}

            self.assertEqual(slash_values, {})

    def test_lifecycle_premise_labels_are_distinct(self):
        for codebook_dir in CODEBOOK_DIRS:
            allowed = json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8"))
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            for label in ("회귀", "빙의", "환생"):
                self.assertIn(label, allowed["타"])
                self.assertIn(label, definitions["타"])

            self.assertIn("무한회귀", allowed["능"])
            self.assertIn("무한회귀", definitions["능"])

    def test_graph_labels_for_recommendation_slots_are_preserved(self):
        sect_labels = ("마교", "정파", "사파", "소림", "화산", "개방", "객잔", "곤륜")

        for codebook_dir in CODEBOOK_DIRS:
            allowed = json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8"))
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            self.assertIn("무림", allowed["세"])
            self.assertIn("강호", definitions["세"]["무림"])
            self.assertIn("중원", definitions["세"]["무림"])

            self.assertIn("판타지, 헌터, 마법, 초능력", definitions["세"]["아카데미"])
            self.assertIn("입학, 편입, 선발시험", definitions["세"]["아카데미"])
            self.assertIn("입학 목표가 한 번 언급", definitions["세"]["아카데미"])
            self.assertIn("현대 학교생활", definitions["세"]["학원"])
            self.assertIn("물리적 학교 공간", definitions["세"]["학교"])
            self.assertIn("세계를 구하려는 인물", definitions["직"]["소방관"])
            self.assertIn("소방 공무원", definitions["직"]["소방관"])
            self.assertIn("정보 인터페이스", definitions["능"]["상태창"])
            self.assertIn("집행하는 메커니즘", definitions["능"]["시스템"])
            self.assertIn("반복 재시도", definitions["능"]["무한회귀"])
            self.assertIn("특정 사건", definitions["작"]["루프"])
            self.assertIn("실패를 수정", definitions["타"]["회귀"])
            self.assertIn("신분과 제약", definitions["타"]["빙의"])
            self.assertIn("새 육체", definitions["타"]["환생"])
            self.assertIn("살아 있는 상태", definitions["목"]["차원이동"])
            self.assertIn("동등한 파트너십", definitions["연"]["조력자"])

            for label in sect_labels:
                self.assertIn(label, allowed["타"])
                self.assertIn("핵심", definitions["타"][label])

            self.assertIn("사건 허브", definitions["타"]["객잔"])

    def test_pilot_labels_have_include_and_exclude_guardrails(self):
        for codebook_dir in CODEBOOK_DIRS:
            allowed = json.loads((codebook_dir / "allowed-labels-by-axis.json").read_text(encoding="utf-8"))
            definitions = json.loads((codebook_dir / "label-definitions-by-axis.json").read_text(encoding="utf-8"))

            for axis, labels in PILOT_LABELS_BY_AXIS.items():
                for label in labels:
                    self.assertIn(label, allowed[axis])
                    self.assertIn(label, definitions[axis])
                    self.assertIn("선택한다", definitions[axis][label])
                    self.assertIn("선택하지 않는다", definitions[axis][label])

            self.assertNotIn("스킬", allowed["능"])

    def test_dna_prompt_treats_labels_as_graph_signals(self):
        module = load_module()
        prompt = module.DNA_SYSTEM_PROMPT

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
        self.assertIn("axis_label_scores는 작품 연결 라벨별 확신도", prompt)
        self.assertIn("evidence는 작품 신호를 선택한 회차 근거", prompt)
        self.assertIn("axis_* 이름은 저장용 내부 키", prompt)
        self.assertNotIn("/", prompt)
        self.assertIn("초반 진입 포인트", prompt)
        self.assertIn("광고 카피가 아니라", prompt)
        self.assertIn("추상 홍보문구", prompt)


class AiDnaOpenRouterFallbackTest(TestCase):
    def test_default_runtime_profile_is_openrouter_auto_schema_only(self):
        with patch.dict(os.environ, {}, clear=True):
            module = load_module()

        self.assertEqual(module.AI_DNA_PROVIDER, "openrouter")
        self.assertEqual(module.AI_DNA_OPENROUTER_PROVIDER_ONLY, "")
        self.assertEqual(module.AI_DNA_RESPONSE_FORMAT, "json_schema")
        self.assertFalse(hasattr(module, "call_claude"))

    def test_openrouter_length_error_preserves_safe_usage(self):
        module = load_module()
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "choices": [{"finish_reason": "length", "message": {"content": "{}"}}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 8192,
                "total_tokens": 8292,
                "cost": "0.12345",
                "untrusted_extra": "must not persist",
            },
        }
        client = MagicMock()
        credit_response = MagicMock()
        credit_response.json.return_value = {"data": {"total_credits": 20.0, "total_usage": 10.0}}
        client.__enter__.return_value.get.return_value = credit_response
        client.__enter__.return_value.post.return_value = response

        with (
            patch.object(module, "OPENROUTER_API_KEY", "test-key"),
            patch.object(module, "AI_DNA_OPENROUTER_MODEL", "test-model"),
            patch.object(module, "_build_openrouter_response_format", return_value={}),
            patch.object(module.httpx, "Client", return_value=client),
        ):
            with self.assertRaises(module.OpenRouterResponseValidationError) as ctx:
                module.call_openrouter("system", "user", {})

        self.assertEqual(
            ctx.exception.safe_llm_usage,
            {
                "prompt_tokens": 100,
                "completion_tokens": 8192,
                "total_tokens": 8292,
                "cost": "0.12345",
            },
        )

    def test_anthropic_runtime_profile_is_rejected(self):
        module = load_module()
        module.AI_DNA_PROVIDER = "anthropic"

        with self.assertRaisesRegex(RuntimeError, "unsupported AI_DNA_PROVIDER: anthropic"):
            module._call_llm("system", "user", {axis: set() for axis in module.AXIS_ORDER})


class AiDnaNormalizePayloadTest(TestCase):
    def test_axis_label_scores_are_normalized_with_confidence_fallback(self):
        module = load_module()
        allowed_labels = {
            "세": {"아카데미"},
            "직": {"헌터"},
            "능": {"상태창", "시스템"},
            "연": set(),
            "작": {"통쾌"},
            "타": {"빙의"},
            "목": {"성장"},
        }
        payload = {
            "summary": {
                "protagonist_type": "빙의자",
                "protagonist_desc": "원작 인물의 몸으로 들어간 주인공이다.",
                "heroine_type": "없음",
                "heroine_weight": "none",
                "mood": "통쾌",
                "pacing": "fast",
                "premise": "아카데미에서 상태창으로 성장한다.",
                "hook": "초반 시험에서 상태창 보상을 얻는다.",
                "themes": ["성장"],
                "taste_tags": ["아카데미"],
            },
            "axis_labels": {
                "세": ["아카데미"],
                "직": ["헌터"],
                "능": ["상태창"],
                "연": [],
                "작": ["통쾌"],
                "타": ["빙의"],
                "목": ["성장"],
            },
            "axis_confidence": {
                "세": 0.7,
                "직": 0.65,
                "능": 0.8,
                "연": 0.0,
                "작": 0.75,
                "타": 0.85,
                "목": 0.9,
            },
            "axis_label_scores": {
                "능": [
                    {"label": "상태창", "score": 0.91},
                    {"label": "시스템", "score": 0.3},
                ]
            },
            "overall_confidence": 0.82,
        }

        normalized = module.normalize_payload(payload, allowed_labels)

        self.assertEqual(normalized["axis_label_scores"]["능"], [{"label": "상태창", "score": 0.91}])
        self.assertEqual(normalized["axis_label_scores"]["세"], [{"label": "아카데미", "score": 0.7}])
        self.assertEqual(normalized["axis_label_scores"]["연"], [])

    def test_source_evidence_guards_remove_firefighter_and_add_academy(self):
        module = load_module()
        allowed_labels = {
            "세": {"중세", "아카데미"},
            "직": {"마법사", "소방관"},
            "능": {"마법", "소드마스터"},
            "연": set(),
            "작": {"후회"},
            "타": {"회귀", "성장형"},
            "목": {"성장"},
        }
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

        normalized = module.normalize_payload(
            payload,
            allowed_labels,
            source_text="중세 제국의 전사 아카데미 입학 시험을 통과해야 한다.",
            allow_axis_confidence_score_fallback=False,
        )

        self.assertEqual(normalized["worldview_tags"], ["중세", "아카데미"])
        self.assertEqual(normalized["protagonist_job_tags"], ["마법사"])
        self.assertEqual(normalized["axis_label_scores"]["직"], [{"label": "마법사", "score": 0.8}])
        self.assertEqual(normalized["axis_label_scores"]["세"], [])

    def test_source_evidence_guards_replace_status_window_with_buff(self):
        module = load_module()
        allowed_labels = {
            "세": {"이종족", "중세"},
            "직": {"헌터"},
            "능": {"상태창", "버프"},
            "연": set(),
            "작": {"비장"},
            "타": {"성장형"},
            "목": {"복수"},
        }
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
            "axis_label_scores": {"능": [{"label": "상태창", "score": 0.2}]},
            "evidence": {"능": ["상태창이나 시스템은 없지만 계약으로 버프를 받는다."]},
            "overall_confidence": 0.8,
        }

        normalized = module.normalize_payload(
            payload,
            allowed_labels,
            source_text="다크엘프에게 버프를 받고 계약을 통해 힘을 얻는다.",
            allow_axis_confidence_score_fallback=False,
        )

        self.assertEqual(normalized["protagonist_material_tags"], ["버프"])
        self.assertEqual(normalized["axis_label_scores"]["능"], [])

    def test_source_evidence_guards_remove_explicit_false_possession_without_synthesizing_growth_type(self):
        module = load_module()
        allowed_labels = {
            "세": {"현대", "재벌", "연예계"},
            "직": {"가수"},
            "능": {"시스템", "상태창"},
            "연": set(),
            "작": {"코미디"},
            "타": {"빙의", "성장형"},
            "목": {"성장"},
        }
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

        normalized = module.normalize_payload(
            payload,
            allowed_labels,
            source_text="주인공은 원래 자신의 몸과 신분 그대로다. 몸이나 영혼의 이동은 없다.",
        )

        self.assertEqual(normalized["protagonist_type_tags"], [])
        self.assertEqual(normalized["axis_label_scores"]["타"], [])

    def test_possession_contradiction_does_not_match_valid_transfer_contexts(self):
        module = load_module()
        valid_contexts = (
            "그 몸은 원래 자신의 몸이 아니었다.",
            "원래 자신의 몸으로 돌아가기 위해 타인의 육체에서 살아간다.",
            "시스템이 빙의시킨 소설 속 악역의 몸에서 깨어났다.",
            "타인의 몸에 빙의한 뒤 별도의 프로그램이 설치되었다.",
        )

        for source_text in valid_contexts:
            with self.subTest(source_text=source_text):
                self.assertFalse(module._has_possession_contradiction(source_text))

    def test_source_evidence_guards_replace_non_protagonist_knight_with_hunter(self):
        module = load_module()
        allowed_labels = {
            "세": {"이종족", "중세"},
            "직": {"기사", "헌터"},
            "능": {"버프"},
            "연": set(),
            "작": {"비장"},
            "타": {"성장형"},
            "목": {"복수"},
        }
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
            "axis_label_scores": {"직": [{"label": "기사", "score": 0.2}]},
            "evidence": {"직": ["주인공의 아버지가 기사이며, 주인공도 검술을 사용한다."]},
            "overall_confidence": 0.82,
        }

        normalized = module.normalize_payload(
            payload,
            allowed_labels,
            source_text="괴물사냥꾼이 되어 괴물을 사냥한다. 주인공의 아버지가 기사다.",
            allow_axis_confidence_score_fallback=False,
        )

        self.assertEqual(normalized["protagonist_job_tags"], ["헌터"])
        self.assertEqual(normalized["axis_label_scores"]["직"], [])


class FakeCursor:
    def __init__(self):
        self.sql = ""
        self.params = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return []


class FakeConnection:
    def __init__(self):
        self.last_cursor = FakeCursor()

    def cursor(self):
        return self.last_cursor


class AiDnaProductTargetQueryTest(TestCase):
    def test_target_query_requires_ai_content_consent(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=True)

        self.assertIn("COALESCE(p.ai_content_service_enabled_yn, 'N') = 'Y'", conn.last_cursor.sql)

    def test_first_open_episode_minimum_text_count_is_500(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=True)

        self.assertEqual(module.MIN_FIRST_EPISODE_TEXT_COUNT, 500)
        self.assertIn("), 0) >= 500", conn.last_cursor.sql)
        self.assertNotIn(">= 1000", conn.last_cursor.sql)

    def test_first_episode_gate_uses_open_order_not_episode_no(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=True)

        sql = conn.last_cursor.sql
        self.assertNotIn("fe.episode_no = 1", sql)
        self.assertRegex(
            sql,
            r"fe\.open_yn = 'Y'[\s\S]+ORDER BY fe\.episode_no ASC, fe\.episode_id ASC[\s\S]+LIMIT 1",
        )

    def test_success_refresh_waits_for_retry_cooldown(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=False)

        self.assertRegex(
            conn.last_cursor.sql,
            rf"analysis_status[^\n]+success[\s\S]+updated_date[\s\S]+INTERVAL\s+{module.INCOMPLETE_RETRY_COOLDOWN_DAYS}\s+DAY[\s\S]+LIMIT 1 OFFSET {module.MAX_ANALYZE_EPISODES - 1}",
        )

    def test_success_refresh_tracks_tenth_open_episode(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=False)

        sql = conn.last_cursor.sql
        self.assertNotIn(f"le.episode_no = {module.MAX_ANALYZE_EPISODES}", sql)
        self.assertIn("le.open_yn = 'Y'", sql)

    def test_episode_collection_has_stable_public_order(self):
        module = load_module()
        conn = FakeConnection()

        module.get_episodes(conn, product_id=1225)

        self.assertIn("ORDER BY episode_no ASC, episode_id ASC", conn.last_cursor.sql)

    def test_save_dna_writes_axis_label_scores(self):
        module = load_module()
        conn = FakeConnection()
        dna = {
            "axis_label_scores": {
                "능": [{"label": "상태창", "score": 0.91}],
            }
        }

        module.save_dna(conn, product_id=1, dna=dna, parsed={"ok": True}, attempt_count=1)

        self.assertIn("axis_label_scores", conn.last_cursor.sql)
        axis_score_param = next(param for param in conn.last_cursor.params if isinstance(param, str) and "상태창" in param)
        self.assertEqual(
            json.loads(axis_score_param),
            {"능": [{"label": "상태창", "score": 0.91}]},
        )

    def test_save_dna_writes_normalized_unmapped_concepts_to_raw_analysis(self):
        module = load_module()
        conn = FakeConnection()
        dna = {"unmapped_concepts": ["짐꾼", "재능거래"]}
        parsed = {
            "unmapped_concepts": ["짐꾼", " 짐꾼 ", "", "재능거래"],
            "_llm_calls": [{"stage": "initial"}],
        }

        module.save_dna(conn, product_id=1, dna=dna, parsed=parsed, attempt_count=1)

        raw_analysis_candidates = []
        for param in conn.last_cursor.params:
            if not isinstance(param, str):
                continue
            try:
                payload = json.loads(param)
            except json.JSONDecodeError:
                continue
            if isinstance(payload, dict) and "_llm_calls" in payload:
                raw_analysis_candidates.append(payload)

        self.assertEqual(len(raw_analysis_candidates), 1)
        self.assertEqual(raw_analysis_candidates[0]["unmapped_concepts"], ["짐꾼", "재능거래"])

    def test_save_failed_does_not_overwrite_existing_success(self):
        module = load_module()
        conn = FakeConnection()

        module.save_failed(
            conn,
            product_id=1162,
            attempt_count=3,
            error_message="provider failed",
        )

        self.assertRegex(
            conn.last_cursor.sql,
            r"analysis_status\s*=\s*IF\(\s*analysis_status\s*=\s*'success',\s*analysis_status,\s*VALUES\(analysis_status\)\s*\)",
        )
        self.assertRegex(
            conn.last_cursor.sql,
            r"analysis_attempt_count\s*=\s*IF\(\s*analysis_status\s*=\s*'success',\s*analysis_attempt_count,\s*VALUES\(analysis_attempt_count\)\s*\)",
        )
        self.assertRegex(
            conn.last_cursor.sql,
            r"analysis_error_message\s*=\s*IF\(\s*analysis_status\s*=\s*'success',\s*analysis_error_message,\s*VALUES\(analysis_error_message\)\s*\)",
        )
        self.assertRegex(
            conn.last_cursor.sql,
            r"model_version\s*=\s*IF\(\s*analysis_status\s*=\s*'success',\s*model_version,\s*VALUES\(model_version\)\s*\)",
        )

    def test_legacy_save_failed_does_not_overwrite_existing_success(self):
        module = load_legacy_module()
        conn = FakeConnection()

        module.save_failed(
            conn,
            product_id=1162,
            attempt_count=3,
            error_message="provider failed",
        )

        for column in (
            "analysis_status",
            "analysis_attempt_count",
            "analysis_error_message",
            "model_version",
        ):
            self.assertRegex(
                conn.last_cursor.sql,
                rf"{column}\s*=\s*IF\(\s*analysis_status\s*=\s*'success',\s*{column},\s*VALUES\({column}\)\s*\)",
            )

    def test_openrouter_402_raises_batch_circuit_breaker(self):
        module = load_module()
        response = MagicMock()
        response.status_code = 402
        response.json.return_value = {
            "error": {"code": 402, "message": "insufficient credits"}
        }
        client = MagicMock()
        credit_response = MagicMock()
        credit_response.json.return_value = {
            "data": {"total_credits": 20.0, "total_usage": 10.0}
        }
        client.__enter__.return_value.get.return_value = credit_response
        client.__enter__.return_value.post.return_value = response

        with (
            patch.object(module, "OPENROUTER_API_KEY", "test-key"),
            patch.object(module, "AI_DNA_OPENROUTER_MODEL", "test-model"),
            patch.object(module, "_build_openrouter_response_format", return_value={}),
            patch.object(module.httpx, "Client", return_value=client),
        ):
            with self.assertRaises(module.OpenRouterInsufficientCreditsError):
                module.call_openrouter("system", "user", {})

    def test_openrouter_non_402_keeps_existing_retry_path(self):
        module = load_module()
        response = MagicMock()
        response.status_code = 429
        response.json.return_value = {
            "error": {"code": 429, "message": "rate limited"}
        }
        client = MagicMock()
        credit_response = MagicMock()
        credit_response.json.return_value = {
            "data": {"total_credits": 20.0, "total_usage": 10.0}
        }
        client.__enter__.return_value.get.return_value = credit_response
        client.__enter__.return_value.post.return_value = response

        with (
            patch.object(module, "OPENROUTER_API_KEY", "test-key"),
            patch.object(module, "AI_DNA_OPENROUTER_MODEL", "test-model"),
            patch.object(module, "_build_openrouter_response_format", return_value={}),
            patch.object(module.httpx, "Client", return_value=client),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                module.call_openrouter("system", "user", {})

        self.assertNotIsInstance(ctx.exception, module.OpenRouterInsufficientCreditsError)

    def test_main_reserve_block_does_not_mark_product_failed(self):
        module = load_module()
        conn = MagicMock()
        products = [{"product_id": 1211, "title": "protected"}]

        with (
            patch.object(module, "load_allowed_labels", return_value={}),
            patch.object(module, "_validate_runtime_config"),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "get_products", return_value=products),
            patch.object(module, "get_episodes", return_value=[]),
            patch.object(module, "_build_episode_context", return_value=("context", 10)),
            patch.object(
                module,
                "analyze_product",
                side_effect=OpenRouterBackgroundCreditReserveError("reserve blocked"),
            ) as analyze,
            patch.object(module, "save_failed") as save_failed,
            patch.object(module.time, "sleep"),
            patch("sys.argv", ["extract_product_dna.py", "--all"]),
        ):
            with self.assertRaisesRegex(SystemExit, "1"):
                module.main()

        self.assertEqual(analyze.call_count, 1)
        save_failed.assert_not_called()

    def test_main_stops_after_first_openrouter_402(self):
        module = load_module()
        conn = MagicMock()
        products = [
            {"product_id": 1211, "title": "first"},
            {"product_id": 1212, "title": "second"},
        ]

        with (
            patch.object(module, "load_allowed_labels", return_value={}),
            patch.object(module, "_validate_runtime_config"),
            patch.object(module, "db_connect", return_value=conn),
            patch.object(module, "get_products", return_value=products),
            patch.object(module, "get_episodes", return_value=[]),
            patch.object(module, "_build_episode_context", return_value=("context", 10)),
            patch.object(
                module,
                "analyze_product",
                side_effect=module.OpenRouterInsufficientCreditsError("credits"),
            ) as analyze,
            patch.object(module, "save_failed") as save_failed,
            patch.object(module.time, "sleep"),
            patch("sys.argv", ["extract_product_dna.py", "--all"]),
        ):
            with self.assertRaisesRegex(SystemExit, "1"):
                module.main()

        self.assertEqual(analyze.call_count, 1)
        save_failed.assert_called_once_with(conn, 1211, 1, "credits")


class AiDnaEmptyAxisPolicyTest(TestCase):
    """min_items 강제 제거 정책: 부합 라벨이 없는 축은 빈 배열이 정답이다."""

    ALLOWED_LABELS = {
        "세": {"현대", "아카데미"},
        "직": {"헌터", "집사"},
        "능": {"상태창", "버프"},
        "연": set(),
        "작": {"통쾌"},
        "타": {"빙의"},
        "목": {"성장"},
    }

    @staticmethod
    def build_payload(axis_labels: dict, **extra) -> dict:
        payload = {
            "summary": {
                "protagonist_type": "짐꾼",
                "protagonist_desc": "게이트에서 부산물을 줍는 S급 짐꾼이다.",
                "heroine_type": "없음",
                "heroine_weight": "none",
                "mood": "유쾌",
                "pacing": "fast",
                "premise": "짐꾼이 이종족을 일꾼으로 부린다.",
                "hook": "각성 검사에서 짐꾼 능력의 비밀이 드러난다.",
                "themes": ["성장"],
                "taste_tags": ["게이트"],
            },
            "axis_labels": axis_labels,
            "axis_confidence": {axis: 0.5 for axis in ("세", "직", "능", "연", "작", "타", "목")},
            "overall_confidence": 0.5,
        }
        payload.update(extra)
        return payload

    def test_empty_axes_pass_without_goal_fallback(self):
        module = load_module()
        payload = self.build_payload(
            {"세": ["현대"], "직": [], "능": [], "연": [], "작": [], "타": [], "목": []}
        )

        normalized = module.normalize_payload(payload, self.ALLOWED_LABELS)

        self.assertEqual(normalized["protagonist_job_tags"], [])
        self.assertEqual(normalized["protagonist_type_tags"], [])
        self.assertIsNone(normalized["protagonist_goal_primary"])
        self.assertNotIn("성장", normalized["taste_tags"])

    def test_unmapped_concepts_are_normalized_and_preserved(self):
        module = load_module()
        payload = self.build_payload(
            {"세": ["현대"], "직": [], "능": [], "연": [], "작": [], "타": [], "목": []},
            unmapped_concepts=["짐꾼", " 짐꾼 ", "재능거래", ""],
        )

        normalized = module.normalize_payload(payload, self.ALLOWED_LABELS)

        self.assertEqual(normalized["unmapped_concepts"], ["짐꾼", "재능거래"])

    def test_unsupported_label_still_raises(self):
        module = load_module()
        payload = self.build_payload(
            {"세": ["현대"], "직": ["광부"], "능": [], "연": [], "작": [], "타": [], "목": []}
        )

        with self.assertRaises(module.UnsupportedLabelError):
            module.normalize_payload(payload, self.ALLOWED_LABELS)

    def test_prompt_forbids_nearest_label_filling_and_requires_unmapped(self):
        module = load_module()
        prompt = module.DNA_SYSTEM_PROMPT

        self.assertIn("빈 배열로 둔다", prompt)
        self.assertIn("unmapped_concepts", prompt)
        self.assertNotIn("가장 가까운 허용 라벨", prompt)
        self.assertIn("unmapped_concepts", module.DNA_USER_TEMPLATE)
        self.assertNotIn("최소 개수를 충족", module.DNA_REPAIR_TEMPLATE)

    def test_openrouter_schema_allows_empty_axes_and_requires_unmapped(self):
        module = load_module()
        module.AI_DNA_RESPONSE_FORMAT = "json_schema"

        response_format = module._build_openrouter_response_format(self.ALLOWED_LABELS)

        schema = response_format["json_schema"]["schema"]
        for axis in ("세", "직", "능", "연", "작", "타", "목"):
            self.assertEqual(schema["properties"]["axis_labels"]["properties"][axis]["minItems"], 0)
        self.assertIn("unmapped_concepts", schema["properties"])
        self.assertIn("unmapped_concepts", schema["required"])


class AiDnaLibrarianCopyTest(TestCase):
    """AI 사서 노출 카피(librarian) 검증: 금칙어/개수 미달은 None 강등(프론트 fallback), 분석 실패 아님."""

    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_valid_librarian_passes_through(self):
        result = self.module._normalize_librarian({
            "librarian": {
                "intro": "해고된 날 머릿속에 대문호가 깃들었어요. 유쾌한 이야기를 좋아하면 잘 맞아요.",
                "points": ["출발점은 게임 개발이에요.", "주인공은 개발자예요.", "코미디를 좋아하면 어울려요."],
                "chips": ["먼치킨", "게임개발", "코미디"],
            }
        })
        self.assertTrue(result["librarian_intro"].startswith("해고된 날"))
        self.assertEqual(len(result["librarian_points"]), 3)
        self.assertEqual(result["librarian_chips"], ["먼치킨", "게임개발", "코미디"])

    def test_suspicious_unicode_demotes_public_copy_and_filters_tags(self):
        result = self.module._normalize_librarian({
            "librarian": {
                "intro": "통쾌한 사ī다를 좋아하면 잘 맞아요.",
                "points": ["배ԩ을 살펴요.", "주인공을 따라가요.", "반전을 즐겨요."],
                "chips": ["미스터리", "사ī다"],
            }
        })
        self.assertIsNone(result["librarian_intro"])
        self.assertIsNone(result["librarian_points"])
        self.assertIsNone(result["librarian_chips"])

        allowed = {axis: set() for axis in ("세", "직", "능", "연", "작", "타", "목")}
        normalized = self.module.normalize_payload(
            {
                "summary": {
                    "protagonist_type": "기자",
                    "protagonist_desc": "사건을 추적하는 전직 기자",
                    "heroine_type": "없음",
                    "heroine_weight": "none",
                    "mood": "긴장감 있는 분위기",
                    "pacing": "medium",
                    "premise": "카페를 운영하며 사건을 해결하는 이야기",
                    "hook": "이웃의 누명을 벗기기 위해 진범을 추적한다",
                    "themes": ["추리"],
                    "taste_tags": ["범죄 수사", "사이다 먼ō"],
                },
                "axis_labels": {axis: [] for axis in allowed},
                "axis_confidence": {},
                "overall_confidence": 0.9,
            },
            allowed,
        )
        self.assertEqual(normalized["taste_tags"], ["범죄 수사"])

    def test_banned_words_demote_to_none_not_failure(self):
        result = self.module._normalize_librarian({
            "librarian": {
                "intro": "이야기의 결이 선명한 작품이에요.",
                "points": [
                    "성장의 축으로 움직여요.",
                    "주인공은 개발자예요.",
                    "코미디를 좋아하면 어울려요.",
                ],
                "chips": ["서사", "동력", "몰입감", "텍스트"],
            }
        })
        self.assertIsNone(result["librarian_intro"])  # 결이 포함
        self.assertIsNone(result["librarian_points"])  # 축으로 포함
        self.assertIsNone(result["librarian_chips"])

    def test_one_bad_chip_keeps_atomic_copy_only_when_three_valid_chips_remain(self):
        base = {
            "intro": "사건의 진실을 추적하는 이야기를 좋아하면 잘 맞아요.",
            "points": ["생활형 추리예요.", "주인공은 기자예요.", "반전을 따라가요."],
        }

        kept = self.module._normalize_librarian(
            {"librarian": {**base, "chips": ["추리", "기자", "반전", "텍스트"]}}
        )
        dropped = self.module._normalize_librarian(
            {"librarian": {**base, "chips": ["추리", "반전", "텍스트"]}}
        )

        self.assertEqual(kept["librarian_chips"], ["추리", "기자", "반전"])
        self.assertEqual(
            dropped,
            {"librarian_intro": None, "librarian_points": None, "librarian_chips": None},
        )

    def test_editorial_terms_are_not_librarian_banned_words(self):
        banned_rule = next(
            line for line in self.module.DNA_SYSTEM_PROMPT.splitlines() if "14-2) 금칙어:" in line
        )
        for word in ("서사", "동력", "몰입감"):
            self.assertNotIn(f'"{word}"', banned_rule)
        for text in ("서사가 탄탄해요.", "성장의 동력이 분명해요.", "몰입감이 좋아요."):
            self.assertIsNone(self.module._LIBRARIAN_BANNED_RE.search(text), text)

    def test_banned_re_does_not_flag_normal_words(self):
        # 결혼/대결/축제 같은 정상 단어는 오탐하지 않는다
        for text in (
            "결혼을 앞둔 주인공이에요.",
            "축제에서 사건이 벌어져요.",
            "대결 구도가 뚜렷해요.",
            "숙명의 대결을 벌여요.",
            "한결은 끝까지 포기하지 않아요.",
            "문제를 해결을 통해 풀어요.",
            "인물 연결의 의미를 살펴요.",
        ):
            self.assertIsNone(self.module._LIBRARIAN_BANNED_RE.search(text), text)

        for text in ("결이 좋아요.", "결을 봐요.", "결의 의미예요.", "결은 선명해요."):
            self.assertIsNotNone(self.module._LIBRARIAN_BANNED_RE.search(text), text)

    def test_missing_or_short_librarian_falls_back(self):
        self.assertEqual(
            self.module._normalize_librarian({}),
            {"librarian_intro": None, "librarian_points": None, "librarian_chips": None},
        )
        result = self.module._normalize_librarian({
            "librarian": {"intro": "한 줄이에요.", "points": ["하나", "둘"], "chips": []}
        })
        self.assertIsNone(result["librarian_points"])  # 3개 미만
        self.assertIsNone(result["librarian_chips"])

    def test_normalize_payload_includes_librarian_keys(self):
        allowed = {axis: {"성장"} if axis == "목" else {"현대"} for axis in ("세", "직", "능", "연", "작", "타", "목")}
        payload = {
            "summary": {
                "protagonist_type": "개발자",
                "protagonist_desc": "설명",
                "heroine_type": "없음",
                "heroine_weight": "none",
                "mood": "유쾌",
                "pacing": "fast",
                "premise": "전제",
                "hook": "훅",
                "themes": ["성장"],
                "taste_tags": ["먼치킨"],
                "librarian": {
                    "intro": "유쾌한 이야기예요.",
                    "points": ["하나예요.", "둘이에요.", "셋이에요."],
                    "chips": ["먼치킨", "코미디", "현대판타지"],
                },
            },
            "axis_labels": {axis: [] for axis in ("세", "직", "능", "연", "작", "타", "목")},
            "axis_confidence": {},
            "overall_confidence": 0.9,
        }
        dna = self.module.normalize_payload(payload, allowed)
        self.assertEqual(dna["librarian_intro"], "유쾌한 이야기예요.")
        self.assertEqual(len(dna["librarian_points"]), 3)
        self.assertEqual(len(dna["librarian_chips"]), 3)


class AiDnaLlmPayloadContractTest(TestCase):
    @staticmethod
    def build_payload() -> dict:
        axes = ("세", "직", "능", "연", "작", "타", "목")
        return {
            "summary": {
                "protagonist_type": "기자",
                "protagonist_desc": "사건을 추적하는 전직 기자",
                "heroine_type": "없음",
                "heroine_weight": "none",
                "mood": "긴장감 있는 분위기",
                "pacing": "medium",
                "premise": "카페를 운영하며 사건을 해결하는 이야기",
                "hook": "이웃의 누명을 벗기기 위해 진범을 추적한다",
                "themes": ["추리"],
                "taste_tags": ["범죄 수사"],
                "librarian": {
                    "intro": "사건의 진실을 추적하는 이야기를 좋아하면 잘 맞아요.",
                    "points": ["생활형 추리예요.", "주인공은 기자예요.", "반전을 따라가요."],
                    "chips": ["추리", "기자", "반전"],
                },
            },
            "axis_labels": {axis: [] for axis in axes},
            "axis_confidence": {axis: 0.9 for axis in axes},
            "axis_label_scores": {axis: [] for axis in axes},
            "overall_confidence": 0.9,
            "evidence": {axis: [] for axis in axes},
            "unmapped_concepts": [],
        }

    def test_contract_accepts_complete_payload_with_empty_axes(self):
        module = load_module()

        module._validate_llm_payload_contract(self.build_payload())

    def test_contract_rejects_misspelled_required_top_level_key(self):
        module = load_module()
        payload = self.build_payload()
        payload["overall_conffidence"] = payload.pop("overall_confidence")

        with self.assertRaisesRegex(ValueError, "missing required key: overall_confidence"):
            module._validate_llm_payload_contract(payload)

    def test_contract_rejects_missing_axis_container_key(self):
        module = load_module()
        payload = self.build_payload()
        del payload["evidence"]["능"]

        with self.assertRaisesRegex(ValueError, "evidence missing required key: 능"):
            module._validate_llm_payload_contract(payload)

    def test_contract_allows_missing_librarian_and_normalizer_falls_back_atomically(self):
        module = load_module()
        payload = self.build_payload()
        payload["summary"]["librarrian"] = payload["summary"].pop("librarian")

        module._validate_llm_payload_contract(payload)
        normalized = module.normalize_payload(
            payload,
            {axis: set() for axis in module.AXIS_ORDER},
        )

        self.assertIsNone(normalized["librarian_intro"])
        self.assertIsNone(normalized["librarian_points"])
        self.assertIsNone(normalized["librarian_chips"])

    def test_contract_rejects_observed_garbled_generated_text(self):
        module = load_module()
        latin_payload = self.build_payload()
        latin_payload["summary"]["librarian"]["intro"] = "통쾌한 사ø다를 좋아하면 잘 맞아요."
        cjk_payload = self.build_payload()
        cjk_payload["summary"]["themes"] = ["착各과 오해"]

        module._validate_llm_payload_contract(latin_payload)
        librarian = module._normalize_librarian(latin_payload["summary"])
        self.assertIsNone(librarian["librarian_intro"])
        with self.assertRaisesRegex(ValueError, "suspicious generated text"):
            module._validate_llm_payload_contract(cjk_payload)

    def test_suspicious_text_requires_exact_prompt_source_token(self):
        module = load_module()
        self.assertFalse(
            module._has_suspicious_generated_text("가수 Beyoncé가 등장해요.", "원문에 Beyoncé가 등장한다.")
        )
        self.assertTrue(
            module._has_suspicious_generated_text("가수 Beyoncé가 등장해요.", "원문에는 Beyoncè가 등장한다.")
        )
        self.assertTrue(
            module._has_suspicious_generated_text("Beyoncé", "원문 xBeyoncéy 표기")
        )
        self.assertFalse(module._has_suspicious_generated_text("한中글", "원문 한中글 표기"))
        self.assertTrue(module._has_suspicious_generated_text("한中글", "원문 중中문 표기"))
        self.assertTrue(
            module._has_suspicious_generated_text("한中글文자", "원문 한中글 표기")
        )
        self.assertFalse(
            module._has_suspicious_generated_text(
                "한中글文자",
                "원문 한中글과 글文자가 모두 표기",
            )
        )

        payload = self.build_payload()
        payload["summary"]["themes"] = ["Beyoncé"]
        payload["evidence"]["세"] = ["Beyoncé"]
        with self.assertRaisesRegex(ValueError, "suspicious generated text"):
            module._validate_llm_payload_contract(payload, source_text="")

    def test_contract_rejects_nonfinite_confidence_and_score_label_drift(self):
        module = load_module()
        for field, value in (
            ("overall_confidence", float("nan")),
            ("overall_confidence", float("inf")),
            ("overall_confidence", 1.1),
        ):
            with self.subTest(field=field, value=value):
                payload = self.build_payload()
                payload[field] = value
                with self.assertRaisesRegex(ValueError, "overall_confidence"):
                    module._validate_llm_payload_contract(payload)

        mismatch = self.build_payload()
        mismatch["axis_labels"]["타"] = ["환생"]
        with self.assertRaisesRegex(ValueError, "labels must match"):
            module._validate_llm_payload_contract(mismatch)

        duplicate = self.build_payload()
        duplicate["axis_labels"]["타"] = ["환생", "환생"]
        duplicate["axis_label_scores"]["타"] = [
            {"label": "환생", "score": 0.9},
            {"label": "환생", "score": 0.8},
        ]
        with self.assertRaisesRegex(ValueError, "duplicate label"):
            module._validate_llm_payload_contract(duplicate)

        over_limit = self.build_payload()
        over_limit["axis_labels"]["목"] = ["생존", "성장"]
        over_limit["axis_label_scores"]["목"] = [
            {"label": "생존", "score": 0.9},
            {"label": "성장", "score": 0.8},
        ]
        with self.assertRaisesRegex(ValueError, "axis_labels.목 exceeds maximum of 1"):
            module._validate_llm_payload_contract(over_limit)

    def test_contract_rejects_unsupported_labels_against_codebook(self):
        module = load_module()
        payload = self.build_payload()
        payload["axis_labels"]["타"] = ["없는라벨"]
        payload["axis_label_scores"]["타"] = [{"label": "없는라벨", "score": 0.9}]

        with self.assertRaises(module.UnsupportedLabelError):
            module._validate_llm_payload_contract(
                payload,
                {axis: set() for axis in module.AXIS_ORDER},
            )

    def test_analyze_product_validates_raw_payload_before_normalizing(self):
        module = load_module()
        payload = self.build_payload()
        payload["overall_conffidence"] = payload.pop("overall_confidence")
        call_meta = {
            "provider": "openrouter",
            "model": "test-model",
            "provider_only": [],
            "response_format": "json_schema",
            "usage": {},
        }

        with (
            patch.object(module, "_call_llm", return_value=(json.dumps(payload), call_meta)),
            self.assertRaisesRegex(ValueError, "missing required key: overall_confidence"),
        ):
            module.analyze_product(
                {"title": "테스트", "genres": "", "keywords": "", "synopsis_text": ""},
                {axis: set() for axis in module.AXIS_ORDER},
                "회차 본문",
                3,
            )

    def test_analyze_product_validates_repaired_payload_before_saving(self):
        module = load_module()
        initial = self.build_payload()
        initial["axis_labels"]["타"] = ["없는라벨"]
        initial["axis_label_scores"]["타"] = [{"label": "없는라벨", "score": 0.9}]
        repaired = self.build_payload()
        repaired["axis_label_scores"]["타"] = [{"label": "남은점수", "score": 0.9}]
        call_meta = {
            "provider": "openrouter",
            "model": "test-model",
            "provider_only": [],
            "response_format": "json_schema",
            "usage": {},
        }

        with (
            patch.object(
                module,
                "_call_llm",
                side_effect=[
                    (json.dumps(initial), call_meta),
                    (json.dumps(repaired), call_meta),
                ],
            ) as call_llm,
            self.assertRaisesRegex(ValueError, "labels must match"),
        ):
            module.analyze_product(
                {"title": "테스트", "genres": "", "keywords": "", "synopsis_text": ""},
                {axis: set() for axis in module.AXIS_ORDER},
                "회차 본문",
                3,
            )

        self.assertEqual(call_llm.call_count, 2)

    def test_analyze_product_preserves_all_rejected_labels_through_persistence(self):
        module = load_module()
        initial = self.build_payload()
        initial["axis_labels"]["직"] = ["없는직업"]
        initial["axis_label_scores"]["직"] = [{"label": "없는직업", "score": 0.8}]
        initial["axis_labels"]["타"] = ["없는라벨"]
        initial["axis_label_scores"]["타"] = [{"label": "없는라벨", "score": 0.9}]
        repaired = self.build_payload()
        call_meta = {
            "provider": "openrouter",
            "model": "test-model",
            "provider_only": [],
            "response_format": "json_schema",
            "usage": {},
        }

        with patch.object(
            module,
            "_call_llm",
            side_effect=[
                (json.dumps(initial), call_meta),
                (json.dumps(repaired), call_meta),
            ],
        ):
            normalized, raw = module.analyze_product(
                {"title": "테스트", "genres": "", "keywords": "", "synopsis_text": ""},
                {axis: set() for axis in module.AXIS_ORDER},
                "회차 본문",
                3,
            )

        expected = ["없는직업", "없는라벨"]
        self.assertEqual(normalized["unmapped_concepts"], expected)
        self.assertEqual(raw["unmapped_concepts"], expected)

        conn = FakeConnection()
        module.save_dna(conn, product_id=1, dna=normalized, parsed=raw, attempt_count=1)
        persisted_raw = next(
            json.loads(param)
            for param in conn.last_cursor.params
            if isinstance(param, str) and '"_llm_meta"' in param
        )
        self.assertEqual(persisted_raw["unmapped_concepts"], expected)

    def test_analyze_product_fails_closed_when_repair_cannot_preserve_rejected_label(self):
        module = load_module()
        initial = self.build_payload()
        initial["axis_labels"]["타"] = ["없는라벨"]
        initial["axis_label_scores"]["타"] = [{"label": "없는라벨", "score": 0.9}]
        repaired = self.build_payload()
        repaired["unmapped_concepts"] = [f"미지원개념{i}" for i in range(10)]
        call_meta = {
            "provider": "openrouter",
            "model": "test-model",
            "provider_only": [],
            "response_format": "json_schema",
            "usage": {},
        }

        with (
            patch.object(
                module,
                "_call_llm",
                side_effect=[
                    (json.dumps(initial), call_meta),
                    (json.dumps(repaired), call_meta),
                ],
            ) as call_llm,
            self.assertRaisesRegex(ValueError, "cannot preserve every rejected label"),
        ):
            module.analyze_product(
                {"title": "테스트", "genres": "", "keywords": "", "synopsis_text": ""},
                {axis: set() for axis in module.AXIS_ORDER},
                "회차 본문",
                3,
            )

        self.assertEqual(call_llm.call_count, 2)

    def test_analyze_product_treats_typo_librarian_unicode_as_one_call_fallback(self):
        module = load_module()
        payload = self.build_payload()
        typo_librarian = payload["summary"].pop("librarian")
        typo_librarian["intro"] = "통쾌한 사ø다를 좋아하면 잘 맞아요."
        payload["summary"]["librarrian"] = typo_librarian
        call_meta = {
            "provider": "openrouter",
            "model": "test-model",
            "provider_only": [],
            "response_format": "json_schema",
            "usage": {},
        }

        with patch.object(
            module,
            "_call_llm",
            return_value=(json.dumps(payload), call_meta),
        ) as call_llm:
            normalized, _ = module.analyze_product(
                {"title": "테스트", "genres": "", "keywords": "", "synopsis_text": ""},
                {axis: set() for axis in module.AXIS_ORDER},
                "회차 본문",
                3,
            )

        self.assertEqual(call_llm.call_count, 1)
        self.assertIsNone(normalized["librarian_intro"])
        self.assertIsNone(normalized["librarian_points"])
        self.assertIsNone(normalized["librarian_chips"])

    def test_analyze_product_source_exception_uses_only_prompt_visible_synopsis(self):
        module = load_module()
        payload = self.build_payload()
        payload["summary"]["themes"] = ["Beyoncé"]
        call_meta = {
            "provider": "openrouter",
            "model": "test-model",
            "provider_only": [],
            "response_format": "json_schema",
            "usage": {},
        }

        with (
            patch.object(module, "_call_llm", return_value=(json.dumps(payload), call_meta)),
            self.assertRaisesRegex(ValueError, "suspicious generated text"),
        ):
            module.analyze_product(
                {
                    "title": "테스트",
                    "genres": "",
                    "keywords": "",
                    "synopsis_text": ("가" * 1000) + "Beyoncé",
                },
                {axis: set() for axis in module.AXIS_ORDER},
                "회차 본문",
                3,
            )
