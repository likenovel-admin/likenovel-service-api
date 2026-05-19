import hashlib
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages
from app.exceptions import CustomResponseException
from app.rdb import likenovel_db_session
import app.schemas.admin as admin_schema
logger = logging.getLogger(__name__)


@asynccontextmanager
async def _transaction_scope(db: AsyncSession):
    if db.in_transaction():
        yield
        return

    async with db.begin():
        yield


def _normalise_operation_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "episode_no": item.get("episode_no"),
        "title": item.get("episode_title") or item.get("title"),
        "epub_file_id": item.get("epub_file_id"),
        "source_sha256": item.get("source_sha256"),
        "author_comment": item.get("author_comment"),
        "comment_open_yn": item.get("comment_open_yn"),
        "evaluation_open_yn": item.get("evaluation_open_yn"),
        "publish_reserve_yn": item.get("publish_reserve_yn"),
        "publish_reserve_date": item.get("publish_reserve_date"),
        "price_type": item.get("price_type"),
    }


def build_admin_episode_operation_idempotency_key(
    *,
    product_id: int,
    action: str,
    items: list[dict[str, Any]],
) -> str:
    normalised_items = sorted(
        (_normalise_operation_item(item) for item in items),
        key=lambda item: (
            item.get("episode_no") or 0,
            item.get("epub_file_id") or 0,
            item.get("source_sha256") or "",
        ),
    )
    payload = {
        "product_id": product_id,
        "action": action,
        "items": normalised_items,
    }
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _build_item_key(action: str, episode_no: int, epub_file_id: int, source_sha256: str | None) -> str:
    payload = f"{action}:{episode_no}:{epub_file_id}:{source_sha256 or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _datetime_to_iso(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def _serialise_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: _datetime_to_iso(value) for key, value in row.items()}


def _operation_items_to_dicts(
    req_body: admin_schema.AdminDelegatedEpisodeOperationReqBody,
) -> list[dict[str, Any]]:
    items = []
    for episode in req_body.episodes:
        item = episode.model_dump()
        if episode.publish_reserve_date is not None:
            item["publish_reserve_date"] = episode.publish_reserve_date.isoformat()
        items.append(item)
    return items


async def _load_product_context(
    *,
    product_id: int,
    db: AsyncSession,
    for_update: bool = False,
) -> dict[str, Any]:
    lock_clause = " for update" if for_update else ""
    query = text(
        f"""
        select p.product_id
             , p.title
             , p.user_id
             , p.author_name
             , u.email as author_email
             , p.price_type
             , p.paid_open_date
             , p.paid_episode_no
             , coalesce(p.series_regular_price, 0) as series_regular_price
             , coalesce(p.single_regular_price, 0) as single_regular_price
             , coalesce(episode_stats.episode_count, 0) as episode_count
             , coalesce(episode_stats.max_episode_no, 0) as max_episode_no
          from tb_product p
          left join tb_user u on u.user_id = p.user_id
          left join (
              select product_id
                   , count(*) as episode_count
                   , max(episode_no) as max_episode_no
                from tb_product_episode
               where product_id = :product_id
                 and use_yn = 'Y'
               group by product_id
          ) episode_stats on episode_stats.product_id = p.product_id
         where p.product_id = :product_id
        {lock_clause}
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    if row is None:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.INVALID_PRODUCT_INFO,
        )
    return dict(row)


async def _load_existing_episodes(
    *,
    product_id: int,
    db: AsyncSession,
    for_update: bool = False,
) -> dict[int, dict[str, Any]]:
    lock_clause = " for update" if for_update else ""
    query = text(
        f"""
        select episode_id
             , product_id
             , price_type
             , episode_no
             , episode_title
             , episode_text_count
             , epub_file_id
             , author_comment
             , comment_open_yn
             , evaluation_open_yn
             , publish_reserve_date
             , open_yn
             , use_yn
             , created_id
             , updated_id
          from tb_product_episode
         where product_id = :product_id
           and use_yn = 'Y'
        {lock_clause}
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    rows = result.mappings().all()
    episode_no_counts: dict[int, int] = {}
    for row in rows:
        if row.get("episode_no") is None:
            continue
        episode_no = int(row.get("episode_no"))
        episode_no_counts[episode_no] = episode_no_counts.get(episode_no, 0) + 1
    duplicate_episode_nos = sorted(
        episode_no for episode_no, count in episode_no_counts.items() if count > 1
    )
    if duplicate_episode_nos:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=f"활성 회차 번호가 중복되어 관리자 대리 작업을 진행할 수 없습니다: {duplicate_episode_nos[0]}화",
        )
    return {
        int(row.get("episode_no")): dict(row)
        for row in rows
        if row.get("episode_no") is not None
    }


def _compute_episode_price_type(product: dict[str, Any], episode_no: int) -> str:
    from app.services.product.episode_service import _default_episode_price_type

    is_paid_product = _is_paid_product_configured(product)
    return _default_episode_price_type(
        is_paid_product=is_paid_product,
        paid_open_date=product.get("paid_open_date"),
        paid_episode_no=product.get("paid_episode_no"),
        episode_no=episode_no,
    )


def _is_paid_product_configured(product: dict[str, Any]) -> bool:
    return (
        product.get("price_type") == "paid"
        or int(product.get("series_regular_price") or 0) > 0
        or int(product.get("single_regular_price") or 0) > 0
    )


def _product_summary(product: dict[str, Any]) -> dict[str, Any]:
    return {
        "productId": int(product.get("product_id")),
        "title": product.get("title"),
        "authorUserId": product.get("user_id"),
        "authorName": product.get("author_name"),
        "authorEmail": product.get("author_email"),
        "priceType": product.get("price_type"),
        "paidOpenDate": _datetime_to_iso(product.get("paid_open_date")),
        "paidEpisodeNo": product.get("paid_episode_no"),
        "episodeCount": int(product.get("episode_count") or 0),
        "maxEpisodeNo": int(product.get("max_episode_no") or 0),
    }


async def get_admin_delegated_episode_summary(product_id: int, db: AsyncSession):
    product = await _load_product_context(product_id=product_id, db=db)
    return {"data": {"product": _product_summary(product)}}


async def _build_operation_preview(
    *,
    product_id: int,
    req_body: admin_schema.AdminDelegatedEpisodeOperationReqBody,
    db: AsyncSession,
    for_update: bool = False,
    epub_cache: dict[int, dict] | None = None,
) -> dict[str, Any]:
    product = await _load_product_context(product_id=product_id, db=db, for_update=for_update)
    existing_episodes = await _load_existing_episodes(
        product_id=product_id,
        db=db,
        for_update=for_update,
    )
    requested_file_group_ids = {int(episode.epub_file_id) for episode in req_body.episodes}
    if epub_cache is None:
        from app.services.product.episode_service import _get_epub_cache_from_epub_files

        epub_cache = await _get_epub_cache_from_epub_files(
            file_group_ids=requested_file_group_ids,
            db=db,
        )

    errors = []
    items = []
    used_episode_nos = set(existing_episodes.keys())
    item_dicts = _operation_items_to_dicts(req_body)
    idempotency_key = build_admin_episode_operation_idempotency_key(
        product_id=product_id,
        action=req_body.action,
        items=item_dicts,
    )

    for episode in req_body.episodes:
        episode_no = int(episode.episode_no)
        epub_file_id = int(episode.epub_file_id)
        existing_episode = existing_episodes.get(episode_no)
        epub_payload = epub_cache.get(epub_file_id, {"text_count": 0, "html_content": ""})
        text_count = int(epub_payload.get("text_count") or 0)
        html_content = epub_payload.get("html_content") or ""
        item_errors = []

        if req_body.action == "append_epub" and episode_no in used_episode_nos:
            item_errors.append("이미 존재하는 회차 번호입니다.")
        if req_body.action == "replace_epub" and existing_episode is None:
            item_errors.append("수정할 기존 회차가 없습니다.")
        if req_body.action == "replace_epub" and episode.price_type:
            item_errors.append("기존 회차의 가격 타입은 이 작업에서 변경할 수 없습니다.")
        if text_count <= 0 or not html_content:
            item_errors.append("EPUB 본문을 추출하지 못했습니다.")

        publish_reserve_date = None
        if episode.publish_reserve_yn == "Y":
            from app.services.product.episode_service import _normalize_publish_reserve_datetime

            publish_reserve_date = _normalize_publish_reserve_datetime(
                episode.publish_reserve_date
            )
        elif existing_episode is not None and req_body.action == "replace_epub":
            publish_reserve_date = existing_episode.get("publish_reserve_date")

        price_type = (
            existing_episode.get("price_type")
            if existing_episode is not None and req_body.action == "replace_epub"
            else episode.price_type
        )
        if not price_type:
            price_type = _compute_episode_price_type(product, episode_no)

        if not _is_paid_product_configured(product) and price_type == "paid":
            item_errors.append("무료 작품에 유료 회차를 직접 추가할 수 없습니다.")

        item_key = _build_item_key(
            action=req_body.action,
            episode_no=episode_no,
            epub_file_id=epub_file_id,
            source_sha256=episode.source_sha256,
        )
        items.append(
            {
                "itemKey": item_key,
                "episodeNo": episode_no,
                "episodeId": existing_episode.get("episode_id") if existing_episode else None,
                "title": episode.title,
                "epubFileId": epub_file_id,
                "sourceSha256": episode.source_sha256,
                "priceType": price_type,
                "textCount": text_count,
                "publishReserveDate": _datetime_to_iso(publish_reserve_date),
                "errors": item_errors,
            }
        )
        errors.extend(f"{episode_no}화: {error}" for error in item_errors)

    return {
        "product": _product_summary(product),
        "action": req_body.action,
        "idempotencyKey": idempotency_key,
        "items": items,
        "errors": errors,
    }


async def preview_admin_delegated_episode_operation(
    product_id: int,
    req_body: admin_schema.AdminDelegatedEpisodeOperationReqBody,
    db: AsyncSession,
):
    try:
        preview = await _build_operation_preview(
            product_id=product_id,
            req_body=req_body,
            db=db,
        )
        return {"data": preview}
    except CustomResponseException:
        raise
    except OperationalError as e:
        logger.error(e, exc_info=True)
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError as e:
        logger.error(e, exc_info=True)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception as e:
        logger.error(e, exc_info=True)
        raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


async def _has_existing_operation(
    *, idempotency_key: str, db: AsyncSession
) -> bool:
    query = text(
        """
        select 1
          from tb_admin_episode_operation_audit
         where idempotency_key = :idempotency_key
         limit 1
        """
    )
    result = await db.execute(query, {"idempotency_key": idempotency_key})
    return result.first() is not None


async def _select_episode_snapshots_by_no(
    *, product_id: int, episode_nos: list[int], db: AsyncSession
) -> dict[int, dict[str, Any]]:
    if not episode_nos:
        return {}

    params: dict[str, Any] = {"product_id": product_id}
    placeholders = []
    for idx, episode_no in enumerate(episode_nos):
        key = f"episode_no_{idx}"
        params[key] = episode_no
        placeholders.append(f":{key}")

    query = text(
        f"""
        select episode_id
             , product_id
             , price_type
             , episode_no
             , episode_title
             , episode_text_count
             , epub_file_id
             , author_comment
             , comment_open_yn
             , evaluation_open_yn
             , publish_reserve_date
             , open_yn
             , use_yn
             , created_id
             , updated_id
          from tb_product_episode
         where product_id = :product_id
           and use_yn = 'Y'
           and episode_no in ({", ".join(placeholders)})
        """
    )
    result = await db.execute(query, params)
    rows = result.mappings().all()
    return {
        int(row.get("episode_no")): dict(row)
        for row in rows
        if row.get("episode_no") is not None
    }


async def apply_admin_delegated_episode_operation(
    product_id: int,
    req_body: admin_schema.AdminDelegatedEpisodeOperationReqBody,
    admin_user_id: int,
    db: AsyncSession,
):
    try:
        from app.services.product.episode_service import (
            _get_epub_cache_from_epub_files,
            _normalize_publish_reserve_datetime,
        )

        requested_file_group_ids = {int(episode.epub_file_id) for episode in req_body.episodes}
        async with likenovel_db_session() as read_db:
            epub_cache = await _get_epub_cache_from_epub_files(
                file_group_ids=requested_file_group_ids,
                db=read_db,
            )

        async with _transaction_scope(db):
            preview = await _build_operation_preview(
                product_id=product_id,
                req_body=req_body,
                db=db,
                for_update=True,
                epub_cache=epub_cache,
            )
            if preview["errors"]:
                raise CustomResponseException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    message=preview["errors"][0],
                )
            if await _has_existing_operation(
                idempotency_key=preview["idempotencyKey"],
                db=db,
            ):
                raise CustomResponseException(
                    status_code=status.HTTP_409_CONFLICT,
                    message="이미 처리된 관리자 회차 작업입니다.",
                )

            before_by_no = await _select_episode_snapshots_by_no(
                product_id=product_id,
                episode_nos=[item["episodeNo"] for item in preview["items"]],
                db=db,
            )

            if req_body.action == "append_epub":
                insert_rows = []
                episode_by_no = {episode.episode_no: episode for episode in req_body.episodes}
                for item in preview["items"]:
                    episode = episode_by_no[item["episodeNo"]]
                    publish_reserve_date = _normalize_publish_reserve_datetime(
                        episode.publish_reserve_date
                    ) if episode.publish_reserve_yn == "Y" else None
                    epub_data = epub_cache.get(
                        int(item["epubFileId"]), {"text_count": 0, "html_content": ""}
                    )
                    insert_rows.append(
                        {
                            "product_id": product_id,
                            "price_type": item["priceType"],
                            "episode_no": item["episodeNo"],
                            "episode_title": episode.title,
                            "episode_text_count": int(epub_data.get("text_count") or 0),
                            "episode_content": epub_data.get("html_content") or "",
                            "epub_file_id": item["epubFileId"],
                            "author_comment": episode.author_comment,
                            "comment_open_yn": episode.comment_open_yn,
                            "evaluation_open_yn": episode.evaluation_open_yn,
                            "publish_reserve_date": publish_reserve_date,
                            "open_yn": "N",
                            "created_id": admin_user_id,
                            "updated_id": admin_user_id,
                        }
                    )
                query = text(
                    """
                    insert into tb_product_episode (
                        product_id, price_type, episode_no, episode_title,
                        episode_text_count, episode_content, epub_file_id,
                        author_comment, comment_open_yn, evaluation_open_yn,
                        publish_reserve_date, open_yn, created_id, updated_id
                    )
                    values (
                        :product_id, :price_type, :episode_no, :episode_title,
                        :episode_text_count, :episode_content, :epub_file_id,
                        :author_comment, :comment_open_yn, :evaluation_open_yn,
                        :publish_reserve_date, :open_yn, :created_id, :updated_id
                    )
                    """
                )
                await db.execute(query, insert_rows)

            if req_body.action == "replace_epub":
                episode_by_no = {episode.episode_no: episode for episode in req_body.episodes}
                for item in preview["items"]:
                    episode = episode_by_no[item["episodeNo"]]
                    before = before_by_no[item["episodeNo"]]
                    epub_data = epub_cache.get(
                        int(item["epubFileId"]), {"text_count": 0, "html_content": ""}
                    )
                    update_values = {
                        "product_id": product_id,
                        "episode_id": before["episode_id"],
                        "episode_no": item["episodeNo"],
                        "episode_title": episode.title,
                        "episode_text_count": int(epub_data.get("text_count") or 0),
                        "episode_content": epub_data.get("html_content") or "",
                        "epub_file_id": item["epubFileId"],
                        "author_comment": episode.author_comment
                        if episode.author_comment is not None
                        else before.get("author_comment"),
                        "comment_open_yn": before.get("comment_open_yn"),
                        "evaluation_open_yn": before.get("evaluation_open_yn"),
                        "updated_id": admin_user_id,
                    }
                    publish_reserve_set_clause = ""
                    if episode.publish_reserve_yn == "Y":
                        update_values["publish_reserve_date"] = _normalize_publish_reserve_datetime(
                            episode.publish_reserve_date
                        )
                        publish_reserve_set_clause = ", publish_reserve_date = :publish_reserve_date"

                    query = text(
                        f"""
                        update tb_product_episode
                           set episode_title = :episode_title
                             , episode_text_count = :episode_text_count
                             , episode_content = :episode_content
                             , epub_file_id = :epub_file_id
                             , author_comment = :author_comment
                             , comment_open_yn = :comment_open_yn
                             , evaluation_open_yn = :evaluation_open_yn
                             {publish_reserve_set_clause}
                             , updated_id = :updated_id
                         where product_id = :product_id
                           and episode_id = :episode_id
                           and use_yn = 'Y'
                        """
                    )
                    result = await db.execute(
                        query,
                        update_values,
                    )
                    if result.rowcount != 1:
                        raise CustomResponseException(
                            status_code=status.HTTP_409_CONFLICT,
                            message=f"{item['episodeNo']}화 수정 대상이 1건이 아닙니다.",
                        )

            after_by_no = await _select_episode_snapshots_by_no(
                product_id=product_id,
                episode_nos=[item["episodeNo"] for item in preview["items"]],
                db=db,
            )

            audit_rows = []
            for item in preview["items"]:
                episode_no = item["episodeNo"]
                after = after_by_no.get(episode_no)
                audit_rows.append(
                    {
                        "idempotency_key": preview["idempotencyKey"],
                        "item_key": item["itemKey"],
                        "admin_user_id": admin_user_id,
                        "product_id": product_id,
                        "episode_id": after.get("episode_id") if after else item.get("episodeId"),
                        "episode_no": episode_no,
                        "action": req_body.action,
                        "status": "succeeded",
                        "before_json": json.dumps(
                            _serialise_row(before_by_no.get(episode_no)),
                            ensure_ascii=False,
                            sort_keys=True,
                        ) if before_by_no.get(episode_no) else None,
                        "after_json": json.dumps(
                            _serialise_row(after),
                            ensure_ascii=False,
                            sort_keys=True,
                        ) if after else None,
                        "error_message": None,
                        "created_id": admin_user_id,
                        "updated_id": admin_user_id,
                    }
                )

            query = text(
                """
                insert into tb_admin_episode_operation_audit (
                    idempotency_key, item_key, admin_user_id, product_id,
                    episode_id, episode_no, action, status,
                    before_json, after_json, error_message,
                    created_id, updated_id
                )
                values (
                    :idempotency_key, :item_key, :admin_user_id, :product_id,
                    :episode_id, :episode_no, :action, :status,
                    :before_json, :after_json, :error_message,
                    :created_id, :updated_id
                )
                """
            )
            await db.execute(query, audit_rows)

            return {
                "data": {
                    "idempotencyKey": preview["idempotencyKey"],
                    "count": len(preview["items"]),
                    "episodeIds": [
                        after_by_no[item["episodeNo"]]["episode_id"]
                        for item in preview["items"]
                    ],
                    "items": preview["items"],
                }
            }
    except CustomResponseException:
        raise
    except OperationalError as e:
        logger.error(e, exc_info=True)
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message=ErrorMessages.DB_CONNECTION_ERROR,
        )
    except SQLAlchemyError as e:
        logger.error(e, exc_info=True)
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=ErrorMessages.DB_OPERATION_ERROR,
        )
    except Exception as e:
        logger.error(e, exc_info=True)
        raise CustomResponseException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
