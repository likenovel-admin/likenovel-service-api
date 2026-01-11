import json
import logging
from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

from app.exceptions import CustomResponseException
from app.const import CommonConstants, ErrorMessages

import app.schemas.user_giftbook as user_giftbook_schema
import app.services.user.user_giftbook_service as user_giftbook_service

logger = logging.getLogger(__name__)


"""
quests 도메인 개별 서비스 함수 모음
"""


async def check_daily_attendance(user_id: int, db: AsyncSession) -> bool:
    """
    출석체크 처리 및 확인

    Args:
        user_id: 유저 아이디
        db: 데이터베이스 세션

    Returns:
        오늘 출석했는지 여부 (True: 출석함, False: 출석 안 함)
    """
    try:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)

        # 오늘 출석 기록이 있는지 확인
        query = text("""
            SELECT id
            FROM tb_quest_user
            WHERE user_id = :user_id
              AND quest_id = 1
              AND created_date >= :today_start
            ORDER BY created_date DESC
            LIMIT 1
        """)
        result = await db.execute(
            query, {"user_id": user_id, "today_start": today_start}
        )
        attendance_row = result.mappings().one_or_none()

        if attendance_row:
            # 이미 오늘 출석함
            return True

        # 출석 기록이 없으면 새로 생성
        insert_query = text("""
            INSERT INTO tb_quest_user
            (quest_id, user_id, achieve_yn, reward_own_yn, current_stage, created_id, created_date, updated_id, updated_date)
            VALUES (1, :user_id, 'N', 'N', 1, -1, NOW(), -1, NOW())
        """)
        await db.execute(insert_query, {"user_id": user_id})
        await db.commit()

        return True

    except Exception as e:
        logger.error(f"Error in check_daily_attendance: {e}")
        await db.rollback()
        return False


async def get_quest_progress_count(
    quest_id: int, user_id: int, db: AsyncSession
) -> int:
    """
    퀘스트별 진행상황(current_process) 조회

    Args:
        quest_id: 퀘스트 아이디
        user_id: 유저 아이디
        db: 데이터베이스 세션

    Returns:
        현재 진행 횟수
    """
    try:
        # quest_id 1: 출석체크 - 오늘 출석했으면 1, 아니면 0
        if quest_id == 1:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            query = text("""
                SELECT COUNT(*) as count
                FROM tb_quest_user
                WHERE user_id = :user_id
                  AND quest_id = 1
                  AND created_date >= :today_start
            """)
            result = await db.execute(
                query, {"user_id": user_id, "today_start": today_start}
            )
            row = result.mappings().one_or_none()
            return 1 if (row and row["count"] > 0) else 0

        # quest_id 2: 투표하기 - 주간 카운트 (월요일부터)
        elif quest_id == 2:
            today = datetime.now()
            # 이번 주 월요일 계산
            monday = today - timedelta(days=today.weekday())
            monday_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)

            query = text("""
                SELECT COUNT(*) as count
                FROM tb_event_vote_user_req
                WHERE user_id = :user_id
                  AND created_date >= :start_date
            """)
            result = await db.execute(
                query, {"user_id": user_id, "start_date": monday_start}
            )
            row = result.mappings().one_or_none()
            return row["count"] if row else 0

        # quest_id 3: 평가하기 - 일일 카운트
        elif quest_id == 3:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            query = text("""
                SELECT COUNT(*) as count
                FROM tb_product_evaluation
                WHERE user_id = :user_id
                  AND created_date >= :start_date
            """)
            result = await db.execute(
                query, {"user_id": user_id, "start_date": today_start}
            )
            row = result.mappings().one_or_none()
            return row["count"] if row else 0

        # quest_id 6: 작품 리뷰 작성하기 - 일일 카운트
        elif quest_id == 6:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            query = text("""
                SELECT COUNT(*) as count
                FROM tb_product_review
                WHERE user_id = :user_id
                  AND created_date >= :start_date
            """)
            result = await db.execute(
                query, {"user_id": user_id, "start_date": today_start}
            )
            row = result.mappings().one_or_none()
            return row["count"] if row else 0

        # quest_id 9: 회차 결제하기 - 일일 카운트
        # 실제 결제로 획득한 대여권만 카운트 (선물함, 이벤트 등 제외)
        elif quest_id == 9:
            today_start = datetime.now().replace(
                hour=0, minute=0, second=0, microsecond=0
            )

            query = text("""
                SELECT COUNT(*) as count
                FROM tb_user_productbook
                WHERE user_id = :user_id
                  AND created_date >= :start_date
                  AND acquisition_type IS NULL
            """)
            result = await db.execute(
                query, {"user_id": user_id, "start_date": today_start}
            )
            row = result.mappings().one_or_none()
            return row["count"] if row else 0

        # 기타 quest_id는 0 반환
        else:
            return 0

    except Exception as e:
        logger.error(f"Error in get_quest_progress_count: {e}")
        return 0


async def quest_all(kc_user_id: str, db: AsyncSession):
    """
    퀘스트 목록
    """
    try:
        user_id = None
        where_str = ""

        # 사용자 정보 조회
        if kc_user_id is not None:
            user_id, user_info = await comm_service.get_user_from_kc(
                kc_user_id, db, ["role_type"]
            )
            if user_id != -1:
                # 로그인 상태에서 퀘스트 목록 조회 시 출석체크 자동 처리
                await check_daily_attendance(user_id, db)

                if user_info["role_type"] != "admin":
                    where_str = f"where q.quest_id in (select distinct quest_id from tb_quest_user where user_id = {user_id})"

        # tb_quest LEFT JOIN tb_quest_user (최신 레코드만 사용하여 중복 방지)
        query = text(f"""
                    select
                        q.*,
                        qu.current_stage,
                        qu.reward_own_yn,
                        qu.user_id as quest_user_id
                    from tb_quest q
                    left join (
                        select qu1.quest_id, qu1.current_stage, qu1.reward_own_yn, qu1.user_id
                        from tb_quest_user qu1
                        inner join (
                            select quest_id, max(updated_date) as max_updated_date, max(id) as max_id
                            from tb_quest_user
                            where user_id = {user_id if user_id else 0}
                            group by quest_id
                        ) qu2 on qu1.quest_id = qu2.quest_id
                            and qu1.updated_date = qu2.max_updated_date
                            and qu1.id = qu2.max_id
                        where qu1.user_id = {user_id if user_id else 0}
                    ) qu on q.quest_id = qu.quest_id
                    {where_str}
                    """)
        result = await db.execute(query, {})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = []
        for row in rows:
            quest = dict(row)

            # current_stage, quest_user_id는 quest 객체에서 제거 (내부 사용용)
            current_stage = quest.pop("current_stage", None) or 0
            quest.pop("quest_user_id", None)

            # reward_own_yn은 quest 객체에 그대로 유지, 기본값만 설정
            if quest.get("reward_own_yn") is None:
                quest["reward_own_yn"] = CommonConstants.NO

            quest["renewal"] = (
                json.loads(quest["renewal"]) if quest["renewal"] is not None else {}
            )
            if "MON" not in quest["renewal"]:
                quest["renewal"]["MON"] = CommonConstants.NO
            if "TUE" not in quest["renewal"]:
                quest["renewal"]["TUE"] = CommonConstants.NO
            if "WED" not in quest["renewal"]:
                quest["renewal"]["WED"] = CommonConstants.NO
            if "THU" not in quest["renewal"]:
                quest["renewal"]["THU"] = CommonConstants.NO
            if "FRI" not in quest["renewal"]:
                quest["renewal"]["FRI"] = CommonConstants.NO
            if "SAT" not in quest["renewal"]:
                quest["renewal"]["SAT"] = CommonConstants.NO
            if "SUN" not in quest["renewal"]:
                quest["renewal"]["SUN"] = CommonConstants.NO

            # current_stage에 따라 해당하는 step만 current_stage로 반환
            # current_stage가 0이면 step1을 기본값으로 사용
            stage_num = current_stage if current_stage > 0 else 1
            step_field = f"step{stage_num}"

            quest["current_stage"] = (
                json.loads(quest[step_field]) if quest[step_field] is not None else {}
            )
            if "useYn" not in quest["current_stage"]:
                quest["current_stage"]["useYn"] = CommonConstants.NO
            if "count_process" not in quest["current_stage"]:
                quest["current_stage"]["count_process"] = 0
            if "count_ticket" not in quest["current_stage"]:
                quest["current_stage"]["count_ticket"] = 0

            # step1, step2, step3 필드 제거
            quest.pop("step1", None)
            quest.pop("step2", None)
            quest.pop("step3", None)

            # 진행상황 추가
            current_process = 0
            if user_id is not None:
                current_process = await get_quest_progress_count(
                    quest["quest_id"], user_id, db
                )

            quest["progress"] = {
                "current_stage": current_stage,
                "current_process": current_process,
            }

            res_body["data"].append(quest)

        return res_body

    except Exception as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


async def quest_rewarded(kc_user_id: str, db: AsyncSession):
    """
    로그인한 유저가 보상을 받은 퀘스트 리스트 조회

    Args:
        kc_user_id: Keycloak user ID
        db: 데이터베이스 세션

    Returns:
        보상을 받은 퀘스트 리스트
    """
    try:
        # kc_user_id로 user_id 조회
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)

        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_MEMBER,
            )

        # tb_quest_user에서 reward_own_yn = 'Y'인 퀘스트 조회
        query = text("""
            select
                q.quest_id,
                q.title,
                q.reward_id,
                q.use_yn,
                q.end_date,
                q.created_date,
                q.updated_date,
                qr.item_id,
                qr.item_name,
                qr.item_type,
                qu.current_stage,
                qu.achieve_yn,
                qu.reward_own_yn,
                qu.updated_date as reward_received_date
            from tb_quest_user qu
            inner join tb_quest q on qu.quest_id = q.quest_id
            left join tb_quest_reward qr on q.reward_id = qr.reward_id
            where qu.user_id = :user_id
              and qu.reward_own_yn = 'Y'
            order by qu.updated_date desc
        """)

        result = await db.execute(query, {"user_id": user_id})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = []

        for row in rows:
            quest_data = {
                "quest_id": row["quest_id"],
                "title": row["title"],
                "reward_id": row["reward_id"],
                "use_yn": row["use_yn"],
                "end_date": row["end_date"],
                "created_date": row["created_date"],
                "updated_date": row["updated_date"],
                "reward": {
                    "item_id": row["item_id"],
                    "item_name": row["item_name"],
                    "item_type": row["item_type"],
                }
                if row["item_id"] is not None
                else None,
                "current_stage": row["current_stage"],
                "achieve_yn": row["achieve_yn"],
                "reward_own_yn": row["reward_own_yn"],
                "reward_received_date": row["reward_received_date"],
            }
            res_body["data"].append(quest_data)

        return res_body

    except CustomResponseException:
        raise
    except Exception as e:
        logger.error(f"Error in quest_rewarded: {e}")
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


async def update_quest_rewards_by_userid(
    quest_id: str, reward_id: str, kc_user_id: str, db: AsyncSession
):
    """
    퀘스트 달성 사용자 보상 지급
    """
    # reward_id를 int로 변환 (타입 불일치 방지)
    reward_id_int = int(reward_id)

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_MEMBER,
        )

    query = text("""
                 select * from tb_quest where quest_id = :quest_id
                 """)
    result = await db.execute(query, {"quest_id": quest_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_QUEST,
        )
    quest = dict(row)
    if quest.get("reward_id") != reward_id_int:
        # 보상이 퀘스트에 할당된 보상이 아님
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.QUEST_REWARD_ERROR,
        )

    query = text("""
                 select * from tb_quest_reward where reward_id = :reward_id
                 """)
    result = await db.execute(query, {"reward_id": reward_id_int})
    row = result.mappings().one_or_none()
    if row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.QUEST_REWARD_ERROR,
        )
    reward = dict(row)

    # 선물함을 통해 보상 지급 (범용 대여권으로 발급)
    req_body = user_giftbook_schema.PostUserGiftbookReqBody(
        user_id=user_id,
        product_id=None,  # 범용: 모든 작품에 사용 가능
        episode_id=None,  # 범용: 모든 에피소드에 사용 가능
        ticket_type="comped",  # 무료 대여권
        own_type="rental",  # 대여
        acquisition_type="quest",  # 퀘스트 보상
        acquisition_id=quest_id,  # 퀘스트 ID
        reason="퀘스트 보상",
        amount=1,
    )
    result = await user_giftbook_service.post_user_giftbook(
        req_body=req_body, kc_user_id=kc_user_id, db=db, user_id=user_id
    )

    # tb_quest_user 달성 여부, 보상 소유 여부 업데이트
    query = text("""
                        update tb_quest_user set
                        achieve_yn = :achieve_yn,
                        reward_own_yn = :reward_own_yn
                        where quest_id = :quest_id and user_id = :user_id
                    """)
    await db.execute(
        query,
        {
            "quest_id": quest_id,
            "user_id": user_id,
            "achieve_yn": CommonConstants.YES,
            "reward_own_yn": CommonConstants.YES,
        },
    )

    # tb_user_notification_item에 알림 추가
    quest_title = quest.get("title", "퀘스트")
    reward_name = reward.get("item_name", "보상")
    notification_content = (
        f"{quest_title} 퀘스트를 완료하여 {reward_name}을(를) 획득했습니다"
    )

    notification_query = text("""
        insert into tb_user_notification_item
        (user_id, noti_type, title, content, read_yn, created_id, created_date)
        values (:user_id, :noti_type, :title, :content, :read_yn, :created_id, NOW())
    """)
    await db.execute(
        notification_query,
        {
            "user_id": user_id,
            "noti_type": "benefit",
            "title": "퀘스트 보상 획득",
            "content": notification_content,
            "read_yn": "N",
            "created_id": -1,
        },
    )

    return result
