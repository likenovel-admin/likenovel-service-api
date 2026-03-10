import json
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.user_giftbook as user_giftbook_schema
import app.services.user.user_giftbook_service as user_giftbook_service

logger = logging.getLogger(__name__)


async def check_and_grant_event_reward(
    event_type: str,
    user_id: int,
    product_id: int | None,
    db: AsyncSession,
):
    """
    이벤트 보상 자동 지급.
    event_type: "view-3-times" | "add-comment" | "add-product"
    """
    # 1. 진행 중인 이벤트 조회
    query = text("""
        SELECT id, title, type, target_product_ids, reward_type, reward_amount, reward_max_people
        FROM tb_event_v2
        WHERE type = :event_type
          AND start_date <= NOW() AND end_date >= NOW()
    """)
    result = await db.execute(query, {"event_type": event_type})
    events = result.mappings().all()

    if not events:
        return

    for event in events:
        event_id = event["id"]
        event_title = event["title"]
        target_product_ids_raw = event["target_product_ids"]
        reward_type = event["reward_type"]
        reward_amount = event["reward_amount"]
        reward_max_people = event["reward_max_people"]

        if not reward_type or not reward_amount:
            continue

        # 2a. target_product_ids 확인
        if event_type != "add-product":
            if not product_id:
                continue
            target_ids = _parse_product_ids(target_product_ids_raw)
            if target_ids and product_id not in target_ids:
                continue

        # 2b. 중복 지급 방지
        dup_query = text("""
            SELECT 1 FROM tb_event_v2_reward_recipient
            WHERE event_id = :event_id AND user_id = :user_id
            LIMIT 1
        """)
        dup_result = await db.execute(dup_query, {"event_id": event_id, "user_id": user_id})
        if dup_result.first():
            continue

        # 2c. 인원 제한 확인
        if reward_max_people:
            count_query = text("""
                SELECT COUNT(*) as cnt FROM tb_event_v2_reward_recipient
                WHERE event_id = :event_id
            """)
            count_result = await db.execute(count_query, {"event_id": event_id})
            current_count = count_result.scalar()
            if current_count >= reward_max_people:
                continue

        # 2d. view-3-times: 3화 이상 읽었는지 확인
        if event_type == "view-3-times":
            usage_query = text("""
                SELECT COUNT(DISTINCT episode_id) as cnt
                FROM tb_user_product_usage
                WHERE user_id = :user_id AND product_id = :product_id AND use_yn = 'Y'
            """)
            usage_result = await db.execute(
                usage_query, {"user_id": user_id, "product_id": product_id}
            )
            episode_count = usage_result.scalar()
            if episode_count < 3:
                continue

        # 2e. 조건 충족 → 보상 지급
        # 수령 기록 INSERT
        recipient_query = text("""
            INSERT INTO tb_event_v2_reward_recipient
            (event_id, user_id, created_id, updated_id)
            VALUES (:event_id, :user_id, -1, -1)
        """)
        await db.execute(recipient_query, {"event_id": event_id, "user_id": user_id})

        if reward_type == "ticket":
            await _grant_ticket_reward(
                user_id=user_id,
                event_id=event_id,
                event_title=event_title,
                amount=reward_amount,
                db=db,
            )
        elif reward_type == "cash":
            await _grant_cash_reward(
                user_id=user_id,
                event_id=event_id,
                event_title=event_title,
                amount=reward_amount,
                db=db,
            )


async def _grant_ticket_reward(
    user_id: int,
    event_id: int,
    event_title: str,
    amount: int,
    db: AsyncSession,
):
    giftbook_req = user_giftbook_schema.PostUserGiftbookReqBody(
        user_id=user_id,
        product_id=None,
        ticket_type="comped",
        own_type="rental",
        acquisition_type="event",
        acquisition_id=event_id,
        promotion_type="event",
        reason=f"이벤트 보상: {event_title}",
        amount=amount,
    )
    await user_giftbook_service.post_user_giftbook(
        req_body=giftbook_req, kc_user_id="", db=db, user_id=user_id
    )


async def _grant_cash_reward(
    user_id: int,
    event_id: int,
    event_title: str,
    amount: int,
    db: AsyncSession,
):
    # 캐시 잔액 추가
    cashbook_query = text("""
        INSERT INTO tb_user_cashbook (user_id, balance, created_id, updated_id)
        VALUES (:user_id, :amount, -1, -1)
    """)
    await db.execute(cashbook_query, {"user_id": user_id, "amount": amount})

    # 거래 내역 기록
    transaction_query = text("""
        INSERT INTO tb_user_cashbook_transaction
        (from_user_id, to_user_id, amount, created_id, created_date, updated_id)
        VALUES (:user_id, :user_id, :amount, -1, NOW(), -1)
    """)
    await db.execute(transaction_query, {"user_id": user_id, "amount": amount})

    # 알림
    noti_query = text("""
        SELECT noti_yn FROM tb_user_notification
        WHERE user_id = :user_id AND noti_type = 'benefit'
    """)
    noti_result = await db.execute(noti_query, {"user_id": user_id})
    noti_setting = noti_result.mappings().first()

    if not noti_setting or noti_setting.get("noti_yn") == "Y":
        noti_insert = text("""
            INSERT INTO tb_user_notification_item
            (user_id, noti_type, title, content, read_yn, created_id, created_date)
            VALUES (:user_id, 'benefit', :title, :content, 'N', -1, NOW())
        """)
        await db.execute(
            noti_insert,
            {
                "user_id": user_id,
                "title": "이벤트 보상이 도착했습니다",
                "content": f"{event_title} - 캐시 {amount}개 지급",
            },
        )


def _parse_product_ids(raw: str | None) -> list[int]:
    if not raw:
        return []
    try:
        ids = json.loads(raw)
        if isinstance(ids, list):
            return [int(x) for x in ids]
    except (json.JSONDecodeError, ValueError, TypeError):
        pass
    return []
