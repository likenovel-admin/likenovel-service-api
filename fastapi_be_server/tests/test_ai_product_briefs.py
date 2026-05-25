import unittest

from app.services.ai import recommendation_service


class AiProductBriefsUnitTest(unittest.IsolatedAsyncioTestCase):
    class _FakeMappingsResult:
        def __init__(self, rows):
            self._rows = rows

        def mappings(self):
            return self

        def all(self):
            return self._rows

    async def test_get_product_ai_briefs_returns_public_successful_metadata(self):
        class FakeDb:
            def __init__(self):
                self.executed_sql = ""
                self.params = {}

            async def execute(self, query, params):
                self.executed_sql = str(query)
                self.params = params
                return AiProductBriefsUnitTest._FakeMappingsResult(
                    [
                        {
                            "product_id": 1158,
                            "title": "월영루의 검",
                            "premise": "권력에 가족을 잃은 청년이 금단의 무공으로 복수를 준비한다.",
                            "hook": "단전 파괴된 무인이 절벽 아래에서 마신의 무공을 익힌다.",
                            "mood": "비장하고 암울한 분위기",
                            "pacing": "fast",
                            "protagonist_type": "무인",
                            "protagonist_goal_primary": "복수",
                            "taste_tags": "[\"강렬한 서사\", \"복수\"]",
                            "worldview_tags": "[\"선협\"]",
                            "protagonist_type_tags": "[\"성장형\"]",
                            "protagonist_job_tags": "[\"무인\"]",
                            "protagonist_material_tags": "[\"마신\"]",
                            "axis_style_tags": "[\"비장\", \"피폐\"]",
                            "axis_romance_tags": "[]",
                        }
                    ]
                )

        db = FakeDb()

        briefs = await recommendation_service.get_product_ai_briefs(
            [1158, 1158, 0, -1], db, adult_yn="N"
        )

        self.assertEqual(db.params["product_ids"], [1158])
        self.assertIn("p.open_yn = 'Y'", db.executed_sql)
        self.assertIn("m.analysis_status = 'success'", db.executed_sql)
        self.assertIn("COALESCE(m.exclude_from_recommend_yn, 'N') = 'N'", db.executed_sql)
        self.assertIn("p.ratings_code = 'all'", db.executed_sql)
        self.assertEqual(
            briefs,
            [
                {
                    "productId": 1158,
                    "title": "월영루의 검",
                    "premise": "권력에 가족을 잃은 청년이 금단의 무공으로 복수를 준비한다.",
                    "hook": "단전 파괴된 무인이 절벽 아래에서 마신의 무공을 익힌다.",
                    "mood": "비장하고 암울한 분위기",
                    "pacing": "fast",
                    "protagonistType": "무인",
                    "protagonistGoal": "복수",
                    "tasteTags": ["강렬한 서사", "복수"],
                    "worldviewTags": ["선협"],
                    "protagonistTypeTags": ["성장형"],
                    "protagonistJobTags": ["무인"],
                    "protagonistMaterialTags": ["마신"],
                    "styleTags": ["비장", "피폐"],
                    "romanceTags": [],
                }
            ],
        )

    async def test_get_product_ai_briefs_never_trusts_public_adult_query_param(self):
        class FakeDb:
            def __init__(self):
                self.executed_sql = ""

            async def execute(self, query, params):
                self.executed_sql = str(query)
                return AiProductBriefsUnitTest._FakeMappingsResult([])

        db = FakeDb()

        await recommendation_service.get_product_ai_briefs([1158], db, adult_yn="Y")

        self.assertIn("p.ratings_code = 'all'", db.executed_sql)
