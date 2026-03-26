import uuid
from contextlib import asynccontextmanager

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
import app.schemas.prediction as prediction_schema
import app.services.common.comm_service as comm_service


@asynccontextmanager
async def _transaction_scope(db: AsyncSession):
    """
    Avoid nested transaction begin() errors when the session already has a transaction.
    """
    if db.in_transaction():
        yield
        return

    async with db.begin():
        yield


async def post_author_episode_prediction(
    req_body: prediction_schema.PostAuthorEpisodePredictionReqBody,
    kc_user_id: str,
    db: AsyncSession,
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    try:
        async with _transaction_scope(db):
            user_id = await comm_service.get_user_from_kc(kc_user_id, db)
            if user_id == -1:
                raise CustomResponseException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    message=ErrorMessages.LOGIN_REQUIRED,
                )

            product_owner_query = text("""
                select author_id
                  from tb_product
                 where product_id = :product_id
            """)
            product_owner_result = await db.execute(
                product_owner_query, {"product_id": req_body.product_id}
            )
            product_owner = product_owner_result.mappings().one_or_none()
            if not product_owner:
                raise CustomResponseException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=ErrorMessages.INVALID_PRODUCT_INFO,
                )
            if product_owner.get("author_id") != user_id:
                raise CustomResponseException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    message=ErrorMessages.FORBIDDEN_NOT_AUTHOR_OF_PRODUCT,
                )

            rank_query = text("""
                select current_rank
                  from tb_product_rank
                 where product_id = :product_id
                   and created_date = (select max(created_date) from tb_product_rank)
                 limit 1
            """)
            rank_result = await db.execute(rank_query, {"product_id": req_body.product_id})
            rank_row = rank_result.mappings().one_or_none()
            baseline_rank = rank_row.get("current_rank") if rank_row else None

            hit_query = text("""
                select count_hit
                  from tb_product
                 where product_id = :product_id
                 limit 1
            """)
            hit_result = await db.execute(hit_query, {"product_id": req_body.product_id})
            hit_row = hit_result.mappings().one_or_none()
            baseline_hit_count = hit_row.get("count_hit") if hit_row else 0

            prediction_key = req_body.prediction_key or str(uuid.uuid4())
            insert_query = text("""
                insert into tb_author_episode_prediction_log (
                    prediction_key,
                    product_id,
                    author_user_id,
                    screen_name,
                    target_week_start_date,
                    target_weekly_upload_goal,
                    recommended_weekly_upload_goal,
                    uploads_this_week,
                    remaining_target_uploads,
                    remaining_recommended_uploads,
                    prediction_base_uploads,
                    sample_episode_count,
                    sample_window_type,
                    prediction_basis,
                    expected_views_min,
                    expected_views_max,
                    expected_rank_gain_min,
                    expected_rank_gain_max,
                    has_enough_data,
                    model_version,
                    baseline_rank,
                    baseline_hit_count,
                    created_id,
                    updated_id
                )
                values (
                    :prediction_key,
                    :product_id,
                    :author_user_id,
                    :screen_name,
                    :target_week_start_date,
                    :target_weekly_upload_goal,
                    :recommended_weekly_upload_goal,
                    :uploads_this_week,
                    :remaining_target_uploads,
                    :remaining_recommended_uploads,
                    :prediction_base_uploads,
                    :sample_episode_count,
                    :sample_window_type,
                    :prediction_basis,
                    :expected_views_min,
                    :expected_views_max,
                    :expected_rank_gain_min,
                    :expected_rank_gain_max,
                    :has_enough_data,
                    :model_version,
                    :baseline_rank,
                    :baseline_hit_count,
                    :created_id,
                    :updated_id
                )
            """)
            await db.execute(
                insert_query,
                {
                    "prediction_key": prediction_key,
                    "product_id": req_body.product_id,
                    "author_user_id": user_id,
                    "screen_name": req_body.screen_name,
                    "target_week_start_date": req_body.target_week_start_date,
                    "target_weekly_upload_goal": req_body.target_weekly_upload_goal,
                    "recommended_weekly_upload_goal": req_body.recommended_weekly_upload_goal,
                    "uploads_this_week": req_body.uploads_this_week,
                    "remaining_target_uploads": req_body.remaining_target_uploads,
                    "remaining_recommended_uploads": req_body.remaining_recommended_uploads,
                    "prediction_base_uploads": req_body.prediction_base_uploads,
                    "sample_episode_count": req_body.sample_episode_count,
                    "sample_window_type": req_body.sample_window_type,
                    "prediction_basis": req_body.prediction_basis,
                    "expected_views_min": req_body.expected_views_min,
                    "expected_views_max": req_body.expected_views_max,
                    "expected_rank_gain_min": req_body.expected_rank_gain_min,
                    "expected_rank_gain_max": req_body.expected_rank_gain_max,
                    "has_enough_data": req_body.has_enough_data,
                    "model_version": req_body.model_version,
                    "baseline_rank": baseline_rank,
                    "baseline_hit_count": baseline_hit_count,
                    "created_id": user_id,
                    "updated_id": user_id,
                },
            )

            select_query = text("""
                select prediction_id
                  from tb_author_episode_prediction_log
                 where prediction_key = :prediction_key
                 limit 1
            """)
            select_result = await db.execute(select_query, {"prediction_key": prediction_key})
            prediction_row = select_result.mappings().one_or_none()
            prediction_id = prediction_row.get("prediction_id") if prediction_row else None

    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )

    return {
        "data": {
            "predictionId": prediction_id,
            "predictionKey": prediction_key,
        }
    }


async def get_author_episode_prediction_accuracy(
    days: int,
    product_id: int | None,
    kc_user_id: str,
    db: AsyncSession,
):
    if not kc_user_id:
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message=ErrorMessages.LOGIN_REQUIRED,
        )

    safe_days = max(1, min(days, 365))

    try:
        user_id = await comm_service.get_user_from_kc(kc_user_id, db)
        if user_id == -1:
            raise CustomResponseException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                message=ErrorMessages.LOGIN_REQUIRED,
            )

        where_product_sql = ""
        bind_var = {"user_id": user_id}
        if product_id is not None:
            where_product_sql = " and l.product_id = :product_id "
            bind_var["product_id"] = product_id

        summary_query = text(f"""
            with measured as (
                select l.prediction_id
                     , l.product_id
                     , l.expected_views_min
                     , l.expected_views_max
                     , l.expected_rank_gain_min
                     , l.expected_rank_gain_max
                     , l.baseline_rank
                     , (coalesce(s.current_count_hit, 0) - coalesce(s.privious_count_hit, 0)) as measured_views_24h
                  from tb_author_episode_prediction_log l
                 inner join tb_product p on l.product_id = p.product_id
                  left join tb_batch_daily_product_count_summary s on l.product_id = s.product_id
                   and date(s.created_date) = date(date_add(l.created_date, interval 1 day))
                 where p.author_id = :user_id
                   and p.open_yn = 'Y'
                   and l.created_date >= date_sub(now(), interval {safe_days} day)
                   and l.has_enough_data = 'Y'
                   {where_product_sql}
            )
            select count(1) as sample_count
                 , sum(case when measured_views_24h is not null then 1 else 0 end) as measured_count
                 , sum(case when measured_views_24h is null then 1 else 0 end) as pending_count
                 , round(avg(case
                               when measured_views_24h is null then null
                               when measured_views_24h between expected_views_min and expected_views_max then 1
                               else 0
                             end), 4) as range_hit_rate
                 , round(avg(case
                               when measured_views_24h is null then null
                               else abs(measured_views_24h - ((expected_views_min + expected_views_max) / 2)) / greatest(abs(measured_views_24h), 1)
                             end), 4) as mape_views
                 , round(avg(case
                               when measured_views_24h is null then null
                               else abs(measured_views_24h - ((expected_views_min + expected_views_max) / 2))
                             end), 4) as mae_views
              from measured
        """)
        summary_result = await db.execute(summary_query, bind_var)
        summary_row = summary_result.mappings().one_or_none()

        by_product_query = text(f"""
            with measured as (
                select l.product_id
                     , l.expected_views_min
                     , l.expected_views_max
                     , (coalesce(s.current_count_hit, 0) - coalesce(s.privious_count_hit, 0)) as measured_views_24h
                  from tb_author_episode_prediction_log l
                 inner join tb_product p on l.product_id = p.product_id
                  left join tb_batch_daily_product_count_summary s on l.product_id = s.product_id
                   and date(s.created_date) = date(date_add(l.created_date, interval 1 day))
                 where p.author_id = :user_id
                   and p.open_yn = 'Y'
                   and l.created_date >= date_sub(now(), interval {safe_days} day)
                   and l.has_enough_data = 'Y'
                   {where_product_sql}
            )
            select m.product_id
                 , count(1) as sample_count
                 , sum(case when m.measured_views_24h is not null then 1 else 0 end) as measured_count
                 , round(avg(case
                               when m.measured_views_24h is null then null
                               when m.measured_views_24h between m.expected_views_min and m.expected_views_max then 1
                               else 0
                             end), 4) as range_hit_rate
                 , round(avg(case
                               when m.measured_views_24h is null then null
                               else abs(m.measured_views_24h - ((m.expected_views_min + m.expected_views_max) / 2)) / greatest(abs(m.measured_views_24h), 1)
                             end), 4) as mape_views
              from measured m
             group by m.product_id
             order by m.product_id desc
        """)
        by_product_result = await db.execute(by_product_query, bind_var)
        by_product_rows = by_product_result.mappings().all()

        latest_rank_query = text("""
            select product_id, current_rank, privious_rank
              from tb_product_rank
             where created_date = (select max(created_date) from tb_product_rank)
        """)
        latest_rank_result = await db.execute(latest_rank_query)
        latest_rank_rows = latest_rank_result.mappings().all()
        latest_rank_map = {
            row.get("product_id"): {
                "currentRank": row.get("current_rank"),
                "previousRank": row.get("privious_rank"),
            }
            for row in latest_rank_rows
        }

    except SQLAlchemyError:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )

    return {
        "data": {
            "days": safe_days,
            "summary": {
                "sampleCount": summary_row.get("sample_count") if summary_row else 0,
                "measuredCount": summary_row.get("measured_count") if summary_row else 0,
                "pendingCount": summary_row.get("pending_count") if summary_row else 0,
                "rangeHitRate": summary_row.get("range_hit_rate") if summary_row else None,
                "mapeViews": summary_row.get("mape_views") if summary_row else None,
                "maeViews": summary_row.get("mae_views") if summary_row else None,
                "rankAccuracyAvailable": False,
            },
            "byProduct": [
                {
                    "productId": row.get("product_id"),
                    "sampleCount": row.get("sample_count"),
                    "measuredCount": row.get("measured_count"),
                    "rangeHitRate": row.get("range_hit_rate"),
                    "mapeViews": row.get("mape_views"),
                    "latestRankSnapshot": latest_rank_map.get(row.get("product_id")),
                }
                for row in by_product_rows
            ],
            "notes": [
                "조회수 실측은 기존 일배치(summary_daily_batch) 산출값(tb_batch_daily_product_count_summary)을 재사용합니다.",
                "랭킹은 과거 스냅샷 테이블이 없어 현재 시점 스냅샷만 참고로 제공합니다.",
            ],
        }
    }
