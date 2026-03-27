from fastapi import status
from sqlalchemy import RowMapping, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import List

import json
import logging
from datetime import datetime, timedelta

from app.const import LOGGER_TYPE, settings, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.time import convert_to_kor_time
from app.utils.query import get_file_path_sub_query
from app.utils.response import build_list_response
import app.services.common.comm_service as comm_service
import app.schemas.product as product_schema
from app.services.common.cp_link_service import (
    get_accepted_cp_info_by_nickname,
    get_accepted_cp_info_by_user_id,
    normalize_cp_nickname,
)

from app.config.log_config import service_error_logger

from collections import defaultdict
import app.services.common.statistics_service as statistics_service
import app.schemas.user_giftbook as user_giftbook_schema
import app.services.user.user_giftbook_service as user_giftbook_service
import app.services.event.event_reward_service as event_reward_service

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)
logger = logging.getLogger(__name__)

"""
products ?꾨찓??媛쒕퀎 ?쒕퉬???⑥닔 紐⑥쓬
"""

DEFAULT_PUBLISHER_PROMOTION_TITLE = "출판사 프로모션"
MAIN_RULE_SLOT_DEFINITIONS = [
    {
        "slot_key": "free-new-3up",
        "suggest_id": 1001,
        "suggest_name": "free-new-3up",
        "suggest_title": "3화 돌파 신작",
    },
    {
        "slot_key": "free-binge-10up",
        "suggest_id": 1002,
        "suggest_name": "free-binge-10up",
        "suggest_title": "10화 연독 인기작",
    },
]


async def _resolve_current_user_role(kc_user_id: str, db: AsyncSession) -> str:
    """
    kc_user_id 湲곗? ?꾩옱 ?ъ슜????븷??議고쉶?쒕떎.
    admin > partner(cp) > author ?쒖쑝濡?留ㅽ븨?쒕떎.
    """
    query = text("""
        select
            u.role_type,
            (
                select apply_type
                  from tb_user_profile_apply
                 where user_id = u.user_id
                   and approval_code = 'accepted'
                 order by created_date desc
                 limit 1
            ) as apply_type
          from tb_user u
         where u.kc_user_id = :kc_user_id
           and u.use_yn = 'Y'
         limit 1
    """)
    result = await db.execute(query, {"kc_user_id": kc_user_id})
    row = result.mappings().one_or_none()

    if row is None:
        return "author"

    if row.get("role_type") == "admin":
        return "admin"

    if row.get("apply_type") == "cp":
        return "CP"

    return "author"


async def _resolve_author_id(
    author_nickname: str,
    db: AsyncSession,
    allow_external_author_nickname: bool = False,
) -> int:
    """
    ?묎? ?됰꽕?꾩쑝濡?author_id瑜?議고쉶?쒕떎.
    - 湲곕낯: tb_user_profile.nickname 留ㅼ묶 ?꾩슂
    - allow_external_author_nickname=True ?닿퀬 ?됰꽕?꾩씠 鍮꾩뼱?덉? ?딆쑝硫?鍮꾪쉶???묎?(0) ?덉슜
    """
    query = text("""
                     select user_id
                       from tb_user_profile
                      where nickname = :nickname
                     """)

    result = await db.execute(query, {"nickname": author_nickname})
    db_rst = result.mappings().all()

    if db_rst:
        return db_rst[0].get("user_id")

    if allow_external_author_nickname and author_nickname and author_nickname.strip():
        return settings.DB_DML_DEFAULT_ID

    raise CustomResponseException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        message=ErrorMessages.INVALID_NICKNAME_INFO,
    )


async def _resolve_cp_link_info(
    cp_contract_yn: str,
    cp_nickname: str | None,
    db: AsyncSession,
    *,
    for_update: bool = False,
) -> dict | None:
    if cp_contract_yn != "Y":
        return None

    normalized_cp_nickname = normalize_cp_nickname(cp_nickname)
    if normalized_cp_nickname is None:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="유효한 CP를 확인할 수 없습니다.",
        )

    cp_info = await get_accepted_cp_info_by_nickname(
        normalized_cp_nickname, db, for_update=for_update
    )
    if cp_info is None:
        logger.warning("invalid cp nickname requested during contract validation")
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="유효한 CP를 확인할 수 없습니다.",
        )

    return cp_info


def get_select_fields_and_joins_for_product(
    user_id: int | None = None,
    join_rank: bool = False,
    rank_area_code: str | None = None,
):
    join_rank_enabled = join_rank or rank_area_code is not None
    return {
        "select_fields": ",".join(
            [
                "p.product_id as productId",
                "if(p.ratings_code = 'adult', 'Y', 'N') as adultYn",
                "p.title",
                "p.synopsis_text as synopsis",
                "p.author_name as authorNickname",
                "p.price_type as priceType",
                "COALESCE(p.single_regular_price, 0) as singleRegularPrice",
                "COALESCE(p.single_rental_price, 0) as singleRentalPrice",
                "COALESCE(p.series_regular_price, 0) as seriesRegularPrice",
                "p.illustrator_name as illustratorNickname",
                "ifnull(p.product_type, 'free') as productType",
                "p.created_date as createdDate",
                "p.updated_date as updatedDate",
                "p.author_id as authorId",
                "(SELECT GROUP_CONCAT(DISTINCT sk2.keyword_name SEPARATOR '|') FROM tb_mapped_product_keyword mpk2 LEFT JOIN tb_standard_keyword sk2 ON sk2.keyword_id = mpk2.keyword_id WHERE mpk2.product_id = p.product_id) as keywords",
                "pg.keyword_name as primary_genre",
                "sg.keyword_name as sub_genre",
                "pr.current_rank" if join_rank_enabled else "NULL as current_rank",
                "(pr.privious_rank - pr.current_rank) as rank_indicator"
                if join_rank
                else "(pr.previous_rank - pr.current_rank) as rank_indicator"
                if rank_area_code is not None
                else "NULL as rank_indicator",
                "cf.file_path as coverImagePath",
                "p.count_hit",
                "p.count_cp_hit",
                "p.count_recommend",
                "p.count_bookmark",
                "COALESCE(ep_count.episode_count, 0) as hasEpisodeCount",
                "COALESCE(ep_count.open_episode_count, 0) as totalOpenEpisodeCount",
                "wff.status as waitingForFreeStatus",
                "p69.status as sixNinePathStatus",
                # "fff.num_of_ticket_per_person as freeEpisodes",
                "if(p.created_date >= DATE_SUB(NOW(), INTERVAL 3 DAY), 'Y', 'N') as newReleaseYn",
                "COALESCE(ut.ticket_count, 0) as freeEpisodeTicketCount"
                if user_id
                else "0 as freeEpisodeTicketCount",
                "aeb.file_path as authorEventLevelBadgeImagePath",
                "aib.file_path as authorInterestLevelBadgeImagePath",
                f"(SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY) FROM tb_user_product_usage upu2 WHERE upu2.product_id = p.product_id AND upu2.user_id = {user_id} AND upu2.use_yn = 'Y') as interestEndDate"
                if user_id
                else "NULL as interestEndDate",
                f"""CASE
                    WHEN (SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY) FROM tb_user_product_usage upu2 WHERE upu2.product_id = p.product_id AND upu2.user_id = {user_id} AND upu2.use_yn = 'Y') IS NULL THEN 'no_interest'
                    WHEN (SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY) FROM tb_user_product_usage upu2 WHERE upu2.product_id = p.product_id AND upu2.user_id = {user_id} AND upu2.use_yn = 'Y') > NOW() THEN
                        CASE
                            WHEN (SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY) FROM tb_user_product_usage upu2 WHERE upu2.product_id = p.product_id AND upu2.user_id = {user_id} AND upu2.use_yn = 'Y') <= DATE_ADD(NOW(), INTERVAL 72 HOUR) THEN 'interest_ending_soon'
                            ELSE 'interest_active'
                        END
                    ELSE 'no_interest'
                END as interestStatus"""
                if user_id
                else "'no_interest' as interestStatus",
                "pti.reading_rate as readThroughRate",
                "pcv.reading_rate_indicator as readThroughIndicator",
                "pcv.count_cp_hit_indicator as cpHitIndicator",
                "COALESCE(interest_count.total_interest, 0) as totalInterestCount",
                "pcv.count_interest_indicator as totalInterestIndicator",
                "pdcs.current_count_interest_sustain as interestSustainCount",
                "pcv.count_interest_sustain_indicator as interestSustainIndicator",
                "pdcs.current_count_interest_loss as interestLossCount",
                "pcv.count_interest_loss_indicator as interestLossIndicator",
                "pcv.count_hit_indicator as hitIndicator",
                "pcv.count_recommend_indicator as recommendIndicator",
                "pcv.count_bookmark_indicator as bookmarkIndicator",
                "pti.writing_count_per_week as averageWeeklyEpisodes",
                "pti.primary_reader_group as primaryReaderGroup",
                "COALESCE(readed_count.count, 0) as readedEpisodeCount"
                if user_id
                else "0 as readedEpisodeCount",
                "pco_latest.offer_price as advancePayment",
                "COALESCE(total_sales.total, 0) as totalSales",
                "p.publish_days",
                "p.last_episode_date",
                "COALESCE(ub.use_yn, 'N') as bookmarkYn"
                if user_id
                else "'N' as bookmarkYn",
                "p.monopoly_yn",
                "p.contract_yn",
                "p.status_code",
                "p.publish_regular_yn",
                "COALESCE(offer_stats.offer_count, 0) as offerCount",
                "pco_latest.offer_id as offerId",
                "pco_latest.offer_date as offerDate",
                "pco_latest.offer_price as offerAdvancePayment",
                "pco_latest.settlement_ratio as settlementRatioSnippet",
                "pco_latest.decision_state as offerDecisionState",
                "COALESCE(ppa_latest.paid_state, 'not_applied') as convertToPaidState",
                "CASE WHEN ppa_latest.apply_count = 2 OR (ppa_latest.apply_count = 1 AND ppa_latest.status_code_raw != 'denied') THEN 'N' ELSE 'Y' END as canApplyForPaid",
                "(5 - COALESCE(notification_log.weekly_notification_count, 0)) as remainingNotificationCount",
                "latest_episode.episode_no as latestEpisodeNo",
                "latest_episode.episode_id as latestEpisodeId",
                "first_episode.episode_id as firstEpisodeId",
                "recent_read_episode.episode_id as recentReadEpisodeId"
                if user_id
                else "NULL as recentReadEpisodeId",
                "recent_read_episode.episode_no as recentReadEpisodeNo"
                if user_id
                else "NULL as recentReadEpisodeNo",
            ]
        ),
        "joins": """
            LEFT JOIN tb_standard_keyword pg ON pg.keyword_id = p.primary_genre_id AND pg.use_yn = 'Y' AND pg.major_genre_yn = 'Y'
            LEFT JOIN tb_standard_keyword sg ON sg.keyword_id = p.sub_genre_id AND sg.use_yn = 'Y' AND sg.major_genre_yn = 'Y'
            """
        + (
            "INNER JOIN tb_product_rank pr ON pr.product_id = p.product_id"
            if join_rank
            else f"""
            INNER JOIN (
                SELECT r1.product_id, r1.current_rank, r1.previous_rank
                FROM tb_product_rank_area r1
                INNER JOIN (
                    SELECT product_id, MAX(created_date) AS max_created_date
                    FROM tb_product_rank_area
                    WHERE area_code = '{rank_area_code}'
                    GROUP BY product_id
                ) r2
                  ON r1.product_id = r2.product_id
                 AND r1.created_date = r2.max_created_date
                WHERE r1.area_code = '{rank_area_code}'
            ) pr ON pr.product_id = p.product_id
            """
            if rank_area_code is not None
            else ""
        )
        + """
            LEFT JOIN (
                SELECT cf.file_group_id, cfi.file_path
                FROM tb_common_file cf
                JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
                WHERE cf.use_yn = 'Y' AND cfi.use_yn = 'Y' AND cf.group_type = 'cover'
            ) cf ON cf.file_group_id = p.thumbnail_file_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) as episode_count, SUM(CASE WHEN open_yn = 'Y' THEN 1 ELSE 0 END) as open_episode_count
                FROM tb_product_episode
                WHERE use_yn = 'Y'
                GROUP BY product_id
            ) ep_count ON ep_count.product_id = p.product_id
            """
        + "LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND wff.status = 'ing' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())"
        + "LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND p69.status = 'ing' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())"
        # + "LEFT JOIN tb_direct_promotion fff ON fff.product_id = p.product_id AND fff.type = 'free-for-first'"
        + (
            f"""
            LEFT JOIN (
                SELECT product_id, COUNT(*) as ticket_count
                FROM tb_user_ticketbook
                WHERE user_id = {user_id} AND ticket_type = 'free' AND use_yn = 'Y'
                  AND (use_expired_date IS NULL OR use_expired_date > NOW())
                GROUP BY product_id
            ) ut ON ut.product_id = p.product_id
            LEFT JOIN (
                SELECT product_id, user_id, COUNT(DISTINCT episode_id) as count, MAX(updated_date) as updated_date
                FROM tb_user_product_usage
                WHERE user_id = {user_id} AND use_yn = 'Y'
                GROUP BY product_id, user_id
            ) readed_count ON readed_count.product_id = p.product_id
            LEFT JOIN tb_user_bookmark ub ON ub.product_id = p.product_id AND ub.user_id = {user_id}
            """
            if user_id
            else """
            LEFT JOIN (SELECT NULL as product_id, 0 as ticket_count WHERE FALSE) ut ON ut.product_id = p.product_id
            LEFT JOIN (SELECT NULL as product_id, 0 as count WHERE FALSE) readed_count ON readed_count.product_id = p.product_id
            LEFT JOIN (SELECT NULL as product_id, 'N' as use_yn WHERE FALSE) ub ON ub.product_id = p.product_id
            """
        )
        + """
            LEFT JOIN (
                SELECT cf.file_group_id, cfi.file_path, ub.user_id
                FROM tb_common_file cf
                JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
                JOIN tb_user_badge ub ON ub.badge_image_id = cf.file_group_id
                WHERE cf.use_yn = 'Y' AND cfi.use_yn = 'Y' AND cf.group_type = 'badge'
                  AND ub.badge_type = 'event' AND ub.use_yn = 'Y' AND ub.display_yn = 'Y'
            ) aeb ON aeb.user_id = p.author_id
            LEFT JOIN (
                SELECT cf.file_group_id, cfi.file_path, ub.user_id
                FROM tb_common_file cf
                JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
                JOIN tb_user_badge ub ON ub.badge_image_id = cf.file_group_id
                WHERE cf.use_yn = 'Y' AND cfi.use_yn = 'Y' AND cf.group_type = 'badge'
                  AND ub.badge_type = 'interest' AND ub.use_yn = 'Y' AND ub.display_yn = 'Y'
            ) aib ON aib.user_id = p.author_id
            LEFT JOIN tb_product_trend_index pti ON pti.product_id = p.product_id
            LEFT JOIN tb_product_count_variance pcv ON pcv.product_id = p.product_id
            LEFT JOIN (
                SELECT product_id, current_count_interest_sustain, current_count_interest_loss
                FROM (
                    SELECT
                        product_id,
                        current_count_interest_sustain,
                        current_count_interest_loss,
                        ROW_NUMBER() OVER (
                            PARTITION BY product_id
                            ORDER BY created_date DESC, id DESC
                        ) AS rn
                    FROM tb_batch_daily_product_count_summary
                ) latest_pdcs
                WHERE rn = 1
            ) pdcs ON pdcs.product_id = p.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(DISTINCT user_id) as total_interest
                FROM tb_user_product_usage
                WHERE use_yn = 'Y'
                GROUP BY product_id
            ) interest_count ON interest_count.product_id = p.product_id
            LEFT JOIN (
                SELECT poii.product_id, SUM(po.total_price) as total
                FROM tb_product_order po
                JOIN tb_product_order_item poi ON po.order_id = poi.order_id
                JOIN tb_product_order_item_info poii ON poi.item_id = poii.item_info_id
                WHERE po.cancel_yn = 'N'
                GROUP BY poii.product_id
            ) total_sales ON total_sales.product_id = p.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) as offer_count
                FROM tb_product_contract_offer
                WHERE use_yn = 'Y'
                GROUP BY product_id
            ) offer_stats ON offer_stats.product_id = p.product_id
            LEFT JOIN (
                SELECT DISTINCT
                    product_id,
                    FIRST_VALUE(offer_id) OVER (PARTITION BY product_id ORDER BY created_date DESC) as offer_id,
                    FIRST_VALUE(offer_date) OVER (PARTITION BY product_id ORDER BY created_date DESC) as offer_date,
                    FIRST_VALUE(offer_price) OVER (PARTITION BY product_id ORDER BY created_date DESC) as offer_price,
                    FIRST_VALUE(CONCAT('?뺤궛鍮?CP ', offer_profit, ' : ?묎? ', author_profit)) OVER (PARTITION BY product_id ORDER BY created_date DESC) as settlement_ratio,
                    FIRST_VALUE(CASE WHEN author_accept_yn = 'Y' THEN 'accepted' WHEN author_accept_yn = 'N' THEN 'review' ELSE 'review' END) OVER (PARTITION BY product_id ORDER BY created_date DESC) as decision_state
                FROM tb_product_contract_offer
                WHERE use_yn = 'Y'
            ) pco_latest ON pco_latest.product_id = p.product_id
            LEFT JOIN (
                SELECT DISTINCT
                    product_id,
                    CASE
                        WHEN COUNT(*) OVER (PARTITION BY product_id) = 1 THEN
                            FIRST_VALUE(CASE WHEN status_code = 'review' THEN 'review' WHEN status_code = 'denied' THEN 'rejected' WHEN status_code = 'accepted' THEN 'approval' ELSE 'review' END) OVER (PARTITION BY product_id ORDER BY created_date ASC)
                        WHEN COUNT(*) OVER (PARTITION BY product_id) = 2 THEN
                            FIRST_VALUE(CASE WHEN status_code = 'review' THEN 'review' WHEN status_code = 'denied' THEN 'rejected' WHEN status_code = 'accepted' THEN 'approval' ELSE 'review' END) OVER (PARTITION BY product_id ORDER BY created_date DESC)
                        ELSE 'review'
                    END as paid_state,
                    COUNT(*) OVER (PARTITION BY product_id) as apply_count,
                    CASE
                        WHEN COUNT(*) OVER (PARTITION BY product_id) = 1 THEN
                            FIRST_VALUE(status_code) OVER (PARTITION BY product_id ORDER BY created_date ASC)
                        WHEN COUNT(*) OVER (PARTITION BY product_id) = 2 THEN
                            FIRST_VALUE(status_code) OVER (PARTITION BY product_id ORDER BY created_date DESC)
                        ELSE NULL
                    END as status_code_raw
                FROM tb_product_paid_apply
                WHERE use_yn = 'Y'
            ) ppa_latest ON ppa_latest.product_id = p.product_id
            LEFT JOIN (
                SELECT product_id, COUNT(*) as weekly_notification_count
                FROM tb_user_notification_log
                WHERE created_date >= DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY)
                  AND created_date < DATE_ADD(DATE_SUB(CURDATE(), INTERVAL WEEKDAY(CURDATE()) DAY), INTERVAL 7 DAY)
                GROUP BY product_id
            ) notification_log ON notification_log.product_id = p.product_id
            LEFT JOIN (
                SELECT DISTINCT
                    product_id,
                    FIRST_VALUE(episode_id) OVER (PARTITION BY product_id ORDER BY created_date DESC, episode_id DESC) as episode_id,
                    FIRST_VALUE(episode_no) OVER (PARTITION BY product_id ORDER BY created_date DESC, episode_id DESC) as episode_no
                FROM tb_product_episode
                WHERE open_yn = 'Y' AND use_yn = 'Y'
            ) latest_episode ON latest_episode.product_id = p.product_id
            LEFT JOIN (
                SELECT DISTINCT
                    product_id,
                    FIRST_VALUE(episode_id) OVER (PARTITION BY product_id ORDER BY created_date ASC, episode_id ASC) as episode_id
                FROM tb_product_episode
                WHERE open_yn = 'Y' AND use_yn = 'Y'
            ) first_episode ON first_episode.product_id = p.product_id
        """
        + (
            f"""
            LEFT JOIN (
                SELECT DISTINCT
                    upb.product_id,
                    FIRST_VALUE(pe.episode_id) OVER (PARTITION BY upb.product_id ORDER BY upb.updated_date DESC, upb.episode_id DESC) as episode_id,
                    FIRST_VALUE(pe.episode_no) OVER (PARTITION BY upb.product_id ORDER BY upb.updated_date DESC, upb.episode_id DESC) as episode_no
                FROM tb_user_productbook upb
                INNER JOIN tb_product_episode pe ON upb.episode_id = pe.episode_id
                WHERE upb.user_id = {user_id} AND upb.use_yn = 'Y'
            ) recent_read_episode ON recent_read_episode.product_id = p.product_id
            """
            if user_id
            else ""
        )
        + """
        """,
    }


TOP_MANAGED_AREA_ALIASES = {
    "freeTop": "freeSerialTop",
    "paidTop": "paidSerialTop",
}

TOP_MANAGED_AREA_RULES = {
    "freeSerialTop": {
        "rank_area_code": "freeSerialTop",
        "area_label": "freeSerialTop",
        "filters": [
            'p.price_type = "free"',
            'p.status_code IN ("ongoing", "rest")',
        ],
    },
    "paidSerialTop": {
        "rank_area_code": "paidSerialTop",
        "area_label": "paidSerialTop",
        "filters": [
            'p.price_type = "paid"',
            'p.publish_regular_yn = "Y"',
            'p.status_code IN ("ongoing", "rest")',
        ],
    },
    "paidEndTop": {
        "rank_area_code": "paidEndTop",
        "area_label": "paidEndTop",
        "filters": [
            'p.price_type = "paid"',
            'p.publish_regular_yn = "Y"',
            'p.status_code = "end"',
        ],
    },
    "paidStandaloneTop": {
        "rank_area_code": "paidStandaloneTop",
        "area_label": "paidStandaloneTop",
        "filters": [
            'p.price_type = "paid"',
            'p.publish_regular_yn = "N"',
        ],
    },
    "paidMainTop": {
        "rank_area_code": "paidMainTop",
        "area_label": "paidMainTop",
        "filters": [
            'p.price_type = "paid"',
            'p.publish_regular_yn = "Y"',
            'p.status_code IN ("ongoing", "rest", "end")',
        ],
    },
}


def convert_product_data(row: RowMapping):
    data = dict(row)
    if data["keywords"] is not None:
        data["keywords"] = data["keywords"].split("|")
    else:
        data["keywords"] = []
    data["genre"] = []
    if data["primary_genre"] is not None:
        data["genre"].append(data.pop("primary_genre"))
    if data["sub_genre"] is not None:
        data["genre"].append(data.pop("sub_genre"))
    data["rank"] = dict()
    if data["current_rank"] is not None:
        data["rank"]["currentRank"] = data.pop("current_rank")
    if "rank_indicator" in data and data["rank_indicator"] is not None:
        data["rank"]["rankIndicator"] = data.pop("rank_indicator")
    data["image"] = dict()
    data["image"]["coverImagePath"] = data.pop("coverImagePath")
    data["image"]["adultDefaultcoverImagePath"] = (
        "https://cdn.likenovel.dev/cover/adult_default.webp"
    )
    data["badge"] = dict()
    # data["badge"]["waitForFreeYn"] = data.pop("waitForFreeYn")
    data["badge"]["episodeUploadYn"] = data["hasEpisodeCount"] > 0
    data["badge"]["waitingForFreeYn"] = (
        "Y" if data.get("waitingForFreeStatus") == "ing" else "N"
    )  # 湲곕떎由щ㈃ 臾대즺 ?꾨줈紐⑥뀡 吏꾪뻾 ?щ?
    data["badge"]["sixNinePathYn"] = (
        "Y" if data.get("sixNinePathStatus") == "ing" else "N"
    )  # 6-9 ?⑥뒪 ?꾨줈紐⑥뀡 吏꾪뻾 ?щ?
    # data["badge"]["freeEpisodes"] = data.pop("freeEpisodes") if data.get("freeEpisodes") is not None else 0 # 泥?諛⑸Ц??臾대즺 ?댁슜沅?吏????- n?붾Т ?꾩씠肄??쒖떆 -> ?닿굅 ?ъ슜 ?덊븿
    data["badge"]["newReleaseYn"] = data.pop(
        "newReleaseYn"
    )  # 理쒖떊 ?뚯옄 - UP ?꾩씠肄??쒖떆
    data["badge"]["freeEpisodeTicketCount"] = data.pop("freeEpisodeTicketCount")
    data["badge"]["authorEventLevelBadgeImagePath"] = data.pop(
        "authorEventLevelBadgeImagePath"
    )
    data["badge"]["authorInterestLevelBadgeImagePath"] = data.pop(
        "authorInterestLevelBadgeImagePath"
    )
    data["badge"]["interestFireActiveImagePath"] = (
        "https://cdn.likenovel.dev/badge/fire/on.webp"
    )
    data["badge"]["interestFireFadeImagePath"] = (
        "https://cdn.likenovel.dev/badge/fire/off.webp"
    )
    data["badge"]["interestEndDate"] = data.pop("interestEndDate")
    data["trendindex"] = dict()
    data["trendindex"]["readThroughRate"] = (
        data.pop("readThroughRate") if data.get("readThroughRate") is not None else 0
    )
    data["trendindex"]["readThroughIndicator"] = (
        data.pop("readThroughIndicator")
        if data.get("readThroughIndicator") is not None
        else 0
    )
    data["trendindex"]["cpHitCount"] = data.pop("count_cp_hit")
    data["trendindex"]["cpHitIndicator"] = (
        data.pop("cpHitIndicator") if data.get("cpHitIndicator") is not None else 0
    )
    data["trendindex"]["totalInterestCount"] = data.pop("totalInterestCount")
    data["trendindex"]["totalInterestIndicator"] = (
        data.pop("totalInterestIndicator")
        if data.get("totalInterestIndicator") is not None
        else 0
    )
    data["trendindex"]["interestSustainCount"] = (
        data.pop("interestSustainCount")
        if data.get("interestSustainCount") is not None
        else 0
    )
    data["trendindex"]["interestSustainIndicator"] = (
        data.pop("interestSustainIndicator")
        if data.get("interestSustainIndicator") is not None
        else 0
    )
    data["trendindex"]["interestLossCount"] = (
        data.pop("interestLossCount")
        if data.get("interestLossCount") is not None
        else 0
    )
    data["trendindex"]["interestLossIndicator"] = (
        data.pop("interestLossIndicator")
        if data.get("interestLossIndicator") is not None
        else 0
    )
    data["trendindex"]["hitCount"] = data.pop("count_hit")
    data["trendindex"]["hitIndicator"] = (
        data.pop("hitIndicator") if data.get("hitIndicator") is not None else 0
    )
    data["trendindex"]["recommendCount"] = data.pop("count_recommend")
    data["trendindex"]["recommendIndicator"] = (
        data.pop("recommendIndicator")
        if data.get("recommendIndicator") is not None
        else 0
    )
    # data["trendindex"]["notRecommendCount"] = 0 # 鍮꾩텛泥?湲곕뒫 援ы쁽 ?덈맖
    # data["trendindex"]["notRecommendIndicator"] = 0 # 鍮꾩텛泥?湲곕뒫 援ы쁽 ?덈맖
    data["trendindex"]["bookmarkCount"] = data.pop("count_bookmark")
    data["trendindex"]["bookmarkIndicator"] = (
        data.pop("bookmarkIndicator")
        if data.get("bookmarkIndicator") is not None
        else 0
    )
    data["trendindex"]["hasEpisodeCount"] = data.pop("hasEpisodeCount")
    data["trendindex"]["readedEpisodeCount"] = (
        data.pop("readedEpisodeCount")
        if data.get("readedEpisodeCount") is not None
        else 0
    )
    raw_reader_group = data.pop("primaryReaderGroup", None)
    if raw_reader_group and isinstance(raw_reader_group, str):
        try:
            data["trendindex"]["primaryReaderGroup"] = json.loads(raw_reader_group)
        except (json.JSONDecodeError, TypeError):
            data["trendindex"]["primaryReaderGroup"] = ""
    else:
        data["trendindex"]["primaryReaderGroup"] = raw_reader_group or ""
    data["properties"] = dict()
    data["properties"]["updateFrequency"] = data.pop("publish_days")
    data["properties"]["averageWeeklyEpisodes"] = (
        data.pop("averageWeeklyEpisodes")
        if data.get("averageWeeklyEpisodes") is not None
        else 0
    )
    # data["properties"]["remarkContentSnippet"] = "" # 愿由ъ옄媛 ?낅젰?섎뒗 鍮꾧퀬 ?띿뒪??- 誘멸뎄???곹깭
    data["properties"]["latestEpisodeDate"] = data.pop("last_episode_date")
    data["properties"]["bookmarkYn"] = data.pop("bookmarkYn")
    data["contract"] = dict()
    data["contract"]["monopolyYn"] = data.pop("monopoly_yn")
    data["contract"]["cpContractYn"] = data.pop("contract_yn")
    data["contract"]["advancePayment"] = (
        data.pop("advancePayment") if data.get("advancePayment") is not None else 0
    )
    data["contract"]["totalSales"] = (
        data.pop("totalSales") if data.get("totalSales") is not None else 0
    )
    data["contract"]["offerCount"] = (
        data.pop("offerCount") if data.get("offerCount") is not None else 0
    )
    data["contract"]["offerId"] = (
        str(data.pop("offerId")) if data.get("offerId") is not None else ""
    )
    data["contract"]["offerUserRole"] = "cp"
    data["contract"]["offerDate"] = (
        data.pop("offerDate") if data.get("offerDate") is not None else ""
    )
    data["contract"]["offerAdvancePayment"] = data.pop("offerAdvancePayment")
    data["contract"]["settlementRatioSnippet"] = (
        data.pop("settlementRatioSnippet")
        if data.get("settlementRatioSnippet") is not None
        else ""
    )
    data["contract"]["offerDecisionState"] = (
        data.pop("offerDecisionState")
        if data.get("offerDecisionState") is not None
        else "review"
    )
    data["publishRegularYn"] = data.pop("publish_regular_yn", "Y")
    data["state"] = dict()
    data["state"]["ongoingState"] = data.pop("status_code")
    data["state"]["convertToPaidState"] = (
        data.pop("convertToPaidState")
        if data.get("convertToPaidState") is not None
        else "review"
    )
    data["state"]["canApplyForPaid"] = data.pop("canApplyForPaid") == "Y"
    return data


async def get_user_id(kc_user_id: str, db: AsyncSession):
    query = text("select user_id from tb_user where kc_user_id = :kc_user_id")
    result = await db.execute(query, {"kc_user_id": kc_user_id})
    row = result.mappings().first()
    return int(row.get("user_id")) if row else None


async def save_product_hit_log(product_id: int, db: AsyncSession):
    """
    ?묓뭹 ?쇰퀎 議고쉶??濡쒓렇 ???
    ?ㅻ뒛 ?좎쭨??議고쉶?섎? +1 利앷?
    """
    try:
        query = text("""
            INSERT INTO tb_product_hit_log (product_id, hit_date, hit_count)
            VALUES (:product_id, CURDATE(), 1)
            ON DUPLICATE KEY UPDATE hit_count = hit_count + 1
        """)
        await db.execute(query, {"product_id": product_id})
    except Exception as e:
        error_logger.error(
            f"Failed to save product hit log: product_id={product_id}, error={e}"
        )
        # 濡쒓렇 ????ㅽ뙣??硫붿씤 濡쒖쭅???곹뼢??二쇱? ?딅룄濡??덉쇅瑜?臾댁떆


async def products_of_managed(
    division: str,
    area: str,
    limit: int | None,
    adult_yn: str,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    硫붿씤, ?좊즺Top50, 臾대즺Top50 ?묓뭹 紐⑸줉 議고쉶
    """
    user_id = await get_user_id(kc_user_id, db)

    if limit is None:
        limit = 50

    await statistics_service.insert_site_statistics_log(
        db=db, type="visit", user_id=user_id
    )
    await statistics_service.insert_site_statistics_log(
        db=db, type="page_view", user_id=user_id
    )

    filter_option = []
    filter_option.append('p.open_yn = "Y"')
    # ?깆씤?깃툒 ?꾪꽣留? adult_yn??N?대㈃ ?꾩껜?댁슜媛留?議고쉶
    if adult_yn == "N":
        filter_option.append('p.ratings_code = "all"')
    # if division is not None:
    # TODO: cleaned garbled comment (encoding issue).
    #     filter_option.append(f'division = "{division}"')
    order_by = "p.product_id DESC"
    join_rank = False
    rank_area_code = None
    resolved_area = TOP_MANAGED_AREA_ALIASES.get(area, area)
    if resolved_area in TOP_MANAGED_AREA_RULES:
        rule = TOP_MANAGED_AREA_RULES[resolved_area]
        filter_option.extend(rule["filters"])
        order_by = "pr.current_rank ASC"
        rank_area_code = rule["rank_area_code"]

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=join_rank, rank_area_code=rank_area_code
    )
    query = text(f"""
        SELECT {query_parts["select_fields"]}, "{resolved_area}" as area
        FROM tb_product p
        {query_parts["joins"]}
        {f"WHERE {' AND '.join(filter_option)}" if len(filter_option) > 0 else ""}
        ORDER BY {order_by}
        {f"LIMIT {limit}"}
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    res_body = dict()
    res_data = [convert_product_data(row) for row in rows]

    # 鍮꾧났媛??묓뭹 ?꾪꽣留????쒖쐞 ?ы븷??(freeTop, paidTop??寃쎌슦)
    if join_rank or rank_area_code is not None:
        for idx, item in enumerate(res_data, start=1):
            if "rank" in item:
                item["rank"]["currentRank"] = idx

    res_body["data"] = res_data

    return res_body


async def product_by_product_id(product_id: str, kc_user_id: str, db: AsyncSession):
    """
    ?묓뭹 ?뺣낫 議고쉶
    """
    user_id = await get_user_id(kc_user_id, db)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    query = text(f"""
        SELECT {query_parts["select_fields"]}
        FROM tb_product p
        {query_parts["joins"]}
        WHERE p.product_id = :product_id AND p.open_yn = 'Y'
    """)
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()

    if row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCT,
        )

    res_body = dict()
    res_body["data"] = convert_product_data(row)

    await statistics_service.insert_site_statistics_log(
        db=db, type="visit", user_id=user_id
    )
    await statistics_service.insert_site_statistics_log(
        db=db, type="page_view", user_id=user_id
    )

    return res_body


async def products_all(
    price_type: str,
    product_type: str,
    product_state: str,
    page: int,
    limit: int,
    kc_user_id: str,
    db: AsyncSession,
    genres: list[str] = None,
    adult_yn: str = "N",
):
    """
    ?묓뭹 紐⑸줉 ?꾩껜 議고쉶(?좊즺, 臾대즺)
    """
    page = page if page else settings.PAGINATION_DEFAULT_PAGE_NO
    limit = limit if limit else settings.PAGINATION_PRODUCT_DEFAULT_LIMIT

    # ?꾪꽣 ?듭뀡 ?ㅼ젙
    filter_option = []
    if price_type is not None:
        filter_option.append(f'p.price_type = "{price_type}"')
    if product_type is not None:
        if product_type == "free":
            filter_option.append("p.product_type is null")
        else:
            filter_option.append(f'p.product_type = "{product_type}"')
    if product_state is not None:
        if product_state == "standalone":
            filter_option.append("p.publish_regular_yn = 'N'")
        else:
            filter_option.append(f'p.status_code = "{product_state}"')

    try:
        if genres is not None:
            genre_filter = " OR ".join(
                [
                    f"p.primary_genre_id in (select keyword_id from tb_standard_keyword where keyword_name = '{genre}') or sub_genre_id in (select keyword_id from tb_standard_keyword where keyword_name = '{genre}')"
                    for genre in genres
                ]
            )
            filter_option.append(f"({genre_filter})")
    except Exception as e:
        error_logger.error(f"Error in products_all: {e}")

    user_id = await get_user_id(kc_user_id, db)

    # ?깆씤 ?묓뭹 ?꾪꽣留?
    # adult_yn='Y'?닿퀬 濡쒓렇???곹깭?닿퀬 19???댁긽??寃쎌슦?먮쭔 ?깆씤 ?묓뭹 ?ы븿
    # 洹???紐⑤뱺 寃쎌슦(誘몃줈洹몄씤, 19??誘몃쭔, adult_yn='N')???깆씤 ?묓뭹 ?쒖쇅
    if user_id == -1:
        # 誘몃줈洹몄씤 ?곹깭: ?깆씤 ?묓뭹 ?쒖쇅
        filter_option.append("p.ratings_code = 'all'")
    elif adult_yn != "Y":
        # 濡쒓렇???곹깭?댁?留?adult_yn='N'??寃쎌슦: ?깆씤 ?묓뭹 ?쒖쇅
        filter_option.append("p.ratings_code = 'all'")
    else:
        # adult_yn='Y'??寃쎌슦: ?ъ슜???섏씠 ?뺤씤
        from app.utils.time import get_full_age

        user_query = text("""
            SELECT DATE_FORMAT(birthdate, '%Y-%m-%d') as birthdate
            FROM tb_user
            WHERE user_id = :user_id
        """)
        user_result = await db.execute(user_query, {"user_id": user_id})
        user_row = user_result.mappings().one_or_none()

        if user_row and user_row["birthdate"]:
            user_age = get_full_age(date=user_row["birthdate"])
            if user_age < 19:
                # 19??誘몃쭔: ?깆씤 ?묓뭹 ?쒖쇅
                filter_option.append("p.ratings_code = 'all'")
        # 19???댁긽?닿퀬 adult_yn='Y'??寃쎌슦: ?꾪꽣 異붽? ?덊븿 (?깆씤 ?묓뭹 ?ы븿)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    filter_option.append("p.open_yn = 'Y'")
    query = text(f"""
        SELECT {query_parts["select_fields"]}
        FROM tb_product p
        {query_parts["joins"]}
        WHERE {" and ".join(filter_option)}
        ORDER BY p.last_episode_date DESC, p.product_id DESC
        LIMIT {limit} OFFSET {(page - 1) * limit}
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    res_body = dict()
    res_body["data"] = [convert_product_data(row) for row in rows]

    await statistics_service.insert_site_statistics_log(
        db=db, type="visit", user_id=user_id
    )
    await statistics_service.insert_site_statistics_log(
        db=db, type="page_view", user_id=user_id
    )

    return res_body


async def episodes_by_product_id(
    product_id: str,
    kc_user_id: str,
    page: int,
    limit: int,
    order_by: str,
    order_dir: str,
    db: AsyncSession,
):
    """
    ?묓뭹 - ?먰뵾?뚮뱶 紐⑸줉
    """
    page = page if page else settings.PAGINATION_DEFAULT_PAGE_NO
    limit = limit if limit else settings.PAGINATION_DEFAULT_LIMIT
    order_by = order_by if order_by else "episodeNo"
    order_dir = order_dir if order_dir else settings.PAGINATION_ORDER_DIRECTION_ASC

    user_id = await get_user_id(kc_user_id, db)

    try:
        query = text(f"""
            select
                episode_id as episodeId,
                product_id as productId,
                episode_no as episodeNo,
                episode_title as episodeTitle,
                episode_text_count as episodeTextCount,
                comment_open_yn as commentOpenYn,
                count_evaluation as countEvaluation,
                count_comment as countComment,
                price_type as priceType,
                evaluation_open_yn as evaluationOpenYn,
                publish_reserve_date as publishReserveDate,
                count_hit as countHit,
                count_recommend as countRecommend,
                open_yn as episodeOpenYn,
                (select count(*) from tb_product_episode_like where episode_id = e.episode_id) as countLike,
                created_date as createdDate,
                (select own_type from tb_user_productbook where (
                    episode_id = e.episode_id
                    or
                    (episode_id is null and (product_id = e.product_id or product_id is null))
                ) and user_id = :user_id and use_yn = 'Y'
                and (rental_expired_date IS NULL OR rental_expired_date > NOW())
                order by id desc limit 1) as ownType,
                (
                    select
                        CASE
                            WHEN rental_expired_date IS NULL THEN NULL
                            WHEN rental_expired_date <= NOW() THEN JSON_OBJECT('days', 0, 'hours', 0)
                            ELSE JSON_OBJECT(
                                'days', FLOOR(TIMESTAMPDIFF(SECOND, NOW(), rental_expired_date) / 86400),
                                'hours', FLOOR((TIMESTAMPDIFF(SECOND, NOW(), rental_expired_date) % 86400) / 3600)
                            )
                        END
                    from tb_user_productbook
                    where (
                        episode_id = e.episode_id
                        or
                        (episode_id is null and (product_id = e.product_id or product_id is null))
                    ) and user_id = :user_id and own_type = 'rental' and use_yn = 'Y'
                    order by id desc limit 1
                ) as rentalRemaining
            from tb_product_episode e where product_id = :product_id and e.use_yn = 'Y'
                and (
                    e.open_yn = 'Y'
                    OR EXISTS (
                        select 1 from tb_user_productbook pb
                        where (pb.episode_id = e.episode_id
                               OR (pb.episode_id IS NULL
                                   AND (pb.product_id = e.product_id
                                        OR pb.product_id IS NULL)))
                          AND pb.user_id = :user_id
                          AND pb.use_yn = 'Y'
                          AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                    )
                )
            order by {order_by} {order_dir}
            limit {limit} offset {(page - 1) * limit}
        """)
        result = await db.execute(query, {"user_id": user_id, "product_id": product_id})
        rows = result.mappings().all()
        episodes = [dict(row) for row in rows]

        # rentalRemaining JSON ?뚯떛
        for episode in episodes:
            if episode.get("rentalRemaining"):
                try:
                    episode["rentalRemaining"] = json.loads(episode["rentalRemaining"])
                except (json.JSONDecodeError, TypeError):
                    episode["rentalRemaining"] = None

        query = text("""
            select
                episode_id as episodeId,
                use_yn as readYn,
                recommend_yn as recommendYn
            from tb_user_product_usage where user_id = :user_id and product_id = :product_id
        """)
        result = await db.execute(query, {"user_id": user_id, "product_id": product_id})
        rows = result.mappings().all()
        usage = [dict(row) for row in rows]

        # 洹몃９???뺤뀛?덈━ ?앹꽦
        grouped_results = dict()
        grouped_results["episodes"] = episodes
        grouped_results["usage"] = usage

        # ?꾩껜 ?먰뵾?뚮뱶 媛?닔 議고쉶
        count_query = text("""
            select count(*) as total
            from tb_product_episode e where e.product_id = :product_id and e.use_yn = 'Y'
                and (
                    e.open_yn = 'Y'
                    OR EXISTS (
                        select 1 from tb_user_productbook pb
                        where (pb.episode_id = e.episode_id
                               OR (pb.episode_id IS NULL
                                   AND (pb.product_id = e.product_id
                                        OR pb.product_id IS NULL)))
                          AND pb.user_id = :user_id
                          AND pb.use_yn = 'Y'
                          AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                    )
                )
        """)
        count_result = await db.execute(count_query, {"product_id": product_id, "user_id": user_id})
        episodeTotalCount = count_result.scalar()

        # ?ъ슜???쎌? 理쒖쥌 ?뚯감
        max_episode_no = 0
        max_episode_id = 0
        max_episode_title = ""
        min_episode_id = min(
            (hit.get("episodeId", 0) for hit in grouped_results["episodes"])
            if grouped_results["episodes"]
            else [0]
        )

        # 최근 읽은 에피소드 중 공개 또는 소유/대여 회차를 이어보기 대상으로 선정
        if grouped_results["usage"]:
            latest_read_query = text("""
                select u.episode_id as episodeId, e.episode_no as episodeNo, e.episode_title as episodeTitle
                from tb_user_product_usage u
                join tb_product_episode e on u.episode_id = e.episode_id
                where u.user_id = :user_id
                  and u.product_id = :product_id
                  and e.use_yn = 'Y'
                  and (
                    e.open_yn = 'Y'
                    OR EXISTS (
                      select 1 from tb_user_productbook pb
                      where (pb.episode_id = e.episode_id
                             OR (pb.episode_id IS NULL
                                 AND (pb.product_id = e.product_id
                                      OR pb.product_id IS NULL)))
                        AND pb.user_id = :user_id
                        AND pb.use_yn = 'Y'
                        AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                    )
                  )
                order by u.episode_id desc
                limit 1
            """)
            latest_read_result = await db.execute(
                latest_read_query, {"user_id": user_id, "product_id": product_id}
            )
            latest_read_row = latest_read_result.mappings().first()
            if latest_read_row:
                max_episode_id = latest_read_row["episodeId"]
                max_episode_no = latest_read_row["episodeNo"]
                max_episode_title = latest_read_row.get("episodeTitle", "")

        # usage ?곗씠?곗쓽 episodeId媛 episodes?먮룄 議댁옱?섎뒗吏 ?뺤씤
        combined_new_episodes = []
        if user_id and "usage" in grouped_results and "episodes" in grouped_results:
            for episode in grouped_results["episodes"]:
                for usage in grouped_results["usage"]:
                    # ?쎌쓬?щ?, 異붿쿇?щ?
                    if usage.get("episodeId", 0) == episode.get("episodeId", -1):
                        # ?쇱튂?섎뒗 ?먰뵾?뚮뱶 ?뺣낫???ъ슜 ?뺣낫 異붽? (?쎌쓬?щ?, 異붿쿇?щ?)
                        episode["usage"] = {
                            "readYn": usage.get("readYn", "N"),
                            "recommendYn": usage.get("recommendYn", "N"),
                        }

                combined_new_episodes.append(episode)
        else:
            # for episode in grouped_results["episodes"]:
            #     if episode.get("episodeNo", 1) == 1:
            #         max_episode_id = episode.get("episodeId", "")

            combined_new_episodes = grouped_results["episodes"]

        for episode in combined_new_episodes:
            if "usage" not in episode:
                # usage ?뺣낫媛 ?녿뒗 寃쎌슦 -> ?쎌??곸씠 ?놁뼱??洹몃윴嫄곕땲 ????N?쇰줈 ?명똿
                episode["usage"] = {"readYn": "N", "recommendYn": "N"}

        if max_episode_id == 0:
            max_episode_id = min_episode_id

        res_body = dict()
        res_body["data"] = {
            "latestEpisodeNo": max_episode_no,
            "latestEpisodeId": max_episode_id,
            "latestEpisodeTitle": max_episode_title,
            "episodes": combined_new_episodes,
            "pagination": {
                "totalCount": episodeTotalCount,
                "page": page,
                "limit": limit,
            },
        }

        return res_body

    except Exception as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


async def product_details_group_by_product_id(
    product_id: str, kc_user_id: str, db: AsyncSession
):
    """
    ?묓뭹 ?곸꽭 洹몃９ - ?묓뭹 ?곸꽭, ?묓뭹 ?됯?, ?묓뭹 怨듭?, ?먰뵾?뚮뱶 紐⑸줉??臾띠뼱???묐떟

    NOTE: ?묎?媛 ?먯떊???묓뭹??議고쉶???뚮뒗 鍮꾧났媛??묓뭹??議고쉶 媛?ν빐????(?묓뭹 ?섏젙???꾪빐)
    """
    try:
        user_id = await get_user_id(kc_user_id, db)
        current_user_role = await _resolve_current_user_role(kc_user_id, db)

        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        product_visibility_condition = (
            "1=1"
            if current_user_role == "admin"
            else "(p.open_yn = 'Y' OR p.user_id = :user_id OR p.author_id = :user_id)"
        )
        # ?묎?媛 ?먯떊???묓뭹??議고쉶?섎뒗 寃쎌슦 鍮꾧났媛??묓뭹??議고쉶 媛??
        # ?ㅻⅨ ?ъ슜?먮뒗 怨듦컻???묓뭹留?議고쉶 媛??
        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE p.product_id = :product_id
              AND {product_visibility_condition}
        """)
        result = await db.execute(query, {"product_id": product_id, "user_id": user_id})
        rows = result.mappings().all()
        product = convert_product_data(rows[0]) if rows else None

        # 작품이 존재하지만 비공개인 경우 조기 반환
        if product is None:
            private_check_query = text("""
                select product_id, open_yn
                from tb_product
                where product_id = :product_id
            """)
            private_check_result = await db.execute(private_check_query, {"product_id": product_id})
            private_check_row = private_check_result.mappings().first()
            if private_check_row and private_check_row.get("open_yn") == "N":
                return {
                    "data": {
                        "product": {"privateYn": "Y"},
                        "episodes": [],
                        "evaluations": {},
                        "notices": [],
                        "comments": [],
                        "issuedVouchers": [],
                    }
                }

        # 濡쒓렇?명븳 ?ъ슜?먯씤 寃쎌슦 ownType 議고쉶瑜??꾪빐 user_id ?꾨떖
        episode_query_params = {"product_id": product_id}
        own_type_query = ""
        if user_id and user_id != -1:
            episode_query_params["user_id"] = user_id
            own_type_query = """
                , (select own_type from tb_user_productbook where (
                    episode_id = e.episode_id
                    or
                    (episode_id is null and (product_id = e.product_id or product_id is null))
                ) and user_id = :user_id and use_yn = 'Y'
                and (rental_expired_date IS NULL OR rental_expired_date > NOW())
                order by id desc limit 1) as ownType
            """

        # NOTE:
        # ?쇰? ?섍꼍(dev RDS ???먮뒗 tb_product_episode_apply 留덉씠洹몃젅?댁뀡???꾩쭅 諛섏쁺?섏? ?딆븘
        # details-group 議고쉶 ??500??諛쒖깮?????덈떎. ?뚯씠釉?議댁옱 ?щ????곕씪 reviewYn 怨꾩궛?앹쓣 遺꾧린?쒕떎.
        review_yn_query = "'N' as reviewYn"
        episode_version_query = "1 as episodeVersion"
        latest_apply_id_query = "NULL as latestApplyId"
        latest_apply_status_query = "NULL as latestApplyStatus"
        latest_apply_join_query = ""
        table_exists_query = text("""
            select 1
            from information_schema.tables
            where table_schema = database()
              and table_name = 'tb_product_episode_apply'
            limit 1
        """)
        table_exists_result = await db.execute(table_exists_query)
        has_episode_apply_table = table_exists_result.scalar() is not None
        if has_episode_apply_table:
            latest_apply_id_query = "pea_latest.latest_apply_id as latestApplyId"
            latest_apply_status_query = "pea_latest.latest_apply_status as latestApplyStatus"
            episode_version_query = """
                case
                    when ifnull(pea_accepted.accepted_count, 0) < 1 then 1
                    else pea_accepted.accepted_count
                end as episodeVersion
            """
            review_yn_query = """
                case
                    when pea_latest.latest_apply_status = 'review' then 'Y'
                    else 'N'
                end as reviewYn
            """
            latest_apply_join_query = """
                left join (
                    select
                        pea.episode_id,
                        pea.id as latest_apply_id,
                        pea.status_code as latest_apply_status
                    from tb_product_episode_apply pea
                    inner join (
                        select
                            episode_id,
                            max(id) as max_id
                        from tb_product_episode_apply
                        where use_yn = 'Y'
                        group by episode_id
                    ) pea_max
                      on pea_max.episode_id = pea.episode_id
                     and pea_max.max_id = pea.id
                    where pea.use_yn = 'Y'
                ) pea_latest
                  on pea_latest.episode_id = e.episode_id
                left join (
                    select
                        episode_id,
                        count(*) as accepted_count
                    from tb_product_episode_apply
                    where use_yn = 'Y'
                      and status_code = 'accepted'
                    group by episode_id
                ) pea_accepted
                  on pea_accepted.episode_id = e.episode_id
            """

        query = text(f"""
            select
                e.episode_id as episodeId,
                e.product_id as productId,
                e.episode_no as episodeNo,
                e.episode_title as episodeTitle,
                e.episode_text_count as episodeTextCount,
                e.comment_open_yn as commentOpenYn,
                e.count_evaluation as countEvaluation,
                COALESCE((
                    select count_evaluation_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countEvaluationIndicator,
                e.count_comment as countComment,
                COALESCE((
                    select count_comment_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countCommentIndicator,
                e.price_type as priceType,
                e.evaluation_open_yn as evaluationOpenYn,
                e.publish_reserve_date as publishReserveDate,
                e.count_hit as countHit,
                COALESCE((
                    select count_hit_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countHitIndicator,
                e.count_recommend as countRecommend,
                COALESCE((
                    select count_recommend_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countRecommendIndicator,
                (
                    select cfi.file_org_name
                    from tb_common_file cf
                    inner join tb_common_file_item cfi
                       on cfi.file_group_id = cf.file_group_id
                      and cfi.use_yn = 'Y'
                    where cf.use_yn = 'Y'
                      and cf.group_type = 'epub'
                      and cf.file_group_id = e.epub_file_id
                    limit 1
                ) as epubFileName,
                e.open_yn as episodeOpenYn,
                e.open_yn as openYn,
                e.use_yn as useYn,
                {episode_version_query},
                {latest_apply_id_query},
                {latest_apply_status_query},
                {review_yn_query},
                (select count(*) from tb_product_episode_like where episode_id = e.episode_id) as countLike,
                COALESCE((
                    select count(*) - count(*) +
                           (select count(*) from tb_product_episode_like where episode_id = e.episode_id) -
                           (select count(*) from tb_product_episode_like where episode_id = e.episode_id
                            and DATE(created_date) <= CURDATE() - INTERVAL 1 DAY)
                    from dual
                ), 0) as countLikeIndicator,
                e.created_date as createdDate
                {own_type_query}
            from tb_product_episode e
            {latest_apply_join_query}
            where e.product_id = :product_id and e.use_yn = 'Y'
        """)
        result = await db.execute(query, episode_query_params)
        rows = result.mappings().all()
        episodes = [dict(row) for row in rows]

        query = text("""
            select
                episode_id as episodeId,
                use_yn as readYn,
                recommend_yn as recommendYn
            from tb_user_product_usage where user_id = :user_id
        """)
        result = await db.execute(query, {"user_id": user_id})
        rows = result.mappings().all()
        useage = [dict(row) for row in rows]

        if user_id:
            combined_new_episodes = []
            for episode in episodes:
                for usage in useage:
                    # ?쎌쓬?щ?, 異붿쿇?щ?
                    if usage.get("episodeId", 0) == episode.get("episodeId", -1):
                        # ?쇱튂?섎뒗 ?먰뵾?뚮뱶 ?뺣낫???ъ슜 ?뺣낫 異붽? (?쎌쓬?щ?, 異붿쿇?щ?)
                        episode["usage"] = {
                            "readYn": usage.get("readYn", "N"),
                            "recommendYn": usage.get("recommendYn", "N"),
                        }

                combined_new_episodes.append(episode)
            episodes = combined_new_episodes

        query = text("""
            select *
            from tb_product_evaluation where product_id = :product_id
        """)
        result = await db.execute(query, {"product_id": product_id})
        rows = result.mappings().all()
        evaluations = [dict(row) for row in rows]

        query = text("""
            select *
            from tb_product_notice
            where product_id = :product_id
              and use_yn = 'Y'
              and open_yn = 'Y'
        """)
        result = await db.execute(query, {"product_id": product_id})
        rows = result.mappings().all()
        notices = [dict(row) for row in rows]

        query = text("""
            select *
            from tb_product_comment
            where product_id = :product_id
              and use_yn = 'Y'
              and open_yn = 'Y'
        """)
        result = await db.execute(query, {"product_id": product_id})
        rows = result.mappings().all()
        comments = [dict(row) for row in rows]

        grouped_results = dict()
        grouped_results["product"] = product
        grouped_results["episodes"] = episodes
        grouped_results["evaluations"] = _count_evaluations(evaluations)
        grouped_results["notices"] = notices
        grouped_results["comments"] = comments

        # ?덈줈 吏湲됰맂 ??ш텒 ?뚮┝ ?뺣낫
        issued_vouchers = []

        # 泥?諛⑸Ц??臾대즺 ?댁슜沅??먮룞 諛쒓툒 (free-for-first) -> ?좊Ъ?⑥쑝濡?吏湲?
        if user_id and user_id != -1:
            # ???묓뭹???댁쟾??諛⑸Ц???곸씠 ?덈뒗吏 泥댄겕 (tb_user_product_usage??湲곕줉???덈뒗吏)
            query = text("""
                select count(*) as visit_count
                  from tb_user_product_usage
                 where user_id = :user_id
                   and product_id = :product_id
            """)
            result = await db.execute(
                query, {"user_id": user_id, "product_id": product_id}
            )
            visit_count = result.scalar()

            query = text("""
                select dp.id, dp.num_of_ticket_per_person, dp.type
                  from tb_direct_promotion dp
                 where dp.product_id = :product_id
                   and dp.type in ('free-for-first', 'admin-gift')
                   and dp.status = 'ing'
                   and DATE(dp.start_date) <= CURDATE()
                   and (dp.end_date IS NULL OR DATE(dp.end_date) >= CURDATE())
            """)
            result = await db.execute(query, {"product_id": product_id})
            promotions = result.mappings().all()

            for promotion in promotions:
                promo_type = promotion["type"]
                if promo_type == "free-for-first" and visit_count != 0:
                    continue

                query = text("""
                    select count(*) as already_received
                      from tb_user_giftbook
                     where user_id = :user_id
                       and acquisition_type = 'direct_promotion'
                       and acquisition_id = :promotion_id
                """)
                result = await db.execute(
                    query, {"user_id": user_id, "promotion_id": promotion["id"]}
                )
                already_received = result.scalar()

                if already_received == 0:
                    num_of_ticket = promotion["num_of_ticket_per_person"]
                    reason = (
                        "관리자 지급 대여권" if promo_type == "admin-gift" else "첫방문자 무료 대여권"
                    )
                    message = (
                        f"관리자 지급 대여권 {num_of_ticket}장이 지급되었습니다"
                        if promo_type == "admin-gift"
                        else f"첫방문자 무료 대여권 {num_of_ticket}장이 지급되었습니다"
                    )
                    giftbook_req = user_giftbook_schema.PostUserGiftbookReqBody(
                        user_id=user_id,
                        product_id=product_id,
                        episode_id=None,
                        ticket_type="paid" if promo_type == "admin-gift" else promo_type,
                        own_type="rental",
                        acquisition_type="direct_promotion",
                        acquisition_id=promotion["id"],
                        reason=reason,
                        amount=num_of_ticket,
                        promotion_type=promo_type,
                        expiration_date=None,
                        ticket_expiration_type="days",
                        ticket_expiration_value=7,
                    )
                    await user_giftbook_service.post_user_giftbook(
                        req_body=giftbook_req,
                        kc_user_id="",
                        db=db,
                        user_id=user_id,
                    )
                    issued_vouchers.append(
                        {
                            "type": promo_type,
                            "amount": num_of_ticket,
                            "message": message,
                        }
                    )

        # 6-9 ?⑥뒪 ?먮룞 諛쒓툒 -> ?좊Ъ?⑥쑝濡?吏湲?
        if user_id and user_id != -1:
            # ?꾩옱 ?쒓컙 ?뺤씤 (6-9???먮뒗 18-21?? - KST 湲곗?
            from zoneinfo import ZoneInfo

            kst_now = datetime.now(ZoneInfo("Asia/Seoul"))
            current_hour = kst_now.hour
            if (6 <= current_hour < 9) or (18 <= current_hour < 21):
                # 吏꾪뻾以묒씤 6-9-path ?꾨줈紐⑥뀡 議고쉶
                query = text("""
                    select ap.id, ap.product_id, ap.type
                      from tb_applied_promotion ap
                     where ap.product_id = :product_id
                       and ap.type = '6-9-path'
                       and ap.status = 'ing'
                       and DATE(ap.start_date) <= CURDATE()
                       and (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
                """)
                result = await db.execute(query, {"product_id": product_id})
                sixnine_promotion = result.mappings().one_or_none()

                if sixnine_promotion:
                    # ?ㅻ뒛 ?대? ?좊Ъ?⑥뿉 諛쏆븯?붿? 泥댄겕
                    query = text("""
                        select count(*) as received_today
                          from tb_user_giftbook
                         where user_id = :user_id
                           and acquisition_type = 'applied_promotion'
                           and acquisition_id = :promotion_id
                           and DATE(created_date) = CURDATE()
                    """)
                    result = await db.execute(
                        query,
                        {"user_id": user_id, "promotion_id": sixnine_promotion["id"]},
                    )
                    received_today = result.scalar()

                    # ?ㅻ뒛 ?꾩쭅 諛쏆? ?딆븯?쇰㈃ ?좊Ъ?⑥쑝濡?諛쒓툒
                    if received_today == 0:
                        # 6-9?⑥뒪: ?좏슚湲곌컙 ?섎（ (?섎졊 ?쒖젏遺??
                        giftbook_req = user_giftbook_schema.PostUserGiftbookReqBody(
                            user_id=user_id,
                            product_id=product_id,
                            episode_id=None,
                            ticket_type=sixnine_promotion["type"],
                            own_type="rental",
                            acquisition_type="applied_promotion",
                            acquisition_id=sixnine_promotion["id"],
                            reason="6-9패스 대여권",
                            amount=1,
                            promotion_type="6-9-path",
                            expiration_date=None,  # ?좊Ъ???좏슚湲곌컙 ?놁쓬
                            ticket_expiration_type="on_receive_days",  # ?섎졊 ?쒖젏遺??N??
                            ticket_expiration_value=1,  # ?섎（
                        )
                        await user_giftbook_service.post_user_giftbook(
                            req_body=giftbook_req,
                            kc_user_id="",
                            db=db,
                            user_id=user_id,
                        )
                        # ?뚮┝ ?뺣낫 異붽?
                        issued_vouchers.append(
                            {
                                "type": "6-9-path",
                                "amount": 1,
                                "message": f"6-9패스 대여권 {giftbook_req.amount}장이 지급되었습니다",
                            }
                        )

        # 湲곕떎由щ㈃ 臾대즺 (waiting-for-free) 理쒖큹 1媛??먮룞 諛쒓툒 -> ?좊Ъ?⑥쑝濡?吏湲?
        if user_id and user_id != -1:
            # 吏꾪뻾以묒씤 waiting-for-free ?꾨줈紐⑥뀡 議고쉶
            query = text("""
                select ap.id, ap.product_id, ap.type
                  from tb_applied_promotion ap
                 where ap.product_id = :product_id
                   and ap.type = 'waiting-for-free'
                   and ap.status = 'ing'
                   and DATE(ap.start_date) <= CURDATE()
                   and (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
            """)
            result = await db.execute(query, {"product_id": product_id})
            waiting_promotion = result.mappings().one_or_none()

            if waiting_promotion:
                # ?대? ???꾨줈紐⑥뀡?쇰줈 ?좊Ъ?⑥뿉 諛쏆븯?붿? 泥댄겕
                query = text("""
                    select count(*) as already_received
                      from tb_user_giftbook
                     where user_id = :user_id
                       and acquisition_type = 'applied_promotion'
                       and acquisition_id = :promotion_id
                """)
                result = await db.execute(
                    query,
                    {"user_id": user_id, "promotion_id": waiting_promotion["id"]},
                )
                already_received = result.scalar()

                # ?꾩쭅 諛쏆? ?딆븯?쇰㈃ ?좊Ъ?⑥쑝濡?1媛?諛쒓툒
                if already_received == 0:
                    # 湲곕떎由щ㈃ 臾대즺: ?좏슚湲곌컙 ?놁쓬
                    giftbook_req = user_giftbook_schema.PostUserGiftbookReqBody(
                        user_id=user_id,
                        product_id=product_id,
                        episode_id=None,
                        ticket_type=waiting_promotion["type"],
                        own_type="rental",
                        acquisition_type="applied_promotion",
                        acquisition_id=waiting_promotion["id"],
                        reason="기다리면 무료 대여권",
                        amount=1,
                        promotion_type="waiting-for-free",
                        expiration_date=None,  # ?좊Ъ???좏슚湲곌컙 ?놁쓬
                        ticket_expiration_type="none",  # ?섎졊 ????ш텒 ?좏슚湲곌컙 ?놁쓬
                        ticket_expiration_value=None,
                    )
                    await user_giftbook_service.post_user_giftbook(
                        req_body=giftbook_req,
                        kc_user_id="",
                        db=db,
                        user_id=user_id,
                    )
                    # ?뚮┝ ?뺣낫 異붽?
                    issued_vouchers.append(
                        {
                            "type": "waiting-for-free",
                            "amount": 1,
                            "message": f"기다리면 무료 대여권 {giftbook_req.amount}장이 지급되었습니다",
                        }
                    )

        # 吏湲됰맂 ??ш텒 ?뚮┝ ?뺣낫瑜??묐떟??異붽?
        # 선작독자 대여권 자동 받기 (미수령 건이 있으면 상세 페이지 진입 시 처리)
        if user_id and user_id != -1:
            unreceived_query = text("""
                SELECT id, amount
                  FROM tb_user_giftbook
                 WHERE user_id = :user_id
                   AND product_id = :product_id
                   AND promotion_type = 'reader-of-prev'
                   AND received_yn = 'N'
                   AND (expiration_date IS NULL OR expiration_date > NOW())
            """)
            unreceived_result = await db.execute(
                unreceived_query, {"user_id": user_id, "product_id": product_id}
            )
            unreceived_gifts = unreceived_result.mappings().all()

            for gift in unreceived_gifts:
                try:
                    await user_giftbook_service.receive_user_giftbook(
                        giftbook_id=gift["id"],
                        kc_user_id=kc_user_id,
                        db=db,
                    )
                    issued_vouchers.append(
                        {
                            "type": "reader-of-prev",
                            "amount": gift["amount"],
                            "message": f"선작독자 무료 대여권 {gift['amount']}장이 지급되었습니다",
                        }
                    )
                except Exception as e:
                    logger.error(f"Failed to auto-receive reader-of-prev gift: {e}")

        grouped_results["issuedVouchers"] = issued_vouchers

        res_body = dict()
        res_body["data"] = grouped_results

        await statistics_service.insert_site_statistics_log(
            db=db, type="visit", user_id=user_id
        )
        await statistics_service.insert_site_statistics_log(
            db=db, type="page_view", user_id=user_id
        )

        return res_body

    except Exception:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.INTERNAL_SERVER_ERROR,
        )


async def product_evaluations_by_id(
    db: AsyncSession,
    product_id: str = None,
    episode_id: str = None,
    author_id: str = None,
):
    """
    ?묓뭹 ?됯? 議고쉶
    """

    try:
        # ?꾪꽣 ?듭뀡 ?ㅼ젙
        filter_option = []
        if product_id is not None:
            filter_option.append(f'eval.product_id = "{product_id}"')
        if author_id is not None:
            filter_option.append(f'prod.author_id = "{author_id}"')
        if episode_id is not None:
            filter_option.append(f'eval.episode_id = "{episode_id}"')

        query = text(f"""
            select eval.*
            from tb_product_evaluation eval
            inner join tb_product prod on prod.product_id = eval.product_id
            where {" and ".join(filter_option)}
        """)
        result = await db.execute(query, {})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = _count_evaluations([dict(row) for row in rows])

        return res_body

    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def suggest_products_by_product_id(
    product_id: str, nearby: str, kc_user_id: str, db: AsyncSession
):
    """
    ?묓뭹 ?곸꽭 - 異붿쿇?묓뭹 議고쉶
    """

    try:
        # ?꾪꽣 ?듭뀡 ?ㅼ젙
        filter_option = [f'product_id = "{product_id}"']
        if nearby is not None:
            filter_option.append(f'type = "{nearby}"')

        query = text(f"""
            select similar_subject_ids
            from tb_algorithm_recommend_similar
            where {" and ".join(filter_option)}
        """)
        result = await db.execute(query, {})
        row = result.mappings().first()

        if row is None:
            res_body = dict()
            res_body["data"] = []
            return res_body

        raw_ids = dict(row).get("similar_subject_ids")
        if not raw_ids or not raw_ids.strip():
            return {"data": []}

        suggested_results = json.loads(raw_ids)

        if len(suggested_results) > 0:
            # ?꾪꽣 ?듭뀡 ?ㅼ젙
            filter_option = (
                (
                    f"p.product_id IN ({','.join(map(str, suggested_results))}) AND p.open_yn = 'Y'"
                )
                if len(suggested_results) > 1
                else f"p.product_id = {suggested_results[0]} AND p.open_yn = 'Y'"
            )

            user_id = await get_user_id(kc_user_id, db)

            query_parts = get_select_fields_and_joins_for_product(
                user_id=user_id, join_rank=False
            )
            query = text(f"""
                SELECT {query_parts["select_fields"]}
                FROM tb_product p
                {query_parts["joins"]}
                WHERE {filter_option}
            """)
            result = await db.execute(query, {})
            rows = result.mappings().all()

            res_body = dict()
            res_body["data"] = [convert_product_data(row) for row in rows]
            return res_body
        else:
            res_body = dict()
            res_body["data"] = []
            return res_body

    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except (json.JSONDecodeError, ValueError, TypeError):
        return {"data": []}


async def suggest_managed_products(
    db: AsyncSession, kc_user_id: str | None = None, adult_yn: str = "N"
):
    """
    硫붿씤 - 異붿쿇?묓뭹 議고쉶

    tb_algorithm_recommend_section ?먯꽌
    濡쒓렇???곹깭???곕씪
    泥ル쾲吏??ㅻ쾲吏??뱀뀡 鍮꾨줈洹몄씤(2,3,4,5)
    泥ル쾲吏??ㅻ쾲吏??뱀뀡 濡쒓렇??6,7,8,9)
    ???대떦?섎뒗 feature瑜?媛?몄???
    tb_algorithm_recommend_set_topic ?먯꽌 feature媛 ?쇱튂?섎뒗 ??ぉ?ㅼ쓣 媛?몄삩??
    """

    try:
        # ?ъ슜?먮퀎 feature 媛믪쓣 議고쉶?섏뿬 ?꾪꽣留?
        user_features = {}  # feature紐?-> target 踰덊샇 留ㅽ븨
        section_features = []  # 異붿쿇 ?뱀뀡??feature 紐⑸줉 (?쒖꽌?濡?

        if kc_user_id is not None:
            # 濡쒓렇???좎?: ?ъ슜?먮퀎 feature 議고쉶
            user_id = await get_user_id(kc_user_id, db)

            # ?ъ슜?먯쓽 feature 媛?議고쉶
            query = text("""
                SELECT feature_1, feature_2, feature_3, feature_4, feature_5,
                       feature_6, feature_7, feature_8, feature_9, feature_10, feature_basic
                FROM tb_algorithm_recommend_user
                WHERE user_id = :user_id
                ORDER BY updated_date DESC, id DESC
                LIMIT 1
            """)
            result = await db.execute(query, {"user_id": user_id})
            user_feature_row = result.mappings().first()

            if user_feature_row:
                # ?ъ슜?먯쓽 feature 媛믪씠 ?덈뒗 寃쎌슦
                user_feature_data = dict(user_feature_row)

                # feature_1~10, feature_basic源뚯? 留ㅽ븨 ???
                for i in range(1, 11):
                    feature_key = f"feature_{i}"
                    target_value = user_feature_data.get(feature_key)
                    if target_value is not None and target_value != 0:
                        user_features[feature_key] = target_value

                # feature_basic??留ㅽ븨 (male, female ??
                feature_basic_value = user_feature_data.get("feature_basic")
                if feature_basic_value:
                    user_features["feature_basic"] = feature_basic_value

                # 濡쒓렇????異붿쿇 ?뱀뀡 (id 6,7,8,9) 議고쉶
                query = text("""
                    SELECT feature FROM tb_algorithm_recommend_section
                    WHERE id IN (6, 7, 8, 9)
                    ORDER BY id
                """)
                result = await db.execute(query, {})
                rows = result.mappings().all()
                section_features = [dict(row).get("feature") for row in rows]
            else:
                # ?ъ슜?먯쓽 feature 媛믪씠 ?녿뒗 寃쎌슦: 鍮꾨줈洹몄씤怨??숈씪
                query = text("""
                    SELECT feature FROM tb_algorithm_recommend_section
                    WHERE id IN (2, 3, 4, 5)
                    ORDER BY id
                """)
                result = await db.execute(query, {})
                rows = result.mappings().all()
                section_features = [dict(row).get("feature") for row in rows]
        else:
            # 鍮꾨줈洹몄씤: default ?뱀뀡留?(id 2,3,4,5)
            query = text("""
                SELECT feature FROM tb_algorithm_recommend_section
                WHERE id IN (2, 3, 4, 5)
                ORDER BY id
            """)
            result = await db.execute(query, {})
            rows = result.mappings().all()
            section_features = [dict(row).get("feature") for row in rows]

        # 寃??寃곌낵
        suggested_results = []
        section_mapping = {
            "default_1": 1,
            "default_2": 2,
            "default_3": 3,
            "default_4": 4,
            "feature_1": 5,
            "feature_2": 6,
            "feature_3": 7,
            "feature_4": 8,
            "feature_basic": 9,
        }

        # 媛??뱀뀡蹂꾨줈 ?뺥솗??1媛쒖뵫留?媛?몄삤湲?
        for feature_name in section_features:
            if not feature_name:
                continue

            # default??寃쎌슦 target ?놁씠 議고쉶
            if feature_name.startswith("default_"):
                query = text("""
                    SELECT *
                    FROM tb_algorithm_recommend_set_topic
                    WHERE feature = :feature
                    LIMIT 1
                """)
                result = await db.execute(query, {"feature": feature_name})
                hit = result.mappings().one_or_none()
            # feature??寃쎌슦 ?ъ슜?먯쓽 target怨?留ㅼ묶
            else:
                # ?ъ슜?먯쓽 ?대떦 feature target 媛??뺤씤
                target_value = user_features.get(feature_name)

                if target_value is None:
                    # ?ъ슜?먯뿉寃??좊떦??feature媛 ?놁쑝硫?湲곕낯媛?1 ?ъ슜
                    target_value = 1

                # feature? target???쇱튂?섎뒗 ?덉퐫??議고쉶
                query = text("""
                    SELECT *
                    FROM tb_algorithm_recommend_set_topic
                    WHERE feature = :feature AND target = :target
                    LIMIT 1
                """)
                result = await db.execute(
                    query, {"feature": feature_name, "target": target_value}
                )
                hit = result.mappings().one_or_none()

            if hit:
                hit = dict(hit)
                section_no = section_mapping.get(feature_name)
                if section_no:
                    novel_list = json.loads(hit["novel_list"])
                    if len(novel_list) == 0:
                        products = []
                    else:
                        user_id = (
                            await get_user_id(kc_user_id, db) if kc_user_id else None
                        )

                        query_parts = get_select_fields_and_joins_for_product(
                            user_id=user_id, join_rank=False
                        )
                        adult_filter = (
                            "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
                        )
                        query = text(f"""
                            SELECT {query_parts["select_fields"]}
                            FROM tb_product p
                            {query_parts["joins"]}
                            WHERE p.product_id in ({",".join([str(product_id) for product_id in novel_list])}) AND p.open_yn = 'Y' {adult_filter}
                        """)
                        result = await db.execute(query, {})
                        rows = result.mappings().all()
                        products = [convert_product_data(row) for row in rows]

                    suggested_results.append(
                        {
                            "sectionData": {
                                "products": products,
                                "suggestId": hit["id"],
                                "suggestName": hit["feature"],
                                "suggestTarget": hit["target"],
                                "suggestTitle": hit["title"],
                            },
                            "sectionNo": section_no,
                        }
                    )

        res_body = dict()
        res_body["data"] = suggested_results

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def other_products_of_author(
    kc_user_id: str,
    author_id: int,
    author_nickname: str,
    price_type: str,
    adult_yn: str,
    exclude_product_id: str,
    page: int,
    limit: int,
    order_by: str,
    order_dir: str,
    db: AsyncSession,
):
    """
    ?묎????ㅻⅨ ?묓뭹 紐⑸줉
    """
    page = page if page else settings.PAGINATION_DEFAULT_PAGE_NO
    limit = limit if limit else settings.PAGINATION_DEFAULT_LIMIT
    order_by = order_by if order_by else "createdDate"
    order_dir = order_dir if order_dir else settings.PAGINATION_ORDER_DIRECTION_DESC

    try:
        # ?꾪꽣 ?듭뀡 ?ㅼ젙
        filter_option = [f'p.author_id = "{author_id}"']
        if author_nickname is not None:
            filter_option.append(f'p.author_name = "{author_nickname}"')
        if price_type is not None:
            filter_option.append(f'p.price_type = "{price_type}"')
        if adult_yn is not None:
            # adult_yn='Y': ?꾩껜 議고쉶 (?깆씤 ?ы븿), adult_yn='N': ?깆씤 ?쒖쇅 (all留?
            if adult_yn == "N":
                filter_option.append('p.ratings_code = "all"')
            # adult_yn='Y'??寃쎌슦 ?꾪꽣 異붽? ?덊븿 (?꾩껜 議고쉶)
        if exclude_product_id is not None:
            filter_option.append(f'p.product_id != "{exclude_product_id}"')

        user_id = await get_user_id(kc_user_id, db)

        filter_option.append("p.open_yn = 'Y'")
        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE {" and ".join(filter_option)}
            ORDER BY {order_by} {order_dir}
            LIMIT {limit} OFFSET {(page - 1) * limit}
        """)
        result = await db.execute(query, {})
        rows = result.mappings().all()

        res_body = dict()
        res_body["data"] = {
            "products": [convert_product_data(row) for row in rows]
            # , "pagination":{"totalCount":results['total'], "page":page, "limit":limit}
        }

        return res_body

    except SQLAlchemyError as e:
        logger.error(e)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def get_products_cover_upload_file_name(
    file_name: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            # ?쒕뜡 ?앹꽦 uuid 以묐났 泥댄겕
            while True:
                file_name_to_uuid = comm_service.make_rand_uuid()
                file_name_to_uuid = f"{file_name_to_uuid}.webp"

                query = text("""
                                    select a.file_group_id
                                    from tb_common_file a
                                    inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                    and b.use_yn = 'Y'
                                    and b.file_name = :file_name
                                    where a.group_type = 'cover'
                                    and a.use_yn = 'Y'
                                """)

                result = await db.execute(query, {"file_name": file_name_to_uuid})
                db_rst = result.mappings().all()

                if not db_rst:
                    break

            presigned_url = comm_service.make_r2_presigned_url(
                type="upload",
                bucket_name=settings.R2_SC_IMAGE_BUCKET,
                file_id=f"cover/{file_name_to_uuid}",
            )

            query = text("""
                                insert into tb_common_file (group_type, created_id, updated_id)
                                values (:group_type, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "group_type": "cover",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            query = text("""
                                select last_insert_id()
                                """)

            result = await db.execute(query)
            new_file_group_id = result.scalar()

            query = text("""
                                insert into tb_common_file_item (file_group_id, file_name, file_org_name, file_path, created_id, updated_id)
                                values (:file_group_id, :file_name, :file_org_name, :file_path, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "file_group_id": new_file_group_id,
                    "file_name": file_name_to_uuid,
                    "file_org_name": file_name,
                    "file_path": f"{settings.R2_SC_CDN_URL}/cover/{file_name_to_uuid}",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            res_data = {
                "coverImageFileId": new_file_group_id,
                "coverImageUploadPath": presigned_url,
            }
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def get_products_product_id_conversion(
    category: str, product_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            if category == "rank-up":
                # ?쇰컲?밴툒: 湲?먯닔 20,000???댁긽, 5?뚯감 ?댁긽
                query = text("""
                                    select a.product_id
                                        , case when count(1) >= 5 then 'Y' else 'N' end as episode_fulfill_yn
                                        , case when sum(b.episode_text_count) >= 20000 then 'Y' else 'N' end as text_count_fulfill_yn
                                    from tb_product a
                                    inner join tb_product_episode b on a.product_id = b.product_id
                                    and b.use_yn = 'Y'
                                    where a.user_id = :user_id
                                    and a.product_id = :product_id
                                    group by a.product_id
                                    """)

                result = await db.execute(
                    query, {"user_id": user_id, "product_id": product_id_to_int}
                )
                db_rst = result.mappings().all()

                text_count_fulfill_yn = (
                    db_rst[0].get("text_count_fulfill_yn") if db_rst else "N"
                )
                episode_fulfill_yn = (
                    db_rst[0].get("episode_fulfill_yn") if db_rst else "N"
                )

                res_data = {
                    "productId": product_id_to_int,
                    "contentTextCountFulfillYn": text_count_fulfill_yn,
                    "episodeCountFulfillYn": episode_fulfill_yn,
                }
            elif category == "paid":
                pass
            else:
                pass
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def get_products_genres(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                            select keyword_id as genre_id
                                , keyword_name as genre
                            from tb_standard_keyword
                            where use_yn = 'Y'
                                and category_id = 1
                            order by case keyword_name
                                when '무협' then 1
                                when '판타지' then 2
                                when '퓨전' then 3
                                when '게임' then 4
                                when '스포츠' then 5
                                when '로맨스' then 6
                                when '라이트노벨' then 7
                                when '현대판타지' then 8
                                when '대체역사' then 9
                                when '전쟁·밀리터리' then 10
                                when 'SF' then 11
                                when '추리' then 12
                                when '공포·미스테리' then 13
                                when '일반소설' then 14
                                when '드라마' then 15
                                when '팬픽·패러디' then 16
                                else 999
                            end, keyword_id asc
                            """)

            result = await db.execute(query)
            db_rst = result.mappings().all()

            if db_rst:
                res_data = [
                    product_schema.GetProductsGenresToCamel(**row) for row in db_rst
                ]
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def get_products_keywords(kc_user_id: str, db: AsyncSession):
    res_data = list()

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                                select a.category_id
                                    , b.category_name as category
                                    , count(1) as category_count
                                    , json_arrayagg(a.keyword_name) as keywords
                                from tb_standard_keyword a
                                inner join tb_standard_keyword_category b on a.category_id = b.category_id
                                and b.use_yn = 'Y'
                                where a.use_yn = 'Y'
                                group by a.category_id
                                """)

            result = await db.execute(query)
            db_rst = result.mappings().all()

            if db_rst:
                for row in db_rst:
                    row_data = dict()
                    row_data["categoryId"] = row.get("category_id")
                    row_data["category"] = row.get("category")
                    row_data["categoryCount"] = row.get("category_count")
                    row_data["keywords"] = json.loads(row.get("keywords"))

                    res_data.append(row_data)
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def get_products_product_id_episodes_count(
    product_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                                select count(1) as count
                                from tb_product_episode
                                where product_id = :product_id
                                and use_yn = 'Y'
                                """)

            result = await db.execute(query, {"product_id": product_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                res_data = {"hasEpisodeCount": db_rst[0].get("count")}
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def get_products_product_id_info(
    product_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            keywords = list()
            custom_keywords = list()

            query = text("""
                                select b.keyword_name
                                from tb_mapped_product_keyword a
                                inner join tb_standard_keyword b on a.keyword_id = b.keyword_id
                                and b.use_yn = 'Y'
                                inner join tb_standard_keyword_category c on b.category_id = c.category_id
                                and c.use_yn = 'Y'
                                where a.product_id = :product_id
                                """)

            result = await db.execute(query, {"product_id": product_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                for row in db_rst:
                    keywords.append(row.get("keyword_name"))

            query = text("""
                                select a.keyword_name
                                from tb_product_user_keyword a
                                where a.product_id = :product_id
                                and a.use_yn = 'Y'
                                """)

            result = await db.execute(query, {"product_id": product_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                for row in db_rst:
                    custom_keywords.append(row.get("keyword_name"))

            query = text(f"""
                                select a.product_id
                                    , {get_file_path_sub_query("a.thumbnail_file_id", "cover_image_path", "cover")}
                                    , a.status_code
                                    , a.title
                                    , a.author_name as author_nickname
                                    , a.illustrator_name
                                    , a.publish_regular_yn
                                    , a.publish_days
                                    , (select z.keyword_name from tb_standard_keyword z
                                        where z.use_yn = 'Y'
                                        and z.major_genre_yn = 'Y'
                                        and a.primary_genre_id = z.keyword_id) as primary_genre_name
                                    , (select z.keyword_name from tb_standard_keyword z
                                        where z.use_yn = 'Y'
                                        and z.major_genre_yn = 'Y'
                                        and a.sub_genre_id = z.keyword_id) as sub_genre_name
                                    , a.synopsis_text
                                    , case when a.ratings_code = 'adult' then 'Y'
                                            else 'N'
                                    end as adult_yn
                                    , a.open_yn
                                    , a.blind_yn
                                    , a.monopoly_yn
                                    , a.contract_yn
                                    , a.cp_user_id
                                    , (
                                        select up.nickname
                                          from tb_user_profile up
                                         where up.user_id = a.cp_user_id
                                           and up.default_yn = 'Y'
                                         order by up.profile_id asc
                                         limit 1
                                      ) as cp_nickname
                                    , a.paid_open_date as paid_setting_date
                                    , a.paid_episode_no
                                    , a.price_type
                                    , a.product_type
                                    , (
                                        select ppa.status_code
                                          from tb_product_paid_apply ppa
                                         where ppa.product_id = a.product_id
                                           and ppa.use_yn = 'Y'
                                         order by ppa.id desc
                                         limit 1
                                      ) as paid_apply_status
                                    , case when exists (
                                        select 1
                                          from tb_product_paid_apply ppa
                                         where ppa.product_id = a.product_id
                                           and ppa.use_yn = 'Y'
                                           and ppa.status_code = 'accepted'
                                      ) then 'Y' else 'N'
                                      end as paid_approved_yn
                                from tb_product a
                                where a.user_id = :user_id
                                and a.product_id = :product_id
                                """)

            result = await db.execute(
                query, {"user_id": user_id, "product_id": product_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                update_frequency = list()

                publish_days_value = db_rst[0].get("publish_days")
                if publish_days_value:
                    tmp = json.loads(publish_days_value)
                    for key in tmp:
                        update_frequency.append(key.lower())

                res_data = {
                    "productId": product_id_to_int,
                    "coverImagePath": db_rst[0].get("cover_image_path"),
                    "ongoingState": db_rst[0].get("status_code"),
                    "title": db_rst[0].get("title"),
                    "authorNickname": db_rst[0].get("author_nickname"),
                    "illustratorNickname": db_rst[0].get("illustrator_name"),
                    "updateFrequency": update_frequency,
                    "publishRegularYn": db_rst[0].get("publish_regular_yn"),
                    "primaryGenre": db_rst[0].get("primary_genre_name"),
                    "subGenre": db_rst[0].get("sub_genre_name"),
                    "keywords": keywords,
                    "customKeywords": custom_keywords,
                    "synopsis": db_rst[0].get("synopsis_text"),
                    "adultYn": db_rst[0].get("adult_yn"),
                    "openYn": db_rst[0].get("open_yn"),
                    "blindYn": db_rst[0].get("blind_yn"),
                    "monopolyYn": db_rst[0].get("monopoly_yn"),
                    "cpContractYn": db_rst[0].get("contract_yn"),
                    "cpNickname": db_rst[0].get("cp_nickname"),
                    "paidSettingDate": db_rst[0].get("paid_setting_date"),
                    "paidEpisodeNo": db_rst[0].get("paid_episode_no"),
                    "priceType": db_rst[0].get("price_type"),
                    "paidApplyStatus": db_rst[0].get("paid_apply_status"),
                    "paidApprovedYn": db_rst[0].get("paid_approved_yn"),
                    "productType": db_rst[0].get("product_type"),
                }
        except CustomResponseException as e:
            logger.error(e)
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def get_products_validate_cp_nickname(
    nickname: str, kc_user_id: str, db: AsyncSession
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    current_user_role = await _resolve_current_user_role(kc_user_id, db)
    if current_user_role != "author":
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN,
        )

    cp_info = await get_accepted_cp_info_by_nickname(nickname, db)
    return {
        "data": {
            "valid": cp_info is not None,
        }
    }


async def post_products(
    req_body: product_schema.PostProductsReqBody, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    if kc_user_id:
        # ?곗옱?붿씪 寃利?
        publish_days = {}
        for item in req_body.update_frequency:
            if item not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                raise CustomResponseException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=ErrorMessages.INVALID_PRODUCT_INFO,
                )
            else:
                if item == "mon":
                    publish_days["MON"] = "Y"
                elif item == "tue":
                    publish_days["TUE"] = "Y"
                elif item == "wed":
                    publish_days["WED"] = "Y"
                elif item == "thu":
                    publish_days["THU"] = "Y"
                elif item == "fri":
                    publish_days["FRI"] = "Y"
                elif item == "sat":
                    publish_days["SAT"] = "Y"
                elif item == "sun":
                    publish_days["SUN"] = "Y"

        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )
                current_user_role = await _resolve_current_user_role(
                    kc_user_id=kc_user_id, db=db
                )
                allow_external_author_nickname = current_user_role in ("admin", "CP")
                requested_blind_yn = (req_body.blind_yn or "N").upper()
                if current_user_role != "admin" and requested_blind_yn != "N":
                    raise CustomResponseException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        message="관리자 블라인드는 관리자만 변경할 수 있습니다.",
                    )
                series_regular_price = int(req_body.series_regular_price or 0)
                single_regular_price = int(req_body.single_regular_price or 0)
                single_rental_price = int(req_body.single_rental_price or 0)
                created_price_type = (
                    "paid"
                    if series_regular_price > 0 or single_regular_price > 0
                    else "free"
                )

                # 以묐났 ?묓뭹 ?앹꽦 諛⑹? (10珥????숈씪 ?쒕ぉ)
                duplicate_check_query = text("""
                    SELECT COUNT(*) as cnt FROM tb_product
                    WHERE user_id = :user_id
                      AND title = :title
                      AND created_date > DATE_SUB(NOW(), INTERVAL 10 SECOND)
                """)
                duplicate_result = await db.execute(
                    duplicate_check_query,
                    {"user_id": user_id, "title": req_body.title}
                )
                duplicate_count = duplicate_result.scalar()
                if duplicate_count > 0:
                    raise CustomResponseException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        message=ErrorMessages.DUPLICATE_PRODUCT_CREATION,
                    )

                # ?곗옱?곹깭 寃利?
                query = text("""
                                 select 1
                                   from tb_common_code
                                  where code_group = 'PROD_STAT_CODE'
                                    and code_key = :code_key
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"code_key": req_body.ongoing_state})
                db_rst = result.mappings().all()

                if db_rst:
                    pass
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # ?묎?紐?寃利?(愿由ъ옄/CP??誘멸????됰꽕???덉슜)
                author_id = await _resolve_author_id(
                    author_nickname=req_body.author_nickname,
                    db=db,
                    allow_external_author_nickname=allow_external_author_nickname,
                )
                cp_link_info = await _resolve_cp_link_info(
                    req_body.cp_contract_yn,
                    req_body.cp_nickname,
                    db,
                    for_update=True,
                )

                # 1李??λⅤ 寃利?
                query = text("""
                                 select keyword_id
                                      , keyword_name
                                   from tb_standard_keyword
                                  where use_yn = 'Y'
                                    and category_id = 1
                                 """)

                result = await db.execute(query)
                db_rst = result.mappings().all()

                primary_genre_id = None
                if db_rst:
                    for row in db_rst:
                        if req_body.primary_genre == row["keyword_name"]:
                            primary_genre_id = row["keyword_id"]
                            break

                    if primary_genre_id is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_PRODUCT_INFO,
                        )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # 2李??λⅤ 寃利?
                sub_genre_id = None
                if req_body.sub_genre is not None and req_body.sub_genre != "":
                    if req_body.primary_genre == req_body.sub_genre:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.PRIMARY_SECONDARY_GENRE_SAME,
                        )
                    sub_genre_query = text("""
                                     select keyword_id
                                          , keyword_name
                                       from tb_standard_keyword
                                      where use_yn = 'Y'
                                        and category_id = 1
                                     """)
                    sub_genre_result = await db.execute(sub_genre_query)
                    sub_genre_rst = sub_genre_result.mappings().all()

                    for row in sub_genre_rst:
                        if req_body.sub_genre == row["keyword_name"]:
                            sub_genre_id = row["keyword_id"]
                            break

                    if sub_genre_id is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_PRODUCT_INFO,
                        )

                # ?ㅼ썙??寃利?
                query = text("""
                                 select keyword_id
                                      , keyword_name
                                   from tb_standard_keyword a
                                  inner join tb_standard_keyword_category b on a.category_id = b.category_id
                                    and b.use_yn = 'Y'
                                  where a.use_yn = 'Y'
                                 """)

                result = await db.execute(query)
                db_rst = result.mappings().all()

                keyword_id_list = []
                if db_rst:
                    if req_body.keywords is None or req_body.keywords == [""]:
                        pass
                    else:
                        for item in req_body.keywords:
                            for row in db_rst:
                                if item == row["keyword_name"]:
                                    keyword_id_list.append(row["keyword_id"])
                                    break

                        if len(keyword_id_list) != len(req_body.keywords):
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_PRODUCT_INFO,
                            )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                if current_user_role in ("admin", "CP"):
                    product_type = "normal"
                elif req_body.product_type == "normal":
                    # 일반연재 자격 확인: 기존 승급 작품이 있는지 체크
                    qual_query = text("""
                        SELECT 1 FROM tb_product
                        WHERE user_id = (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id AND use_yn = 'Y')
                          AND product_type = 'normal'
                        LIMIT 1
                    """)
                    qual_result = await db.execute(qual_query, {"kc_user_id": kc_user_id})
                    product_type = "normal" if qual_result.scalar() else None
                else:
                    product_type = None

                query = text("""
                                 insert into tb_product (title, price_type, product_type, status_code, ratings_code, synopsis_text, user_id, author_id, author_name, illustrator_name, publish_regular_yn, publish_days, thumbnail_file_id, primary_genre_id, sub_genre_id, open_yn, blind_yn, monopoly_yn, contract_yn, cp_user_id, series_regular_price, single_regular_price, single_rental_price, created_id, updated_id)
                                 select :title, :price_type, :product_type, :status_code, :ratings_code, :synopsis_text, user_id, :author_id, :author_name, :illustrator_name, :publish_regular_yn, :publish_days, :thumbnail_file_id, :primary_genre_id, :sub_genre_id, :open_yn, :blind_yn, :monopoly_yn, :contract_yn, :cp_user_id, :series_regular_price, :single_regular_price, :single_rental_price, :created_id, :updated_id
                                   from tb_user
                                  where kc_user_id = :kc_user_id
                                    and use_yn = 'Y'
                                 """)

                await db.execute(
                    query,
                    {
                        "kc_user_id": kc_user_id,
                        "price_type": created_price_type,
                        "product_type": product_type,
                        "thumbnail_file_id": req_body.cover_image_file_id
                        if req_body.cover_image_file_id
                        and req_body.cover_image_file_id != 0
                        else settings.R2_COVER_DEFAULT_IMAGE,
                        "status_code": req_body.ongoing_state,
                        "title": req_body.title,
                        "author_id": author_id,
                        "author_name": req_body.author_nickname,
                        "illustrator_name": req_body.illustrator_nickname
                        if req_body.illustrator_nickname != ""
                        else None,
                        "publish_regular_yn": req_body.publish_regular_yn,
                        "publish_days": json.dumps(publish_days),
                        "primary_genre_id": primary_genre_id,
                        "sub_genre_id": sub_genre_id,
                        "synopsis_text": req_body.synopsis,
                        "ratings_code": "adult" if req_body.adult_yn == "Y" else "all",
                        "open_yn": "N" if requested_blind_yn == "Y" else req_body.open_yn,
                        "blind_yn": requested_blind_yn,
                        "monopoly_yn": req_body.monopoly_yn,
                        "contract_yn": req_body.cp_contract_yn,
                        "cp_user_id": cp_link_info.get("user_id") if cp_link_info else None,
                        "series_regular_price": series_regular_price,
                        "single_regular_price": single_regular_price,
                        "single_rental_price": single_rental_price,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

                query = text("""
                                 select last_insert_id()
                                 """)

                result = await db.execute(query)
                new_product_id = result.scalar()
                res_data = {"product_id": new_product_id}

                # tb_product_trend_index ins
                query = text("""
                                 insert into tb_product_trend_index (product_id, created_id, updated_id)
                                 values (:product_id, :created_id, :updated_id)
                                 """)

                await db.execute(
                    query,
                    {
                        "product_id": new_product_id,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

                # tb_mapped_product_keyword ins
                if req_body.keywords is None or req_body.keywords == [""]:
                    pass
                else:
                    for item in keyword_id_list:
                        query = text("""
                                         insert into tb_mapped_product_keyword (product_id, keyword_id, created_id, updated_id)
                                         values (:product_id, :keyword_id, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "product_id": new_product_id,
                                "keyword_id": item,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                # tb_product_user_keyword ins
                if req_body.custom_keywords is None or req_body.custom_keywords == [""]:
                    pass
                else:
                    for item in req_body.custom_keywords:
                        query = text("""
                                         insert into tb_product_user_keyword (product_id, keyword_name, created_id, updated_id)
                                         values (:product_id, :keyword_name, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "product_id": new_product_id,
                                "keyword_name": item,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                # tb_ptn_product_statistics 珥덇린 ?곗씠???앹꽦 (?뚰듃???듦퀎??
                query = text("""
                    INSERT INTO tb_ptn_product_statistics
                    (product_id, title, author_nickname, count_episode, paid_yn,
                     count_hit, count_bookmark, count_unbookmark, count_recommend, count_evaluation,
                     count_total_sales, sum_total_sales_price, sales_price_per_count_hit,
                     count_cp_hit, reading_rate, created_id, updated_id)
                    VALUES
                    (:product_id, :title, :author_nickname, 0, 'N',
                     0, 0, 0, 0, 0,
                     0, 0, 0,
                     0, 0, :created_id, :updated_id)
                """)

                await db.execute(
                    query,
                    {
                        "product_id": new_product_id,
                        "title": req_body.title,
                        "author_nickname": req_body.author_nickname,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

                # TODO 理쒖긽???묎???寃쎌슦 ?낅줈???뚮엺 ?앹꽦

                try:
                    await event_reward_service.check_and_grant_event_reward(
                        event_type="add-product", user_id=user_id, product_id=new_product_id, db=db
                    )
                except Exception as e:
                    logger.error(f"Event reward check failed: {e}")

        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


async def put_products_product_id(
    product_id: str,
    req_body: product_schema.PutProductsProductIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    product_id_to_int = int(product_id)

    if kc_user_id:
        # ?곗옱?붿씪 寃利?
        publish_days = {}
        for item in req_body.update_frequency:
            if item not in ("mon", "tue", "wed", "thu", "fri", "sat", "sun"):
                raise CustomResponseException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=ErrorMessages.INVALID_PRODUCT_INFO,
                )
            else:
                if item == "mon":
                    publish_days["MON"] = "Y"
                elif item == "tue":
                    publish_days["TUE"] = "Y"
                elif item == "wed":
                    publish_days["WED"] = "Y"
                elif item == "thu":
                    publish_days["THU"] = "Y"
                elif item == "fri":
                    publish_days["FRI"] = "Y"
                elif item == "sat":
                    publish_days["SAT"] = "Y"
                elif item == "sun":
                    publish_days["SUN"] = "Y"

        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )
                current_user_role = await _resolve_current_user_role(
                    kc_user_id=kc_user_id, db=db
                )
                allow_external_author_nickname = current_user_role in ("admin", "CP")
                query = text("""
                                 select blind_yn
                                      , open_yn
                                      , contract_yn
                                      , cp_user_id
                                      , (
                                            select ppa.status_code
                                              from tb_product_paid_apply ppa
                                             where ppa.product_id = tb_product.product_id
                                               and ppa.use_yn = 'Y'
                                             order by ppa.id desc
                                             limit 1
                                        ) as paid_apply_status
                                   from tb_product
                                  where product_id = :product_id
                                  limit 1
                                  for update
                                 """)
                result = await db.execute(query, {"product_id": product_id_to_int})
                current_product = result.mappings().one_or_none()
                if current_product is None:
                    raise CustomResponseException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        message=ErrorMessages.NOT_FOUND_PRODUCT,
                    )
                current_blind_yn = (current_product.get("blind_yn") or "N").upper()
                current_open_yn = (current_product.get("open_yn") or "N").upper()
                current_contract_yn = (current_product.get("contract_yn") or "N").upper()
                current_cp_user_id = current_product.get("cp_user_id")
                current_paid_apply_status = current_product.get("paid_apply_status")
                fields_set = getattr(req_body, "model_fields_set", set()) or set()
                blind_yn_in_request = "blind_yn" in fields_set
                requested_blind_yn = (
                    (req_body.blind_yn or current_blind_yn).upper()
                    if blind_yn_in_request
                    else current_blind_yn
                )
                if current_user_role != "admin":
                    if blind_yn_in_request and requested_blind_yn != current_blind_yn:
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message="관리자 블라인드는 관리자만 변경할 수 있습니다.",
                        )
                    if (
                        current_blind_yn == "Y"
                        and "open_yn" in fields_set
                        and req_body.open_yn != current_open_yn
                    ):
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message="관리자 블라인드된 작품은 공개 상태를 변경할 수 없습니다.",
                        )
                is_contract_locked = current_paid_apply_status in ("review", "accepted")
                current_cp_info = await get_accepted_cp_info_by_user_id(
                    current_cp_user_id, db
                )
                current_cp_nickname = (
                    current_cp_info.get("nickname") if current_cp_info else None
                )
                requested_cp_link_info = await _resolve_cp_link_info(
                    req_body.cp_contract_yn,
                    req_body.cp_nickname,
                    db,
                    for_update=True,
                )
                requested_cp_user_id = (
                    requested_cp_link_info.get("user_id")
                    if requested_cp_link_info
                    else None
                )
                requested_cp_nickname = (
                    requested_cp_link_info.get("nickname")
                    if requested_cp_link_info
                    else None
                )
                if is_contract_locked and (
                    req_body.cp_contract_yn != current_contract_yn
                    or normalize_cp_nickname(requested_cp_nickname)
                    != normalize_cp_nickname(current_cp_nickname)
                ):
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message="심사중 또는 승인된 작품은 계약 정보를 변경할 수 없습니다.",
                    )

                # ?곗옱?곹깭 寃利?
                query = text("""
                                 select 1
                                   from tb_common_code
                                  where code_group = 'PROD_STAT_CODE'
                                    and code_key = :code_key
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"code_key": req_body.ongoing_state})
                db_rst = result.mappings().all()

                if db_rst:
                    pass
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # ?묎?紐?寃利?(愿由ъ옄/CP??誘멸????됰꽕???덉슜)
                author_id = await _resolve_author_id(
                    author_nickname=req_body.author_nickname,
                    db=db,
                    allow_external_author_nickname=allow_external_author_nickname,
                )

                # 1李??λⅤ 寃利?
                query = text("""
                                 select keyword_id
                                      , keyword_name
                                   from tb_standard_keyword
                                  where use_yn = 'Y'
                                    and category_id = 1
                                 """)

                result = await db.execute(query)
                db_rst = result.mappings().all()

                primary_genre_id = None
                if db_rst:
                    for row in db_rst:
                        if req_body.primary_genre == row["keyword_name"]:
                            primary_genre_id = row["keyword_id"]
                            break

                    if primary_genre_id is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_PRODUCT_INFO,
                        )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # 2李??λⅤ 寃利?
                sub_genre_id = None
                if req_body.sub_genre is not None and req_body.sub_genre != "":
                    if req_body.primary_genre == req_body.sub_genre:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.PRIMARY_SECONDARY_GENRE_SAME,
                        )
                    sub_genre_query = text("""
                                     select keyword_id
                                          , keyword_name
                                       from tb_standard_keyword
                                      where use_yn = 'Y'
                                        and category_id = 1
                                     """)
                    sub_genre_result = await db.execute(sub_genre_query)
                    sub_genre_rst = sub_genre_result.mappings().all()

                    for row in sub_genre_rst:
                        if req_body.sub_genre == row["keyword_name"]:
                            sub_genre_id = row["keyword_id"]
                            break

                    if sub_genre_id is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_PRODUCT_INFO,
                        )

                # ?ㅼ썙??寃利?
                query = text("""
                                 select keyword_id
                                      , keyword_name
                                   from tb_standard_keyword a
                                  inner join tb_standard_keyword_category b on a.category_id = b.category_id
                                    and b.use_yn = 'Y'
                                  where a.use_yn = 'Y'
                                 """)

                result = await db.execute(query)
                db_rst = result.mappings().all()

                keyword_id_list = []
                if db_rst:
                    if req_body.keywords is None or req_body.keywords == [""]:
                        pass
                    else:
                        for item in req_body.keywords:
                            for row in db_rst:
                                if item == row["keyword_name"]:
                                    keyword_id_list.append(row["keyword_id"])
                                    break

                        if len(keyword_id_list) != len(req_body.keywords):
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_PRODUCT_INFO,
                            )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # 臾대즺 ?묓뭹??寃쎌슦 ?좊즺 愿??媛?臾댁떆

                # ?좊즺 寃利?
                if req_body.paid_setting_date or (
                    req_body.paid_episode_no and req_body.paid_episode_no != 0
                ):
                    query = text("""
                                     select 1
                                       from tb_product a
                                      left join tb_product_paid_apply b on a.product_id = b.product_id
                                        and b.use_yn = 'Y'
                                        and b.status_code = 'accepted'
                                      where a.product_id = :product_id
                                        and (a.price_type = 'paid' or b.id is not null)
                                      limit 1
                                     """)

                    result = await db.execute(query, {"product_id": product_id_to_int})
                    db_rst = result.mappings().all()

                    if db_rst:
                        pass
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_PRODUCT_INFO,
                        )

                if (
                    req_body.cover_image_file_id is None
                    or req_body.cover_image_file_id == 0
                ):
                    query = text("""
                                     update tb_product a
                                        set a.title = :title
                                          , a.status_code = :status_code
                                          , a.synopsis_text = :synopsis_text
                                          , a.author_id = :author_id
                                          , a.author_name = :author_name
                                          , a.illustrator_name = :illustrator_name
                                          , a.publish_regular_yn = :publish_regular_yn
                                          , a.publish_days = :publish_days
                                          , a.primary_genre_id = :primary_genre_id
                                          , a.sub_genre_id = :sub_genre_id
                                          , a.ratings_code = :ratings_code
                                          , a.open_yn = :open_yn
                                          , a.blind_yn = :blind_yn
                                          , a.monopoly_yn = :monopoly_yn
                                          , a.contract_yn = :contract_yn
                                          , a.cp_user_id = :cp_user_id
                                          , a.paid_open_date = :paid_open_date
                                          , a.paid_episode_no = :paid_episode_no
                                          , a.updated_id = a.user_id
                                      where a.product_id = :product_id
                                        and exists (select 1 from tb_user z
                                                     where z.kc_user_id = :kc_user_id
                                                       and z.use_yn = 'Y'
                                                       and z.user_id = a.user_id)
                                     """)

                    result = await db.execute(
                        query,
                        {
                            "kc_user_id": kc_user_id,
                            "product_id": product_id_to_int,
                            "status_code": req_body.ongoing_state,
                            "title": req_body.title,
                            "author_id": author_id,
                            "author_name": req_body.author_nickname,
                            "illustrator_name": req_body.illustrator_nickname
                            if req_body.illustrator_nickname != ""
                            else None,
                            "publish_regular_yn": req_body.publish_regular_yn,
                            "publish_days": json.dumps(publish_days),
                            "primary_genre_id": primary_genre_id,
                            "sub_genre_id": sub_genre_id,
                            "synopsis_text": req_body.synopsis,
                            "ratings_code": "adult"
                            if req_body.adult_yn == "Y"
                            else "all",
                            "open_yn": "N" if requested_blind_yn == "Y" else req_body.open_yn,
                            "blind_yn": requested_blind_yn,
                            "monopoly_yn": req_body.monopoly_yn,
                            "contract_yn": req_body.cp_contract_yn,
                            "cp_user_id": requested_cp_user_id,
                            "paid_open_date": convert_to_kor_time(
                                req_body.paid_setting_date
                            )
                            if req_body.paid_setting_date
                            else None,
                            "paid_episode_no": req_body.paid_episode_no
                            if req_body.paid_episode_no
                            and req_body.paid_episode_no != 0
                            else None,
                        },
                    )
                    if result.rowcount == 0:
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message=ErrorMessages.FORBIDDEN,
                        )
                else:
                    query = text("""
                                     update tb_product a
                                        set a.title = :title
                                          , a.status_code = :status_code
                                          , a.synopsis_text = :synopsis_text
                                          , a.author_id = :author_id
                                          , a.author_name = :author_name
                                          , a.illustrator_name = :illustrator_name
                                          , a.publish_regular_yn = :publish_regular_yn
                                          , a.publish_days = :publish_days
                                          , a.thumbnail_file_id = :thumbnail_file_id
                                          , a.primary_genre_id = :primary_genre_id
                                          , a.sub_genre_id = :sub_genre_id
                                          , a.ratings_code = :ratings_code
                                          , a.open_yn = :open_yn
                                          , a.blind_yn = :blind_yn
                                          , a.monopoly_yn = :monopoly_yn
                                          , a.contract_yn = :contract_yn
                                          , a.cp_user_id = :cp_user_id
                                          , a.paid_open_date = :paid_open_date
                                          , a.paid_episode_no = :paid_episode_no
                                          , a.updated_id = a.user_id
                                      where a.product_id = :product_id
                                        and exists (select 1 from tb_user z
                                                     where z.kc_user_id = :kc_user_id
                                                       and z.use_yn = 'Y'
                                                       and z.user_id = a.user_id)
                                     """)

                    result = await db.execute(
                        query,
                        {
                            "kc_user_id": kc_user_id,
                            "product_id": product_id_to_int,
                            "thumbnail_file_id": req_body.cover_image_file_id,
                            "status_code": req_body.ongoing_state,
                            "title": req_body.title,
                            "author_id": author_id,
                            "author_name": req_body.author_nickname,
                            "illustrator_name": req_body.illustrator_nickname
                            if req_body.illustrator_nickname != ""
                            else None,
                            "publish_regular_yn": req_body.publish_regular_yn,
                            "publish_days": json.dumps(publish_days),
                            "primary_genre_id": primary_genre_id,
                            "sub_genre_id": sub_genre_id,
                            "synopsis_text": req_body.synopsis,
                            "ratings_code": "adult"
                            if req_body.adult_yn == "Y"
                            else "all",
                            "open_yn": "N" if requested_blind_yn == "Y" else req_body.open_yn,
                            "blind_yn": requested_blind_yn,
                            "monopoly_yn": req_body.monopoly_yn,
                            "contract_yn": req_body.cp_contract_yn,
                            "cp_user_id": requested_cp_user_id,
                            "paid_open_date": convert_to_kor_time(
                                req_body.paid_setting_date
                            )
                            if req_body.paid_setting_date
                            else None,
                            "paid_episode_no": req_body.paid_episode_no
                            if req_body.paid_episode_no
                            and req_body.paid_episode_no != 0
                            else None,
                        },
                    )
                    if result.rowcount == 0:
                        raise CustomResponseException(
                            status_code=status.HTTP_403_FORBIDDEN,
                            message=ErrorMessages.FORBIDDEN,
                        )

                # tb_mapped_product_keyword upd
                query = text("""
                                 delete from tb_mapped_product_keyword
                                  where product_id = :product_id
                                 """)

                await db.execute(query, {"product_id": product_id_to_int})

                if req_body.keywords is None or req_body.keywords == [""]:
                    pass
                else:
                    for item in keyword_id_list:
                        query = text("""
                                         insert into tb_mapped_product_keyword (product_id, keyword_id, created_id, updated_id)
                                         values (:product_id, :keyword_id, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "product_id": product_id_to_int,
                                "keyword_id": item,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                # tb_product_user_keyword upd
                query = text("""
                                 update tb_product_user_keyword a
                                  inner join (
                                     select z.user_id
                                          , z.product_id
                                       from tb_product z
                                      where z.product_id = :product_id
                                  ) as t on a.product_id = t.product_id
                                    set a.use_yn = 'N'
                                      , a.updated_id = t.user_id
                                  where 1=1
                                 """)

                await db.execute(query, {"product_id": product_id_to_int})

                if req_body.custom_keywords is None or req_body.custom_keywords == [""]:
                    pass
                else:
                    for item in req_body.custom_keywords:
                        query = text("""
                                         insert into tb_product_user_keyword (product_id, keyword_name, created_id, updated_id)
                                         values (:product_id, :keyword_name, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "product_id": product_id_to_int,
                                "keyword_name": item,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )
        except CustomResponseException:
            raise
        except OperationalError:
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


async def put_products_product_id_conversion(
    category: str, product_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_id_to_int = int(product_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                if category == "rank-up":
                    # ?쇰컲?밴툒: 湲?먯닔 20,000???댁긽, 5?뚯감 ?댁긽 (議곌굔留?留뚯”?섎㈃ 諛붾줈 ?밴툒 泥섎━)
                    query = text("""
                                     select a.product_id
                                       from tb_product a
                                      inner join tb_product_episode b on a.product_id = b.product_id
                                        and b.use_yn = 'Y'
                                      where a.user_id = :user_id
                                        and a.product_id = :product_id
                                      group by a.product_id
                                      having count(1) >= 5 and sum(b.episode_text_count) >= 20000
                                     """)

                    result = await db.execute(
                        query, {"user_id": user_id, "product_id": product_id_to_int}
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        query = text("""
                                         update tb_product
                                            set product_type = 'normal'
                                              , updated_id = :user_id
                                              , apply_date = now()
                                          where product_id = :product_id
                                         """)

                        await db.execute(
                            query, {"user_id": user_id, "product_id": product_id_to_int}
                        )

                        res_data = {
                            "productId": product_id_to_int,
                            "productType": "normal",
                        }
                elif category == "paid":
                    contract_query = text("""
                                     select contract_yn, cp_user_id
                                       from tb_product
                                      where user_id = :user_id
                                        and product_id = :product_id
                                      limit 1
                                      for update
                                     """)
                    contract_result = await db.execute(
                        contract_query,
                        {"user_id": user_id, "product_id": product_id_to_int},
                    )
                    contract_row = contract_result.mappings().one_or_none()
                    if contract_row is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_404_NOT_FOUND,
                            message=ErrorMessages.NOT_FOUND_PRODUCT,
                        )
                    if (
                        contract_row.get("contract_yn") != "Y"
                        or contract_row.get("cp_user_id") is None
                    ):
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message="계약 상태 작품만 유료전환 신청이 가능합니다.",
                        )
                    linked_cp_info = await get_accepted_cp_info_by_user_id(
                        contract_row.get("cp_user_id"),
                        db,
                        for_update=True,
                    )
                    if linked_cp_info is None:
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message="유효한 CP를 확인할 수 없습니다.",
                        )
                    # ?좊즺?꾪솚: 理쒕? 2踰??좎껌 媛?? ?ъ궗 ???뱀씤?섎㈃ ?밴툒 泥섎━
                    query = text("""
                                     select a.product_id
                                       from tb_product a
                                       left join tb_product_paid_apply b on a.product_id = b.product_id
                                        and b.use_yn = 'Y'
                                      where a.user_id = :user_id
                                        and a.product_id = :product_id
                                        and a.product_type = 'normal'
                                      group by a.product_id
                                      having count(1) < 2
                                     """)

                    result = await db.execute(
                        query, {"user_id": user_id, "product_id": product_id_to_int}
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        query = text("""
                                         insert into tb_product_paid_apply (product_id, status_code, req_user_id, created_id, updated_id)
                                         values (:product_id, :status_code, :user_id, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "product_id": product_id_to_int,
                                "status_code": "review",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        query = text("""
                                         update tb_product
                                            set updated_id = :user_id
                                              , apply_date = now()
                                          where product_id = :product_id
                                         """)

                        await db.execute(
                            query, {"user_id": user_id, "product_id": product_id_to_int}
                        )

                        res_data = {
                            "productId": product_id_to_int,
                            "convertToPaidState": "review",
                        }
                else:
                    pass
        except CustomResponseException:
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_body = {"data": res_data}

    return res_body


def _count_evaluations(user_evaluations: List[dict]) -> dict:
    """?됯? 肄붾뱶蹂?媛쒖닔瑜?吏묎퀎?섎뒗 ?대? ?⑥닔"""
    evaluation_counts = defaultdict(int)
    for hit in user_evaluations:
        if "evaluationCode" in hit:
            evaluation_counts[hit["evaluationCode"]] += 1
        if "eval_code" in hit:
            evaluation_counts[hit["eval_code"]] += 1
    if "highlypositive" not in evaluation_counts:
        evaluation_counts["highlypositive"] = 0
    if "verypositive" not in evaluation_counts:
        evaluation_counts["verypositive"] = 0
    if "positive" not in evaluation_counts:
        evaluation_counts["positive"] = 0
    if "somewhatpositive" not in evaluation_counts:
        evaluation_counts["somewhatpositive"] = 0
    if "neutral" not in evaluation_counts:
        evaluation_counts["neutral"] = 0
    if "somewhatnegative" not in evaluation_counts:
        evaluation_counts["somewhatnegative"] = 0
    if "negative" not in evaluation_counts:
        evaluation_counts["negative"] = 0
    if "verynegative" not in evaluation_counts:
        evaluation_counts["verynegative"] = 0
    if "highlynegative" not in evaluation_counts:
        evaluation_counts["highlynegative"] = 0
    return dict(evaluation_counts)


async def get_user_interest_drop_products(kc_user_id: str, db: AsyncSession):
    res_data = []

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await get_user_id(kc_user_id, db)
                query_parts = get_select_fields_and_joins_for_product(
                    user_id=user_id, join_rank=False
                )
                query = text(f"""
                    SELECT {query_parts["select_fields"]}
                    FROM tb_product p
                    {query_parts["joins"]}
                    where p.product_id IN (
                        select b.product_id
                        from tb_user a
                        inner join tb_user_product_usage b on b.user_id = a.user_id
                        where a.kc_user_id = :kc_user_id
                            and a.use_yn = 'Y'
                            and b.use_yn = 'Y'
                        order by b.updated_date desc
                    ) AND p.open_yn = 'Y'
                """)
                result = await db.execute(query, {"kc_user_id": kc_user_id})
                rows = result.mappings().all()
                res_data = [convert_product_data(row) for row in rows]

                if len(res_data) > 0:
                    fetch_product_ids = ",".join(
                        [str(product.get("productId")) for product in res_data]
                    )

                    # ?먰뵾?뚮뱶 ?뺣낫 議고쉶 (latestEpisodeNo, firstEpisodeId)
                    episode_info_query = text(f"""
                        SELECT
                            product_id,
                            MAX(episode_no) as latest_episode_no,
                            (SELECT episode_id FROM tb_product_episode
                             WHERE product_id = pe.product_id AND open_yn = 'Y' AND use_yn = 'Y'
                             ORDER BY episode_no ASC LIMIT 1) as first_episode_id
                        FROM tb_product_episode pe
                        WHERE product_id IN ({fetch_product_ids})
                          AND open_yn = 'Y' AND use_yn = 'Y'
                        GROUP BY product_id
                    """)
                    episode_info_result = await db.execute(episode_info_query, {})
                    episode_info_rows = episode_info_result.mappings().all()

                    episode_info_map = {
                        row["product_id"]: {
                            "latestEpisodeNo": row["latest_episode_no"],
                            "firstEpisodeId": row["first_episode_id"],
                        }
                        for row in episode_info_rows
                    }

                    # ?ъ슜?먯쓽 理쒓렐 ?쎌? ?먰뵾?뚮뱶 議고쉶 (lastViewedEpisodeId, lastViewedEpisodeNo)
                    recent_read_map = {}
                    if user_id:
                        recent_read_query = text(f"""
                            SELECT
                                upu.product_id,
                                upu.episode_id as last_viewed_episode_id,
                                pe.episode_no as last_viewed_episode_no
                            FROM tb_user_product_usage upu
                            INNER JOIN (
                                SELECT u2.product_id, MAX(u2.updated_date) as max_date
                                FROM tb_user_product_usage u2
                                INNER JOIN tb_product_episode ep2 ON u2.episode_id = ep2.episode_id
                                WHERE u2.user_id = :user_id
                                  AND u2.product_id IN ({fetch_product_ids})
                                  AND u2.use_yn = 'Y'
                                  AND (
                                    ep2.open_yn = 'Y'
                                    OR EXISTS (
                                      SELECT 1 FROM tb_user_productbook pb
                                      WHERE (pb.episode_id = ep2.episode_id
                                             OR (pb.episode_id IS NULL
                                                 AND (pb.product_id = ep2.product_id
                                                      OR pb.product_id IS NULL)))
                                        AND pb.user_id = :user_id
                                        AND pb.use_yn = 'Y'
                                        AND (pb.rental_expired_date IS NULL OR pb.rental_expired_date > NOW())
                                    )
                                  )
                                GROUP BY u2.product_id
                            ) latest ON upu.product_id = latest.product_id
                                     AND upu.updated_date = latest.max_date
                            LEFT JOIN tb_product_episode pe ON upu.episode_id = pe.episode_id
                            WHERE upu.user_id = :user_id
                              AND upu.use_yn = 'Y'
                        """)
                        recent_read_result = await db.execute(
                            recent_read_query, {"user_id": user_id}
                        )
                        recent_read_rows = recent_read_result.mappings().all()
                        recent_read_map = {
                            row["product_id"]: {
                                "last_viewed_episode_id": row["last_viewed_episode_id"],
                                "last_viewed_episode_no": row["last_viewed_episode_no"],
                            }
                            for row in recent_read_rows
                        }

                    # ?먰뵾?뚮뱶 ?뺣낫瑜?媛??묓뭹 ?곗씠?곗뿉 異붽?
                    for product in res_data:
                        product_id = product.get("productId")

                        # ?먰뵾?뚮뱶 ?뺣낫 異붽?
                        if product_id in episode_info_map:
                            product["latestEpisodeNo"] = episode_info_map[product_id][
                                "latestEpisodeNo"
                            ]
                            product["firstEpisodeId"] = episode_info_map[product_id][
                                "firstEpisodeId"
                            ]
                        else:
                            product["latestEpisodeNo"] = None
                            product["firstEpisodeId"] = None

                        # 理쒓렐 ?쎌? ?먰뵾?뚮뱶 ?뺣낫 異붽?
                        if product_id in recent_read_map:
                            product["lastViewedEpisodeId"] = recent_read_map[
                                product_id
                            ]["last_viewed_episode_id"]
                            product["lastViewedEpisodeNo"] = recent_read_map[
                                product_id
                            ]["last_viewed_episode_no"]
                        else:
                            product["lastViewedEpisodeId"] = None
                            product["lastViewedEpisodeNo"] = None

        except Exception as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    res_body = {"data": res_data}

    return res_body


async def get_user_interest_drop_products_soon(
    kc_user_id: str, db: AsyncSession, adult_yn: str = "N"
):
    res_data = []

    if kc_user_id:
        try:
            async with db.begin():
                query = text("""
                                 select b.product_id
                                 from tb_user a
                                    inner join tb_user_product_usage b on b.user_id = a.user_id
                                 where a.kc_user_id = :kc_user_id
                                    and a.use_yn = 'Y'
                                    and b.use_yn = 'Y'
                                    and b.updated_date > now() - interval 3 day
                                 order by b.updated_date desc
                                 """)

                result = await db.execute(query, {"kc_user_id": kc_user_id})
                db_rst = result.mappings().all()

                if len(db_rst) > 0:
                    fetch_product_ids = ",".join(
                        [str(row.get("product_id")) for row in db_rst]
                    )

                    # ?꾪꽣 ?듭뀡 ?ㅼ젙
                    filter_option = []
                    filter_option.append(f"p.product_id IN ({fetch_product_ids})")
                    filter_option.append("p.open_yn = 'Y'")
                    # ?깆씤?깃툒 ?꾪꽣留? adult_yn??N?대㈃ ?꾩껜?댁슜媛留?議고쉶
                    if adult_yn == "N":
                        filter_option.append("p.ratings_code = 'all'")

                    user_id = await get_user_id(kc_user_id, db)

                    query_parts = get_select_fields_and_joins_for_product(
                        user_id=user_id, join_rank=False
                    )
                    query = text(f"""
                        SELECT {query_parts["select_fields"]}
                        FROM tb_product p
                        {query_parts["joins"]}
                        WHERE {" and ".join(filter_option)}
                    """)
                    result = await db.execute(query, {})
                    rows = result.mappings().all()
                    res_data = [convert_product_data(row) for row in rows]

        except Exception:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    res_body = {"data": res_data}

    return res_body


async def get_product_rank(db: AsyncSession):
    """
    ??臾대즺 top 50 議고쉶
    """
    query = text("""
                 SELECT * FROM tb_product_rank ORDER BY current_rank ASC
                 """)
    result = await db.execute(query, {})
    rows = result.mappings().all()
    return build_list_response(rows)


async def products_in_publisher_promotion(
    kc_user_id: str, db: AsyncSession, adult_yn: str = "N"
):
    """
    異쒗뙋???꾨줈紐⑥뀡 ?곹뭹 由ъ뒪??議고쉶
    """
    user_id = await get_user_id(kc_user_id, db)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
    query = text(f"""
        SELECT {query_parts["select_fields"]}
        FROM tb_product p
        {query_parts["joins"]}
        INNER JOIN tb_publisher_promotion pp ON p.product_id = pp.product_id
        WHERE p.open_yn = 'Y' {adult_filter}
        ORDER BY pp.show_order DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    config_query = text("""
        SELECT title
        FROM tb_publisher_promotion_config
        ORDER BY id ASC
        LIMIT 1
    """)
    config_result = await db.execute(config_query, {})
    config_row = config_result.mappings().one_or_none()
    section_title = (
        (config_row.get("title") if config_row is not None else None)
        or DEFAULT_PUBLISHER_PROMOTION_TITLE
    )

    res_body = dict()
    res_body["data"] = [convert_product_data(row) for row in rows]
    res_body["title"] = section_title

    return res_body


async def products_in_latest_update(
    kc_user_id: str, db: AsyncSession, adult_yn: str = "N"
):
    """
    理쒖떊 ?낅뜲?댄듃 ?곹뭹 由ъ뒪??議고쉶
    """
    user_id = await get_user_id(kc_user_id, db)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
    query = text(f"""
        SELECT {query_parts["select_fields"]}
        FROM tb_product p
        {query_parts["joins"]}
        WHERE p.last_episode_date IS NOT NULL AND p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR) AND p.open_yn = 'Y' {adult_filter}
        ORDER BY p.last_episode_date DESC
    """)
    result = await db.execute(query, {})
    rows = result.mappings().all()

    res_body = dict()
    res_body["data"] = [convert_product_data(row) for row in rows]

    return res_body


async def products_in_main_rule_slots(
    kc_user_id: str | None, db: AsyncSession, adult_yn: str = "N"
):
    user_id = await get_user_id(kc_user_id, db) if kc_user_id else None

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    adult_filter = (
        "AND p.ratings_code = 'all'"
        if adult_yn == "N"
        else "AND p.ratings_code IN ('all', 'adult')"
    )

    res_body = {"data": []}

    for slot in MAIN_RULE_SLOT_DEFINITIONS:
        query = text(f"""
            SELECT {query_parts["select_fields"]}, s.display_order
              FROM tb_main_rule_slot_snapshot s
              INNER JOIN tb_product p
                      ON p.product_id = s.product_id
              {query_parts["joins"]}
             WHERE s.slot_key = :slot_key
               AND s.adult_yn = :adult_yn
               AND s.snapshot_start_date = (
                   SELECT MAX(s2.snapshot_start_date)
                     FROM tb_main_rule_slot_snapshot s2
                    WHERE s2.slot_key = :slot_key
                      AND s2.adult_yn = :adult_yn
                      AND s2.snapshot_start_date <= CURDATE()
               )
               AND p.price_type = 'free'
               AND p.open_yn = 'Y'
               AND p.blind_yn = 'N'
               AND p.status_code IN ('ongoing', 'rest')
               {adult_filter}
             ORDER BY s.display_order ASC
        """)
        result = await db.execute(
            query,
            {
                "slot_key": slot["slot_key"],
                "adult_yn": adult_yn,
            },
        )
        rows = result.mappings().all()

        if not rows:
            continue

        res_body["data"].append(
            {
                "suggestId": slot["suggest_id"],
                "suggestName": slot["suggest_name"],
                "suggestTarget": "free",
                "suggestTitle": slot["suggest_title"],
                "products": [convert_product_data(row) for row in rows],
            }
        )

    return res_body


async def products_in_applied_promotion(type: str, kc_user_id: str, db: AsyncSession):
    """
    ?좎껌 ?꾨줈紐⑥뀡 ?곹뭹 由ъ뒪??議고쉶
    """
    user_id = await get_user_id(kc_user_id, db)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    query = text(f"""
        SELECT {query_parts["select_fields"]}, ap.start_date AS promotion_start_date, ap.end_date AS promotion_end_date
        FROM tb_product p
        {query_parts["joins"]}
        INNER JOIN tb_applied_promotion ap ON p.product_id = ap.product_id AND ap.type = :type AND ap.status = 'ing'
        WHERE p.open_yn = 'Y'
          AND DATE(ap.start_date) <= CURDATE()
          AND (ap.end_date IS NULL OR DATE(ap.end_date) >= CURDATE())
    """)
    result = await db.execute(query, {"type": type})
    rows = result.mappings().all()

    res_body = dict()
    res_body["data"] = {}
    for row in rows:
        data = convert_product_data(row)
        start_date: datetime = row.get("promotion_start_date")
        end_date: datetime | None = row.get("promotion_end_date")

        # start_date遺??end_date源뚯? ?좎쭨蹂꾨줈 ?곗씠?곕? 遺꾨쪟
        current_date = start_date.date() if start_date else None
        end_date_only = end_date.date() if end_date else None

        if current_date:
            # start_date에만 작품 추가 (기간 전체 중복 표시 방지)
            date_str = current_date.isoformat()
            if date_str not in res_body["data"]:
                res_body["data"][date_str] = []
            res_body["data"][date_str].append(data)

    # ?좎쭨瑜???닚(理쒖떊 ?좎쭨遺???쇰줈 ?뺣젹
    res_body["data"] = dict(sorted(res_body["data"].items(), reverse=True))

    return res_body


async def products_in_admin_gift_promotion(kc_user_id: str, db: AsyncSession):
    user_id = await get_user_id(kc_user_id, db)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    query = text(f"""
        SELECT {query_parts["select_fields"]}, dp.created_date AS promotion_created_date
        FROM tb_product p
        {query_parts["joins"]}
        INNER JOIN tb_direct_promotion dp ON p.product_id = dp.product_id AND dp.type = 'admin-gift' AND dp.status = 'ing'
        WHERE p.open_yn = 'Y'
          AND DATE(dp.start_date) <= CURDATE()
          AND (dp.end_date IS NULL OR DATE(dp.end_date) >= CURDATE())
    """)
    result = await db.execute(query)
    rows = result.mappings().all()

    res_body = dict()
    res_body["data"] = {}
    for row in rows:
        data = convert_product_data(row)
        created_date: datetime = row.get("promotion_created_date")
        if created_date:
            date_str = created_date.date().isoformat()
            if date_str not in res_body["data"]:
                res_body["data"][date_str] = []
            res_body["data"][date_str].append(data)

    res_body["data"] = dict(sorted(res_body["data"].items(), reverse=True))

    return res_body


async def post_product_report(
    product_id: str,
    req_body: product_schema.PostProductReportReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    ?묓뭹 ?좉퀬
    """
    product_id_to_int = int(product_id)
    if kc_user_id:
        try:
            async with db.begin():
                # ?ъ슜???뺤씤
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # tb_user_report insert
                query = text("""
                    insert into tb_user_report (product_id, episode_id, comment_id, user_id, reported_user_id, report_type, content, created_id, updated_id)
                    select :product_id, NULL, NULL, :user_id, user_id as reported_user_id, :report_type, :content, :created_id, :updated_id
                    from tb_product
                    where product_id = :product_id
                """)
                await db.execute(
                    query,
                    {
                        "product_id": product_id_to_int,
                        "user_id": user_id,
                        "report_type": req_body.reportType
                        if req_body.reportType != ""
                        else None,
                        "content": req_body.content,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )
        except CustomResponseException:
            raise
        except OperationalError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )
    return


async def revive_product_interest(product_id: str, kc_user_id: str, db: AsyncSession):
    """
    愿???섏궡由ш린: 愿?щ걡湲곌린 ?꾨컯 ?곹깭瑜?愿???좎?以묒쑝濡?蹂寃?
    tb_user_product_usage??updated_date瑜??꾩옱 ?쒓컙?쇰줈 ?낅뜲?댄듃
    """
    try:
        product_id_to_int = int(product_id)
    except ValueError:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="유효하지 않은 작품 ID입니다",
        )

    # kc_user_id濡?user_id 議고쉶
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # ?묓뭹 議댁옱 ?щ? ?뺤씤
    product_query = text("""
        SELECT product_id
        FROM tb_product
        WHERE product_id = :product_id
    """)
    product_result = await db.execute(product_query, {"product_id": product_id_to_int})
    product_row = product_result.mappings().one_or_none()

    if not product_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="작품을 찾을 수 없습니다.",
        )

    # tb_user_product_usage?먯꽌 媛??理쒓렐 ?덉퐫??議고쉶
    # ???뚯씠釉붿? episode_id蹂꾨줈 ?덉퐫?쒓? ?앹꽦?섎?濡?ORDER BY濡?理쒖떊 ?덉퐫?쒕쭔 議고쉶
    usage_query = text("""
        SELECT id, updated_date,
               DATE_ADD(COALESCE(updated_date, created_date), INTERVAL 3 DAY) as interest_end_date
        FROM tb_user_product_usage
        WHERE product_id = :product_id
        AND user_id = :user_id
        AND use_yn = 'Y'
        ORDER BY COALESCE(updated_date, created_date) DESC
        LIMIT 1
    """)
    usage_result = await db.execute(
        usage_query, {"product_id": product_id_to_int, "user_id": user_id}
    )
    usage_row = usage_result.mappings().one_or_none()

    if not usage_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="관심 작품 기록을 찾을 수 없습니다.",
        )

    now = datetime.now()

    # ?대떦 ?덉퐫?쒖쓽 updated_date ?낅뜲?댄듃
    update_query = text("""
        UPDATE tb_user_product_usage
        SET updated_date = :updated_date,
            updated_id = :updated_id
        WHERE id = :id
    """)
    await db.execute(
        update_query,
        {
            "updated_date": now,
            "updated_id": settings.DB_DML_DEFAULT_ID,
            "id": usage_row["id"],
        },
    )

    # ?덈줈??愿??醫낅즺??怨꾩궛 (?꾩옱 ?쒓컙 + 3??
    from datetime import timedelta

    interest_end_date = now + timedelta(days=3)

    return {
        "data": {
            "productId": product_id_to_int,
            "interestStatus": "interest_active",
            "interestEndDate": interest_end_date.isoformat(),
            "message": "관심이 성공적으로 활성화되었습니다",
        }
    }


async def suggest_products_by_recent_viewed(
    kc_user_id: str, adult_yn: str, db: AsyncSession
):
    """
    理쒓렐 蹂??묓뭹 湲곕컲 異붿쿇 ?묓뭹 議고쉶

    ?ъ슜?먭? 媛??理쒓렐??蹂??묓뭹??湲곕컲?쇰줈 ?좎궗???묓뭹?ㅼ쓣 異붿쿇?⑸땲??
    tb_algorithm_recommend_similar ?뚯씠釉붿쓽 ?곗씠?곕? ?쒖슜?⑸땲??

    Args:
        kc_user_id: ?꾩옱 ?ъ슜??keycloak ID
        adult_yn: ?깆씤 ?묓뭹 ?ы븿 ?щ? (Y | N)
        db: ?곗씠?곕쿋?댁뒪 ?몄뀡

    Returns:
        異붿쿇 ?묓뭹 紐⑸줉
    """
    try:
        # ?ъ슜??ID 議고쉶
        user_id = await get_user_id(kc_user_id, db)

        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 媛??理쒓렐??蹂??묓뭹 議고쉶
        recent_query = text("""
            SELECT product_id
            FROM tb_user_product_recent
            WHERE user_id = :user_id
              AND use_yn = 'Y'
            ORDER BY updated_date DESC
            LIMIT 1
        """)
        result = await db.execute(recent_query, {"user_id": user_id})
        recent_row = result.mappings().one_or_none()

        if recent_row is None:
            # 理쒓렐 蹂??묓뭹???놁쑝硫?鍮?諛곗뿴 諛섑솚
            return {"data": []}

        recent_product_id = recent_row["product_id"]

        # 理쒓렐 蹂??묓뭹 湲곕컲 異붿쿇 ?묓뭹 ID 議고쉶
        recommend_query = text("""
            SELECT similar_subject_ids
            FROM tb_algorithm_recommend_similar
            WHERE product_id = :product_id
            LIMIT 1
        """)
        result = await db.execute(recommend_query, {"product_id": recent_product_id})
        recommend_row = result.mappings().one_or_none()

        if recommend_row is None or not recommend_row["similar_subject_ids"]:
            # 異붿쿇 ?곗씠?곌? ?놁쑝硫?鍮?諛곗뿴 諛섑솚
            return {"data": []}

        # JSON ?뚯떛?섏뿬 異붿쿇 ?묓뭹 ID 由ъ뒪??異붿텧
        suggested_product_ids = json.loads(recommend_row["similar_subject_ids"])

        if not suggested_product_ids or len(suggested_product_ids) == 0:
            return {"data": []}

        # 異붿쿇 ?묓뭹 ?곸꽭 ?뺣낫 議고쉶
        adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
        filter_option = (
            f"p.product_id IN ({','.join(map(str, suggested_product_ids))}) AND p.open_yn = 'Y' {adult_filter}"
            if len(suggested_product_ids) > 1
            else f"p.product_id = {suggested_product_ids[0]} AND p.open_yn = 'Y' {adult_filter}"
        )

        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )

        products_query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE {filter_option}
        """)

        result = await db.execute(products_query, {})
        rows = result.mappings().all()

        return {"data": [convert_product_data(row) for row in rows]}

    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def get_direct_recommend_products(
    kc_user_id: str | None, db: AsyncSession, adult_yn: str = "N"
):
    """
    吏곸젒 異붿쿇 援ъ쥖 ?묓뭹 紐⑸줉 議고쉶

    愿由ъ옄媛 ?ㅼ젙??吏곸젒 異붿쿇 援ъ쥖???묓뭹?ㅼ쓣 議고쉶?⑸땲??
    ?몄텧 湲곌컙怨??쒓컙?瑜?怨좊젮?섏뿬 ?꾩옱 ?쒖꽦?붾맂 異붿쿇 援ъ쥖留?諛섑솚?⑸땲??

    Args:
        kc_user_id: ?꾩옱 ?ъ슜??keycloak ID (?좏깮)
        db: ?곗씠?곕쿋?댁뒪 ?몄뀡
        adult_yn: ?깆씤?깃툒 ?묓뭹 ?ы븿 ?щ? (Y/N)

    Returns:
        吏곸젒 異붿쿇 援ъ쥖 ?묓뭹 紐⑸줉
    """
    try:
        # ?ъ슜??ID 議고쉶 (濡쒓렇???곹깭 ?뺤씤?? ?꾩닔 ?꾨떂)
        user_id = None
        if kc_user_id:
            user_id = await get_user_id(kc_user_id, db)
            if user_id == -1:
                user_id = None

        # ?꾩옱 ?쒓컙 湲곗??쇰줈 ?쒖꽦?붾맂 吏곸젒 異붿쿇 援ъ쥖 議고쉶
        now = datetime.now()
        day_of_week = now.weekday()  # 0=?붿슂?? 6=?쇱슂??

        # ?됱씪(0-4) / 二쇰쭚(5-6) 援щ텇
        is_weekend = day_of_week >= 5

        # ?쒖꽦?붾맂 吏곸젒 異붿쿇 援ъ쥖 議고쉶
        # DB??UTC ?쒓컙?대?濡??쒓뎅 ?쒓컙(+9?쒓컙)?쇰줈 蹂?섑븯??鍮꾧탳
        if is_weekend:
            time_condition = """
                AND TIME(CONVERT_TZ(NOW(), '+00:00', '+09:00')) BETWEEN CAST(exposure_start_time_weekend AS TIME) AND CAST(exposure_end_time_weekend AS TIME)
            """
        else:
            time_condition = """
                AND TIME(CONVERT_TZ(NOW(), '+00:00', '+09:00')) BETWEEN CAST(exposure_start_time_weekday AS TIME) AND CAST(exposure_end_time_weekday AS TIME)
            """

        recommend_query = text(f"""
            SELECT id, name, product_ids, `order`
            FROM tb_direct_recommend
            WHERE CURDATE() BETWEEN DATE(exposure_start_date) AND DATE(exposure_end_date)
              {time_condition}
            ORDER BY `order` ASC
        """)

        result = await db.execute(recommend_query, {})
        recommend_rows = result.mappings().all()

        if not recommend_rows:
            return {"data": []}

        # 媛?異붿쿇 援ъ쥖蹂꾨줈 ?묓뭹 議고쉶
        results = []
        for recommend_row in recommend_rows:
            product_ids = json.loads(recommend_row["product_ids"])

            if not product_ids or len(product_ids) == 0:
                continue

            # ?묓뭹 ?곸꽭 ?뺣낫 議고쉶
            adult_filter = "AND p.ratings_code = 'all'" if adult_yn == "N" else ""
            filter_option = (
                f"p.product_id IN ({','.join(map(str, product_ids))}) AND p.open_yn = 'Y' {adult_filter}"
                if len(product_ids) > 1
                else f"p.product_id = {product_ids[0]} AND p.open_yn = 'Y' {adult_filter}"
            )

            query_parts = get_select_fields_and_joins_for_product(
                user_id=user_id, join_rank=False
            )

            products_query = text(f"""
                SELECT {query_parts["select_fields"]}
                FROM tb_product p
                {query_parts["joins"]}
                WHERE {filter_option}
            """)

            result = await db.execute(products_query, {})
            product_rows = result.mappings().all()

            # 異붿쿇 援ъ쥖 ?뺣낫? ?묓뭹 由ъ뒪?몃? ?④퍡 諛섑솚
            results.append(
                {
                    "recommendId": recommend_row["id"],
                    "title": recommend_row["name"],
                    "order": recommend_row["order"],
                    "productList": [convert_product_data(row) for row in product_rows],
                }
            )

        return {"data": results}

    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )


async def get_can_create_normal(kc_user_id: str, db: AsyncSession):
    """일반연재 자격 확인: 기존 승급된 작품이 1개 이상 있으면 True"""
    query = text("""
        SELECT 1 FROM tb_product
        WHERE user_id = (SELECT user_id FROM tb_user WHERE kc_user_id = :kc_user_id AND use_yn = 'Y')
          AND product_type = 'normal'
        LIMIT 1
    """)
    result = await db.execute(query, {"kc_user_id": kc_user_id})
    return {"can_create_normal": result.scalar() is not None}
