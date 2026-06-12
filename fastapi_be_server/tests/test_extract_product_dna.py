import json
import importlib.util
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch


MODULE_PATH = Path(__file__).resolve().parents[1] / "dist" / "batch" / "extract_product_dna.py"
REPO_ROOT = MODULE_PATH.parents[5]
FASTAPI_ROOT = MODULE_PATH.parents[2]
CODEBOOK_DIRS = [
    REPO_ROOT / "docs" / "ai-codebook",
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


class AiDnaCodebookContractTest(TestCase):
    def test_codebook_copies_stay_in_sync(self):
        docs_dir = CODEBOOK_DIRS[0]

        for filename in ("allowed-labels-by-axis.json", "label-definitions-by-axis.json"):
            expected = (docs_dir / filename).read_text(encoding="utf-8")
            for codebook_dir in CODEBOOK_DIRS[1:]:
                self.assertEqual(
                    (codebook_dir / filename).read_text(encoding="utf-8"),
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


class AiDnaDeepseekFallbackTest(TestCase):
    def test_anthropic_failure_falls_back_to_deepseek_v4flash(self):
        module = load_module()
        module.AI_DNA_PROVIDER = "anthropic"
        module.ANTHROPIC_MODEL = "claude-haiku-4-5-20251001"
        module.DEEPSEEK_API_KEY = "test-key"
        module.AI_DNA_DEEPSEEK_FALLBACK_MODEL = "deepseek-v4-flash"

        with patch.object(module, "call_claude", side_effect=RuntimeError("Claude API error: 429 credit")), \
             patch.object(module, "call_deepseek", return_value=("{}", {"total_tokens": 123})) as mocked_deepseek:
            raw, meta = module._call_llm("system", "user", {axis: set() for axis in module.AXIS_ORDER})

        self.assertEqual(raw, "{}")
        mocked_deepseek.assert_called_once()
        self.assertEqual(meta["provider"], "deepseek")
        self.assertEqual(meta["fallback_from"], "anthropic")
        self.assertEqual(meta["model"], "deepseek-v4-flash")
        self.assertIn("Claude API error", meta["fallback_reason"])
        self.assertEqual(meta["usage"], {"prompt_tokens": None, "completion_tokens": None, "total_tokens": 123, "cost": None})

    def test_anthropic_failure_without_deepseek_key_raises_original_error(self):
        module = load_module()
        module.AI_DNA_PROVIDER = "anthropic"
        module.DEEPSEEK_API_KEY = ""
        module.AI_DNA_DEEPSEEK_FALLBACK_MODEL = "deepseek-v4-flash"

        with patch.object(module, "call_claude", side_effect=RuntimeError("Claude API error: 429 credit")):
            with self.assertRaisesRegex(RuntimeError, "Claude API error"):
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
        )

        self.assertEqual(normalized["worldview_tags"], ["중세", "아카데미"])
        self.assertEqual(normalized["protagonist_job_tags"], ["마법사"])
        self.assertEqual(normalized["axis_label_scores"]["직"], [{"label": "마법사", "score": 0.8}])

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
            "evidence": {"능": ["상태창이나 시스템은 없지만 계약으로 버프를 받는다."]},
            "overall_confidence": 0.8,
        }

        normalized = module.normalize_payload(
            payload,
            allowed_labels,
            source_text="다크엘프에게 버프를 받고 계약을 통해 힘을 얻는다.",
        )

        self.assertEqual(normalized["protagonist_material_tags"], ["버프"])
        self.assertEqual(normalized["axis_label_scores"]["능"], [{"label": "버프", "score": 0.7}])

    def test_source_evidence_guards_replace_false_possession_with_growth_type(self):
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
            source_text="재벌집 손자가 트로트 가수 데뷔 목표와 시스템 퀘스트를 받으며 성장한다.",
        )

        self.assertEqual(normalized["protagonist_type_tags"], ["성장형"])
        self.assertEqual(normalized["axis_label_scores"]["타"], [{"label": "성장형", "score": 0.7}])

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
            "evidence": {"직": ["주인공의 아버지가 기사이며, 주인공도 검술을 사용한다."]},
            "overall_confidence": 0.82,
        }

        normalized = module.normalize_payload(
            payload,
            allowed_labels,
            source_text="괴물사냥꾼이 되어 괴물을 사냥한다. 주인공의 아버지가 기사다.",
        )

        self.assertEqual(normalized["protagonist_job_tags"], ["헌터"])
        self.assertEqual(normalized["axis_label_scores"]["직"], [{"label": "헌터", "score": 0.7}])


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
    def test_first_episode_minimum_text_count_is_1000(self):
        module = load_module()
        conn = FakeConnection()

        module.get_products(conn, force=True)

        self.assertIn("fe.episode_text_count >= 1000", conn.last_cursor.sql)
        self.assertNotIn("fe.episode_text_count >= 5000", conn.last_cursor.sql)

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

    def test_banned_words_demote_to_none_not_failure(self):
        result = self.module._normalize_librarian({
            "librarian": {
                "intro": "성장 서사가 강하게 깔린 작품이에요.",
                "points": ["이 결이 좋아요.", "축으로 움직여요.", "정상 문장이에요."],
                "chips": ["먼치킨", "서사", "텍스트", "회귀"],
            }
        })
        self.assertIsNone(result["librarian_intro"])  # 서사 포함
        self.assertIsNone(result["librarian_points"])  # 결이/축으로 포함
        self.assertEqual(result["librarian_chips"], ["먼치킨", "회귀"])  # 금칙 칩만 제거

    def test_banned_re_does_not_flag_normal_words(self):
        # 결혼/대결/축제 같은 정상 단어는 오탐하지 않는다
        for text in ("결혼을 앞둔 주인공이에요.", "축제에서 사건이 벌어져요.", "대결 구도가 뚜렷해요."):
            self.assertIsNone(self.module._LIBRARIAN_BANNED_RE.search(text), text)

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
