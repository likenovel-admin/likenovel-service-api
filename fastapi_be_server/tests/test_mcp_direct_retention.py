import copy
import unittest
from datetime import date, timedelta

from app.services.ai import direct_curator_service as curator, mcp_policy as policy


class WithdrawnRetentionTests(unittest.TestCase):
    def setUp(self):
        names = (curator.SLOT_PD, curator.SLOT_WAIT_FREE, curator.SLOT_FREE_NEW,
                 curator.SLOT_LOWPOINT, curator.SLOT_PAID_OPENRUN)
        self.slots = [{"slot_id": index, "name": name, "product_ids": [1238]}
                      for index, name in enumerate(names, 1)]
        ids = [1277, 1275, *range(117, 100, -1), 1238]
        self.candidates = [
            {"product_id": product_id,
             "title": "실명자들 : 소리내는 순간 죽는다" if product_id == 1238 else f"검증 작품 {product_id}",
             "price_type": "free", "product_type": "normal", "status_code": "ongoing",
             "publish_regular_yn": "Y", "waiting_for_free_yn": "N",
             "exclude_from_recommend_yn": "N",
             "first_public_episode_date": (date(2026, 10, 26) - timedelta(days=index)).isoformat()}
            for index, product_id in enumerate(ids)
        ]
        self.slots[2]["product_ids"] = ids[2:]
        self.expected = ids[:18]

    def validate(self, ids=None, candidates=None):
        policy.validate_direct_updates(
            [{"slot_id": 3, "product_ids": self.expected if ids is None else ids,
              "reason": "사용자가 철회한 특별 유지 조건을 제외하고 최신 무료신작 순서로 보정합니다."}],
            self.slots, self.candidates if candidates is None else candidates,
        )

    def test_withdrawn_1238_retention_uses_ordinary_newest_first_capacity(self):
        self.validate()
        self.assertNotIn(1238, self.expected)
        self.assertEqual(len(self.expected), len(self.slots[2]["product_ids"]))

    def test_1238_is_still_eligible_when_ordinary_ranking_includes_it(self):
        candidates = copy.deepcopy(self.candidates)
        candidates[-1]["first_public_episode_date"] = "2099-01-01"
        self.validate([1238, *self.expected[:17]], candidates)

    def test_withdrawal_does_not_relax_order_capacity_duplicate_or_free_eligibility(self):
        for ids in (list(reversed(self.expected)), self.expected[:-1],
                    [self.expected[0], *self.expected[:-1]]):
            with self.subTest(ids=ids):
                with self.assertRaises(ValueError):
                    self.validate(ids)
        for field, value in (("price_type", "paid"), ("product_type", "fanfiction"),
                             ("status_code", "end"), ("exclude_from_recommend_yn", "Y")):
            candidates = copy.deepcopy(self.candidates)
            candidates[0][field] = value
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    self.validate(candidates=candidates)
        with self.assertRaisesRegex(ValueError, "missing"):
            self.validate(candidates=self.candidates[1:])


if __name__ == "__main__":
    unittest.main()
