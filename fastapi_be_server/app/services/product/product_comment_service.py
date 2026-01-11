from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import Optional

from app.const import LOGGER_TYPE, settings, ErrorMessages
from app.exceptions import CustomResponseException
import app.schemas.product as product_schema
from app.utils.query import (
    get_file_path_sub_query,
    get_badge_image_sub_query,
    get_user_block_filter,
)
from app.utils.common import handle_exceptions

from app.config.log_config import service_error_logger

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)

"""
product comment 도메인 개별 서비스 함수 모음
"""


async def get_products_product_id_comments(
    product_id: str,
    page: str,
    limit: str,
    order: str,
    kc_user_id: str,
    db: AsyncSession,
    episode_id: Optional[str] = None,
):
    res_data = {}
    product_id_to_int = int(product_id)
    episode_id_to_int = int(episode_id) if episode_id else None
    page_to_int = int(page) if page else settings.PAGINATION_DEFAULT_PAGE_NO
    limit_to_int = int(limit) if limit else settings.PAGINATION_DEFAULT_LIMIT

    if order not in ["recommend", "recent"]:
        order = "recent"

    if kc_user_id:
        res_data = list()

        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)

                if episode_id_to_int:
                    query = text(f"""
                                     select count(1) as count_total
                                       from tb_product_comment a
                                      inner join tb_product_episode c on a.episode_id = c.episode_id
                                        and c.use_yn = 'Y'
                                      where a.product_id = :product_id
                                        and a.episode_id = :episode_id
                                        and a.use_yn = 'Y'
                                        and a.open_yn = 'Y'
                                        {get_user_block_filter()}
                                     """)

                    result = await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id_to_int,
                            "episode_id": episode_id_to_int,
                        },
                    )
                else:
                    query = text(f"""
                                     select count(1) as count_total
                                       from tb_product_comment a
                                      inner join tb_product_episode c on a.episode_id = c.episode_id
                                        and c.use_yn = 'Y'
                                      where a.product_id = :product_id
                                        and a.use_yn = 'Y'
                                        and a.open_yn = 'Y'
                                        {get_user_block_filter()}
                                     """)

                    result = await db.execute(
                        query, {"user_id": user_id, "product_id": product_id_to_int}
                    )

                db_rst = result.mappings().all()

                if db_rst:
                    count_total = db_rst[0].get("count_total")

                if episode_id_to_int:
                    # 회차단위 조회
                    # 본인이 차단한 댓글 제외
                    if order == "recent":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_1 as (
                                             select comment_id
                                                  , recommend_yn as recommend_yn
                                                  , not_recommend_yn as not_recommend_yn
                                               from tb_user_product_comment_recommend
                                              where user_id = :user_id
                                                and product_id = :product_id
                                                and episode_id = :episode_id
                                                and use_yn = 'Y'
                                         ),
                                         tmp_get_products_product_id_comments_2 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , coalesce(d.recommend_yn, 'N') as recommend_yn
                                              , coalesce(d.not_recommend_yn, 'N') as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , e.author_nickname
                                              , e.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                           left join tmp_get_products_product_id_comments_1 d on a.comment_id = d.comment_id
                                          inner join tmp_get_products_product_id_comments_2 e on a.product_id = e.product_id
                                          where a.product_id = :product_id
                                            and a.episode_id = :episode_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                            {get_user_block_filter()}
                                         order by a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)
                    elif order == "recommend":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_1 as (
                                             select comment_id
                                                  , recommend_yn as recommend_yn
                                                  , not_recommend_yn as not_recommend_yn
                                               from tb_user_product_comment_recommend
                                              where user_id = :user_id
                                                and product_id = :product_id
                                                and episode_id = :episode_id
                                                and use_yn = 'Y'
                                         ),
                                         tmp_get_products_product_id_comments_2 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , coalesce(d.recommend_yn, 'N') as recommend_yn
                                              , coalesce(d.not_recommend_yn, 'N') as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , e.author_nickname
                                              , e.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                           left join tmp_get_products_product_id_comments_1 d on a.comment_id = d.comment_id
                                          inner join tmp_get_products_product_id_comments_2 e on a.product_id = e.product_id
                                          where a.product_id = :product_id
                                            and a.episode_id = :episode_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                            {get_user_block_filter()}
                                         order by a.count_recommend desc, a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)

                    result = await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id_to_int,
                            "episode_id": episode_id_to_int,
                            "offset": limit_to_int * (page_to_int - 1),
                            "limit": limit_to_int,
                        },
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        res_data = [
                            product_schema.GetProductsProductIdCommentsToCamel(**row)
                            for row in db_rst
                        ]
                else:
                    # 작품단위 조회
                    # 본인이 차단한 댓글 제외
                    if order == "recent":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_1 as (
                                             select comment_id
                                                  , recommend_yn as recommend_yn
                                                  , not_recommend_yn as not_recommend_yn
                                               from tb_user_product_comment_recommend
                                              where user_id = :user_id
                                                and product_id = :product_id
                                                and use_yn = 'Y'
                                         ),
                                         tmp_get_products_product_id_comments_2 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , coalesce(d.recommend_yn, 'N') as recommend_yn
                                              , coalesce(d.not_recommend_yn, 'N') as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , e.author_nickname
                                              , e.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                           left join tmp_get_products_product_id_comments_1 d on a.comment_id = d.comment_id
                                          inner join tmp_get_products_product_id_comments_2 e on a.product_id = e.product_id
                                          where a.product_id = :product_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                            {get_user_block_filter()}
                                         order by a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)
                    elif order == "recommend":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_1 as (
                                             select comment_id
                                                  , recommend_yn as recommend_yn
                                                  , not_recommend_yn as not_recommend_yn
                                               from tb_user_product_comment_recommend
                                              where user_id = :user_id
                                                and product_id = :product_id
                                                and use_yn = 'Y'
                                         ),
                                         tmp_get_products_product_id_comments_2 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , coalesce(d.recommend_yn, 'N') as recommend_yn
                                              , coalesce(d.not_recommend_yn, 'N') as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , e.author_nickname
                                              , e.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                           left join tmp_get_products_product_id_comments_1 d on a.comment_id = d.comment_id
                                          inner join tmp_get_products_product_id_comments_2 e on a.product_id = e.product_id
                                          where a.product_id = :product_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                            {get_user_block_filter()}
                                         order by a.count_recommend desc, a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)

                    result = await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id_to_int,
                            "offset": limit_to_int * (page_to_int - 1),
                            "limit": limit_to_int,
                        },
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        res_data = [
                            product_schema.GetProductsProductIdCommentsToCamel(**row)
                            for row in db_rst
                        ]
        except OperationalError as e:
            error_logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            error_logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            error_logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        res_data = list()

        try:
            async with db.begin():
                if episode_id_to_int:
                    query = text("""
                                     select count(1) as count_total
                                       from tb_product_comment a
                                      inner join tb_product_episode c on a.episode_id = c.episode_id
                                        and c.use_yn = 'Y'
                                      where a.product_id = :product_id
                                        and a.episode_id = :episode_id
                                        and a.use_yn = 'Y'
                                        and a.open_yn = 'Y'
                                     """)

                    result = await db.execute(
                        query,
                        {
                            "product_id": product_id_to_int,
                            "episode_id": episode_id_to_int,
                        },
                    )
                else:
                    query = text("""
                                     select count(1) as count_total
                                       from tb_product_comment a
                                      inner join tb_product_episode c on a.episode_id = c.episode_id
                                        and c.use_yn = 'Y'
                                      where a.product_id = :product_id
                                        and a.use_yn = 'Y'
                                        and a.open_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"product_id": product_id_to_int})

                db_rst = result.mappings().all()

                if db_rst:
                    count_total = db_rst[0].get("count_total")

                if episode_id_to_int:
                    # 회차단위 조회
                    if order == "recent":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_3 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , 'N' as recommend_yn
                                              , 'N' as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , d.author_nickname
                                              , d.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                          inner join tmp_get_products_product_id_comments_3 d on a.product_id = d.product_id
                                          where a.product_id = :product_id
                                            and a.episode_id = :episode_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                         order by a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)
                    elif order == "recommend":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_3 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , 'N' as recommend_yn
                                              , 'N' as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , d.author_nickname
                                              , d.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                          inner join tmp_get_products_product_id_comments_3 d on a.product_id = d.product_id
                                          where a.product_id = :product_id
                                            and a.episode_id = :episode_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                         order by a.count_recommend desc, a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)

                    result = await db.execute(
                        query,
                        {
                            "product_id": product_id_to_int,
                            "episode_id": episode_id_to_int,
                            "offset": limit_to_int * (page_to_int - 1),
                            "limit": limit_to_int,
                        },
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        res_data = [
                            product_schema.GetProductsProductIdCommentsToCamel(**row)
                            for row in db_rst
                        ]
                else:
                    # 작품단위 조회
                    if order == "recent":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_3 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , 'N' as recommend_yn
                                              , 'N' as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , d.author_nickname
                                              , d.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                          inner join tmp_get_products_product_id_comments_3 d on a.product_id = d.product_id
                                          where a.product_id = :product_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                         order by a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)
                    elif order == "recommend":
                        query = text(f"""
                                         with tmp_get_products_product_id_comments_3 as (
                                             select z.product_id
                                                  , z.author_name as author_nickname
                                                  , {get_file_path_sub_query("y.profile_image_id", "author_profile_image_path", "user")}
                                               from tb_product z
                                              inner join tb_user_profile y on z.author_id = y.user_id
                                                and z.author_name = y.nickname
                                              where product_id = :product_id
                                         )
                                         select a.comment_id
                                              , a.user_id
                                              , b.nickname as user_nickname
                                              , {get_file_path_sub_query("b.profile_image_id", "user_profile_image_path", "user")}
                                              , {get_badge_image_sub_query("a.user_id", "interest", "user_interest_level_badge_image_path")}
                                              , {get_badge_image_sub_query("a.user_id", "event", "user_event_level_badge_image_path")}
                                              , a.content
                                              , a.created_date as publish_date
                                              , a.display_top_yn as author_pinned_top_yn
                                              , a.author_recommend_yn
                                              , a.count_recommend as recommend_count
                                              , a.count_not_recommend as not_recommend_count
                                              , 'N' as recommend_yn
                                              , 'N' as not_recommend_yn
                                              , b.role_type as user_role
                                              , concat('댓글 회차 : ', c.episode_no, '화. ', c.episode_title) as comment_episode
                                              , d.author_nickname
                                              , d.author_profile_image_path
                                           from tb_product_comment a
                                          inner join tb_user_profile b on a.user_id = b.user_id
                                            and a.profile_id = b.profile_id
                                          inner join tb_product_episode c on a.episode_id = c.episode_id
                                            and c.use_yn = 'Y'
                                          inner join tmp_get_products_product_id_comments_3 d on a.product_id = d.product_id
                                          where a.product_id = :product_id
                                            and a.use_yn = 'Y'
                                            and a.open_yn = 'Y'
                                         order by a.count_recommend desc, a.created_date desc, a.comment_id desc
                                         limit :limit offset :offset
                                         """)

                    result = await db.execute(
                        query,
                        {
                            "product_id": product_id_to_int,
                            "offset": limit_to_int * (page_to_int - 1),
                            "limit": limit_to_int,
                        },
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        res_data = [
                            product_schema.GetProductsProductIdCommentsToCamel(**row)
                            for row in db_rst
                        ]
        except OperationalError as e:
            error_logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            error_logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            error_logger.error(e)
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    res_body = {"data": {"commentTotalCount": count_total, "comments": res_data}}

    return res_body


@handle_exceptions
async def post_products_comments_episodes_episode_id(
    episode_id: str,
    req_body: product_schema.PostProductsCommentsEpisodesEpisodeIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_data = {}
    episode_id_to_int = int(episode_id)

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         select a.user_id
                              , b.profile_id
                           from tb_user a
                          inner join tb_user_profile b on a.user_id = b.user_id
                            and b.default_yn = 'Y'
                          where a.kc_user_id = :kc_user_id
                            and a.use_yn = 'Y'
                         """)

        result = await db.execute(query, {"kc_user_id": kc_user_id})
        db_rst = result.mappings().all()
        user_id = db_rst[0].get("user_id")
        profile_id = db_rst[0].get("profile_id")

        # tb_product_comment ins
        query = text("""
                         insert into tb_product_comment (product_id, episode_id, user_id, profile_id, content, created_id, updated_id)
                         select product_id, :episode_id, :user_id, :profile_id, :content, :created_id, :updated_id
                           from tb_product_episode
                          where episode_id = :episode_id
                         """)

        await db.execute(
            query,
            {
                "episode_id": episode_id_to_int,
                "user_id": user_id,
                "profile_id": profile_id,
                "content": req_body.content,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        query = text("""
                         select last_insert_id()
                         """)

        result = await db.execute(query)
        new_comment_id = result.scalar()

        # count 재계산
        query = text("""
                         update tb_product_episode a
                          inner join (
                             select episode_id
                                  , count(1) as count_comment
                               from tb_product_comment
                              where episode_id = :episode_id
                                and use_yn = 'Y'
                              group by episode_id
                           ) as t on a.episode_id = t.episode_id
                            set a.count_comment = t.count_comment
                          where 1=1
                         """)

        await db.execute(query, {"episode_id": episode_id_to_int})

        query = text("""
                         select count_comment
                           from tb_product_episode
                          where episode_id = :episode_id
                         """)

        result = await db.execute(query, {"episode_id": episode_id_to_int})
        db_rst = result.mappings().all()
        count_comment = db_rst[0].get("count_comment")

        # 댓글 알림 전송 - 작품 작가에게 알림
        # 1. 작품 작가 조회
        query = text("""
            select p.user_id as author_user_id, p.title as product_title,
                   e.episode_no, e.episode_title
              from tb_product_episode e
             inner join tb_product p on e.product_id = p.product_id
             where e.episode_id = :episode_id
        """)
        result = await db.execute(query, {"episode_id": episode_id_to_int})
        product_info = result.mappings().first()

        if product_info:
            author_user_id = product_info.get("author_user_id")

            # 자기 작품에 자기가 댓글 단 경우 알림 안 보냄
            if author_user_id != user_id:
                # 2. 작가의 댓글 알림 설정 확인
                query = text("""
                    select noti_yn
                      from tb_user_notification
                     where user_id = :author_user_id
                       and noti_type = 'comment'
                """)
                result = await db.execute(query, {"author_user_id": author_user_id})
                noti_setting = result.mappings().first()

                # 알림 설정이 ON이거나 설정이 없는 경우 (기본값 ON)
                if not noti_setting or noti_setting.get("noti_yn") == "Y":
                    # 3. 댓글 작성자 닉네임 조회
                    query = text("""
                        select nickname
                          from tb_user_profile
                         where user_id = :user_id
                           and profile_id = :profile_id
                    """)
                    result = await db.execute(
                        query, {"user_id": user_id, "profile_id": profile_id}
                    )
                    commenter_info = result.mappings().first()
                    commenter_nickname = (
                        commenter_info.get("nickname") if commenter_info else "독자"
                    )

                    # 4. tb_user_notification_item에 알림 저장
                    product_title = product_info.get("product_title")
                    episode_no = product_info.get("episode_no")
                    episode_title = product_info.get("episode_title")

                    noti_title = f"{product_title}에 새 댓글"
                    noti_content = f"{commenter_nickname}님이 {episode_no}화. {episode_title}에 댓글을 남겼습니다"

                    query = text("""
                        insert into tb_user_notification_item
                        (user_id, noti_type, title, content, read_yn, created_id, created_date)
                        values (:user_id, 'comment', :title, :content, 'N', :created_id, NOW())
                    """)
                    await db.execute(
                        query,
                        {
                            "user_id": author_user_id,
                            "title": noti_title,
                            "content": noti_content,
                            "created_id": user_id,
                        },
                    )

                    # TODO: FCM 푸시 알림 전송 (FCM 토큰 테이블 구현 필요)
                    # FCM 토큰이 있다면:
                    # from app.utils.fcm import send_push, PushNotificationPayload
                    # send_push(PushNotificationPayload(
                    #     token=fcm_token,
                    #     title=noti_title,
                    #     body=noti_content
                    # ))

        res_data = {"commentId": new_comment_id, "commentCount": count_comment}

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def put_products_comments_comment_id(
    comment_id: str,
    req_body: product_schema.PutProductsCommentsCommentIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    comment_id_to_int = int(comment_id)
    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         update tb_product_comment a
                            set a.content = :content
                              , a.updated_id = a.user_id
                          where a.comment_id = :comment_id
                            and a.use_yn = 'Y'
                            and exists (select 1 from tb_user z
                                         where a.user_id = z.user_id
                                           and z.kc_user_id = :kc_user_id
                                           and z.use_yn = 'Y')
                         """)

        await db.execute(
            query,
            {
                "comment_id": comment_id_to_int,
                "kc_user_id": kc_user_id,
                "content": req_body.content,
            },
        )

    return


@handle_exceptions
async def delete_products_comments_comment_id(
    comment_id: str, kc_user_id: str, db: AsyncSession
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_data = {}
    comment_id_to_int = int(comment_id)

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         update tb_product_comment a
                            set a.use_yn = 'N'
                              , a.updated_id = a.user_id
                          where a.comment_id = :comment_id
                            and exists (select 1 from tb_user z
                                         where a.user_id = z.user_id
                                           and z.kc_user_id = :kc_user_id
                                           and z.use_yn = 'Y')
                         """)

        await db.execute(
            query, {"comment_id": comment_id_to_int, "kc_user_id": kc_user_id}
        )

        # count 재계산
        query = text("""
                         update tb_product_episode a
                          inner join (
                             select z.episode_id
                                  , count(1) as count_comment
                               from tb_product_comment z
                               join (select distinct episode_id from tb_product_comment
                                      where comment_id = :comment_id) x on z.episode_id = x.episode_id
                              where z.use_yn = 'Y'
                              group by z.episode_id
                           ) as t on a.episode_id = t.episode_id
                            set a.count_comment = t.count_comment
                          where 1=1
                         """)

        await db.execute(query, {"comment_id": comment_id_to_int})

        query = text("""
                         select a.count_comment
                           from tb_product_episode a
                          inner join tb_product_comment b on a.episode_id = b.episode_id
                            and b.comment_id = :comment_id
                         """)

        result = await db.execute(query, {"comment_id": comment_id_to_int})
        db_rst = result.mappings().all()
        count_comment = db_rst[0].get("count_comment")

        res_data = {
            "commentId": comment_id_to_int,
            "commentCount": count_comment,
        }

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def post_products_comments_comment_id_report(
    comment_id: str,
    req_body: product_schema.PostProductsCommentsCommentIdReportReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    comment_id_to_int = int(comment_id)
    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        # tb_user_report ins
        query = text("""
                         insert into tb_user_report (product_id, episode_id, comment_id, user_id, reported_user_id, report_type, content, created_id, updated_id)
                         select product_id, episode_id, :comment_id, :user_id, user_id as reported_user_id, :report_type, :content, :created_id, :updated_id
                           from tb_product_comment
                          where comment_id = :comment_id
                         """)

        await db.execute(
            query,
            {
                "comment_id": comment_id_to_int,
                "user_id": user_id,
                "report_type": req_body.reportType
                if req_body.reportType != ""
                else None,
                "content": req_body.content,
                "created_id": settings.DB_DML_DEFAULT_ID,
                "updated_id": settings.DB_DML_DEFAULT_ID,
            },
        )

    return


@handle_exceptions
async def put_products_comments_comment_id_block(
    comment_id: str, kc_user_id: str, db: AsyncSession
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_data = {}
    comment_id_to_int = int(comment_id)

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         select id
                              , off_yn
                           from tb_user_block
                          where user_id = :user_id
                            and comment_id = :comment_id
                            and use_yn = 'Y'
                         """)

        result = await db.execute(
            query, {"user_id": user_id, "comment_id": comment_id_to_int}
        )
        db_rst = result.mappings().all()

        if db_rst:
            # tb_user_block upd
            id = db_rst[0].get("id")
            off_yn = db_rst[0].get("off_yn")

            # 현재 값이 N이면 Y, Y면 N으로 전환
            query = text("""
                             update tb_user_block
                                set off_yn = (case when off_yn = 'Y' then 'N' else 'Y' end)
                                  , updated_id = :user_id
                              where id = :id
                             """)

            await db.execute(query, {"id": id, "user_id": user_id})

            if off_yn == "N":
                # N -> Y
                block_yn = "Y"
            else:
                # Y -> N
                block_yn = "N"
        else:
            # tb_user_block ins
            query = text("""
                             insert into tb_user_block (product_id, episode_id, comment_id, user_id, off_user_id, created_id, updated_id)
                             select product_id, episode_id, :comment_id, :user_id, user_id as off_user_id, :created_id, :updated_id
                               from tb_product_comment
                              where comment_id = :comment_id
                             """)

            await db.execute(
                query,
                {
                    "comment_id": comment_id_to_int,
                    "user_id": user_id,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            # 초기값은 무조건 Y
            block_yn = "Y"

        res_data = {"commentId": comment_id_to_int, "blockYn": block_yn}

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def put_products_comments_comment_id_pin(
    comment_id: str, kc_user_id: str, db: AsyncSession
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_data = {}
    comment_id_to_int = int(comment_id)

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         select display_top_yn
                           from tb_product_comment
                          where comment_id = :comment_id
                            and use_yn = 'Y'
                         """)

        result = await db.execute(query, {"comment_id": comment_id_to_int})
        db_rst = result.mappings().all()

        if not db_rst:
            raise CustomResponseException(
                status_code=status.HTTP_404_NOT_FOUND,
                message=ErrorMessages.NOT_FOUND_COMMENT,
            )

        display_top_yn = db_rst[0].get("display_top_yn")

        # 현재 값이 N이면 Y, Y면 N으로 전환 (작가 본인인지 필터링 포함)
        query = text("""
                         update tb_product_comment a
                            set a.display_top_yn = (case when a.display_top_yn = 'N' then 'Y' else 'N' end)
                              , a.updated_id = a.user_id
                          where a.comment_id = :comment_id
                            and a.use_yn = 'Y'
                            and exists (select 1 from tb_user z
                                         where z.kc_user_id = :kc_user_id
                                           and z.use_yn = 'Y'
                                           and exists (select 1 from tb_product x
                                                        where a.product_id = x.product_id
                                                          and z.user_id = x.author_id))
                         """)

        result = await db.execute(
            query,
            {"comment_id": comment_id_to_int, "kc_user_id": kc_user_id},
        )

        # upd된 경우만
        if result.rowcount != 0:
            if display_top_yn == "N":
                # N -> Y
                pinned_yn = "Y"
            else:
                # Y -> N
                pinned_yn = "N"

            res_data = {
                "commentId": comment_id_to_int,
                "authorPinnedTopYn": pinned_yn,
            }
        else:
            # UPDATE가 실패한 경우 (작가가 아니거나 권한이 없음)
            raise CustomResponseException(
                status_code=status.HTTP_403_FORBIDDEN,
                message=ErrorMessages.FORBIDDEN,
            )

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def put_products_comments_comment_id_reaction_recommend(
    comment_id: str, kc_user_id: str, db: AsyncSession
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_data = {}
    comment_id_to_int = int(comment_id)

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         select id
                              , recommend_yn
                           from tb_user_product_comment_recommend
                          where user_id = :user_id
                            and comment_id = :comment_id
                            and use_yn = 'Y'
                         """)

        result = await db.execute(
            query, {"user_id": user_id, "comment_id": comment_id_to_int}
        )
        db_rst = result.mappings().all()

        if db_rst:
            # tb_user_product_comment_recommend upd
            id = db_rst[0].get("id")
            thumbs_up_yn = db_rst[0].get("recommend_yn")

            # 현재 값이 N이면 Y, Y면 N으로 전환
            query = text("""
                             update tb_user_product_comment_recommend
                                set recommend_yn = (case when recommend_yn = 'Y' then 'N' else 'Y' end)
                                  , not_recommend_yn = (case when not_recommend_yn = 'Y' then 'N' else 'N' end)
                                  , updated_id = :user_id
                              where id = :id
                             """)

            await db.execute(query, {"id": id, "user_id": user_id})

            if thumbs_up_yn == "N":
                # N -> Y
                recommend_yn = "Y"
            else:
                # Y -> N
                recommend_yn = "N"

            not_recommend_yn = "N"
        else:
            # tb_user_product_comment_recommend ins
            query = text("""
                             insert into tb_user_product_comment_recommend (product_id, episode_id, comment_id, user_id, recommend_yn, created_id, updated_id)
                             select product_id, episode_id, :comment_id, :user_id, :recommend_yn, :created_id, :updated_id
                               from tb_product_comment
                              where comment_id = :comment_id
                             """)

            await db.execute(
                query,
                {
                    "comment_id": comment_id_to_int,
                    "user_id": user_id,
                    "recommend_yn": "Y",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            # 초기값은 무조건 Y
            recommend_yn = "Y"
            not_recommend_yn = "N"

        # count 재계산
        query = text("""
                         update tb_product_comment a
                          inner join (
                             select z.comment_id
                                  , sum(case when z.recommend_yn = 'Y' then 1 else 0 end) as count_recommend
                                  , sum(case when z.not_recommend_yn = 'Y' then 1 else 0 end) as count_not_recommend
                               from tb_user_product_comment_recommend z
                              where z.use_yn = 'Y'
                                and z.comment_id = :comment_id
                              group by z.comment_id
                           ) as t on a.comment_id = t.comment_id
                            set a.count_recommend = t.count_recommend
                              , a.count_not_recommend = t.count_not_recommend
                              , a.updated_id = :user_id
                          where 1=1
                         """)

        await db.execute(query, {"comment_id": comment_id_to_int, "user_id": user_id})

        query = text("""
                         select count_recommend
                              , count_not_recommend
                           from tb_product_comment
                          where comment_id = :comment_id
                         """)

        result = await db.execute(query, {"comment_id": comment_id_to_int})
        db_rst = result.mappings().all()
        count_recommend = db_rst[0].get("count_recommend")
        count_not_recommend = db_rst[0].get("count_not_recommend")

        res_data = {
            "commentId": comment_id_to_int,
            "recommendCount": count_recommend,
            "recommendYn": recommend_yn,
            "notRecommendCount": count_not_recommend,
            "notRecommendYn": not_recommend_yn,
        }

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def put_products_comments_comment_id_reaction_not_recommend(
    comment_id: str, kc_user_id: str, db: AsyncSession
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    res_data = {}
    comment_id_to_int = int(comment_id)

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         select id
                              , not_recommend_yn
                           from tb_user_product_comment_recommend
                          where user_id = :user_id
                            and comment_id = :comment_id
                            and use_yn = 'Y'
                         """)

        result = await db.execute(
            query, {"user_id": user_id, "comment_id": comment_id_to_int}
        )
        db_rst = result.mappings().all()

        if db_rst:
            # tb_user_product_comment_recommend upd
            id = db_rst[0].get("id")
            thumbs_down_yn = db_rst[0].get("not_recommend_yn")

            # 현재 값이 N이면 Y, Y면 N으로 전환
            query = text("""
                             update tb_user_product_comment_recommend
                                set recommend_yn = (case when recommend_yn = 'Y' then 'N' else 'N' end)
                                  , not_recommend_yn = (case when not_recommend_yn = 'Y' then 'N' else 'Y' end)
                                  , updated_id = :user_id
                              where id = :id
                             """)

            await db.execute(query, {"id": id, "user_id": user_id})

            if thumbs_down_yn == "N":
                # N -> Y
                not_recommend_yn = "Y"
            else:
                # Y -> N
                not_recommend_yn = "N"

            recommend_yn = "N"
        else:
            # tb_user_product_comment_recommend ins
            query = text("""
                             insert into tb_user_product_comment_recommend (product_id, episode_id, comment_id, user_id, not_recommend_yn, created_id, updated_id)
                             select product_id, episode_id, :comment_id, :user_id, :not_recommend_yn, :created_id, :updated_id
                               from tb_product_comment
                              where comment_id = :comment_id
                             """)

            await db.execute(
                query,
                {
                    "comment_id": comment_id_to_int,
                    "user_id": user_id,
                    "not_recommend_yn": "Y",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            # 초기값은 무조건 Y
            not_recommend_yn = "Y"
            recommend_yn = "N"

        # count 재계산
        query = text("""
                         update tb_product_comment a
                          inner join (
                             select z.comment_id
                                  , sum(case when z.recommend_yn = 'Y' then 1 else 0 end) as count_recommend
                                  , sum(case when z.not_recommend_yn = 'Y' then 1 else 0 end) as count_not_recommend
                               from tb_user_product_comment_recommend z
                              where z.use_yn = 'Y'
                                and z.comment_id = :comment_id
                              group by z.comment_id
                           ) as t on a.comment_id = t.comment_id
                            set a.count_recommend = t.count_recommend
                              , a.count_not_recommend = t.count_not_recommend
                              , a.updated_id = :user_id
                          where 1=1
                         """)

        await db.execute(query, {"comment_id": comment_id_to_int, "user_id": user_id})

        query = text("""
                         select count_recommend
                              , count_not_recommend
                           from tb_product_comment
                          where comment_id = :comment_id
                         """)

        result = await db.execute(query, {"comment_id": comment_id_to_int})
        db_rst = result.mappings().all()
        count_recommend = db_rst[0].get("count_recommend")
        count_not_recommend = db_rst[0].get("count_not_recommend")

        res_data = {
            "commentId": comment_id_to_int,
            "recommendCount": count_recommend,
            "recommendYn": recommend_yn,
            "notRecommendCount": count_not_recommend,
            "notRecommendYn": not_recommend_yn,
        }

    res_body = {"data": res_data}

    return res_body
