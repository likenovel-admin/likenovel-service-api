import logging
from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from typing import Optional

from bs4 import BeautifulSoup

from app.const import settings, CommonConstants, ErrorMessages
from app.exceptions import CustomResponseException
from app.utils.time import convert_to_kor_time
from app.utils.query import get_file_path_sub_query
import app.services.common.comm_service as comm_service
import app.schemas.episode as episode_schema
import app.services.common.statistics_service as statistics_service
import app.services.product.product_service as product_service

logger = logging.getLogger(__name__)

"""
episodes 도메인 개별 서비스 함수 모음
"""


async def get_episodes_episode_id(episode_id: str, kc_user_id: str, db: AsyncSession):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            liked = await check_like_product_episode(
                episode_id=episode_id_to_int, kc_user_id=kc_user_id, db=db
            )

            query = text("""
                                select user_id
                                from tb_user
                                where kc_user_id = :kc_user_id
                                and use_yn = 'Y'
                                """)

            result = await db.execute(query, {"kc_user_id": kc_user_id})
            db_rst = result.mappings().all()
            user_id = db_rst[0].get("user_id")

            query = text("""
                                with tmp_get_episodes_episode_id_1 as (                                     
                                select 
                                    a.product_id
                                    , max(a.episode_no) as max_episode
                                    , b.title
                                from tb_product_episode a
                                    inner join tb_product b on a.product_id = b.product_id
                                where exists ( 
                                    select b.product_id from tb_product_episode b
                                    where b.episode_id = :episode_id
                                        and b.product_id = a.product_id 
                                )
                                and a.use_yn = 'Y'
                                and a.open_yn = 'Y'
                                group by a.product_id 
                                ),
                                tmp_get_episodes_episode_id_2 as (
                                    select e.product_id
                                        , e.prev_episode_id
                                        , e.next_episode_id
                                    from (
                                        select q.product_id
                                            , q.episode_id
                                            , lag(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as prev_episode_id
                                            , lead(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as next_episode_id
                                            from tb_product_episode q                                            
                                        where exists (select w.product_id from tb_product_episode w
                                                        where w.episode_id = :episode_id
                                                        and q.product_id = w.product_id)
                                            and q.use_yn = 'Y'
                                            and q.open_yn = 'Y'
                                    ) e
                                    where e.episode_id = :episode_id
                                ),
                                tmp_get_episodes_episode_id_3 as (
                                    select user_id
                                    from tb_user_profile
                                    where user_id = :user_id
                                    and role_type = 'cp'
                                )
                                select a.product_id                                      
                                    , e.title
                                    , concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                    , (select y.file_name from tb_common_file z, tb_common_file_item y
                                        where z.file_group_id = y.file_group_id
                                        and z.use_yn = 'Y'
                                        and y.use_yn = 'Y'
                                        and z.group_type = 'epub'
                                        and a.epub_file_id = z.file_group_id) as epub_file_name
                                    , a.count_comment
                                    , b.id as usage_id
                                    , coalesce(b.recommend_yn, 'N') as recommend_yn
                                    , coalesce(c.use_yn, 'N') as bookmark_yn
                                    , a.author_comment
                                    , case when d.eval_code is null then 'N'
                                            else 'Y'
                                    end as evaluation_yn
                                    , case when a.episode_no = e.max_episode then null
                                            else a.episode_no + 1
                                    end as next_episode
                                    , a.comment_open_yn
                                    , a.evaluation_open_yn
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                    , f.prev_episode_id
                                    , f.next_episode_id
                                    , a.price_type
                                    , (select own_type from tb_user_productbook where (
                                        episode_id = a.episode_id -- 해당 에피소드 지정
                                        or
                                        (product_id = a.product_id and episode_id is null) -- 해당 작품 지정
                                        or
                                        product_id is null -- 모든 작품/에피소드에 사용 가능
                                    ) and user_id = :user_id
                                    and use_yn = 'Y'
                                    and (own_type = 'own' or (own_type = 'rental' and (rental_expired_date IS NULL OR rental_expired_date > NOW())))
                                    order by case when own_type = 'own' then 0 else 1 end, id desc limit 1) as own_type
                                    , (select own_type from tb_user_productbook where (
                                        episode_id = f.prev_episode_id -- 이전 에피소드 지정
                                        or
                                        (product_id = a.product_id and episode_id is null) -- 해당 작품 지정
                                        or
                                        product_id is null -- 모든 작품/에피소드에 사용 가능
                                    ) and user_id = :user_id
                                    and use_yn = 'Y'
                                    and (own_type = 'own' or (own_type = 'rental' and (rental_expired_date IS NULL OR rental_expired_date > NOW())))
                                    order by case when own_type = 'own' then 0 else 1 end, id desc limit 1) as prev_own_type
                                    , (select own_type from tb_user_productbook where (
                                        episode_id = f.next_episode_id -- 다음 에피소드 지정
                                        or
                                        (product_id = a.product_id and episode_id is null) -- 해당 작품 지정
                                        or
                                        product_id is null -- 모든 작품/에피소드에 사용 가능
                                    ) and user_id = :user_id
                                    and use_yn = 'Y'
                                    and (own_type = 'own' or (own_type = 'rental' and (rental_expired_date IS NULL OR rental_expired_date > NOW())))
                                    order by case when own_type = 'own' then 0 else 1 end, id desc limit 1) as next_own_type
                                    , (select price_type from tb_product_episode where episode_id = f.prev_episode_id) as prev_price_type
                                    , (select price_type from tb_product_episode where episode_id = f.next_episode_id) as next_price_type
                                    , (select TIMESTAMPDIFF(SECOND, NOW(), rental_expired_date) from tb_user_productbook where (
                                        episode_id = f.prev_episode_id
                                        or
                                        (product_id = a.product_id and episode_id is null)
                                        or
                                        product_id is null
                                    ) and user_id = :user_id
                                    and own_type = 'rental' and use_yn = 'Y'
                                    and rental_expired_date > NOW()
                                    order by id desc limit 1) as prev_rental_remaining
                                    , (select TIMESTAMPDIFF(SECOND, NOW(), rental_expired_date) from tb_user_productbook where (
                                        episode_id = f.next_episode_id
                                        or
                                        (product_id = a.product_id and episode_id is null)
                                        or
                                        product_id is null
                                    ) and user_id = :user_id
                                    and own_type = 'rental' and use_yn = 'Y'
                                    and rental_expired_date > NOW()
                                    order by id desc limit 1) as next_rental_remaining
                                from tb_product_episode a
                                inner join tmp_get_episodes_episode_id_1 e on a.product_id = e.product_id
                                inner join tmp_get_episodes_episode_id_2 f on a.product_id = f.product_id
                                left join tb_user_product_usage b on a.product_id = b.product_id
                                    and a.episode_id = b.episode_id
                                    and b.use_yn = 'Y'
                                    and b.user_id = :user_id
                                left join tb_user_bookmark c on a.product_id = c.product_id
                                    and c.user_id = :user_id
                                left join tb_product_evaluation d on a.product_id = d.product_id
                                    and a.episode_id = d.episode_id
                                    and d.use_yn = 'Y'
                                    and d.user_id = :user_id                                    
                                left join tmp_get_episodes_episode_id_3 g on g.user_id = :user_id
                                where a.episode_id = :episode_id
                                and a.use_yn = 'Y'
                                """)

            result = await db.execute(
                query, {"user_id": user_id, "episode_id": episode_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                epub_file_path = comm_service.make_r2_presigned_url(
                    type="download",
                    bucket_name=settings.R2_SC_EPUB_BUCKET,
                    file_id=db_rst[0].get("epub_file_name"),
                )

                product_id = db_rst[0].get("product_id")
                try:
                    usage_id = db_rst[0].get("usage_id")
                except Exception:
                    usage_id = None

                res_data = {
                    "product_id": product_id,
                    "title": db_rst[0].get("title"),
                    "episodeTitle": db_rst[0].get("episode_title"),
                    "epubFilePath": epub_file_path,
                    "bingeWatchYn": "N",  # TODO: 정주행 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
                    "commentCount": db_rst[0].get("count_comment"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "Y" if liked else "N",
                    "recommendYn": db_rst[0].get("recommend_yn"),
                    "bookmarkYn": db_rst[0].get("bookmark_yn"),
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationYn": db_rst[0].get("evaluation_yn"),
                    "nextEpisodes": db_rst[0].get("next_episode"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "previousEpisodeId": db_rst[0].get(
                        "prev_episode_id"
                    ),  # TODO: 이전화/다음화 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
                    "nextEpisodeId": db_rst[0].get(
                        "next_episode_id"
                    ),  # TODO: 이전화/다음화 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
                    "priceType": db_rst[0].get("price_type"),
                    "ownType": db_rst[0].get("own_type")
                    if db_rst[0].get("own_type")
                    else None,
                    "previousEpisodeOwnType": db_rst[0].get("prev_own_type")
                    if db_rst[0].get("prev_own_type")
                    else None,
                    "nextEpisodeOwnType": db_rst[0].get("next_own_type")
                    if db_rst[0].get("next_own_type")
                    else None,
                    "previousEpisodePriceType": db_rst[0].get("prev_price_type"),
                    "nextEpisodePriceType": db_rst[0].get("next_price_type"),
                    "previousEpisodeRentalRemaining": db_rst[0].get(
                        "prev_rental_remaining"
                    ),
                    "nextEpisodeRentalRemaining": db_rst[0].get(
                        "next_rental_remaining"
                    ),
                }

                # query = text("""
                #                  select id
                #                  from tb_user_product_usage
                #                  where user_id = :user_id
                #                     and product_id = :product_id
                #                     and episode_id = :episode_id
                #                  """)

                # result = await db.execute(query, {
                #     "user_id": user_id,
                #     "product_id": product_id,
                #     "episode_id": episode_id_to_int
                # })
                # db_rst = result.mappings().all()

                if usage_id is not None:
                    # tb_user_product_usage upd
                    # id = db_rst[0].get("id")
                    # TODO : upsert 실행문으로 변경필요

                    query = text("""
                                        update tb_user_product_usage
                                        set updated_id = :user_id
                                        where id = :id
                                        """)

                    await db.execute(query, {"id": usage_id, "user_id": user_id})
                else:
                    # tb_user_product_usage ins
                    query = text("""
                                        insert into tb_user_product_usage (user_id, product_id, episode_id, created_id, updated_id)
                                        values (:user_id, :product_id, :episode_id, :created_id, :updated_id)
                                        """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id,
                            "episode_id": episode_id_to_int,
                            "created_id": settings.DB_DML_DEFAULT_ID,
                            "updated_id": settings.DB_DML_DEFAULT_ID,
                        },
                    )

                query = text("""
                                    select 1
                                    from tb_user_profile
                                    where user_id = :user_id
                                    and role_type = 'cp'
                                    """)

                result = await db.execute(query, {"user_id": user_id})
                db_rst = result.mappings().all()

                cp_yn = CommonConstants.YES if db_rst else CommonConstants.NO

                # count 재계산
                query = text("""
                                    update tb_product_episode
                                    set count_hit = count_hit + 1
                                    where episode_id = :episode_id
                                    """)

                await db.execute(query, {"episode_id": episode_id_to_int})

                query = text("""
                                    update tb_product
                                    set count_hit = count_hit + 1
                                        , count_cp_hit = (case when :cp_yn = 'Y' then count_cp_hit + 1 else count_cp_hit end)
                                    where product_id = :product_id
                                    """)

                await db.execute(query, {"product_id": product_id, "cp_yn": cp_yn})

                # 작품 일별 조회수 로그 저장
                await product_service.save_product_hit_log(product_id=product_id, db=db)

            else:
                logger.warning("db_rst is None")

            await statistics_service.insert_site_statistics_log(
                db=db, type="visit", user_id=user_id
            )
            await statistics_service.insert_site_statistics_log(
                db=db, type="page_view", user_id=user_id
            )
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
        try:
            query = text("""
                                with tmp_get_episodes_episode_id_1 as (
                                    select product_id
                                        , max(episode_no) as max_episode
                                    from tb_product_episode
                                    where product_id in (select product_id from tb_product_episode
                                                        where episode_id = :episode_id)
                                    and use_yn = 'Y'
                                    and open_yn = 'Y'
                                    group by product_id
                                ),
                                tmp_get_episodes_episode_id_2 as (
                                    select e.product_id
                                        , e.prev_episode_id
                                        , e.next_episode_id
                                    from (
                                        select q.product_id
                                            , q.episode_id
                                            , lag(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as prev_episode_id
                                            , lead(q.episode_id, 1) over (partition by q.product_id order by q.episode_no) as next_episode_id
                                            from tb_product_episode q
                                        where q.product_id in (select w.product_id from tb_product_episode w
                                                                where w.episode_id = :episode_id)
                                            and q.use_yn = 'Y'
                                            and q.open_yn = 'Y'
                                    ) e
                                    where e.episode_id = :episode_id
                                )
                                select a.product_id
                                    , (select z.title from tb_product z
                                        where z.product_id = a.product_id) as title
                                    , concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                    , (select y.file_name from tb_common_file z, tb_common_file_item y
                                        where z.file_group_id = y.file_group_id
                                        and z.use_yn = 'Y'
                                        and y.use_yn = 'Y'
                                        and z.group_type = 'epub'
                                        and a.epub_file_id = z.file_group_id) as epub_file_name
                                    , a.count_comment
                                    , a.author_comment
                                    , case when a.episode_no = b.max_episode then null
                                            else a.episode_no + 1
                                    end as next_episode
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                    , a.comment_open_yn
                                    , a.evaluation_open_yn
                                    , c.prev_episode_id
                                    , c.next_episode_id
                                    , a.price_type
                                    , (select price_type from tb_product_episode where episode_id = c.prev_episode_id) as prev_price_type
                                    , (select price_type from tb_product_episode where episode_id = c.next_episode_id) as next_price_type
                                from tb_product_episode a
                                inner join tmp_get_episodes_episode_id_1 b on a.product_id = b.product_id
                                inner join tmp_get_episodes_episode_id_2 c on a.product_id = c.product_id
                                where a.episode_id = :episode_id
                                and a.use_yn = 'Y'
                                """)

            result = await db.execute(query, {"episode_id": episode_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                epub_file_path = comm_service.make_r2_presigned_url(
                    type="download",
                    bucket_name=settings.R2_SC_EPUB_BUCKET,
                    file_id=db_rst[0].get("epub_file_name"),
                )

                res_data = {
                    "product_id": db_rst[0].get("product_id"),
                    "title": db_rst[0].get("title"),
                    "episodeTitle": db_rst[0].get("episode_title"),
                    "epubFilePath": epub_file_path,
                    "bingeWatchYn": "N",  # TODO: 정주행 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
                    "commentCount": db_rst[0].get("count_comment"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "N",
                    "recommendYn": "N",
                    "bookmarkYn": "N",
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationYn": "N",
                    "nextEpisodes": db_rst[0].get("next_episode"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "previousEpisodeId": db_rst[0].get(
                        "prev_episode_id"
                    ),  # TODO: 이전화/다음화 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
                    "nextEpisodeId": db_rst[0].get(
                        "next_episode_id"
                    ),  # TODO: 이전화/다음화 모듈 구현 후 수정 및 최종 테스트 필(초안 개발 완료)
                    "priceType": db_rst[0].get("price_type"),
                    "ownType": None,
                    "previousEpisodeOwnType": None,
                    "nextEpisodeOwnType": None,
                    "previousEpisodePriceType": db_rst[0].get("prev_price_type"),
                    "nextEpisodePriceType": db_rst[0].get("next_price_type"),
                    "previousEpisodeRentalRemaining": None,
                    "nextEpisodeRentalRemaining": None,
                }

                # count 재계산
                query = text("""
                                    update tb_product_episode
                                    set count_hit = count_hit + 1
                                    where episode_id = :episode_id
                                    """)

                await db.execute(query, {"episode_id": episode_id_to_int})
            else:
                logger.warning("db_rst is None")

            await statistics_service.insert_site_statistics_log(
                db=db, type="visit", user_id=None
            )
            await statistics_service.insert_site_statistics_log(
                db=db, type="page_view", user_id=None
            )
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

    res_body = {"data": res_data}

    return res_body


async def get_episodes_episode_upload_file_name(
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
                                    where a.group_type = 'episode'
                                    and a.use_yn = 'Y'
                                """)

                result = await db.execute(query, {"file_name": file_name_to_uuid})
                db_rst = result.mappings().all()

                if not db_rst:
                    break

            presigned_url = comm_service.make_r2_presigned_url(
                type="upload",
                bucket_name=settings.R2_SC_IMAGE_BUCKET,
                file_id=f"episode/{file_name_to_uuid}",
            )

            query = text("""
                                insert into tb_common_file (group_type, created_id, updated_id)
                                values (:group_type, :created_id, :updated_id)
                                """)

            await db.execute(
                query,
                {
                    "group_type": "episode",
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
                    "file_path": f"{settings.R2_SC_CDN_URL}/episode/{file_name_to_uuid}",
                    "created_id": settings.DB_DML_DEFAULT_ID,
                    "updated_id": settings.DB_DML_DEFAULT_ID,
                },
            )

            res_data = {
                "episodeImageFileId": new_file_group_id,
                "episodeImageUploadPath": presigned_url,
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


async def get_episodes_episode_download_episode_image_file_id(
    episode_image_file_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_image_file_id_to_int = int(episode_image_file_id)

    if kc_user_id:
        try:
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            query = text("""
                                select b.file_path
                                from tb_common_file a
                                inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                and b.use_yn = 'Y'
                                where a.use_yn = 'Y'
                                and a.group_type = 'episode'
                                and a.file_group_id = :file_group_id
                                """)

            result = await db.execute(
                query, {"file_group_id": episode_image_file_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                res_data = {
                    "episodeImageFileId": episode_image_file_id_to_int,
                    "episodeImageDownloadPath": db_rst[0].get("file_path"),
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


async def get_episodes_episode_id_info(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            liked = await check_like_product_episode(
                episode_id=episode_id_to_int, kc_user_id=kc_user_id, db=db
            )

            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            # 먼저 회차가 존재하는지, 삭제되었는지 확인
            check_query = text("""
                                select a.episode_id
                                    , a.use_yn
                                from tb_product_episode a
                                where a.episode_id = :episode_id
                                """)

            check_result = await db.execute(
                check_query, {"episode_id": episode_id_to_int}
            )
            check_row = check_result.mappings().one_or_none()

            if not check_row:
                # 회차가 존재하지 않음
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_FOUND_EPISODE,
                )

            if check_row["use_yn"] == "N":
                # 삭제된 회차
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.DELETED_EPISODE,
                )

            query = text("""
                                select a.episode_id
                                    , a.episode_title as title
                                    , a.episode_content as content
                                    , a.author_comment
                                    , a.evaluation_open_yn
                                    , a.comment_open_yn
                                    , a.open_yn as episode_open_yn
                                    , case when a.publish_reserve_date is null then 'N'
                                            else 'Y'
                                    end as reserve_yn
                                    , a.publish_reserve_date
                                    , a.price_type
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                from tb_product_episode a
                                inner join tb_product b on a.product_id = b.product_id
                                and b.user_id = :user_id
                                where a.episode_id = :episode_id
                                and use_yn = 'Y'
                                """)

            result = await db.execute(
                query, {"user_id": user_id, "episode_id": episode_id_to_int}
            )
            db_rst = result.mappings().all()

            if db_rst:
                res_data = {
                    "episodeId": episode_id_to_int,
                    "title": db_rst[0].get("title"),
                    "content": db_rst[0].get("content"),
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "episodeOpenYn": db_rst[0].get("episode_open_yn"),
                    "publishReserveYn": db_rst[0].get("reserve_yn"),
                    "publishReserveDate": db_rst[0].get("publish_reserve_date"),
                    "priceType": db_rst[0].get("price_type"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "Y" if liked else "N",
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
        try:
            # 회차가 존재하는지 확인
            check_query = text("""
                                select a.episode_id
                                    , a.use_yn
                                from tb_product_episode a
                                where a.episode_id = :episode_id
                                """)

            check_result = await db.execute(
                check_query, {"episode_id": episode_id_to_int}
            )
            check_row = check_result.mappings().one_or_none()

            if not check_row:
                # 회차가 존재하지 않음
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.NOT_FOUND_EPISODE,
                )

            if check_row["use_yn"] == "N":
                # 삭제된 회차
                raise CustomResponseException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    message=ErrorMessages.DELETED_EPISODE,
                )

            query = text("""
                                select a.episode_id
                                    , a.episode_title as title
                                    , a.episode_content as content
                                    , a.author_comment
                                    , a.evaluation_open_yn
                                    , a.comment_open_yn
                                    , a.open_yn as episode_open_yn
                                    , case when a.publish_reserve_date is null then 'N'
                                            else 'Y'
                                    end as reserve_yn
                                    , a.publish_reserve_date
                                    , a.price_type
                                    , (select count(*) from tb_product_episode_like where episode_id = a.episode_id) as count_like
                                from tb_product_episode a
                                inner join tb_product b on a.product_id = b.product_id
                                where a.episode_id = :episode_id
                                and a.use_yn = 'Y'
                                """)
            result = await db.execute(query, {"episode_id": episode_id_to_int})
            db_rst = result.mappings().all()
            if db_rst:
                res_data = {
                    "episodeId": episode_id_to_int,
                    "title": db_rst[0].get("title"),
                    "content": db_rst[0].get("content"),
                    "authorComment": db_rst[0].get("author_comment"),
                    "evaluationOpenYn": db_rst[0].get("evaluation_open_yn"),
                    "commentOpenYn": db_rst[0].get("comment_open_yn"),
                    "episodeOpenYn": db_rst[0].get("episode_open_yn"),
                    "publishReserveYn": db_rst[0].get("reserve_yn"),
                    "publishReserveDate": db_rst[0].get("publish_reserve_date"),
                    "priceType": db_rst[0].get("price_type"),
                    "likeCount": db_rst[0].get("count_like"),
                    "liked": "N",
                }
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

    res_body = {"data": res_data}

    return res_body


async def get_episodes_products_product_id_info(
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
                                select a.title
                                from tb_product a
                                where a.product_id = :product_id
                                """)

            result = await db.execute(query, {"product_id": product_id_to_int})
            db_rst = result.mappings().all()

            if db_rst:
                title = db_rst[0].get("title")

                query = text("""
                                    with tmp_get_episodes_products_product_id_info as (
                                        select product_id
                                            , max(episode_no) as max_episode
                                        from tb_product_episode
                                        where product_id = :product_id
                                        and use_yn = 'Y'
                                        group by product_id
                                    )
                                    select concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                    from tb_product_episode a
                                    inner join tmp_get_episodes_products_product_id_info b on a.product_id = b.product_id
                                    and a.episode_no = b.max_episode
                                    """)

                result = await db.execute(query, {"product_id": product_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    res_data = {
                        "title": title,
                        "episodeTitle": db_rst[0].get("episode_title"),
                    }
                else:
                    res_data = {"title": title, "episodeTitle": None}
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


async def post_episodes_products_product_id(
    product_id: str,
    req_body: episode_schema.PostEpisodesProductsProductIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
    save: Optional[str] = None,
    episode_id: Optional[str] = None,
):
    res_data = {}
    product_id_to_int = int(product_id)
    episode_id_to_int = int(episode_id) if episode_id else None

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # 중복 에피소드 생성 방지 (10초 내 동일 제목, 신규 생성시에만 체크)
                if episode_id_to_int is None:
                    duplicate_check_query = text("""
                        SELECT COUNT(*) as cnt FROM tb_product_episode
                        WHERE product_id = :product_id
                          AND episode_title = :episode_title
                          AND created_date > DATE_SUB(NOW(), INTERVAL 10 SECOND)
                    """)
                    duplicate_result = await db.execute(
                        duplicate_check_query,
                        {"product_id": product_id_to_int, "episode_title": req_body.title}
                    )
                    duplicate_count = duplicate_result.scalar()
                    if duplicate_count > 0:
                        raise CustomResponseException(
                            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                            message=ErrorMessages.DUPLICATE_EPISODE_CREATION,
                        )

                # 본인이 등록한 작품인지 검증 및 작품 정보 조회
                query = text("""
                                 select price_type
                                   from tb_product
                                  where user_id = :user_id
                                    and product_id = :product_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "product_id": product_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    product_price_type = db_rst[0]["price_type"]
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # 유료여부 검증
                price_type = "free"
                if req_body.price_type is None or req_body.price_type == "":
                    pass
                else:
                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_PRICE_TYPE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"code_key": req_body.price_type})
                    db_rst = result.mappings().all()

                    if db_rst:
                        price_type = req_body.price_type
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # 무료 작품에서 유료 회차 생성 방지
                if price_type == "paid" and product_price_type != "paid":
                    raise CustomResponseException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                    )

                # 내용 글자수 검증
                try:
                    soup = BeautifulSoup(req_body.content, "html.parser")
                    text_content = soup.get_text(separator=" ", strip=True)  # 태그 제외
                except Exception:
                    # HTML이 아닌 일반 텍스트인 경우
                    text_content = req_body.content

                if len(text_content) > 20000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # 작가의 말 글자수 검증
                if req_body.author_comment is None or req_body.author_comment == "":
                    pass
                else:
                    if len(req_body.author_comment) > 2000:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # 저장 버튼 클릭시 회차목록에 비공개 회차로 등록
                if save == "Y":
                    open_yn = "N"
                elif save == "N":
                    open_yn = req_body.episode_open_yn
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                query = text("""
                                 select 1
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                    and b.user_id = :user_id
                                  where a.episode_id = :episode_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "episode_id": episode_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    # upd - 수정 시에도 무료 작품에서 유료 회차로 변경 방지
                    if price_type == "paid" and product_price_type != "paid":
                        raise CustomResponseException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                        )

                    query = text("""
                                     update tb_product_episode a
                                        set a.price_type = :price_type
                                          , a.episode_title = :episode_title
                                          , a.episode_text_count = :episode_text_count
                                          , a.episode_content = :episode_content
                                          , a.author_comment = :author_comment
                                          , a.comment_open_yn = :comment_open_yn
                                          , a.evaluation_open_yn = :evaluation_open_yn
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "price_type": price_type,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": convert_to_kor_time(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                        },
                    )

                    res_data = {"episodeId": episode_id_to_int}

                    tmp_episode_id = episode_id_to_int
                else:
                    # ins
                    query = text("""
                                     select product_id
                                          , max(episode_no) as max_episode_no
                                       from tb_product_episode
                                      where product_id = :product_id
                                        and use_yn = 'Y'
                                      group by product_id
                                     """)

                    result = await db.execute(query, {"product_id": product_id_to_int})
                    db_rst = result.mappings().all()

                    if db_rst:
                        next_episode_no = db_rst[0].get("max_episode_no") + 1
                    else:
                        next_episode_no = 1

                    query = text("""
                                     insert into tb_product_episode (product_id, price_type, episode_no, episode_title, episode_text_count, episode_content, author_comment, comment_open_yn, evaluation_open_yn, publish_reserve_date, open_yn, created_id, updated_id)
                                     values (:product_id, :price_type, :episode_no, :episode_title, :episode_text_count, :episode_content, :author_comment, :comment_open_yn, :evaluation_open_yn, :publish_reserve_date, :open_yn, :created_id, :updated_id)
                                     """)

                    await db.execute(
                        query,
                        {
                            "product_id": product_id_to_int,
                            "price_type": price_type,
                            "episode_no": next_episode_no,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": convert_to_kor_time(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": open_yn,
                            "created_id": settings.DB_DML_DEFAULT_ID,
                            "updated_id": settings.DB_DML_DEFAULT_ID,
                        },
                    )

                    query = text("""
                                     select last_insert_id()
                                     """)

                    result = await db.execute(query)
                    new_episode_id = result.scalar()

                    res_data = {"episodeId": new_episode_id}

                    tmp_episode_id = new_episode_id

                # last_episode_date upd
                if open_yn == "Y" and req_body.publish_reserve_yn == "N":
                    query = text("""
                                     update tb_product
                                        set last_episode_date = now()
                                      where product_id = :product_id
                                     """)

                    await db.execute(query, {"product_id": product_id_to_int})

                # epub화
                query = text(f"""
                                 select {get_file_path_sub_query("b.thumbnail_file_id", "cover_image_path", "cover")}
                                      , concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                      , a.episode_content
                                      , a.epub_file_id
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                  where episode_id = :episode_id
                                 """)

                result = await db.execute(query, {"episode_id": tmp_episode_id})
                db_rst = result.mappings().all()

                if db_rst:
                    cover_image_path = db_rst[0].get("cover_image_path")
                    episode_title = db_rst[0].get("episode_title")
                    episode_content = db_rst[0].get("episode_content")
                    epub_file_id = db_rst[0].get("epub_file_id")

                    file_org_name = f"{str(tmp_episode_id)}.epub"

                    # 파일 생성
                    await comm_service.make_epub(
                        file_org_name=file_org_name,
                        cover_image_path=cover_image_path,
                        episode_title=episode_title,
                        content_db=episode_content,
                    )

                    if epub_file_id is None:
                        # ins
                        # 랜덤 생성 uuid 중복 체크
                        while True:
                            file_name_to_uuid = comm_service.make_rand_uuid()
                            file_name_to_uuid = f"{file_name_to_uuid}.epub"

                            query = text("""
                                             select a.file_group_id
                                               from tb_common_file a
                                              inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                                and b.use_yn = 'Y'
                                                and b.file_name = :file_name
                                              where a.group_type = 'epub'
                                                and a.use_yn = 'Y'
                                            """)

                            result = await db.execute(
                                query, {"file_name": file_name_to_uuid}
                            )
                            db_rst = result.mappings().all()

                            if not db_rst:
                                break

                        query = text("""
                                         insert into tb_common_file (group_type, created_id, updated_id)
                                         values (:group_type, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "group_type": "epub",
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
                                "file_org_name": file_org_name,
                                "file_path": f"{settings.R2_SC_DOMAIN}/epub/{file_name_to_uuid}",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        epub_file_id = new_file_group_id
                    else:
                        # upd
                        query = text("""
                                         select b.file_name
                                           from tb_common_file a
                                          inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                            and b.use_yn = 'Y'
                                          where a.group_type = 'epub'
                                            and a.use_yn = 'Y'
                                            and a.file_group_id = :epub_file_id
                                        """)

                        result = await db.execute(query, {"epub_file_id": epub_file_id})
                        db_rst = result.mappings().all()

                        if db_rst:
                            file_name_to_uuid = db_rst[0].get("file_name")

                    presigned_url = comm_service.make_r2_presigned_url(
                        type="upload",
                        bucket_name=settings.R2_SC_EPUB_BUCKET,
                        file_id=file_name_to_uuid,
                    )

                    # 파일 업로드
                    await comm_service.upload_epub_to_r2(
                        url=presigned_url, file_name=file_org_name
                    )

                    query = text("""
                                     update tb_product_episode a
                                        set a.epub_file_id = :epub_file_id
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": tmp_episode_id,
                            "epub_file_id": epub_file_id,
                        },
                    )
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


async def put_episodes_episode_id(
    episode_id: str,
    req_body: episode_schema.PutEpisodesEpisodeIdReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                # 본인이 등록한 작품인지 검증
                query = text("""
                                 select a.product_id
                                      , a.last_episode_date
                                      , a.price_type
                                   from tb_product a
                                  inner join tb_product_episode b on a.product_id = b.product_id
                                    and b.use_yn = 'Y'
                                    and b.episode_id = :episode_id
                                  where a.user_id = :user_id
                                 """)

                result = await db.execute(
                    query, {"user_id": user_id, "episode_id": episode_id_to_int}
                )
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")
                    last_episode_date = db_rst[0].get("last_episode_date")
                    product_price_type = db_rst[0].get("price_type")
                else:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # 유료여부 검증
                price_type = None
                if req_body.price_type is None or req_body.price_type == "":
                    pass
                else:
                    # 무료 작품인 경우 유료 회차로 수정 불가
                    if product_price_type == "free" and req_body.price_type != "free":
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE,
                        )

                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_PRICE_TYPE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"code_key": req_body.price_type})
                    db_rst = result.mappings().all()

                    if db_rst:
                        price_type = req_body.price_type
                    else:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                # 내용 글자수 검증
                try:
                    soup = BeautifulSoup(req_body.content, "html.parser")
                    text_content = soup.get_text(separator=" ", strip=True)  # 태그 제외
                except Exception:
                    # HTML이 아닌 일반 텍스트인 경우
                    text_content = req_body.content

                if len(text_content) > 20000:
                    raise CustomResponseException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        message=ErrorMessages.INVALID_EPISODE_INFO,
                    )

                # 작가의 말 글자수 검증
                if req_body.author_comment is None or req_body.author_comment == "":
                    pass
                else:
                    if len(req_body.author_comment) > 2000:
                        raise CustomResponseException(
                            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            message=ErrorMessages.INVALID_EPISODE_INFO,
                        )

                if price_type is None:
                    query = text("""
                                     update tb_product_episode a
                                        set a.episode_title = :episode_title
                                          , a.episode_text_count = :episode_text_count
                                          , a.episode_content = :episode_content
                                          , a.author_comment = :author_comment
                                          , a.comment_open_yn = :comment_open_yn
                                          , a.evaluation_open_yn = :evaluation_open_yn
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": convert_to_kor_time(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": req_body.episode_open_yn,
                        },
                    )
                else:
                    query = text("""
                                     update tb_product_episode a
                                        set a.price_type = :price_type
                                          , a.episode_title = :episode_title
                                          , a.episode_text_count = :episode_text_count
                                          , a.episode_content = :episode_content
                                          , a.author_comment = :author_comment
                                          , a.comment_open_yn = :comment_open_yn
                                          , a.evaluation_open_yn = :evaluation_open_yn
                                          , a.publish_reserve_date = :publish_reserve_date
                                          , a.open_yn = :open_yn
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "price_type": price_type,
                            "episode_title": req_body.title,
                            "episode_text_count": len(text_content),
                            "episode_content": req_body.content,
                            "author_comment": req_body.author_comment,
                            "comment_open_yn": req_body.comment_open_yn,
                            "evaluation_open_yn": req_body.evaluation_open_yn,
                            "publish_reserve_date": convert_to_kor_time(
                                req_body.publish_reserve_date
                            )
                            if req_body.publish_reserve_yn == "Y"
                            else None,
                            "open_yn": req_body.episode_open_yn,
                        },
                    )

                # last_episode_date upd
                if (
                    req_body.episode_open_yn == "Y"
                    and req_body.publish_reserve_yn == "N"
                ):
                    if last_episode_date is None:
                        query = text("""
                                         update tb_product
                                            set last_episode_date = now()
                                          where product_id = :product_id
                                         """)

                        await db.execute(query, {"product_id": product_id})

                # epub화
                query = text(f"""
                                 select {get_file_path_sub_query("b.thumbnail_file_id", "cover_image_path", "cover")}
                                      , concat(a.episode_no, '화. ', a.episode_title) as episode_title
                                      , a.episode_content
                                      , a.epub_file_id
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                  where episode_id = :episode_id
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    cover_image_path = db_rst[0].get("cover_image_path")
                    episode_title = db_rst[0].get("episode_title")
                    episode_content = db_rst[0].get("episode_content")
                    epub_file_id = db_rst[0].get("epub_file_id")

                    file_org_name = f"{str(episode_id_to_int)}.epub"

                    # 파일 생성
                    await comm_service.make_epub(
                        file_org_name=file_org_name,
                        cover_image_path=cover_image_path,
                        episode_title=episode_title,
                        content_db=episode_content,
                    )

                    if epub_file_id is None:
                        # ins
                        # 랜덤 생성 uuid 중복 체크
                        while True:
                            file_name_to_uuid = comm_service.make_rand_uuid()
                            file_name_to_uuid = f"{file_name_to_uuid}.epub"

                            query = text("""
                                             select a.file_group_id
                                               from tb_common_file a
                                              inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                                and b.use_yn = 'Y'
                                                and b.file_name = :file_name
                                              where a.group_type = 'epub'
                                                and a.use_yn = 'Y'
                                            """)

                            result = await db.execute(
                                query, {"file_name": file_name_to_uuid}
                            )
                            db_rst = result.mappings().all()

                            if not db_rst:
                                break

                        query = text("""
                                         insert into tb_common_file (group_type, created_id, updated_id)
                                         values (:group_type, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "group_type": "epub",
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
                                "file_org_name": file_org_name,
                                "file_path": f"{settings.R2_SC_DOMAIN}/epub/{file_name_to_uuid}",
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        epub_file_id = new_file_group_id
                    else:
                        # upd
                        query = text("""
                                         select b.file_name
                                           from tb_common_file a
                                          inner join tb_common_file_item b on a.file_group_id = b.file_group_id
                                            and b.use_yn = 'Y'
                                          where a.group_type = 'epub'
                                            and a.use_yn = 'Y'
                                            and a.file_group_id = :epub_file_id
                                        """)

                        result = await db.execute(query, {"epub_file_id": epub_file_id})
                        db_rst = result.mappings().all()

                        if db_rst:
                            file_name_to_uuid = db_rst[0].get("file_name")

                    presigned_url = comm_service.make_r2_presigned_url(
                        type="upload",
                        bucket_name=settings.R2_SC_EPUB_BUCKET,
                        file_id=file_name_to_uuid,
                    )

                    # 파일 업로드
                    await comm_service.upload_epub_to_r2(
                        url=presigned_url, file_name=file_org_name
                    )

                    query = text("""
                                     update tb_product_episode a
                                        set a.epub_file_id = :epub_file_id
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                     """)

                    await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "episode_id": episode_id_to_int,
                            "epub_file_id": epub_file_id,
                        },
                    )
        except CustomResponseException:
            raise
        except OperationalError as e:
            logger.error(
                f"OperationalError in put_episodes_episode_id: {str(e)}", exc_info=True
            )
            raise CustomResponseException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE
            )
        except SQLAlchemyError as e:
            logger.error(
                f"SQLAlchemyError in put_episodes_episode_id: {str(e)}", exc_info=True
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
        except Exception as e:
            logger.error(
                f"Exception in put_episodes_episode_id: {str(e)}", exc_info=True
            )
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    else:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.EXPIRED_ACCESS_TOKEN,
        )

    return


async def put_episodes_episode_id_open(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select a.product_id
                                      , a.open_yn
                                      , case when a.publish_reserve_date is null then 'N'
                                             else 'Y'
                                        end as publish_reserve_yn
                                      , b.last_episode_date
                                   from tb_product_episode a
                                  inner join tb_product b on a.product_id = b.product_id
                                  where a.episode_id = :episode_id
                                    and a.use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")
                    open_yn = db_rst[0].get("open_yn")
                    publish_reserve_yn = db_rst[0].get("publish_reserve_yn")
                    last_episode_date = db_rst[0].get("last_episode_date")

                    # 현재 값이 N이면 Y, Y면 N으로 전환
                    # 수동 변경 시 open_changed_date가 갱신되어 배치에서 예약 공개 제외됨
                    query = text("""
                                     update tb_product_episode a
                                        set a.open_yn = (case when a.open_yn = 'N' then 'Y' else 'N' end)
                                          , a.open_changed_date = NOW()
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                        and a.use_yn = 'Y'
                                        and exists (select 1 from tb_product z
                                                     where a.product_id = z.product_id
                                                       and z.user_id = :user_id)
                                     """)

                    result = await db.execute(
                        query, {"episode_id": episode_id_to_int, "user_id": user_id}
                    )

                    if open_yn == "N":
                        # N -> Y
                        episode_open_yn = "Y"
                    else:
                        # Y -> N
                        episode_open_yn = "N"

                    # upd된 경우만
                    if result.rowcount != 0:
                        res_data = {
                            "episodeId": episode_id_to_int,
                            "openYn": episode_open_yn,
                        }

                        # last_episode_date upd
                        if episode_open_yn == "Y" and publish_reserve_yn == "N":
                            if last_episode_date is None:
                                query = text("""
                                                 update tb_product
                                                    set last_episode_date = now()
                                                  where product_id = :product_id
                                                 """)

                                await db.execute(query, {"product_id": product_id})

                            # 작품 업데이트 알림 - 선작 등록(북마크)한 사용자들에게 전송
                            try:
                                # 작품 정보 및 회차 정보 조회
                                query = text("""
                                    select p.title as product_title, e.episode_no, e.episode_title
                                      from tb_product p
                                     inner join tb_product_episode e on p.product_id = e.product_id
                                     where e.episode_id = :episode_id
                                """)
                                result = await db.execute(
                                    query, {"episode_id": episode_id_to_int}
                                )
                                episode_info = result.mappings().first()

                                if episode_info:
                                    product_title = episode_info.get("product_title")
                                    episode_no = episode_info.get("episode_no")
                                    episode_title = episode_info.get("episode_title")

                                    # 선작 등록(북마크)한 사용자 조회 (혜택정보 알림 설정 ON인 사용자)
                                    query = text("""
                                        select b.user_id
                                          from tb_user_bookmark b
                                         where b.product_id = :product_id
                                           and b.use_yn = 'Y'
                                           and (
                                               not exists (
                                                   select 1 from tb_user_notification n
                                                    where n.user_id = b.user_id
                                                      and n.noti_type = 'benefit'
                                               )
                                               or exists (
                                                   select 1 from tb_user_notification n
                                                    where n.user_id = b.user_id
                                                      and n.noti_type = 'benefit'
                                                      and n.noti_yn = 'Y'
                                               )
                                           )
                                    """)
                                    result = await db.execute(
                                        query, {"product_id": product_id}
                                    )
                                    bookmarked_users = result.mappings().all()

                                    # 각 사용자에게 알림 저장 (5. 선작 등록한 작품의 업데이트 알림)
                                    noti_title = (
                                        f"[{product_title}]에 새로운 회차가 업데이트"
                                    )
                                    noti_content = f"{episode_no}화. {episode_title}"

                                    for user in bookmarked_users:
                                        query = text("""
                                            insert into tb_user_notification_item
                                            (user_id, noti_type, title, content, read_yn, created_id, created_date)
                                            values (:user_id, 'benefit', :title, :content, 'N', :created_id, NOW())
                                        """)
                                        await db.execute(
                                            query,
                                            {
                                                "user_id": user.get("user_id"),
                                                "title": noti_title,
                                                "content": noti_content,
                                                "created_id": user_id,
                                            },
                                        )

                                    # TODO: FCM 푸시 전송 (FCM 토큰 테이블 구현 필요)
                            except Exception as e:
                                # 알림 전송 실패해도 회차 공개는 성공으로 처리
                                logger.error(
                                    f"Failed to send episode update notification: {e}"
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

    res_body = {"data": res_data}

    return res_body


async def put_episodes_episode_id_paid(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select coalesce(price_type, 'free') as price_type
                                   from tb_product_episode
                                  where episode_id = :episode_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    price_type = db_rst[0].get("price_type")

                    # 현재 값이 N이면 Y, Y면 N으로 전환
                    query = text("""
                                     update tb_product_episode a
                                        set a.price_type = (case when a.price_type is null or a.price_type = 'free' then 'paid' else 'free' end)
                                          , a.updated_id = :user_id
                                      where a.episode_id = :episode_id
                                        and a.use_yn = 'Y'
                                        and exists (select 1 from tb_product z
                                                     where a.product_id = z.product_id
                                                       and z.user_id = :user_id
                                                       and z.price_type = 'paid')
                                     """)

                    result = await db.execute(
                        query, {"episode_id": episode_id_to_int, "user_id": user_id}
                    )

                    if price_type == "free":
                        # N -> Y
                        episode_price_type = "paid"
                    else:
                        # Y -> N
                        episode_price_type = "free"

                    # upd된 경우만
                    if result.rowcount != 0:
                        res_data = {
                            "episodeId": episode_id_to_int,
                            "priceType": episode_price_type,
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


async def put_episodes_episode_id_reaction(
    episode_id: str, kc_user_id: str, db: AsyncSession
):
    res_data = {}
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select product_id
                                   from tb_product_episode
                                  where episode_id = :episode_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")

                    query = text("""
                                     select id
                                          , recommend_yn
                                       from tb_user_product_usage
                                      where user_id = :user_id
                                        and product_id = :product_id
                                        and episode_id = :episode_id
                                     """)

                    result = await db.execute(
                        query,
                        {
                            "user_id": user_id,
                            "product_id": product_id,
                            "episode_id": episode_id_to_int,
                        },
                    )
                    db_rst = result.mappings().all()

                    if db_rst:
                        # tb_user_product_usage upd
                        id = db_rst[0].get("id")
                        thumbs_up_yn = db_rst[0].get("recommend_yn")

                        # 현재 값이 N이면 Y, Y면 N으로 전환
                        query = text("""
                                         update tb_user_product_usage
                                            set recommend_yn = (case when recommend_yn = 'Y' then 'N' else 'Y' end)
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
                    else:
                        # tb_user_product_usage ins
                        query = text("""
                                         insert into tb_user_product_usage (user_id, product_id, episode_id, created_id, updated_id)
                                         values (:user_id, :product_id, :episode_id, :created_id, :updated_id)
                                         """)

                        await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "product_id": product_id,
                                "episode_id": episode_id_to_int,
                                "created_id": settings.DB_DML_DEFAULT_ID,
                                "updated_id": settings.DB_DML_DEFAULT_ID,
                            },
                        )

                        # 초기값은 무조건 Y
                        recommend_yn = "Y"

                    # count 재계산
                    query = text("""
                                     update tb_product_episode a
                                      inner join (
                                         select z.product_id
                                              , z.episode_id
                                              , sum(case when z.recommend_yn = 'Y' then 1 else 0 end) as count_recommend
                                           from tb_user_product_usage z
                                          where z.product_id = :product_id
                                            and z.episode_id = :episode_id
                                            and z.use_yn = 'Y'
                                          group by z.product_id, z.episode_id
                                       ) as t on a.product_id = t.product_id and a.episode_id = t.episode_id
                                        set a.count_recommend = t.count_recommend
                                      where 1=1
                                     """)

                    await db.execute(
                        query,
                        {"product_id": product_id, "episode_id": episode_id_to_int},
                    )

                    query = text("""
                                     update tb_product a
                                      inner join (
                                         select z.product_id
                                              , sum(case when z.recommend_yn = 'Y' then 1 else 0 end) as count_recommend
                                           from tb_user_product_usage z
                                          where z.product_id = :product_id
                                            and z.use_yn = 'Y'
                                          group by z.product_id
                                       ) as t on a.product_id = t.product_id
                                        set a.count_recommend = t.count_recommend
                                      where 1=1
                                     """)

                    await db.execute(query, {"product_id": product_id})

                    res_data = {
                        "episodeId": episode_id_to_int,
                        "recommendYn": recommend_yn,
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


async def post_episodes_episode_id_evaluation(
    episode_id: str,
    req_body: episode_schema.PostEpisodesEpisodeIdEvaluationReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    episode_id_to_int = int(episode_id)

    if kc_user_id:
        try:
            async with db.begin():
                user_id = await comm_service.get_user_from_kc(kc_user_id, db)
                if user_id == -1:
                    raise CustomResponseException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        message=ErrorMessages.LOGIN_REQUIRED,
                    )

                query = text("""
                                 select product_id
                                   from tb_product_episode
                                  where episode_id = :episode_id
                                    and use_yn = 'Y'
                                 """)

                result = await db.execute(query, {"episode_id": episode_id_to_int})
                db_rst = result.mappings().all()

                if db_rst:
                    product_id = db_rst[0].get("product_id")

                    # 평가 등급 검증
                    query = text("""
                                     select 1
                                       from tb_common_code
                                      where code_group = 'PROD_EVAL_CODE'
                                        and code_key = :code_key
                                        and use_yn = 'Y'
                                     """)

                    result = await db.execute(query, {"code_key": req_body.rating})
                    db_rst = result.mappings().all()

                    if db_rst:
                        query = text("""
                                         select 1
                                           from tb_product_evaluation
                                          where user_id = :user_id
                                            and product_id = :product_id
                                            and episode_id = :episode_id
                                         """)

                        result = await db.execute(
                            query,
                            {
                                "user_id": user_id,
                                "product_id": product_id,
                                "episode_id": episode_id_to_int,
                            },
                        )
                        db_rst = result.mappings().all()

                        if db_rst:
                            pass
                        else:
                            query = text("""
                                             insert into tb_product_evaluation (product_id, episode_id, user_id, eval_code, created_id, updated_id)
                                             values (:product_id, :episode_id, :user_id, :eval_code, :created_id, :updated_id)
                                             """)

                            await db.execute(
                                query,
                                {
                                    "user_id": user_id,
                                    "product_id": product_id,
                                    "episode_id": episode_id_to_int,
                                    "eval_code": req_body.rating,
                                    "created_id": settings.DB_DML_DEFAULT_ID,
                                    "updated_id": settings.DB_DML_DEFAULT_ID,
                                },
                            )

                            # count 재계산
                            query = text("""
                                             update tb_product_episode
                                                set count_evaluation = count_evaluation + 1
                                              where episode_id = :episode_id
                                             """)

                            await db.execute(query, {"episode_id": episode_id_to_int})
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


async def check_like_product_episode(
    episode_id: int, kc_user_id: str, db: AsyncSession
):
    """
    회차 에피소드 좋아요 여부 확인
    """
    query = text("""
        select count(*) as cnt from tb_product_episode_like
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
          and episode_id = :episode_id
          and user_id = (select user_id from tb_user where kc_user_id = :kc_user_id)
    """)
    result = await db.execute(
        query, {"episode_id": episode_id, "kc_user_id": kc_user_id}
    )
    db_rst = result.mappings().all()
    cnt = db_rst[0].get("cnt")
    return cnt > 0


async def add_like_product_episode(episode_id: int, kc_user_id: str, db: AsyncSession):
    """
    회차 에피소드 좋아요 추가
    """
    check = await check_like_product_episode(episode_id, kc_user_id, db)
    if check is True:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST, message=ErrorMessages.ALREADY_LIKED
        )

    query = text("""
        insert into tb_product_episode_like (product_id, episode_id, user_id)
        values (
            (select product_id from tb_product_episode where episode_id = :episode_id),
            :episode_id,
            (select user_id from tb_user where kc_user_id = :kc_user_id)
        )
    """)
    await db.execute(query, {"episode_id": episode_id, "kc_user_id": kc_user_id})

    # count_recommend 재계산 (tb_product_episode)
    query = text("""
        update tb_product_episode
        set count_recommend = (select count(*) from tb_product_episode_like where episode_id = :episode_id)
        where episode_id = :episode_id
    """)
    await db.execute(query, {"episode_id": episode_id})

    # count_recommend 재계산 (tb_product)
    query = text("""
        update tb_product
        set count_recommend = (
            select count(*) from tb_product_episode_like
            where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
        )
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
    """)
    await db.execute(query, {"episode_id": episode_id})

    return {"result": True}


async def remove_like_product_episode(
    episode_id: int, kc_user_id: str, db: AsyncSession
):
    """
    회차 에피소드 좋아요 삭제
    """
    check = await check_like_product_episode(episode_id, kc_user_id, db)
    if check is False:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST, message=ErrorMessages.NOT_LIKED_YET
        )

    query = text("""
        delete from tb_product_episode_like
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
          and episode_id = :episode_id
          and user_id = (select user_id from tb_user where kc_user_id = :kc_user_id)
    """)
    await db.execute(query, {"episode_id": episode_id, "kc_user_id": kc_user_id})

    # count_recommend 재계산 (tb_product_episode)
    query = text("""
        update tb_product_episode
        set count_recommend = (select count(*) from tb_product_episode_like where episode_id = :episode_id)
        where episode_id = :episode_id
    """)
    await db.execute(query, {"episode_id": episode_id})

    # count_recommend 재계산 (tb_product)
    query = text("""
        update tb_product
        set count_recommend = (
            select count(*) from tb_product_episode_like
            where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
        )
        where product_id = (select product_id from tb_product_episode where episode_id = :episode_id)
    """)
    await db.execute(query, {"episode_id": episode_id})

    return {"result": True}
