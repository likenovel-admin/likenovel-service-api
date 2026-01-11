from app.services.common import comm_service
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import LOGGER_TYPE, settings, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.common import handle_exceptions

from app.config.log_config import service_error_logger

# Import from product_service for helper functions
from app.services.product.product_service import (
    get_user_id,
    get_select_fields_and_joins_for_product,
    convert_product_data,
)

error_logger = service_error_logger(LOGGER_TYPE.LOGGER_FILE_NAME_FOR_SERVICE_ERROR)

"""
product bookmark 도메인 개별 서비스 함수 모음
"""


@handle_exceptions
async def delete_products_bookmark(kc_user_id: str, db: AsyncSession):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         update tb_user_bookmark
                            set use_yn = 'N'
                              , updated_id = :user_id
                          where user_id = :user_id
                         """)

        await db.execute(query, {"user_id": user_id})

        # count 재계산
        query = text("""
                         update tb_product a
                          inner join (
                             select z.product_id
                                  , sum(case when z.use_yn = 'Y' then 1 else 0 end) as count_bookmark
                                  , sum(case when z.use_yn = 'N' then 1 else 0 end) as count_unbookmark
                               from tb_user_bookmark z
                               join (select distinct product_id from tb_user_bookmark
                                      where user_id = :user_id) x on z.product_id = x.product_id
                              group by z.product_id
                           ) as t on a.product_id = t.product_id
                            set a.count_bookmark = t.count_bookmark
                              , a.count_unbookmark = t.count_unbookmark
                          where 1=1
                         """)

        await db.execute(query, {"user_id": user_id})

    return


@handle_exceptions
async def put_products_product_id_bookmark(
    product_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    product_id_to_int = int(product_id)

    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    async with db.begin():
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        query = text("""
                         select id
                              , use_yn
                           from tb_user_bookmark
                          where user_id = :user_id
                            and product_id = :product_id
                         """)

        result = await db.execute(
            query, {"user_id": user_id, "product_id": product_id_to_int}
        )
        db_rst = result.mappings().all()

        if db_rst:
            # tb_user_bookmark upd
            id = db_rst[0].get("id")
            use_yn = db_rst[0].get("use_yn")

            # 현재 값이 N이면 Y, Y면 N으로 전환
            query = text("""
                             update tb_user_bookmark
                                set use_yn = (case when use_yn = 'Y' then 'N' else 'Y' end)
                                  , updated_id = :user_id
                              where id = :id
                             """)

            await db.execute(query, {"id": id, "user_id": user_id})

            if use_yn == "N":
                # N -> Y
                bookmark_yn = "Y"
            else:
                # Y -> N
                bookmark_yn = "N"
        else:
            # tb_user_bookmark ins
            query = text("""
                             insert into tb_user_bookmark (user_id, product_id, created_id, updated_id)
                             values (:user_id, :product_id, :created_id, :updated_id)
                             """)

            await db.execute(
                query,
                {
                    "user_id": user_id,
                    "product_id": product_id_to_int,
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            # 초기값은 무조건 Y
            bookmark_yn = "Y"

        # count 재계산
        query = text("""
                         update tb_product a
                          inner join (
                             select z.product_id
                                  , sum(case when z.use_yn = 'Y' then 1 else 0 end) as count_bookmark
                                  , sum(case when z.use_yn = 'N' then 1 else 0 end) as count_unbookmark
                               from tb_user_bookmark z
                              where z.product_id = :product_id
                              group by z.product_id
                           ) as t on a.product_id = t.product_id
                            set a.count_bookmark = t.count_bookmark
                              , a.count_unbookmark = t.count_unbookmark
                          where 1=1
                         """)

        await db.execute(query, {"product_id": product_id_to_int})

        query = text("""
                         select count_bookmark
                           from tb_product
                          where product_id = :product_id
                         """)

        result = await db.execute(query, {"product_id": product_id_to_int})
        db_rst = result.mappings().all()
        count_bookmark = db_rst[0].get("count_bookmark")

        res_data = {
            "productId": product_id_to_int,
            "bookmarkCount": count_bookmark,
            "bookmarkYn": bookmark_yn,
        }

    res_body = {"data": res_data}

    return res_body


@handle_exceptions
async def products_bookmark_by_user_id(
    kc_user_id: str, sort_by: str = "recent_update", db: AsyncSession = None
):
    """
    작품 북마크 목록 조회

    Args:
        kc_user_id: Keycloak user ID
        sort_by: 정렬 기준 (recent_update: 최근 업데이트 순, title: 가나다 순, bookmark_date: 선호작 등록 순)
        db: 데이터베이스 세션
    """

    res_data = []
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    async with db.begin():
        query = text("""
                        select b.product_id
                             , b.created_date as bookmark_created_date
                        from tb_user a
                            inner join tb_user_bookmark b on a.user_id = b.user_id and b.use_yn = 'Y'
                        where 1=1
                            and a.kc_user_id = :kc_user_id
                            and a.use_yn = 'Y'
                         """)

        result = await db.execute(query, {"kc_user_id": kc_user_id})
        db_rst = result.mappings().all()

        if len(db_rst) > 0:
            # 북마크 날짜를 product_id로 매핑
            bookmark_dates = {
                row.get("product_id"): row.get("bookmark_created_date")
                for row in db_rst
            }

            fetch_product_ids = ",".join([str(row.get("product_id")) for row in db_rst])

            # 필터 옵션 설정
            filter_option = []
            filter_option.append(f"p.product_id IN ({fetch_product_ids})")
            filter_option.append("p.open_yn = 'Y'")

            user_id = await get_user_id(kc_user_id, db)

            query_parts = get_select_fields_and_joins_for_product(
                user_id=user_id, join_rank=False
            )

            # 정렬 조건 설정
            if sort_by == "title":
                order_by_clause = "ORDER BY p.title ASC"
                additional_join = ""
                additional_select = ""
            elif sort_by == "bookmark_date":
                order_by_clause = "ORDER BY ub.created_date DESC"
                additional_join = f"""
                    INNER JOIN tb_user_bookmark ub ON p.product_id = ub.product_id
                        AND ub.user_id = {user_id} AND ub.use_yn = 'Y'
                """
                additional_select = ", ub.created_date as bookmark_created_date"
            else:  # recent_update (기본값)
                order_by_clause = "ORDER BY p.last_episode_date DESC"
                additional_join = ""
                additional_select = ""

            query = text(f"""
                SELECT {query_parts["select_fields"]}{additional_select}
                FROM tb_product p
                {query_parts["joins"]}
                {additional_join}
                WHERE {" and ".join(filter_option)}
                {order_by_clause}
            """)
            result = await db.execute(query, {})
            rows = result.mappings().all()
            res_data = [convert_product_data(row) for row in rows]

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

            # 북마크 추가 날짜와 에피소드 정보를 각 작품 데이터에 추가
            for product in res_data:
                product_id = product.get("productId")
                if product_id in bookmark_dates:
                    product["bookmarkCreatedDate"] = (
                        bookmark_dates[product_id].isoformat()
                        if bookmark_dates[product_id]
                        else None
                    )

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
                    product["lastViewedEpisodeId"] = recent_read_map[product_id][
                        "last_viewed_episode_id"
                    ]
                    product["lastViewedEpisodeNo"] = recent_read_map[product_id][
                        "last_viewed_episode_no"
                    ]
                else:
                    product["lastViewedEpisodeId"] = None
                    product["lastViewedEpisodeNo"] = None

    res_body = {"data": res_data}

    return res_body
