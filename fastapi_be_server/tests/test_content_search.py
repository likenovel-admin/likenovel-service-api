import unittest

from app.services.common.content_search import search_catalog


def product(pid, title, synopsis="", labels=None, **extra):
    return {
        "product_id": pid, "title": title, "author_name": "작가",
        "synopsis_text": synopsis, "standard_keywords": [],
        "analysis_status": "success", "overall_confidence": 0.95,
        "axis_label_scores": labels or {}, "last_episode_date": "2026-01-01",
        "protagonist_goal_primary": "퇴마", "goal_confidence": 0.9,
        "axis_style_tags": ["공포"], **extra,
    }


class ContentSearchTest(unittest.TestCase):
    def setUp(self):
        self.exorcist = product(1, "귀문록", labels={
            "목": [{"label": "퇴마", "score": 0.9}],
            "작": [{"label": "공포", "score": 0.9}],
        })
        self.cook = product(2, "식당 주인", "요리로 사람들을 구한다", analysis_status=None)

    def test_content_and_title_both_searchable_with_evidence(self):
        result = search_catalog([self.exorcist, self.cook], "퇴마 공포")
        self.assertEqual([p["product_id"] for p in result["matches"]], [1])
        self.assertEqual(result["matches"][0]["searchMatchReasons"], ["주인공 목표: 퇴마", "작풍: 공포"])
        self.assertEqual(search_catalog([self.cook], "요리")["matches"][0]["searchMatchReasons"], ["작품 소개: 요리"])

    def test_all_words_and_selected_tags_required(self):
        self.assertEqual(search_catalog([self.exorcist, self.cook], "퇴마 요리")["matches"], [])
        self.assertEqual(search_catalog([self.exorcist], "", ["dna:goal:퇴마"])["totalCount"], 1)
        self.assertEqual(search_catalog([self.exorcist], "", ["dna:goal:없는태그"])["totalCount"], 0)

    def test_standard_tag_without_dna_and_literal_punctuation(self):
        item = product(3, "A&B [마법]", standard_keywords=[{"id": 7, "label": "요리"}], analysis_status=None)
        self.assertEqual(search_catalog([item], "[마법]")["totalCount"], 1)
        self.assertEqual(search_catalog([item], "", ["keyword:7"])["totalCount"], 1)
        self.assertEqual(search_catalog([item], "%")["totalCount"], 0)

    def test_rejected_dna_cannot_match_or_create_facets(self):
        for patch in [{"analysis_status": "failed"}, {"exclude_from_recommend_yn": "Y"}, {"overall_confidence": 0.2}]:
            item = {**self.exorcist, **patch}
            self.assertEqual(search_catalog([item], "퇴마")["totalCount"], 0)
            self.assertEqual(search_catalog([item], "")["facets"], [])

    def test_facet_count_distinct_products_and_not_fake_popularity(self):
        item = {**self.exorcist, "standard_keywords": [{"id": 7, "label": "퇴마"}, {"id": 7, "label": "퇴마"}]}
        result = search_catalog([item, self.cook], "")
        self.assertEqual(next(f["count"] for f in result["facets"] if f["id"] == "keyword:7"), 1)
        self.assertEqual(result["totalCount"], 2)

    def test_exact_title_first_and_stable_ties(self):
        rows = [product(3, "퇴마 이야기"), product(2, "퇴마"), self.exorcist]
        self.assertEqual([p["product_id"] for p in search_catalog(rows, "퇴마")["matches"]], [2, 3, 1])


if __name__ == "__main__":
    unittest.main()
