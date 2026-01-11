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

from app.config.log_config import service_error_logger

from collections import defaultdict
import app.services.common.statistics_service as statistics_service
import app.schemas.user_giftbook as user_giftbook_schema
import app.services.user.user_giftbook_service as user_giftbook_service

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)
logger = logging.getLogger(__name__)

"""
products 도메인 개별 서비스 함수 모음
"""


def get_select_fields_and_joins_for_product(
    user_id: int | None = None, join_rank: bool = False
):
    return {
        "select_fields": ",".join(
            [
                "p.product_id as productId",
                "if(p.ratings_code = 'adult', 'Y', 'N') as adultYn",
                "p.title",
                "p.synopsis_text as synopsis",
                "p.author_name as authorNickname",
                "p.price_type as priceType",
                "p.illustrator_name as illustratorNickname",
                "ifnull(p.product_type, 'free') as productType",
                "p.created_date as createdDate",
                "p.updated_date as updatedDate",
                "p.author_id as authorId",
                "(SELECT GROUP_CONCAT(DISTINCT sk2.keyword_name SEPARATOR '|') FROM tb_mapped_product_keyword mpk2 LEFT JOIN tb_standard_keyword sk2 ON sk2.keyword_id = mpk2.keyword_id WHERE mpk2.product_id = p.product_id) as keywords",
                "pg.keyword_name as primary_genre",
                "sg.keyword_name as sub_genre",
                "pr.current_rank" if join_rank else "NULL as current_rank",
                "(pr.privious_rank - pr.current_rank) as rank_indicator"
                if join_rank
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
                "if(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') as newReleaseYn",
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
            LEFT JOIN tb_batch_daily_product_count_summary pdcs ON pdcs.product_id = p.product_id
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
                    FIRST_VALUE(CONCAT('정산비 CP ', offer_profit, ' : 작가 ', author_profit)) OVER (PARTITION BY product_id ORDER BY created_date DESC) as settlement_ratio,
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
    )  # 기다리면 무료 프로모션 진행 여부
    data["badge"]["sixNinePathYn"] = (
        "Y" if data.get("sixNinePathStatus") == "ing" else "N"
    )  # 6-9 패스 프로모션 진행 여부
    # data["badge"]["freeEpisodes"] = data.pop("freeEpisodes") if data.get("freeEpisodes") is not None else 0 # 첫 방문자 무료 이용권 지정 수 - n화무 아이콘 표시 -> 이거 사용 안함
    data["badge"]["newReleaseYn"] = data.pop(
        "newReleaseYn"
    )  # 최신 회자 - UP 아이콘 표시
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
    # data["trendindex"]["notRecommendCount"] = 0 # 비추천 기능 구현 안됨
    # data["trendindex"]["notRecommendIndicator"] = 0 # 비추천 기능 구현 안됨
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
    data["trendindex"]["primaryReaderGroup"] = (
        data.pop("primaryReaderGroup")
        if data.get("primaryReaderGroup") is not None
        else ""
    )
    data["properties"] = dict()
    data["properties"]["updateFrequency"] = data.pop("publish_days")
    data["properties"]["averageWeeklyEpisodes"] = (
        data.pop("averageWeeklyEpisodes")
        if data.get("averageWeeklyEpisodes") is not None
        else 0
    )
    # data["properties"]["remarkContentSnippet"] = "" # 관리자가 입력하는 비고 텍스트 - 미구현 상태
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
    작품 일별 조회수 로그 저장
    오늘 날짜의 조회수를 +1 증가
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
        # 로그 저장 실패는 메인 로직에 영향을 주지 않도록 예외를 무시


async def products_of_managed(
    division: str,
    area: str,
    limit: int | None,
    adult_yn: str,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    메인, 유료Top50, 무료Top50 작품 목록 조회
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
    # 성인등급 필터링: adult_yn이 N이면 전체이용가만 조회
    if adult_yn == "N":
        filter_option.append('p.ratings_code = "all"')
    # if division is not None:
    #     # 이거 main으로만 받는거 같은데 굳이 필터가 있을 필요가 있나? tb_product에 division이 없기도 하고 일단 뺴자
    #     filter_option.append(f'division = "{division}"')
    order_by = "p.product_id DESC"
    join_rank = False
    if area is not None:
        if area == "freeTop":
            filter_option.append('p.price_type = "free"')
            order_by = "pr.current_rank ASC"
            join_rank = True
        elif area == "paidTop":
            filter_option.append('p.price_type = "paid"')
            order_by = "pr.current_rank ASC"
            join_rank = True

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=join_rank
    )
    query = text(f"""
        SELECT {query_parts["select_fields"]}, concat(p.price_type, 'Top') as area
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

    # 비공개 작품 필터링 후 순위 재할당 (freeTop, paidTop인 경우)
    if join_rank:
        for idx, item in enumerate(res_data, start=1):
            if "rank" in item:
                item["rank"]["currentRank"] = idx

    res_body["data"] = res_data

    return res_body


async def product_by_product_id(product_id: str, kc_user_id: str, db: AsyncSession):
    """
    작품 정보 조회
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
    작품 목록 전체 조회(유료, 무료)
    """
    page = page if page else settings.PAGINATION_DEFAULT_PAGE_NO
    limit = limit if limit else settings.PAGINATION_PRODUCT_DEFAULT_LIMIT

    # 필터 옵션 설정
    filter_option = []
    if price_type is not None:
        filter_option.append(f'p.price_type = "{price_type}"')
    if product_type is not None:
        if product_type == "free":
            filter_option.append("p.product_type is null")
        else:
            filter_option.append(f'p.product_type = "{product_type}"')
    if product_state is not None:
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

    # 성인 작품 필터링
    # adult_yn='Y'이고 로그인 상태이고 19세 이상인 경우에만 성인 작품 포함
    # 그 외 모든 경우(미로그인, 19세 미만, adult_yn='N')는 성인 작품 제외
    if user_id == -1:
        # 미로그인 상태: 성인 작품 제외
        filter_option.append("p.ratings_code = 'all'")
    elif adult_yn != "Y":
        # 로그인 상태이지만 adult_yn='N'인 경우: 성인 작품 제외
        filter_option.append("p.ratings_code = 'all'")
    else:
        # adult_yn='Y'인 경우: 사용자 나이 확인
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
                # 19세 미만: 성인 작품 제외
                filter_option.append("p.ratings_code = 'all'")
        # 19세 이상이고 adult_yn='Y'인 경우: 필터 추가 안함 (성인 작품 포함)

    query_parts = get_select_fields_and_joins_for_product(
        user_id=user_id, join_rank=False
    )
    filter_option.append("p.open_yn = 'Y'")
    query = text(f"""
        SELECT {query_parts["select_fields"]}
        FROM tb_product p
        {query_parts["joins"]}
        WHERE {" and ".join(filter_option)}
        ORDER BY p.last_episode_date DESC
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
    작품 - 에피소드 목록
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
                    (product_id = e.product_id and episode_id is null)
                    or
                    product_id is null
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
                        (product_id = e.product_id and episode_id is null)
                        or
                        product_id is null
                    ) and user_id = :user_id and own_type = 'rental' and use_yn = 'Y'
                    order by id desc limit 1
                ) as rentalRemaining
            from tb_product_episode e where product_id = :product_id and e.open_yn = 'Y' and e.use_yn = 'Y'
            order by {order_by} {order_dir}
            limit {limit} offset {(page - 1) * limit}
        """)
        result = await db.execute(query, {"user_id": user_id, "product_id": product_id})
        rows = result.mappings().all()
        episodes = [dict(row) for row in rows]

        # rentalRemaining JSON 파싱
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

        # 그룹핑 딕셔너리 생성
        grouped_results = dict()
        grouped_results["episodes"] = episodes
        grouped_results["usage"] = usage

        # 전체 에피소드 갯수 조회
        count_query = text("""
            select count(*) as total
            from tb_product_episode where product_id = :product_id and open_yn = 'Y' and use_yn = 'Y'
        """)
        count_result = await db.execute(count_query, {"product_id": product_id})
        episodeTotalCount = count_result.scalar()

        # 사용자 읽은 최종 회차
        max_episode_no = 0
        max_episode_id = max(
            (hit.get("episodeId", 0) for hit in grouped_results["usage"])
            if grouped_results["usage"]
            else [0]
        )
        min_episode_id = min(
            (hit.get("episodeId", 0) for hit in grouped_results["episodes"])
            if grouped_results["episodes"]
            else [0]
        )

        # max_episode_id에 해당하는 episode_no를 별도로 조회
        if max_episode_id > 0:
            episode_no_query = text("""
                select episode_no as episodeNo
                from tb_product_episode
                where episode_id = :episode_id
            """)
            episode_no_result = await db.execute(
                episode_no_query, {"episode_id": max_episode_id}
            )
            episode_no_row = episode_no_result.scalar()
            if episode_no_row:
                max_episode_no = episode_no_row

        # usage 데이터의 episodeId가 episodes에도 존재하는지 확인
        combined_new_episodes = []
        if user_id and "usage" in grouped_results and "episodes" in grouped_results:
            for episode in grouped_results["episodes"]:
                for usage in grouped_results["usage"]:
                    # 읽음여부, 추천여부
                    if usage.get("episodeId", 0) == episode.get("episodeId", -1):
                        # 일치하는 에피소드 정보에 사용 정보 추가 (읽음여부, 추천여부)
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
                # usage 정보가 없는 경우 -> 읽은적이 없어서 그런거니 둘 다 N으로 세팅
                episode["usage"] = {"readYn": "N", "recommendYn": "N"}

        if max_episode_id == 0:
            max_episode_id = min_episode_id

        res_body = dict()
        res_body["data"] = {
            "latestEpisodeNo": max_episode_no,
            "latestEpisodeId": max_episode_id,
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
    작품 상세 그룹 - 작품 상세, 작품 평가, 작품 공지, 에피소드 목록을 묶어서 응답

    NOTE: 작가가 자신의 작품을 조회할 때는 비공개 작품도 조회 가능해야 함 (작품 수정을 위해)
    """
    try:
        user_id = await get_user_id(kc_user_id, db)

        query_parts = get_select_fields_and_joins_for_product(
            user_id=user_id, join_rank=False
        )
        # 작가가 자신의 작품을 조회하는 경우 비공개 작품도 조회 가능
        # 다른 사용자는 공개된 작품만 조회 가능
        query = text(f"""
            SELECT {query_parts["select_fields"]}
            FROM tb_product p
            {query_parts["joins"]}
            WHERE p.product_id = :product_id
              AND (p.open_yn = 'Y' OR p.user_id = :user_id)
        """)
        result = await db.execute(query, {"product_id": product_id, "user_id": user_id})
        rows = result.mappings().all()
        product = convert_product_data(rows[0]) if rows else None

        # 로그인한 사용자인 경우 ownType 조회를 위해 user_id 전달
        episode_query_params = {"product_id": product_id}
        own_type_query = ""
        if user_id and user_id != -1:
            episode_query_params["user_id"] = user_id
            own_type_query = """
                , (select own_type from tb_user_productbook where (
                    episode_id = e.episode_id
                    or
                    (product_id = e.product_id and episode_id is null)
                    or
                    product_id is null
                ) and user_id = :user_id and use_yn = 'Y'
                and (rental_expired_date IS NULL OR rental_expired_date > NOW())
                order by id desc limit 1) as ownType
            """

        query = text(f"""
            select
                episode_id as episodeId,
                product_id as productId,
                episode_no as episodeNo,
                episode_title as episodeTitle,
                episode_text_count as episodeTextCount,
                comment_open_yn as commentOpenYn,
                count_evaluation as countEvaluation,
                COALESCE((
                    select count_evaluation_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countEvaluationIndicator,
                count_comment as countComment,
                COALESCE((
                    select count_comment_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countCommentIndicator,
                price_type as priceType,
                evaluation_open_yn as evaluationOpenYn,
                publish_reserve_date as publishReserveDate,
                count_hit as countHit,
                COALESCE((
                    select count_hit_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countHitIndicator,
                count_recommend as countRecommend,
                COALESCE((
                    select count_recommend_indicator
                    from tb_product_episode_count_variance
                    where episode_id = e.episode_id
                    order by created_date desc limit 1
                ), 0) as countRecommendIndicator,
                open_yn as episodeOpenYn,
                (select count(*) from tb_product_episode_like where episode_id = e.episode_id) as countLike,
                COALESCE((
                    select count(*) - count(*) +
                           (select count(*) from tb_product_episode_like where episode_id = e.episode_id) -
                           (select count(*) from tb_product_episode_like where episode_id = e.episode_id
                            and DATE(created_date) <= CURDATE() - INTERVAL 1 DAY)
                    from dual
                ), 0) as countLikeIndicator,
                created_date as createdDate
                {own_type_query}
            from tb_product_episode e where product_id = :product_id and e.use_yn = 'Y'
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
                    # 읽음여부, 추천여부
                    if usage.get("episodeId", 0) == episode.get("episodeId", -1):
                        # 일치하는 에피소드 정보에 사용 정보 추가 (읽음여부, 추천여부)
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

        # 새로 지급된 대여권 알림 정보
        issued_vouchers = []

        # 첫 방문자 무료 이용권 자동 발급 (free-for-first) -> 선물함으로 지급
        if user_id and user_id != -1:
            # 이 작품을 이전에 방문한 적이 있는지 체크 (tb_user_product_usage에 기록이 있는지)
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

            # 첫 방문인 경우 (visit_count == 0)
            if visit_count == 0:
                # 진행중인 free-for-first 프로모션 조회
                query = text("""
                    select dp.id, dp.num_of_ticket_per_person, dp.type
                      from tb_direct_promotion dp
                     where dp.product_id = :product_id
                       and dp.type = 'free-for-first'
                       and dp.status = 'ing'
                """)
                result = await db.execute(query, {"product_id": product_id})
                promotion = result.mappings().one_or_none()

                if promotion:
                    # 이미 이 프로모션으로 선물함에 받았는지 체크 (선물함 또는 대여권)
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

                    # 아직 받지 않았으면 선물함으로 발급
                    if already_received == 0:
                        num_of_ticket = promotion["num_of_ticket_per_person"]
                        # 첫방문자 무료: 유효기간 없음 (프로모션 종료 시 만료)
                        # expiration_date = None, ticket_expiration_type = 'none'
                        giftbook_req = user_giftbook_schema.PostUserGiftbookReqBody(
                            user_id=user_id,
                            product_id=product_id,
                            episode_id=None,
                            ticket_type=promotion["type"],
                            own_type="rental",
                            acquisition_type="direct_promotion",
                            acquisition_id=promotion["id"],
                            reason="첫방문자 무료 대여권",
                            amount=num_of_ticket,
                            promotion_type="free-for-first",
                            expiration_date=None,  # 유효기간 없음 (프로모션 종료 시 만료)
                            ticket_expiration_type="none",  # 수령 후 대여권 유효기간 없음
                            ticket_expiration_value=None,
                        )
                        await user_giftbook_service.post_user_giftbook(
                            req_body=giftbook_req,
                            kc_user_id="",
                            db=db,
                            user_id=user_id,
                        )
                        # 알림 정보 추가
                        issued_vouchers.append(
                            {
                                "type": "free-for-first",
                                "amount": num_of_ticket,
                                "message": f"첫방문자 무료 대여권이 {num_of_ticket}장 지급 되었습니다.",
                            }
                        )

        # 6-9 패스 자동 발급 -> 선물함으로 지급
        if user_id and user_id != -1:
            # 현재 시간 확인 (6-9시 또는 18-21시) - KST 기준
            from zoneinfo import ZoneInfo

            kst_now = datetime.now(ZoneInfo("Asia/Seoul"))
            current_hour = kst_now.hour
            if (6 <= current_hour < 9) or (18 <= current_hour < 21):
                # 진행중인 6-9-path 프로모션 조회
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
                    # 오늘 이미 선물함에 받았는지 체크
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

                    # 오늘 아직 받지 않았으면 선물함으로 발급
                    if received_today == 0:
                        # 6-9패스: 유효기간 하루 (수령 시점부터)
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
                            expiration_date=None,  # 선물함 유효기간 없음
                            ticket_expiration_type="on_receive_days",  # 수령 시점부터 N일
                            ticket_expiration_value=1,  # 하루
                        )
                        await user_giftbook_service.post_user_giftbook(
                            req_body=giftbook_req,
                            kc_user_id="",
                            db=db,
                            user_id=user_id,
                        )
                        # 알림 정보 추가
                        issued_vouchers.append(
                            {
                                "type": "6-9-path",
                                "amount": 1,
                                "message": "6-9패스 대여권이 지급 되었습니다.",
                            }
                        )

        # 기다리면 무료 (waiting-for-free) 최초 1개 자동 발급 -> 선물함으로 지급
        if user_id and user_id != -1:
            # 진행중인 waiting-for-free 프로모션 조회
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
                # 이미 이 프로모션으로 선물함에 받았는지 체크
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

                # 아직 받지 않았으면 선물함으로 1개 발급
                if already_received == 0:
                    # 기다리면 무료: 유효기간 없음
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
                        expiration_date=None,  # 선물함 유효기간 없음
                        ticket_expiration_type="none",  # 수령 후 대여권 유효기간 없음
                        ticket_expiration_value=None,
                    )
                    await user_giftbook_service.post_user_giftbook(
                        req_body=giftbook_req,
                        kc_user_id="",
                        db=db,
                        user_id=user_id,
                    )
                    # 알림 정보 추가
                    issued_vouchers.append(
                        {
                            "type": "waiting-for-free",
                            "amount": 1,
                            "message": "기다리면 무료 대여권이 지급 되었습니다.",
                        }
                    )

        # 지급된 대여권 알림 정보를 응답에 추가
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
    작품 평가 조회
    """

    try:
        # 필터 옵션 설정
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
    작품 상세 - 추천작품 조회
    """

    try:
        # 필터 옵션 설정
        filter_option = [f'product_id = "{product_id}"']
        if nearby is not None:
            filter_option.append(f'type = "{nearby}"')

        query = text(f"""
            select similar_subject_ids
            from tb_algorithm_recommend_similar
            where {" and ".join(filter_option)}
        """)
        result = await db.execute(query, {})
        row = result.mappings().one_or_none()

        if row is None:
            res_body = dict()
            res_body["data"] = []
            return res_body

        suggested_results = json.loads(dict(row).get("similar_subject_ids"))

        if len(suggested_results) > 0:
            # 필터 옵션 설정
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


async def suggest_managed_products(
    db: AsyncSession, kc_user_id: str | None = None, adult_yn: str = "N"
):
    """
    메인 - 추천작품 조회

    tb_algorithm_recommend_section 에서
    로그인 상태에 따라
    첫번째~네번째 섹션 비로그인(2,3,4,5)
    첫번째~네번째 섹션 로그인(6,7,8,9)
    에 해당하는 feature를 가져와서
    tb_algorithm_recommend_set_topic 에서 feature가 일치하는 항목들을 가져온다.
    """

    try:
        # 사용자별 feature 값을 조회하여 필터링
        user_features = {}  # feature명 -> target 번호 매핑
        section_features = []  # 추천 섹션의 feature 목록 (순서대로)

        if kc_user_id is not None:
            # 로그인 유저: 사용자별 feature 조회
            user_id = await get_user_id(kc_user_id, db)

            # 사용자의 feature 값 조회
            query = text("""
                SELECT feature_1, feature_2, feature_3, feature_4, feature_5,
                       feature_6, feature_7, feature_8, feature_9, feature_10, feature_basic
                FROM tb_algorithm_recommend_user
                WHERE user_id = :user_id
            """)
            result = await db.execute(query, {"user_id": user_id})
            user_feature_row = result.mappings().one_or_none()

            if user_feature_row:
                # 사용자의 feature 값이 있는 경우
                user_feature_data = dict(user_feature_row)

                # feature_1~10, feature_basic까지 매핑 저장
                for i in range(1, 11):
                    feature_key = f"feature_{i}"
                    target_value = user_feature_data.get(feature_key)
                    if target_value is not None and target_value != 0:
                        user_features[feature_key] = target_value

                # feature_basic도 매핑 (male, female 등)
                feature_basic_value = user_feature_data.get("feature_basic")
                if feature_basic_value:
                    user_features["feature_basic"] = feature_basic_value

                # 로그인 시 추천 섹션 (id 6,7,8,9) 조회
                query = text("""
                    SELECT feature FROM tb_algorithm_recommend_section
                    WHERE id IN (6, 7, 8, 9)
                    ORDER BY id
                """)
                result = await db.execute(query, {})
                rows = result.mappings().all()
                section_features = [dict(row).get("feature") for row in rows]
            else:
                # 사용자의 feature 값이 없는 경우: 비로그인과 동일
                query = text("""
                    SELECT feature FROM tb_algorithm_recommend_section
                    WHERE id IN (2, 3, 4, 5)
                    ORDER BY id
                """)
                result = await db.execute(query, {})
                rows = result.mappings().all()
                section_features = [dict(row).get("feature") for row in rows]
        else:
            # 비로그인: default 섹션만 (id 2,3,4,5)
            query = text("""
                SELECT feature FROM tb_algorithm_recommend_section
                WHERE id IN (2, 3, 4, 5)
                ORDER BY id
            """)
            result = await db.execute(query, {})
            rows = result.mappings().all()
            section_features = [dict(row).get("feature") for row in rows]

        # 검색 결과
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

        # 각 섹션별로 정확히 1개씩만 가져오기
        for feature_name in section_features:
            if not feature_name:
                continue

            # default인 경우 target 없이 조회
            if feature_name.startswith("default_"):
                query = text("""
                    SELECT *
                    FROM tb_algorithm_recommend_set_topic
                    WHERE feature = :feature
                    LIMIT 1
                """)
                result = await db.execute(query, {"feature": feature_name})
                hit = result.mappings().one_or_none()
            # feature인 경우 사용자의 target과 매칭
            else:
                # 사용자의 해당 feature target 값 확인
                target_value = user_features.get(feature_name)

                if target_value is None:
                    # 사용자에게 할당된 feature가 없으면 기본값 1 사용
                    target_value = 1

                # feature와 target이 일치하는 레코드 조회
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
    작가의 다른 작품 목록
    """
    page = page if page else settings.PAGINATION_DEFAULT_PAGE_NO
    limit = limit if limit else settings.PAGINATION_DEFAULT_LIMIT
    order_by = order_by if order_by else "createdDate"
    order_dir = order_dir if order_dir else settings.PAGINATION_ORDER_DIRECTION_DESC

    try:
        # 필터 옵션 설정
        filter_option = [f'p.author_id = "{author_id}"']
        if author_nickname is not None:
            filter_option.append(f'p.author_name = "{author_nickname}"')
        if price_type is not None:
            filter_option.append(f'p.price_type = "{price_type}"')
        if adult_yn is not None:
            # adult_yn='Y': 전체 조회 (성인 포함), adult_yn='N': 성인 제외 (all만)
            if adult_yn == "N":
                filter_option.append('p.ratings_code = "all"')
            # adult_yn='Y'일 경우 필터 추가 안함 (전체 조회)
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

            # 랜덤 생성 uuid 중복 체크
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
                # 일반승급: 글자수 20,000자 이상, 5회차 이상
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
                                and major_genre_yn = 'Y'
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
                                    , a.monopoly_yn
                                    , a.contract_yn
                                    , a.paid_open_date as paid_setting_date
                                    , a.paid_episode_no
                                    , a.price_type
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
                    "monopolyYn": db_rst[0].get("monopoly_yn"),
                    "cpContractYn": db_rst[0].get("contract_yn"),
                    "paidSettingDate": db_rst[0].get("paid_setting_date"),
                    "paidEpisodeNo": db_rst[0].get("paid_episode_no"),
                    "priceType": db_rst[0].get("price_type"),
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


async def post_products(
    req_body: product_schema.PostProductsReqBody, kc_user_id: str, db: AsyncSession
):
    if kc_user_id:
        # 연재요일 검증
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

                # 중복 작품 생성 방지 (10초 내 동일 제목)
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

                # 연재상태 검증
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

                # 작가명 검증
                query = text("""
                                 select user_id
                                   from tb_user_profile
                                  where nickname = :nickname
                                 """)

                result = await db.execute(query, {"nickname": req_body.author_nickname})
                db_rst = result.mappings().all()

                author_id = None
                if db_rst:
                    author_id = db_rst[0].get("user_id")
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_NICKNAME_INFO,
                    )

                # 1차 장르 검증
                query = text("""
                                 select keyword_id
                                      , keyword_name
                                   from tb_standard_keyword
                                  where use_yn = 'Y'
                                    and major_genre_yn = 'Y'
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

                # 2차 장르 검증
                sub_genre_id = None
                if db_rst:
                    if req_body.sub_genre is None or req_body.sub_genre == "":
                        pass
                    else:
                        for row in db_rst:
                            if req_body.sub_genre == row["keyword_name"]:
                                sub_genre_id = row["keyword_id"]
                                break

                        if sub_genre_id is None:
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_PRODUCT_INFO,
                            )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # 키워드 검증
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

                query = text("""
                                 insert into tb_product (title, price_type, status_code, ratings_code, synopsis_text, user_id, author_id, author_name, illustrator_name, publish_regular_yn, publish_days, thumbnail_file_id, primary_genre_id, sub_genre_id, open_yn, monopoly_yn, contract_yn, created_id, updated_id)
                                 select :title, :price_type, :status_code, :ratings_code, :synopsis_text, user_id, :author_id, :author_name, :illustrator_name, :publish_regular_yn, :publish_days, :thumbnail_file_id, :primary_genre_id, :sub_genre_id, :open_yn, :monopoly_yn, :contract_yn, :created_id, :updated_id
                                   from tb_user
                                  where kc_user_id = :kc_user_id
                                    and use_yn = 'Y'
                                 """)

                await db.execute(
                    query,
                    {
                        "kc_user_id": kc_user_id,
                        "price_type": "free",
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
                        "open_yn": req_body.open_yn,
                        "monopoly_yn": req_body.monopoly_yn,
                        "contract_yn": req_body.cp_contract_yn,
                        "created_id": settings.DB_DML_DEFAULT_ID,
                        "updated_id": settings.DB_DML_DEFAULT_ID,
                    },
                )

                query = text("""
                                 select last_insert_id()
                                 """)

                result = await db.execute(query)
                new_product_id = result.scalar()

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

                # tb_ptn_product_statistics 초기 데이터 생성 (파트너 통계용)
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

                # TODO 최상단 작가인 경우 업로드 알람 생성
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


async def put_products_product_id(
    product_id: str,
    req_body: product_schema.PutProductsProductIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    product_id_to_int = int(product_id)

    if kc_user_id:
        # 연재요일 검증
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

                # 연재상태 검증
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

                # 작가명 검증
                query = text("""
                                 select user_id
                                   from tb_user_profile
                                  where nickname = :nickname
                                 """)

                result = await db.execute(query, {"nickname": req_body.author_nickname})
                db_rst = result.mappings().all()

                author_id = None
                if db_rst:
                    author_id = db_rst[0].get("user_id")
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_NICKNAME_INFO,
                    )

                # 1차 장르 검증
                query = text("""
                                 select keyword_id
                                      , keyword_name
                                   from tb_standard_keyword
                                  where use_yn = 'Y'
                                    and major_genre_yn = 'Y'
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

                # 2차 장르 검증
                sub_genre_id = None
                if db_rst:
                    if req_body.sub_genre is None or req_body.sub_genre == "":
                        pass
                    else:
                        for row in db_rst:
                            if req_body.sub_genre == row["keyword_name"]:
                                sub_genre_id = row["keyword_id"]
                                break

                        if sub_genre_id is None:
                            raise CustomResponseException(
                                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                                message=ErrorMessages.INVALID_PRODUCT_INFO,
                            )
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_PRODUCT_INFO,
                    )

                # 키워드 검증
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

                # 무료 작품인 경우 유료 관련 값 무시
                check_price_type_query = text("""
                    SELECT price_type FROM tb_product WHERE product_id = :product_id
                """)
                price_type_result = await db.execute(check_price_type_query, {"product_id": product_id_to_int})
                price_type_row = price_type_result.mappings().first()

                if price_type_row and price_type_row["price_type"] == "free":
                    req_body.paid_setting_date = None
                    req_body.paid_episode_no = None

                # 유료 검증
                if req_body.paid_setting_date or (
                    req_body.paid_episode_no and req_body.paid_episode_no != 0
                ):
                    query = text("""
                                     select 1
                                       from tb_product a
                                      inner join tb_product_paid_apply b on a.product_id = b.product_id
                                        and b.use_yn = 'Y'
                                        and b.status_code = 'accepted'
                                      where a.product_id = :product_id
                                        and a.price_type = 'paid'
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
                                          , a.monopoly_yn = :monopoly_yn
                                          , a.contract_yn = :contract_yn
                                          , a.paid_open_date = :paid_open_date
                                          , a.paid_episode_no = :paid_episode_no
                                          , a.updated_id = a.user_id
                                      where a.product_id = :product_id
                                        and exists (select 1 from tb_user z
                                                     where z.kc_user_id = :kc_user_id
                                                       and z.use_yn = 'Y'
                                                       and z.user_id = a.user_id)
                                     """)

                    await db.execute(
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
                            "open_yn": req_body.open_yn,
                            "monopoly_yn": req_body.monopoly_yn,
                            "contract_yn": req_body.cp_contract_yn,
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
                                          , a.monopoly_yn = :monopoly_yn
                                          , a.contract_yn = :contract_yn
                                          , a.paid_open_date = :paid_open_date
                                          , a.paid_episode_no = :paid_episode_no
                                          , a.updated_id = a.user_id
                                      where a.product_id = :product_id
                                        and exists (select 1 from tb_user z
                                                     where z.kc_user_id = :kc_user_id
                                                       and z.use_yn = 'Y'
                                                       and z.user_id = a.user_id)
                                     """)

                    await db.execute(
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
                            "open_yn": req_body.open_yn,
                            "monopoly_yn": req_body.monopoly_yn,
                            "contract_yn": req_body.cp_contract_yn,
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
                    # 일반승급: 글자수 20,000자 이상, 5회차 이상 (조건만 만족하면 바로 승급 처리)
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
                    # 유료전환: 최대 2번 신청 가능, 심사 후 승인하면 승급 처리
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
    """평가 코드별 개수를 집계하는 내부 함수"""
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

                    # 에피소드 정보 조회 (latestEpisodeNo, firstEpisodeId)
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

                    # 사용자의 최근 읽은 에피소드 조회 (lastViewedEpisodeId, lastViewedEpisodeNo)
                    recent_read_map = {}
                    if user_id:
                        recent_read_query = text(f"""
                            SELECT
                                upu.product_id,
                                upu.episode_id as last_viewed_episode_id,
                                pe.episode_no as last_viewed_episode_no
                            FROM tb_user_product_usage upu
                            INNER JOIN (
                                SELECT product_id, MAX(updated_date) as max_date
                                FROM tb_user_product_usage
                                WHERE user_id = :user_id
                                  AND product_id IN ({fetch_product_ids})
                                  AND use_yn = 'Y'
                                GROUP BY product_id
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

                    # 에피소드 정보를 각 작품 데이터에 추가
                    for product in res_data:
                        product_id = product.get("productId")

                        # 에피소드 정보 추가
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

                        # 최근 읽은 에피소드 정보 추가
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

                    # 필터 옵션 설정
                    filter_option = []
                    filter_option.append(f"p.product_id IN ({fetch_product_ids})")
                    filter_option.append("p.open_yn = 'Y'")
                    # 성인등급 필터링: adult_yn이 N이면 전체이용가만 조회
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
    유/무료 top 50 조회
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
    출판사 프로모션 상품 리스트 조회
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

    res_body = dict()
    res_body["data"] = [convert_product_data(row) for row in rows]

    return res_body


async def products_in_latest_update(
    kc_user_id: str, db: AsyncSession, adult_yn: str = "N"
):
    """
    최신 업데이트 상품 리스트 조회
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


async def products_in_applied_promotion(type: str, kc_user_id: str, db: AsyncSession):
    """
    신청 프로모션 상품 리스트 조회
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
    """)
    result = await db.execute(query, {"type": type})
    rows = result.mappings().all()

    res_body = dict()
    res_body["data"] = {}
    for row in rows:
        data = convert_product_data(row)
        start_date: datetime = row.get("promotion_start_date")
        end_date: datetime | None = row.get("promotion_end_date")

        # start_date부터 end_date까지 날짜별로 데이터를 분류
        current_date = start_date.date() if start_date else None
        end_date_only = end_date.date() if end_date else None

        if current_date:
            if end_date_only:
                # end_date가 있으면 start_date부터 end_date까지 범위 내 모든 날짜에 추가
                # 안전장치: 최대 10년(3650일)까지만 처리
                days_processed = 0
                while current_date <= end_date_only and days_processed < 3650:
                    date_str = current_date.isoformat()
                    if date_str not in res_body["data"]:
                        res_body["data"][date_str] = []
                    res_body["data"][date_str].append(data)
                    current_date += timedelta(days=1)
                    days_processed += 1
            else:
                # end_date가 없으면 start_date에만 추가
                date_str = current_date.isoformat()
                if date_str not in res_body["data"]:
                    res_body["data"][date_str] = []
                res_body["data"][date_str].append(data)

    # 날짜를 역순(최신 날짜부터)으로 정렬
    res_body["data"] = dict(sorted(res_body["data"].items(), reverse=True))

    return res_body


async def post_product_report(
    product_id: str,
    req_body: product_schema.PostProductReportReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    작품 신고
    """
    product_id_to_int = int(product_id)
    if kc_user_id:
        try:
            async with db.begin():
                # 사용자 확인
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
    관심 되살리기: 관심끊기기 임박 상태를 관심 유지중으로 변경
    tb_user_product_usage의 updated_date를 현재 시간으로 업데이트
    """
    try:
        product_id_to_int = int(product_id)
    except ValueError:
        raise CustomResponseException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            message="유효하지 않은 작품 ID입니다.",
        )

    # kc_user_id로 user_id 조회
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 작품 존재 여부 확인
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

    # tb_user_product_usage에서 가장 최근 레코드 조회
    # 이 테이블은 episode_id별로 레코드가 생성되므로 ORDER BY로 최신 레코드만 조회
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

    # 해당 레코드의 updated_date 업데이트
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

    # 새로운 관심 종료일 계산 (현재 시간 + 3일)
    from datetime import timedelta

    interest_end_date = now + timedelta(days=3)

    return {
        "data": {
            "productId": product_id_to_int,
            "interestStatus": "interest_active",
            "interestEndDate": interest_end_date.isoformat(),
            "message": "관심이 성공적으로 되살아났습니다.",
        }
    }


async def suggest_products_by_recent_viewed(
    kc_user_id: str, adult_yn: str, db: AsyncSession
):
    """
    최근 본 작품 기반 추천 작품 조회

    사용자가 가장 최근에 본 작품을 기반으로 유사한 작품들을 추천합니다.
    tb_algorithm_recommend_similar 테이블의 데이터를 활용합니다.

    Args:
        kc_user_id: 현재 사용자 keycloak ID
        adult_yn: 성인 작품 포함 여부 (Y | N)
        db: 데이터베이스 세션

    Returns:
        추천 작품 목록
    """
    try:
        # 사용자 ID 조회
        user_id = await get_user_id(kc_user_id, db)

        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # 가장 최근에 본 작품 조회
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
            # 최근 본 작품이 없으면 빈 배열 반환
            return {"data": []}

        recent_product_id = recent_row["product_id"]

        # 최근 본 작품 기반 추천 작품 ID 조회
        recommend_query = text("""
            SELECT similar_subject_ids
            FROM tb_algorithm_recommend_similar
            WHERE product_id = :product_id
            LIMIT 1
        """)
        result = await db.execute(recommend_query, {"product_id": recent_product_id})
        recommend_row = result.mappings().one_or_none()

        if recommend_row is None or not recommend_row["similar_subject_ids"]:
            # 추천 데이터가 없으면 빈 배열 반환
            return {"data": []}

        # JSON 파싱하여 추천 작품 ID 리스트 추출
        suggested_product_ids = json.loads(recommend_row["similar_subject_ids"])

        if not suggested_product_ids or len(suggested_product_ids) == 0:
            return {"data": []}

        # 추천 작품 상세 정보 조회
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
    직접 추천 구좌 작품 목록 조회

    관리자가 설정한 직접 추천 구좌의 작품들을 조회합니다.
    노출 기간과 시간대를 고려하여 현재 활성화된 추천 구좌만 반환합니다.

    Args:
        kc_user_id: 현재 사용자 keycloak ID (선택)
        db: 데이터베이스 세션
        adult_yn: 성인등급 작품 포함 여부 (Y/N)

    Returns:
        직접 추천 구좌 작품 목록
    """
    try:
        # 사용자 ID 조회 (로그인 상태 확인용, 필수 아님)
        user_id = None
        if kc_user_id:
            user_id = await get_user_id(kc_user_id, db)
            if user_id == -1:
                user_id = None

        # 현재 시간 기준으로 활성화된 직접 추천 구좌 조회
        now = datetime.now()
        day_of_week = now.weekday()  # 0=월요일, 6=일요일

        # 평일(0-4) / 주말(5-6) 구분
        is_weekend = day_of_week >= 5

        # 활성화된 직접 추천 구좌 조회
        # DB는 UTC 시간이므로 한국 시간(+9시간)으로 변환하여 비교
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

        # 각 추천 구좌별로 작품 조회
        results = []
        for recommend_row in recommend_rows:
            product_ids = json.loads(recommend_row["product_ids"])

            if not product_ids or len(product_ids) == 0:
                continue

            # 작품 상세 정보 조회
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

            # 추천 구좌 정보와 작품 리스트를 함께 반환
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
