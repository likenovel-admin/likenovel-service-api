import logging
from fastapi import status
from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime, timedelta

import app.schemas.user_giftbook as user_giftbook_schema
import app.services.common.statistics_service as statistics_service
import app.services.common.comm_service as comm_service
from app.utils.query import build_update_query, build_insert_query

logger = logging.getLogger("user_giftbook_app")  # 커스텀 로거 생성

"""
user_giftbook 선물함 개별 서비스 함수 모음
"""


def _build_giftbook_query_with_joins(
    where_clause: str = "", order_by_clause: str = ""
) -> str:
    """
    선물함 조회 쿼리를 생성하는 헬퍼 함수
    product, episode, thumbnail 정보를 모두 조인하여 조회

    Args:
        where_clause: WHERE 조건절 (예: "ug.user_id = :user_id")
        order_by_clause: ORDER BY 절 (예: "ug.updated_date DESC")

    Returns:
        완성된 SQL 쿼리 문자열
    """
    where_part = f"WHERE {where_clause}" if where_clause else ""
    order_by_part = f"ORDER BY {order_by_clause}" if order_by_clause else ""

    return f"""
        SELECT
            ug.*,
            DATE_ADD(ug.created_date, INTERVAL 7 DAY) AS expiration_date,
            p.product_id, p.title, p.price_type AS product_price_type, p.product_type, p.status_code, p.ratings_code,
            p.synopsis_text, p.user_id AS product_user_id, p.author_id, p.author_name, p.illustrator_id, p.illustrator_name,
            p.publish_regular_yn, p.publish_days, p.thumbnail_file_id, p.primary_genre_id, p.sub_genre_id,
            p.count_hit, p.count_cp_hit, p.count_recommend, p.count_bookmark, p.count_unbookmark,
            p.open_yn AS product_open_yn, p.approval_yn, p.monopoly_yn, p.contract_yn,
            p.paid_open_date, p.paid_episode_no, p.last_episode_date, p.isbn, p.uci,
            p.single_regular_price, p.series_regular_price, p.sale_price, p.apply_date,
            p.created_id AS product_created_id, p.created_date AS product_created_date,
            p.updated_id AS product_updated_id, p.updated_date AS product_updated_date,
            cf.file_path AS product_thumbnail_url,
            COALESCE(ep_count.episode_count, 0) AS has_episode_count,
            IF(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') AS new_release_yn,
            COALESCE(free_ep.free_episode_count, 0) AS free_episode_count,
            wff.status AS waiting_for_free_status,
            p69.status AS six_nine_path_status,
            (SELECT COUNT(*) FROM tb_user_ticketbook ut2 WHERE ut2.product_id = p.product_id AND ut2.user_id = ug.user_id AND ut2.ticket_type = 'free' AND ut2.use_yn = 'Y' AND (ut2.use_expired_date IS NULL OR ut2.use_expired_date > NOW())) AS free_episode_ticket_count,
            aeb.file_path AS author_event_level_badge_image_path,
            aib.file_path AS author_interest_level_badge_image_path,
            (SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY) FROM tb_user_product_usage upu2 WHERE upu2.product_id = p.product_id AND upu2.user_id = ug.user_id AND upu2.use_yn = 'Y') AS interest_end_date,
            pe.episode_id, pe.product_id AS episode_product_id, pe.price_type AS episode_price_type,
            pe.episode_no, pe.episode_title, pe.episode_text_count, pe.episode_content,
            pe.epub_file_id, pe.author_comment, pe.comment_open_yn, pe.evaluation_open_yn,
            pe.publish_reserve_date, pe.open_yn AS episode_open_yn,
            pe.count_hit AS episode_count_hit, pe.count_recommend AS episode_count_recommend,
            pe.count_comment AS episode_count_comment, pe.count_evaluation AS episode_count_evaluation,
            pe.use_yn AS episode_use_yn,
            pe.created_id AS episode_created_id, pe.created_date AS episode_created_date,
            pe.updated_id AS episode_updated_id, pe.updated_date AS episode_updated_date,
            e.id AS event_id, e.title AS event_title, e.start_date AS event_start_date, e.end_date AS event_end_date,
            e.type AS event_type, e.reward_type AS event_reward_type, e.reward_amount AS event_reward_amount,
            q.quest_id, q.title AS quest_title, q.reward_id AS quest_reward_id,
            q.end_date AS quest_end_date, q.goal_stage AS quest_goal_stage, q.use_yn AS quest_use_yn,
            ap.id AS applied_promotion_id, ap.product_id AS applied_promotion_product_id,
            ap.type AS applied_promotion_type, ap.status AS applied_promotion_status,
            ap.start_date AS applied_promotion_start_date, ap.end_date AS applied_promotion_end_date,
            ap.num_of_ticket_per_person AS applied_promotion_num_of_ticket,
            dp.id AS direct_promotion_id, dp.product_id AS direct_promotion_product_id,
            dp.type AS direct_promotion_type, dp.status AS direct_promotion_status,
            dp.start_date AS direct_promotion_start_date,
            dp.num_of_ticket_per_person AS direct_promotion_num_of_ticket
        FROM tb_user_giftbook ug
        LEFT JOIN tb_product p ON p.product_id = coalesce(ug.product_id, if(ug.episode_id is not null, (select product_id from tb_product_episode where episode_id = ug.episode_id), null))
        LEFT JOIN (
            SELECT cf.file_group_id, cfi.file_path
            FROM tb_common_file cf
            JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
            WHERE cf.use_yn = 'Y' AND cfi.use_yn = 'Y' AND cf.group_type = 'cover'
        ) cf ON cf.file_group_id = p.thumbnail_file_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS episode_count
            FROM tb_product_episode
            WHERE use_yn = 'Y'
            GROUP BY product_id
        ) ep_count ON ep_count.product_id = p.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS free_episode_count
            FROM tb_product_episode
            WHERE price_type = 'free' AND open_yn = 'Y'
            GROUP BY product_id
        ) free_ep ON free_ep.product_id = p.product_id
        LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())
        LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())
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
        LEFT JOIN tb_product_episode pe ON ug.episode_id = pe.episode_id
        LEFT JOIN tb_event_v2 e ON ug.acquisition_type = 'event' AND ug.acquisition_id = e.id
        LEFT JOIN tb_quest q ON ug.acquisition_type = 'quest' AND ug.acquisition_id = q.quest_id
        LEFT JOIN tb_applied_promotion ap ON ug.acquisition_type = 'applied_promotion' AND ug.acquisition_id = ap.id
        LEFT JOIN tb_direct_promotion dp ON ug.acquisition_type = 'direct_promotion' AND ug.acquisition_id = dp.id
        {where_part}
        {order_by_part}
    """


def _transform_giftbook_row_to_nested_structure(row_dict: dict) -> dict:
    """
    선물함 조회 결과를 product와 episode 중첩 객체로 변환하는 헬퍼 함수

    Args:
        row_dict: 데이터베이스 조회 결과 (dict)

    Returns:
        변환된 데이터 (선물함 필드 + product 객체 + episode 객체)
    """
    # product 객체 생성 (모든 컬럼)
    product_data = None
    if row_dict.get("product_id") is not None:
        product_data = {
            "product_id": row_dict.pop("product_id", None),
            "title": row_dict.pop("title", None),
            "price_type": row_dict.pop("product_price_type", None),
            "product_type": row_dict.pop("product_type", None),
            "status_code": row_dict.pop("status_code", None),
            "ratings_code": row_dict.pop("ratings_code", None),
            "synopsis_text": row_dict.pop("synopsis_text", None),
            "user_id": row_dict.pop("product_user_id", None),
            "author_id": row_dict.pop("author_id", None),
            "author_name": row_dict.pop("author_name", None),
            "illustrator_id": row_dict.pop("illustrator_id", None),
            "illustrator_name": row_dict.pop("illustrator_name", None),
            "publish_regular_yn": row_dict.pop("publish_regular_yn", None),
            "publish_days": row_dict.pop("publish_days", None),
            "thumbnail_file_id": row_dict.pop("thumbnail_file_id", None),
            "thumbnail_url": row_dict.pop("product_thumbnail_url", None),
            "primary_genre_id": row_dict.pop("primary_genre_id", None),
            "sub_genre_id": row_dict.pop("sub_genre_id", None),
            "count_hit": row_dict.pop("count_hit", None),
            "count_cp_hit": row_dict.pop("count_cp_hit", None),
            "count_recommend": row_dict.pop("count_recommend", None),
            "count_bookmark": row_dict.pop("count_bookmark", None),
            "count_unbookmark": row_dict.pop("count_unbookmark", None),
            "open_yn": row_dict.pop("product_open_yn", None),
            "approval_yn": row_dict.pop("approval_yn", None),
            "monopoly_yn": row_dict.pop("monopoly_yn", None),
            "contract_yn": row_dict.pop("contract_yn", None),
            "paid_open_date": row_dict.pop("paid_open_date", None),
            "paid_episode_no": row_dict.pop("paid_episode_no", None),
            "last_episode_date": row_dict.pop("last_episode_date", None),
            "isbn": row_dict.pop("isbn", None),
            "uci": row_dict.pop("uci", None),
            "single_regular_price": row_dict.pop("single_regular_price", None),
            "series_regular_price": row_dict.pop("series_regular_price", None),
            "sale_price": row_dict.pop("sale_price", None),
            "apply_date": row_dict.pop("apply_date", None),
            "created_id": row_dict.pop("product_created_id", None),
            "created_date": row_dict.pop("product_created_date", None),
            "updated_id": row_dict.pop("product_updated_id", None),
            "updated_date": row_dict.pop("product_updated_date", None),
            "badge": {
                "episodeUploadYn": row_dict.pop("has_episode_count", 0) > 0,
                "waitingForFreeYn": "Y"
                if row_dict.pop("waiting_for_free_status", None) == "ing"
                else "N",
                "sixNinePathYn": "Y"
                if row_dict.pop("six_nine_path_status", None) == "ing"
                else "N",
                "newReleaseYn": row_dict.pop("new_release_yn", None),
                "freeEpisodeTicketCount": row_dict.pop("free_episode_ticket_count", 0),
                "authorEventLevelBadgeImagePath": row_dict.pop(
                    "author_event_level_badge_image_path", None
                ),
                "authorInterestLevelBadgeImagePath": row_dict.pop(
                    "author_interest_level_badge_image_path", None
                ),
                "interestFireActiveImagePath": "https://cdn.likenovel.dev/badge/fire/on.webp",
                "interestFireFadeImagePath": "https://cdn.likenovel.dev/badge/fire/off.webp",
                "interestEndDate": row_dict.pop("interest_end_date", None),
                "freeEpisodeCount": row_dict.pop("free_episode_count", None),
            },
        }
    else:
        # product가 없으면 pop만 처리
        row_dict.pop("product_id", None)
        row_dict.pop("title", None)
        row_dict.pop("product_price_type", None)
        row_dict.pop("product_type", None)
        row_dict.pop("status_code", None)
        row_dict.pop("ratings_code", None)
        row_dict.pop("synopsis_text", None)
        row_dict.pop("product_user_id", None)
        row_dict.pop("author_id", None)
        row_dict.pop("author_name", None)
        row_dict.pop("illustrator_id", None)
        row_dict.pop("illustrator_name", None)
        row_dict.pop("publish_regular_yn", None)
        row_dict.pop("publish_days", None)
        row_dict.pop("thumbnail_file_id", None)
        row_dict.pop("product_thumbnail_url", None)
        row_dict.pop("primary_genre_id", None)
        row_dict.pop("sub_genre_id", None)
        row_dict.pop("count_hit", None)
        row_dict.pop("count_cp_hit", None)
        row_dict.pop("count_recommend", None)
        row_dict.pop("count_bookmark", None)
        row_dict.pop("count_unbookmark", None)
        row_dict.pop("product_open_yn", None)
        row_dict.pop("approval_yn", None)
        row_dict.pop("monopoly_yn", None)
        row_dict.pop("contract_yn", None)
        row_dict.pop("paid_open_date", None)
        row_dict.pop("paid_episode_no", None)
        row_dict.pop("last_episode_date", None)
        row_dict.pop("isbn", None)
        row_dict.pop("uci", None)
        row_dict.pop("single_regular_price", None)
        row_dict.pop("series_regular_price", None)
        row_dict.pop("sale_price", None)
        row_dict.pop("apply_date", None)
        row_dict.pop("product_created_id", None)
        row_dict.pop("product_created_date", None)
        row_dict.pop("product_updated_id", None)
        row_dict.pop("product_updated_date", None)
        row_dict.pop("has_episode_count", None)
        row_dict.pop("new_release_yn", None)
        row_dict.pop("free_episode_count", None)
        row_dict.pop("waiting_for_free_status", None)
        row_dict.pop("six_nine_path_status", None)
        row_dict.pop("free_episode_ticket_count", None)
        row_dict.pop("author_event_level_badge_image_path", None)
        row_dict.pop("author_interest_level_badge_image_path", None)
        row_dict.pop("interest_end_date", None)

    # episode 객체 생성 (모든 컬럼)
    episode_data = None
    if row_dict.get("episode_id") is not None:
        episode_data = {
            "episode_id": row_dict.pop("episode_id", None),
            "product_id": row_dict.pop("episode_product_id", None),
            "price_type": row_dict.pop("episode_price_type", None),
            "episode_no": row_dict.pop("episode_no", None),
            "episode_title": row_dict.pop("episode_title", None),
            "episode_text_count": row_dict.pop("episode_text_count", None),
            "episode_content": row_dict.pop("episode_content", None),
            "epub_file_id": row_dict.pop("epub_file_id", None),
            "author_comment": row_dict.pop("author_comment", None),
            "comment_open_yn": row_dict.pop("comment_open_yn", None),
            "evaluation_open_yn": row_dict.pop("evaluation_open_yn", None),
            "publish_reserve_date": row_dict.pop("publish_reserve_date", None),
            "open_yn": row_dict.pop("episode_open_yn", None),
            "count_hit": row_dict.pop("episode_count_hit", None),
            "count_recommend": row_dict.pop("episode_count_recommend", None),
            "count_comment": row_dict.pop("episode_count_comment", None),
            "count_evaluation": row_dict.pop("episode_count_evaluation", None),
            "use_yn": row_dict.pop("episode_use_yn", None),
            "created_id": row_dict.pop("episode_created_id", None),
            "created_date": row_dict.pop("episode_created_date", None),
            "updated_id": row_dict.pop("episode_updated_id", None),
            "updated_date": row_dict.pop("episode_updated_date", None),
        }
    else:
        # episode가 없으면 pop만 처리
        row_dict.pop("episode_id", None)
        row_dict.pop("episode_product_id", None)
        row_dict.pop("episode_price_type", None)
        row_dict.pop("episode_no", None)
        row_dict.pop("episode_title", None)
        row_dict.pop("episode_text_count", None)
        row_dict.pop("episode_content", None)
        row_dict.pop("epub_file_id", None)
        row_dict.pop("author_comment", None)
        row_dict.pop("comment_open_yn", None)
        row_dict.pop("evaluation_open_yn", None)
        row_dict.pop("publish_reserve_date", None)
        row_dict.pop("episode_open_yn", None)
        row_dict.pop("episode_count_hit", None)
        row_dict.pop("episode_count_recommend", None)
        row_dict.pop("episode_count_comment", None)
        row_dict.pop("episode_count_evaluation", None)
        row_dict.pop("episode_use_yn", None)
        row_dict.pop("episode_created_id", None)
        row_dict.pop("episode_created_date", None)
        row_dict.pop("episode_updated_id", None)
        row_dict.pop("episode_updated_date", None)

    # event 객체 생성 (tb_event_v2)
    event_data = None
    if row_dict.get("event_id") is not None:
        event_data = {
            "id": row_dict.pop("event_id", None),
            "title": row_dict.pop("event_title", None),
            "start_date": row_dict.pop("event_start_date", None),
            "end_date": row_dict.pop("event_end_date", None),
            "type": row_dict.pop("event_type", None),
            "reward_type": row_dict.pop("event_reward_type", None),
            "reward_amount": row_dict.pop("event_reward_amount", None),
        }
    else:
        # event가 없으면 pop만 처리
        row_dict.pop("event_id", None)
        row_dict.pop("event_title", None)
        row_dict.pop("event_start_date", None)
        row_dict.pop("event_end_date", None)
        row_dict.pop("event_type", None)
        row_dict.pop("event_reward_type", None)
        row_dict.pop("event_reward_amount", None)

    # quest 객체 생성
    quest_data = None
    if row_dict.get("quest_id") is not None:
        quest_data = {
            "quest_id": row_dict.pop("quest_id", None),
            "title": row_dict.pop("quest_title", None),
            "reward_id": row_dict.pop("quest_reward_id", None),
            "end_date": row_dict.pop("quest_end_date", None),
            "goal_stage": row_dict.pop("quest_goal_stage", None),
            "use_yn": row_dict.pop("quest_use_yn", None),
        }
    else:
        # quest가 없으면 pop만 처리
        row_dict.pop("quest_id", None)
        row_dict.pop("quest_title", None)
        row_dict.pop("quest_reward_id", None)
        row_dict.pop("quest_end_date", None)
        row_dict.pop("quest_goal_stage", None)
        row_dict.pop("quest_use_yn", None)

    # promotion 객체 생성 (applied_promotion 또는 direct_promotion 중 하나만 존재)
    promotion_data = None

    # applied_promotion 확인
    if row_dict.get("applied_promotion_id") is not None:
        promotion_data = {
            "id": row_dict.pop("applied_promotion_id", None),
            "product_id": row_dict.pop("applied_promotion_product_id", None),
            "type": row_dict.pop("applied_promotion_type", None),
            "status": row_dict.pop("applied_promotion_status", None),
            "start_date": row_dict.pop("applied_promotion_start_date", None),
            "end_date": row_dict.pop("applied_promotion_end_date", None),
            "num_of_ticket_per_person": row_dict.pop(
                "applied_promotion_num_of_ticket", None
            ),
            "promotion_category": "applied_promotion",
        }
    else:
        # applied_promotion이 없으면 pop만 처리
        row_dict.pop("applied_promotion_id", None)
        row_dict.pop("applied_promotion_product_id", None)
        row_dict.pop("applied_promotion_type", None)
        row_dict.pop("applied_promotion_status", None)
        row_dict.pop("applied_promotion_start_date", None)
        row_dict.pop("applied_promotion_end_date", None)
        row_dict.pop("applied_promotion_num_of_ticket", None)

    # direct_promotion 확인 (applied_promotion이 없을 때만)
    if promotion_data is None and row_dict.get("direct_promotion_id") is not None:
        promotion_data = {
            "id": row_dict.pop("direct_promotion_id", None),
            "product_id": row_dict.pop("direct_promotion_product_id", None),
            "type": row_dict.pop("direct_promotion_type", None),
            "status": row_dict.pop("direct_promotion_status", None),
            "start_date": row_dict.pop("direct_promotion_start_date", None),
            "num_of_ticket_per_person": row_dict.pop(
                "direct_promotion_num_of_ticket", None
            ),
            "promotion_category": "direct_promotion",
        }
    else:
        # direct_promotion이 없으면 pop만 처리
        row_dict.pop("direct_promotion_id", None)
        row_dict.pop("direct_promotion_product_id", None)
        row_dict.pop("direct_promotion_type", None)
        row_dict.pop("direct_promotion_status", None)
        row_dict.pop("direct_promotion_start_date", None)
        row_dict.pop("direct_promotion_num_of_ticket", None)

    # 최종 데이터 구성
    row_dict["product"] = product_data
    row_dict["episode"] = episode_data
    row_dict["event"] = event_data
    row_dict["quest"] = quest_data
    row_dict["promotion"] = promotion_data

    return row_dict


def _transform_used_giftbook_row(row_dict: dict) -> dict:
    """
    사용 내역 조회 결과를 변환하는 헬퍼 함수
    - 대여권을 사용한 작품/에피소드 정보
    - 남은 대여 시간 (rental_remaining)

    Args:
        row_dict: 데이터베이스 조회 결과 (dict)

    Returns:
        변환된 데이터
    """
    # product 객체 생성 (대여권을 사용한 작품)
    product_data = None
    if row_dict.get("used_product_id") is not None:
        product_data = {
            "product_id": row_dict.pop("used_product_id", None),
            "title": row_dict.pop("title", None),
            "price_type": row_dict.pop("product_price_type", None),
            "product_type": row_dict.pop("product_type", None),
            "status_code": row_dict.pop("status_code", None),
            "ratings_code": row_dict.pop("ratings_code", None),
            "synopsis_text": row_dict.pop("synopsis_text", None),
            "user_id": row_dict.pop("product_user_id", None),
            "author_id": row_dict.pop("author_id", None),
            "author_name": row_dict.pop("author_name", None),
            "illustrator_id": row_dict.pop("illustrator_id", None),
            "illustrator_name": row_dict.pop("illustrator_name", None),
            "publish_regular_yn": row_dict.pop("publish_regular_yn", None),
            "publish_days": row_dict.pop("publish_days", None),
            "thumbnail_file_id": row_dict.pop("thumbnail_file_id", None),
            "thumbnail_url": row_dict.pop("product_thumbnail_url", None),
            "primary_genre_id": row_dict.pop("primary_genre_id", None),
            "sub_genre_id": row_dict.pop("sub_genre_id", None),
            "count_hit": row_dict.pop("count_hit", None),
            "count_cp_hit": row_dict.pop("count_cp_hit", None),
            "count_recommend": row_dict.pop("count_recommend", None),
            "count_bookmark": row_dict.pop("count_bookmark", None),
            "count_unbookmark": row_dict.pop("count_unbookmark", None),
            "open_yn": row_dict.pop("product_open_yn", None),
            "approval_yn": row_dict.pop("approval_yn", None),
            "monopoly_yn": row_dict.pop("monopoly_yn", None),
            "contract_yn": row_dict.pop("contract_yn", None),
            "paid_open_date": row_dict.pop("paid_open_date", None),
            "paid_episode_no": row_dict.pop("paid_episode_no", None),
            "last_episode_date": row_dict.pop("last_episode_date", None),
            "isbn": row_dict.pop("isbn", None),
            "uci": row_dict.pop("uci", None),
            "single_regular_price": row_dict.pop("single_regular_price", None),
            "series_regular_price": row_dict.pop("series_regular_price", None),
            "sale_price": row_dict.pop("sale_price", None),
            "apply_date": row_dict.pop("apply_date", None),
            "created_id": row_dict.pop("product_created_id", None),
            "created_date": row_dict.pop("product_created_date", None),
            "updated_id": row_dict.pop("product_updated_id", None),
            "updated_date": row_dict.pop("product_updated_date", None),
        }
    else:
        # product가 없으면 pop만 처리
        row_dict.pop("used_product_id", None)
        row_dict.pop("title", None)
        row_dict.pop("product_price_type", None)
        row_dict.pop("product_type", None)
        row_dict.pop("status_code", None)
        row_dict.pop("ratings_code", None)
        row_dict.pop("synopsis_text", None)
        row_dict.pop("product_user_id", None)
        row_dict.pop("author_id", None)
        row_dict.pop("author_name", None)
        row_dict.pop("illustrator_id", None)
        row_dict.pop("illustrator_name", None)
        row_dict.pop("publish_regular_yn", None)
        row_dict.pop("publish_days", None)
        row_dict.pop("thumbnail_file_id", None)
        row_dict.pop("product_thumbnail_url", None)
        row_dict.pop("primary_genre_id", None)
        row_dict.pop("sub_genre_id", None)
        row_dict.pop("count_hit", None)
        row_dict.pop("count_cp_hit", None)
        row_dict.pop("count_recommend", None)
        row_dict.pop("count_bookmark", None)
        row_dict.pop("count_unbookmark", None)
        row_dict.pop("product_open_yn", None)
        row_dict.pop("approval_yn", None)
        row_dict.pop("monopoly_yn", None)
        row_dict.pop("contract_yn", None)
        row_dict.pop("paid_open_date", None)
        row_dict.pop("paid_episode_no", None)
        row_dict.pop("last_episode_date", None)
        row_dict.pop("isbn", None)
        row_dict.pop("uci", None)
        row_dict.pop("single_regular_price", None)
        row_dict.pop("series_regular_price", None)
        row_dict.pop("sale_price", None)
        row_dict.pop("apply_date", None)
        row_dict.pop("product_created_id", None)
        row_dict.pop("product_created_date", None)
        row_dict.pop("product_updated_id", None)
        row_dict.pop("product_updated_date", None)

    # episode 객체 생성 (대여권을 사용한 에피소드)
    episode_data = None
    if row_dict.get("used_episode_id") is not None:
        episode_data = {
            "episode_id": row_dict.pop("used_episode_id", None),
            "product_id": row_dict.pop("episode_product_id", None),
            "price_type": row_dict.pop("episode_price_type", None),
            "episode_no": row_dict.pop("episode_no", None),
            "episode_title": row_dict.pop("episode_title", None),
            "episode_text_count": row_dict.pop("episode_text_count", None),
            "epub_file_id": row_dict.pop("epub_file_id", None),
            "author_comment": row_dict.pop("author_comment", None),
            "comment_open_yn": row_dict.pop("comment_open_yn", None),
            "evaluation_open_yn": row_dict.pop("evaluation_open_yn", None),
            "publish_reserve_date": row_dict.pop("publish_reserve_date", None),
            "open_yn": row_dict.pop("episode_open_yn", None),
            "count_hit": row_dict.pop("episode_count_hit", None),
            "count_recommend": row_dict.pop("episode_count_recommend", None),
            "count_comment": row_dict.pop("episode_count_comment", None),
            "count_evaluation": row_dict.pop("episode_count_evaluation", None),
            "use_yn": row_dict.pop("episode_use_yn", None),
            "created_id": row_dict.pop("episode_created_id", None),
            "created_date": row_dict.pop("episode_created_date", None),
            "updated_id": row_dict.pop("episode_updated_id", None),
            "updated_date": row_dict.pop("episode_updated_date", None),
        }
    else:
        # episode가 없으면 pop만 처리
        row_dict.pop("used_episode_id", None)
        row_dict.pop("episode_product_id", None)
        row_dict.pop("episode_price_type", None)
        row_dict.pop("episode_no", None)
        row_dict.pop("episode_title", None)
        row_dict.pop("episode_text_count", None)
        row_dict.pop("epub_file_id", None)
        row_dict.pop("author_comment", None)
        row_dict.pop("comment_open_yn", None)
        row_dict.pop("evaluation_open_yn", None)
        row_dict.pop("publish_reserve_date", None)
        row_dict.pop("episode_open_yn", None)
        row_dict.pop("episode_count_hit", None)
        row_dict.pop("episode_count_recommend", None)
        row_dict.pop("episode_count_comment", None)
        row_dict.pop("episode_count_evaluation", None)
        row_dict.pop("episode_use_yn", None)
        row_dict.pop("episode_created_id", None)
        row_dict.pop("episode_created_date", None)
        row_dict.pop("episode_updated_id", None)
        row_dict.pop("episode_updated_date", None)

    # event 객체 생성
    event_data = None
    if row_dict.get("event_id") is not None:
        event_data = {
            "id": row_dict.pop("event_id", None),
            "title": row_dict.pop("event_title", None),
            "start_date": row_dict.pop("event_start_date", None),
            "end_date": row_dict.pop("event_end_date", None),
            "type": row_dict.pop("event_type", None),
            "reward_type": row_dict.pop("event_reward_type", None),
            "reward_amount": row_dict.pop("event_reward_amount", None),
        }
    else:
        row_dict.pop("event_id", None)
        row_dict.pop("event_title", None)
        row_dict.pop("event_start_date", None)
        row_dict.pop("event_end_date", None)
        row_dict.pop("event_type", None)
        row_dict.pop("event_reward_type", None)
        row_dict.pop("event_reward_amount", None)

    # quest 객체 생성
    quest_data = None
    if row_dict.get("quest_id") is not None:
        quest_data = {
            "quest_id": row_dict.pop("quest_id", None),
            "title": row_dict.pop("quest_title", None),
            "reward_id": row_dict.pop("quest_reward_id", None),
            "end_date": row_dict.pop("quest_end_date", None),
            "goal_stage": row_dict.pop("quest_goal_stage", None),
            "use_yn": row_dict.pop("quest_use_yn", None),
        }
    else:
        row_dict.pop("quest_id", None)
        row_dict.pop("quest_title", None)
        row_dict.pop("quest_reward_id", None)
        row_dict.pop("quest_end_date", None)
        row_dict.pop("quest_goal_stage", None)
        row_dict.pop("quest_use_yn", None)

    # promotion 객체 생성
    promotion_data = None

    # applied_promotion 확인
    if row_dict.get("applied_promotion_id") is not None:
        promotion_data = {
            "id": row_dict.pop("applied_promotion_id", None),
            "product_id": row_dict.pop("applied_promotion_product_id", None),
            "type": row_dict.pop("applied_promotion_type", None),
            "status": row_dict.pop("applied_promotion_status", None),
            "start_date": row_dict.pop("applied_promotion_start_date", None),
            "end_date": row_dict.pop("applied_promotion_end_date", None),
            "num_of_ticket_per_person": row_dict.pop(
                "applied_promotion_num_of_ticket", None
            ),
            "promotion_category": "applied_promotion",
        }
    else:
        row_dict.pop("applied_promotion_id", None)
        row_dict.pop("applied_promotion_product_id", None)
        row_dict.pop("applied_promotion_type", None)
        row_dict.pop("applied_promotion_status", None)
        row_dict.pop("applied_promotion_start_date", None)
        row_dict.pop("applied_promotion_end_date", None)
        row_dict.pop("applied_promotion_num_of_ticket", None)

    # direct_promotion 확인
    if promotion_data is None and row_dict.get("direct_promotion_id") is not None:
        promotion_data = {
            "id": row_dict.pop("direct_promotion_id", None),
            "product_id": row_dict.pop("direct_promotion_product_id", None),
            "type": row_dict.pop("direct_promotion_type", None),
            "status": row_dict.pop("direct_promotion_status", None),
            "start_date": row_dict.pop("direct_promotion_start_date", None),
            "num_of_ticket_per_person": row_dict.pop(
                "direct_promotion_num_of_ticket", None
            ),
            "promotion_category": "direct_promotion",
        }
    else:
        row_dict.pop("direct_promotion_id", None)
        row_dict.pop("direct_promotion_product_id", None)
        row_dict.pop("direct_promotion_type", None)
        row_dict.pop("direct_promotion_status", None)
        row_dict.pop("direct_promotion_start_date", None)
        row_dict.pop("direct_promotion_num_of_ticket", None)

    # giftbook acquisition 정보 처리
    row_dict["acquisition_type"] = row_dict.pop("giftbook_acquisition_type", None)
    row_dict["acquisition_id"] = row_dict.pop("giftbook_acquisition_id", None)

    # 최종 데이터 구성
    row_dict["product"] = product_data
    row_dict["episode"] = episode_data
    row_dict["event"] = event_data
    row_dict["quest"] = quest_data
    row_dict["promotion"] = promotion_data

    return row_dict


async def user_giftbook_list(kc_user_id: str, db: AsyncSession):
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 만료된 선물함 항목 필터링 (received_yn = 'N'이고 유효기간 지남)
    # expiration_date가 있는 경우: expiration_date 기준
    # expiration_date가 없는 경우: created_date + 7일 기준 (기본 유효기간)
    # 단, promotion_type이 'waiting-for-free'인 경우는 유효기간 없음 (필터 안함)
    # 실제 삭제는 배치에서 처리
    where_clause = """
        ug.user_id = :user_id
        AND NOT (
            ug.received_yn = 'N'
            AND (ug.promotion_type IS NULL OR ug.promotion_type != 'waiting-for-free')
            AND (
                (ug.expiration_date IS NOT NULL AND ug.expiration_date < NOW())
                OR (ug.expiration_date IS NULL AND DATE_ADD(ug.created_date, INTERVAL 7 DAY) < NOW())
            )
        )
    """

    query_str = _build_giftbook_query_with_joins(
        where_clause=where_clause, order_by_clause="ug.updated_date DESC"
    )
    query = text(query_str)
    result = await db.execute(query, {"user_id": user_id})
    rows = result.mappings().all()

    # 데이터 후처리: product와 episode를 중첩 객체로 변환
    data_list = []
    for row in rows:
        row_dict = dict(row)
        transformed = _transform_giftbook_row_to_nested_structure(row_dict)
        data_list.append(transformed)

    res_body = dict()
    res_body["data"] = data_list

    return res_body


async def user_giftbook_detail_by_id(id, db: AsyncSession):
    """
    선물함(user_giftbook) 상세 조회
    """
    query_str = _build_giftbook_query_with_joins(where_clause="ug.id = :id")
    query = text(query_str)
    result = await db.execute(query, {"id": id})
    row = result.mappings().one_or_none()

    res_body = dict()
    if row is not None:
        row_dict = dict(row)
        transformed = _transform_giftbook_row_to_nested_structure(row_dict)
        res_body["data"] = transformed
    else:
        res_body["data"] = None

    return res_body


async def post_user_giftbook(
    req_body: user_giftbook_schema.PostUserGiftbookReqBody,
    kc_user_id: str,
    db: AsyncSession,
    user_id: int | None = None,
):
    if user_id is None:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

    if req_body is not None:
        logger.info(f"post_user_giftbook: {req_body}")

    columns, values, params = build_insert_query(
        req_body,
        required_fields=["user_id", "ticket_type", "own_type", "reason", "amount"],
        optional_fields=[
            "product_id",
            "episode_id",
            "acquisition_type",
            "acquisition_id",
            "promotion_type",
            "expiration_date",
            "ticket_expiration_type",
            "ticket_expiration_value",
        ],
        field_defaults={"reason": "", "amount": 1},
    )

    query = text(f"""
        insert into tb_user_giftbook ({columns}, created_id, created_date)
        values ({values}, :created_id, :created_date)
    """)

    await db.execute(query, params)

    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    # 선물함에 저장만 하고, 받은 내역 기록 및 알림은 receive_user_giftbook에서 처리
    # (대여권 받기 버튼을 눌러야 실제로 받은 것으로 처리됨)

    return {"result": req_body}


async def put_user_giftbook(
    id: int,
    req_body: user_giftbook_schema.PutUserGiftbookReqBody,
    db: AsyncSession,
):
    if req_body is not None:
        logger.info(f"put_user_giftbook: {req_body}")

    set_clause, params = build_update_query(
        req_body,
        allowed_fields=[
            "user_id",
            "product_id",
            "episode_id",
            "ticket_type",
            "own_type",
            "acquisition_type",
            "acquisition_id",
            "read_yn",
            "received_yn",
            "reason",
            "amount",
        ],
    )
    params["id"] = id

    query = text(f"UPDATE tb_user_giftbook SET {set_clause} WHERE id = :id")

    await db.execute(query, params)

    return {"result": req_body}


async def delete_user_giftbook(id: int, db: AsyncSession):
    query = text("""
                        delete from tb_user_giftbook where id = :id
                    """)

    await db.execute(query, {"id": id})

    return {"result": True}


async def insert_gift_transaction(
    type: str,
    user_id: int,
    amount: int,
    giftbook_id: int,
    db: AsyncSession,
    reason: str = "",
):
    """
    선물함 히스토리 기록

    Args:
        type: "received" (받은 내역) 또는 "used" (사용 내역)
        user_id: 유저 아이디
        amount: 대여권 장수
        reason: 거래 사유
        giftbook_id: 선물함 아이디
        db: 데이터베이스 세션
    """
    query = text("""
                    insert into tb_user_gift_transaction
                    (type, user_id, giftbook_id, amount, reason, created_id, created_date)
                    values (:type, :user_id, :giftbook_id, :amount, :reason, :created_id, :created_date)
                """)

    params = {
        "type": type,
        "user_id": user_id,
        "giftbook_id": giftbook_id,
        "amount": amount,
        "reason": reason,
        "created_id": -1,
        "created_date": datetime.now(),
    }

    await db.execute(query, params)


async def receive_user_giftbook(
    giftbook_id: int,
    kc_user_id: str,
    db: AsyncSession,
):
    """
    선물함에서 선물 받기
    - 선물함 항목을 받음 처리하고 (received_yn = 'Y')
    - 대여권을 tb_user_productbook에 추가
    - 프로모션 타입에 따라 대여권 유효기간 설정:
      * free-for-first (첫방문자 무료): 유효기간 없음, 프로모션 종료 시 만료
      * reader-of-prev (선작독자): 유효기간 1주일
      * 6-9-path (6-9패스): 유효기간 하루 (수령 시점부터)
      * waiting-for-free (기다리면 무료): 유효기간 없음
    """
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 1. 선물함 조회 및 검증 (새 컬럼 포함)
    giftbook_query = text("""
        SELECT user_id, product_id, episode_id, ticket_type, own_type, amount, received_yn,
               created_date, expiration_date, promotion_type, acquisition_type, acquisition_id,
               ticket_expiration_type, ticket_expiration_value
        FROM tb_user_giftbook
        WHERE id = :giftbook_id
    """)
    giftbook_result = await db.execute(giftbook_query, {"giftbook_id": giftbook_id})
    giftbook = giftbook_result.mappings().one_or_none()

    if not giftbook:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND,
        )

    # 소유자 확인
    if giftbook.get("user_id") != user_id:
        raise CustomResponseException(
            status_code=status.HTTP_403_FORBIDDEN,
            message=ErrorMessages.FORBIDDEN,
        )

    # 이미 받은 선물인지 확인
    if giftbook.get("received_yn") == "Y":
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.ALREADY_RECEIVED_GIFT,
        )

    promotion_type = giftbook.get("promotion_type")
    # acquisition_type = giftbook.get("acquisition_type")
    acquisition_id = giftbook.get("acquisition_id")

    # 선물함 유효기간 확인 (promotion_type에 따라 다르게 처리)
    expiration_date = giftbook.get("expiration_date")

    # 첫방문자 무료의 경우: 프로모션이 진행 중인지 확인
    if promotion_type == "free-for-first":
        # 해당 프로모션이 아직 진행 중인지 확인
        promo_query = text("""
            SELECT id, status FROM tb_direct_promotion
            WHERE id = :promotion_id AND status = 'ing'
        """)
        promo_result = await db.execute(promo_query, {"promotion_id": acquisition_id})
        promo = promo_result.mappings().one_or_none()
        if not promo:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=ErrorMessages.EXPIRED_GIFT_VALIDITY,
            )
    # 기다리면 무료의 경우: 유효기간 없음 (만료 체크 스킵)
    elif promotion_type == "waiting-for-free":
        pass  # 유효기간 없음
    # 그 외: expiration_date 확인
    elif expiration_date and datetime.now() > expiration_date:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=ErrorMessages.EXPIRED_GIFT_VALIDITY,
        )

    # 2. 사용자의 기본 프로필 조회
    profile_query = text("""
        SELECT profile_id
        FROM tb_user_profile
        WHERE user_id = :user_id
        AND default_yn = 'Y'
    """)
    profile_result = await db.execute(profile_query, {"user_id": user_id})
    profile = profile_result.mappings().one_or_none()

    if not profile:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PROFILE,
        )

    profile_id = profile.get("profile_id")

    # 3. 선물함의 product_id, episode_id를 사용하여 대여권 발급
    product_id = giftbook.get("product_id")
    episode_id = giftbook.get("episode_id")
    ticket_type = giftbook.get("ticket_type")
    own_type = giftbook.get("own_type")
    amount = giftbook.get("amount", 1)
    ticket_expiration_type = giftbook.get("ticket_expiration_type")
    ticket_expiration_value = giftbook.get("ticket_expiration_value")

    # 대여권 유효기간 계산 (수령 시점 기준)
    rental_expired_date = None
    if ticket_expiration_type == "on_receive_days" and ticket_expiration_value:
        # 수령 시점부터 N일 (예: 6-9패스 - 하루)
        rental_expired_date = datetime.now() + timedelta(days=ticket_expiration_value)
    elif ticket_expiration_type == "days" and ticket_expiration_value:
        # N일 (예: 선작독자 - 7일)
        rental_expired_date = datetime.now() + timedelta(days=ticket_expiration_value)
    elif ticket_expiration_type == "hours" and ticket_expiration_value:
        # N시간
        rental_expired_date = datetime.now() + timedelta(hours=ticket_expiration_value)
    # ticket_expiration_type이 'none'이거나 None이면 rental_expired_date는 None (무기한)

    # 대여권 발급 (product_id, episode_id가 NULL이면 범용 티켓)
    # amount 개수만큼 대여권 발급
    insert_query = text("""
        INSERT INTO tb_user_productbook
        (user_id, profile_id, product_id, episode_id, own_type, ticket_type, acquisition_type, acquisition_id, rental_expired_date, use_yn, created_id, created_date)
        VALUES (:user_id, :profile_id, :product_id, :episode_id, :own_type, :ticket_type, 'gift', :acquisition_id, :rental_expired_date, 'N', :created_id, :created_date)
    """)
    for _ in range(amount):
        await db.execute(
            insert_query,
            {
                "user_id": user_id,
                "profile_id": profile_id,
                "product_id": product_id,
                "episode_id": episode_id,
                "own_type": own_type,
                "ticket_type": ticket_type,
                "acquisition_id": giftbook_id,
                "rental_expired_date": rental_expired_date,
                "created_id": -1,
                "created_date": datetime.now(),
            },
        )

    # 4. 선물함 업데이트 (받음 처리)
    update_query = text("""
        UPDATE tb_user_giftbook
        SET received_yn = 'Y',
            received_date = :received_date,
            updated_id = :updated_id,
            updated_date = :updated_date
        WHERE id = :giftbook_id
    """)
    await db.execute(
        update_query,
        {
            "received_date": datetime.now(),
            "updated_id": -1,
            "updated_date": datetime.now(),
            "giftbook_id": giftbook_id,
        },
    )

    # 5. 거래 내역 기록 (받은 내역 - 대여권 받기 버튼 클릭 시)
    await insert_gift_transaction(
        type="received",
        user_id=user_id,
        amount=amount,
        reason=f"선물함에서 받기 (giftbook_id: {giftbook_id})",
        giftbook_id=giftbook_id,
        db=db,
    )

    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=user_id
    )

    return {"result": True, "message": "선물을 받았습니다."}


async def user_gift_transaction_list(kc_user_id: str, type: str, db: AsyncSession):
    user_id = await comm_service.get_user_from_kc(kc_user_id, db)
    if user_id == -1:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    # 사용 내역: 선물함에서 받은 대여권이 실제로 사용된 내역 조회
    if type == "used":
        query = text("""
            SELECT
                upb.id,
                upb.user_id,
                upb.product_id,
                upb.episode_id,
                upb.ticket_type,
                upb.own_type,
                upb.acquisition_type,
                upb.acquisition_id AS giftbook_id,
                upb.rental_expired_date,
                upb.use_yn,
                upb.use_date,
                upb.created_date,
                CASE
                    WHEN upb.rental_expired_date IS NULL THEN NULL
                    WHEN upb.rental_expired_date <= NOW() THEN 0
                    ELSE TIMESTAMPDIFF(SECOND, NOW(), upb.rental_expired_date)
                END AS rental_remaining,
                ug.amount,
                p.product_id AS used_product_id, p.title, p.price_type AS product_price_type, p.product_type, p.status_code, p.ratings_code,
                p.synopsis_text, p.user_id AS product_user_id, p.author_id, p.author_name, p.illustrator_id, p.illustrator_name,
                p.publish_regular_yn, p.publish_days, p.thumbnail_file_id, p.primary_genre_id, p.sub_genre_id,
                p.count_hit, p.count_cp_hit, p.count_recommend, p.count_bookmark, p.count_unbookmark,
                p.open_yn AS product_open_yn, p.approval_yn, p.monopoly_yn, p.contract_yn,
                p.paid_open_date, p.paid_episode_no, p.last_episode_date, p.isbn, p.uci,
                p.single_regular_price, p.series_regular_price, p.sale_price, p.apply_date,
                p.created_id AS product_created_id, p.created_date AS product_created_date,
                p.updated_id AS product_updated_id, p.updated_date AS product_updated_date,
                cf.file_path AS product_thumbnail_url,
                pe.episode_id AS used_episode_id, pe.product_id AS episode_product_id, pe.price_type AS episode_price_type,
                pe.episode_no, pe.episode_title, pe.episode_text_count,
                pe.epub_file_id, pe.author_comment, pe.comment_open_yn, pe.evaluation_open_yn,
                pe.publish_reserve_date, pe.open_yn AS episode_open_yn,
                pe.count_hit AS episode_count_hit, pe.count_recommend AS episode_count_recommend,
                pe.count_comment AS episode_count_comment, pe.count_evaluation AS episode_count_evaluation,
                pe.use_yn AS episode_use_yn,
                pe.created_id AS episode_created_id, pe.created_date AS episode_created_date,
                pe.updated_id AS episode_updated_id, pe.updated_date AS episode_updated_date,
                ug.acquisition_type AS giftbook_acquisition_type, ug.acquisition_id AS giftbook_acquisition_id,
                e.id AS event_id, e.title AS event_title, e.start_date AS event_start_date, e.end_date AS event_end_date,
                e.type AS event_type, e.reward_type AS event_reward_type, e.reward_amount AS event_reward_amount,
                q.quest_id, q.title AS quest_title, q.reward_id AS quest_reward_id,
                q.end_date AS quest_end_date, q.goal_stage AS quest_goal_stage, q.use_yn AS quest_use_yn,
                ap.id AS applied_promotion_id, ap.product_id AS applied_promotion_product_id,
                ap.type AS applied_promotion_type, ap.status AS applied_promotion_status,
                ap.start_date AS applied_promotion_start_date, ap.end_date AS applied_promotion_end_date,
                ap.num_of_ticket_per_person AS applied_promotion_num_of_ticket,
                dp.id AS direct_promotion_id, dp.product_id AS direct_promotion_product_id,
                dp.type AS direct_promotion_type, dp.status AS direct_promotion_status,
                dp.start_date AS direct_promotion_start_date,
                dp.num_of_ticket_per_person AS direct_promotion_num_of_ticket
            FROM tb_user_productbook upb
            LEFT JOIN tb_user_giftbook ug ON upb.acquisition_type = 'gift' AND upb.acquisition_id = ug.id
            LEFT JOIN tb_product p ON p.product_id = upb.product_id
            LEFT JOIN (
                SELECT cf.file_group_id, cfi.file_path
                FROM tb_common_file cf
                JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
                WHERE cf.use_yn = 'Y' AND cfi.use_yn = 'Y' AND cf.group_type = 'cover'
            ) cf ON cf.file_group_id = p.thumbnail_file_id
            LEFT JOIN tb_product_episode pe ON upb.episode_id = pe.episode_id
            LEFT JOIN tb_event_v2 e ON ug.acquisition_type = 'event' AND ug.acquisition_id = e.id
            LEFT JOIN tb_quest q ON ug.acquisition_type = 'quest' AND ug.acquisition_id = q.quest_id
            LEFT JOIN tb_applied_promotion ap ON ug.acquisition_type = 'applied_promotion' AND ug.acquisition_id = ap.id
            LEFT JOIN tb_direct_promotion dp ON ug.acquisition_type = 'direct_promotion' AND ug.acquisition_id = dp.id
            WHERE upb.user_id = :user_id
              AND upb.acquisition_type = 'gift'
              AND upb.use_yn = 'Y'
            ORDER BY upb.use_date DESC
        """)
        result = await db.execute(query, {"user_id": user_id})
        rows = result.mappings().all()

        data_list = []
        for row in rows:
            row_dict = dict(row)
            transformed = _transform_used_giftbook_row(row_dict)
            data_list.append(transformed)

        res_body = dict()
        res_body["data"] = data_list

        return res_body

    # 받은 내역: 기존 로직 유지
    query = text("""
        SELECT
            ugt.*,
            ug.product_id, ug.episode_id, ug.ticket_type, ug.own_type, ug.acquisition_type, ug.acquisition_id,
            DATE_ADD(ug.created_date, INTERVAL 7 DAY) AS expiration_date,
            p.product_id, p.title, p.price_type AS product_price_type, p.product_type, p.status_code, p.ratings_code,
            p.synopsis_text, p.user_id AS product_user_id, p.author_id, p.author_name, p.illustrator_id, p.illustrator_name,
            p.publish_regular_yn, p.publish_days, p.thumbnail_file_id, p.primary_genre_id, p.sub_genre_id,
            p.count_hit, p.count_cp_hit, p.count_recommend, p.count_bookmark, p.count_unbookmark,
            p.open_yn AS product_open_yn, p.approval_yn, p.monopoly_yn, p.contract_yn,
            p.paid_open_date, p.paid_episode_no, p.last_episode_date, p.isbn, p.uci,
            p.single_regular_price, p.series_regular_price, p.sale_price, p.apply_date,
            p.created_id AS product_created_id, p.created_date AS product_created_date,
            p.updated_id AS product_updated_id, p.updated_date AS product_updated_date,
            cf.file_path AS product_thumbnail_url,
            COALESCE(ep_count.episode_count, 0) AS has_episode_count,
            IF(p.last_episode_date >= DATE_SUB(NOW(), INTERVAL 24 HOUR), 'Y', 'N') AS new_release_yn,
            COALESCE(free_ep.free_episode_count, 0) AS free_episode_count,
            wff.status AS waiting_for_free_status,
            p69.status AS six_nine_path_status,
            (SELECT COUNT(*) FROM tb_user_ticketbook ut2 WHERE ut2.product_id = p.product_id AND ut2.user_id = ugt.user_id AND ut2.ticket_type = 'free' AND ut2.use_yn = 'Y' AND (ut2.use_expired_date IS NULL OR ut2.use_expired_date > NOW())) AS free_episode_ticket_count,
            aeb.file_path AS author_event_level_badge_image_path,
            aib.file_path AS author_interest_level_badge_image_path,
            (SELECT DATE_ADD(MAX(upu2.updated_date), INTERVAL 3 DAY) FROM tb_user_product_usage upu2 WHERE upu2.product_id = p.product_id AND upu2.user_id = ugt.user_id AND upu2.use_yn = 'Y') AS interest_end_date,
            pe.episode_id, pe.product_id AS episode_product_id, pe.price_type AS episode_price_type,
            pe.episode_no, pe.episode_title, pe.episode_text_count, pe.episode_content,
            pe.epub_file_id, pe.author_comment, pe.comment_open_yn, pe.evaluation_open_yn,
            pe.publish_reserve_date, pe.open_yn AS episode_open_yn,
            pe.count_hit AS episode_count_hit, pe.count_recommend AS episode_count_recommend,
            pe.count_comment AS episode_count_comment, pe.count_evaluation AS episode_count_evaluation,
            pe.use_yn AS episode_use_yn,
            pe.created_id AS episode_created_id, pe.created_date AS episode_created_date,
            pe.updated_id AS episode_updated_id, pe.updated_date AS episode_updated_date,
            e.id AS event_id, e.title AS event_title, e.start_date AS event_start_date, e.end_date AS event_end_date,
            e.type AS event_type, e.reward_type AS event_reward_type, e.reward_amount AS event_reward_amount,
            q.quest_id, q.title AS quest_title, q.reward_id AS quest_reward_id,
            q.end_date AS quest_end_date, q.goal_stage AS quest_goal_stage, q.use_yn AS quest_use_yn,
            ap.id AS applied_promotion_id, ap.product_id AS applied_promotion_product_id,
            ap.type AS applied_promotion_type, ap.status AS applied_promotion_status,
            ap.start_date AS applied_promotion_start_date, ap.end_date AS applied_promotion_end_date,
            ap.num_of_ticket_per_person AS applied_promotion_num_of_ticket,
            dp.id AS direct_promotion_id, dp.product_id AS direct_promotion_product_id,
            dp.type AS direct_promotion_type, dp.status AS direct_promotion_status,
            dp.start_date AS direct_promotion_start_date,
            dp.num_of_ticket_per_person AS direct_promotion_num_of_ticket
        FROM tb_user_gift_transaction ugt
        LEFT JOIN tb_user_giftbook ug ON ugt.giftbook_id = ug.id
        LEFT JOIN tb_product p ON p.product_id = coalesce(ug.product_id, if(ug.episode_id is not null, (select product_id from tb_product_episode where episode_id = ug.episode_id), null))
        LEFT JOIN (
            SELECT cf.file_group_id, cfi.file_path
            FROM tb_common_file cf
            JOIN tb_common_file_item cfi ON cf.file_group_id = cfi.file_group_id
            WHERE cf.use_yn = 'Y' AND cfi.use_yn = 'Y' AND cf.group_type = 'cover'
        ) cf ON cf.file_group_id = p.thumbnail_file_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS episode_count
            FROM tb_product_episode
            WHERE use_yn = 'Y'
            GROUP BY product_id
        ) ep_count ON ep_count.product_id = p.product_id
        LEFT JOIN (
            SELECT product_id, COUNT(*) AS free_episode_count
            FROM tb_product_episode
            WHERE price_type = 'free' AND open_yn = 'Y'
            GROUP BY product_id
        ) free_ep ON free_ep.product_id = p.product_id
        LEFT JOIN tb_applied_promotion wff ON wff.product_id = p.product_id AND wff.type = 'waiting-for-free' AND DATE(wff.start_date) <= CURDATE() AND (wff.end_date IS NULL OR DATE(wff.end_date) >= CURDATE())
        LEFT JOIN tb_applied_promotion p69 ON p69.product_id = p.product_id AND p69.type = '6-9-path' AND DATE(p69.start_date) <= CURDATE() AND (p69.end_date IS NULL OR DATE(p69.end_date) >= CURDATE())
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
        LEFT JOIN tb_product_episode pe ON ug.episode_id = pe.episode_id
        LEFT JOIN tb_event_v2 e ON ug.acquisition_type = 'event' AND ug.acquisition_id = e.id
        LEFT JOIN tb_quest q ON ug.acquisition_type = 'quest' AND ug.acquisition_id = q.quest_id
        LEFT JOIN tb_applied_promotion ap ON ug.acquisition_type = 'applied_promotion' AND ug.acquisition_id = ap.id
        LEFT JOIN tb_direct_promotion dp ON ug.acquisition_type = 'direct_promotion' AND ug.acquisition_id = dp.id
        WHERE ugt.user_id = :user_id AND ugt.type = :type
        ORDER BY ugt.created_date DESC
    """)
    result = await db.execute(query, {"user_id": user_id, "type": type})
    rows = result.mappings().all()

    # 데이터 후처리: product와 episode를 중첩 객체로 변환
    data_list = []
    for row in rows:
        row_dict = dict(row)
        transformed = _transform_giftbook_row_to_nested_structure(row_dict)
        data_list.append(transformed)

    res_body = dict()
    res_body["data"] = data_list

    return res_body
