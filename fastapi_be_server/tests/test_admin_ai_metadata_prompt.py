import unittest

from app.services.admin import admin_ai_metadata_service


class AdminAiMetadataPromptTest(unittest.TestCase):
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

    def test_normalizer_replaces_false_possession_with_growth_type(self):
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
            source_text="재벌집 손자가 트로트 가수 데뷔 목표와 시스템 퀘스트를 받으며 성장한다.",
        )

        self.assertEqual(normalized["protagonist_type_tags"], ["성장형"])
        self.assertEqual(normalized["axis_label_scores"]["타"], [{"label": "성장형", "score": 0.7}])

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
