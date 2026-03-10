"""
이벤트 보상 자동 지급 스모크 테스트.

실행: docker exec likenovel-api python -m unittest tests.test_event_reward_service -v
"""
import unittest
from unittest.mock import AsyncMock, patch

import app.services.event.event_reward_service as sut


# ── helpers ──────────────────────────────────────────────


class _R:
    """db.execute() 반환값 시뮬레이터."""

    def __init__(self, rows=None, scalar_value=None):
        self._rows = rows or []
        self._scalar = scalar_value

    def mappings(self):
        return self

    def all(self):
        return self._rows

    def first(self):
        return self._rows[0] if self._rows else None

    def scalar(self):
        return self._scalar


EMPTY = _R()


def _ev(
    event_id=1,
    title="테스트 이벤트",
    event_type="view-3-times",
    target_product_ids='[100]',
    reward_type="ticket",
    reward_amount=2,
    reward_max_people=None,
):
    return {
        "id": event_id,
        "title": title,
        "type": event_type,
        "target_product_ids": target_product_ids,
        "reward_type": reward_type,
        "reward_amount": reward_amount,
        "reward_max_people": reward_max_people,
    }


# ── tests ────────────────────────────────────────────────


class EventRewardSmokeTest(unittest.IsolatedAsyncioTestCase):

    # 1. 진행 중인 이벤트 없으면 아무것도 안 함
    async def test_no_active_event(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_R([]))
        await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
        self.assertEqual(db.execute.call_count, 1)

    # 2. view-3-times: 3화 → ticket 지급
    async def test_view3_ticket_granted(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _R([_ev()]),  # 이벤트 조회
            _R([]),       # 중복 없음
            _R(scalar_value=3),  # 3화 읽음
            EMPTY,        # recipient INSERT
        ])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
            m.assert_called_once_with(
                user_id=1, event_id=1, event_title="테스트 이벤트", amount=2, db=db
            )

    # 3. view-3-times: 2화만 → 미지급
    async def test_view3_only2_skipped(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_R([_ev()]), _R([]), _R(scalar_value=2)])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
            m.assert_not_called()

    # 4. 중복 수령 → 미지급
    async def test_duplicate_skipped(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[_R([_ev()]), _R([{"x": 1}])])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
            m.assert_not_called()

    # 5. max_people 초과 → 미지급
    async def test_max_people_exceeded(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _R([_ev(reward_max_people=10)]), _R([]), _R(scalar_value=10),
        ])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
            m.assert_not_called()

    # 6. target_product_ids 미포함 → 미지급
    async def test_product_not_in_target(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_R([_ev(target_product_ids='[200,300]')]))
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
            m.assert_not_called()

    # 7. add-comment: 즉시 ticket 지급
    async def test_add_comment_granted(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _R([_ev(event_type="add-comment")]), _R([]), EMPTY,
        ])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("add-comment", 1, 100, db)
            m.assert_called_once()

    # 8. add-product: target_product_ids 무시 + cash 보상
    async def test_add_product_cash(self):
        db = AsyncMock()
        ev = _ev(event_type="add-product", target_product_ids='[999]',
                 reward_type="cash", reward_amount=500)
        db.execute = AsyncMock(side_effect=[_R([ev]), _R([]), EMPTY])
        with patch.object(sut, "_grant_cash_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("add-product", 1, 50, db)
            m.assert_called_once_with(
                user_id=1, event_id=1, event_title="테스트 이벤트", amount=500, db=db
            )

    # 9. _grant_ticket_reward → post_user_giftbook 파라미터 검증
    async def test_ticket_giftbook_params(self):
        db = AsyncMock()
        with patch.object(
            sut.user_giftbook_service, "post_user_giftbook", new_callable=AsyncMock
        ) as m:
            await sut._grant_ticket_reward(
                user_id=42, event_id=7, event_title="3화 이벤트", amount=3, db=db
            )
            m.assert_called_once()
            req = m.call_args.kwargs["req_body"]
            self.assertEqual(req.user_id, 42)
            self.assertIsNone(req.product_id)
            self.assertEqual(req.ticket_type, "comped")
            self.assertEqual(req.own_type, "rental")
            self.assertEqual(req.acquisition_type, "event")
            self.assertEqual(req.acquisition_id, 7)
            self.assertEqual(req.promotion_type, "event")
            self.assertEqual(req.amount, 3)

    # 10. _grant_cash_reward → 4개 쿼리 (cashbook + tx + noti_check + noti_insert)
    async def test_cash_all_inserts(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[EMPTY, EMPTY, _R([]), EMPTY])
        await sut._grant_cash_reward(
            user_id=42, event_id=7, event_title="캐시", amount=500, db=db
        )
        self.assertEqual(db.execute.call_count, 4)

    # 11. cash 알림 OFF → noti INSERT 스킵
    async def test_cash_noti_off(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[EMPTY, EMPTY, _R([{"noti_yn": "N"}])])
        await sut._grant_cash_reward(
            user_id=42, event_id=7, event_title="캐시", amount=500, db=db
        )
        self.assertEqual(db.execute.call_count, 3)

    # 12~16. _parse_product_ids
    def test_parse_valid(self):
        self.assertEqual(sut._parse_product_ids('[1,2,3]'), [1, 2, 3])

    def test_parse_null(self):
        self.assertEqual(sut._parse_product_ids(None), [])

    def test_parse_empty(self):
        self.assertEqual(sut._parse_product_ids(""), [])

    def test_parse_garbage(self):
        self.assertEqual(sut._parse_product_ids("not-json"), [])

    def test_parse_empty_array(self):
        self.assertEqual(sut._parse_product_ids("[]"), [])

    # 17. reward_type 없으면 스킵
    async def test_no_reward_type(self):
        db = AsyncMock()
        db.execute = AsyncMock(return_value=_R([_ev(reward_type=None)]))
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("view-3-times", 1, 100, db)
            m.assert_not_called()

    # 18. target_product_ids=NULL → 모든 작품 대상
    async def test_null_target_matches_all(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _R([_ev(event_type="add-comment", target_product_ids=None)]),
            _R([]), EMPTY,
        ])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("add-comment", 1, 999, db)
            m.assert_called_once()

    # 19. target_product_ids='[]' → 모든 작품 대상
    async def test_empty_array_target_matches_all(self):
        db = AsyncMock()
        db.execute = AsyncMock(side_effect=[
            _R([_ev(event_type="add-comment", target_product_ids='[]')]),
            _R([]), EMPTY,
        ])
        with patch.object(sut, "_grant_ticket_reward", new_callable=AsyncMock) as m:
            await sut.check_and_grant_event_reward("add-comment", 1, 999, db)
            m.assert_called_once()


if __name__ == "__main__":
    unittest.main()
