from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from fastapi import status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import ErrorMessages, settings
from app.exceptions import CustomResponseException
from app.schemas.story_agent import (
    PostStoryAgentMessageReqBody,
    PostStoryAgentSessionReqBody,
    PatchStoryAgentSessionReqBody,
)
from app.services.common.comm_service import get_user_from_kc
from app.utils.common import handle_exceptions
from app.utils.query import get_file_path_sub_query
from app.utils.time import get_full_age

STORY_AGENT_DEFAULT_TITLE = "새 대화"
STORY_AGENT_SESSION_LOCK_TIMEOUT_SECONDS = 0
STORY_AGENT_PLACEHOLDER_TEMPLATE = (
    "현재 [{title}] 전용 세션의 메시지 저장만 먼저 연결된 상태입니다. "
    "원문 기반 컨텍스트/T2T/T2I 오케스트레이션은 다음 단계에서 붙습니다.\n\n"
    "방금 요청: {user_prompt}"
)
logger = logging.getLogger(__name__)


async def _resolve_actor(kc_user_id: str | None, guest_key: str | None, db: AsyncSession) -> tuple[int | None, str | None]:
    if kc_user_id:
        user_id = await get_user_from_kc(kc_user_id, db)
        if user_id != -1:
            return int(user_id), None
    normalized_guest_key = (guest_key or "").strip()
    if normalized_guest_key:
        return None, normalized_guest_key
    raise CustomResponseException(
        status_code=status.HTTP_400_BAD_REQUEST,
        message="비로그인 요청은 guest_key가 필요합니다.",
    )


async def _resolve_effective_adult_yn(
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
) -> str:
    requested_adult_yn = "Y" if (adult_yn or "").upper() == "Y" else "N"
    if requested_adult_yn != "Y" or not kc_user_id:
        return "N"

    query = text(
        """
        SELECT
            DATE_FORMAT(u.birthdate, '%Y-%m-%d') AS birthdate
        FROM tb_user u
        WHERE u.kc_user_id = :kc_user_id
          AND u.use_yn = 'Y'
        LIMIT 1
        """
    )
    result = await db.execute(query, {"kc_user_id": kc_user_id})
    user_row = result.mappings().one_or_none()
    if not user_row:
        return "N"

    birthdate = user_row.get("birthdate")
    if not birthdate:
        return "N"

    return "Y" if get_full_age(date=birthdate) >= 19 else "N"


async def _get_story_agent_product(product_id: int, adult_yn: str, db: AsyncSession) -> dict[str, Any] | None:
    ratings_filter = "" if adult_yn == "Y" else "AND p.ratings_code = 'all'"
    query = text(
        f"""
        SELECT
            p.product_id AS productId,
            p.title,
            p.author_name AS authorNickname,
            {get_file_path_sub_query('p.thumbnail_file_id', 'coverImagePath')},
            p.status_code AS statusCode,
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo
        FROM tb_product p
        LEFT JOIN tb_product_episode e
          ON e.product_id = p.product_id
         AND e.use_yn = 'Y'
         AND e.open_yn = 'Y'
        WHERE p.product_id = :product_id
          AND p.price_type = 'free'
          AND p.open_yn = 'Y'
          AND p.blind_yn = 'N'
          AND p.contract_yn = 'N'
          {ratings_filter}
        GROUP BY p.product_id, p.title, p.author_name, p.thumbnail_file_id, p.status_code
        """
    )
    result = await db.execute(query, {"product_id": product_id})
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def _acquire_story_agent_session_lock(session_id: int, db: AsyncSession) -> bool:
    result = await db.execute(
        text("SELECT GET_LOCK(:lock_name, :timeout) AS locked"),
        {
            "lock_name": f"story-agent-session:{session_id}",
            "timeout": STORY_AGENT_SESSION_LOCK_TIMEOUT_SECONDS,
        },
    )
    row = result.mappings().one()
    return bool(row.get("locked"))


async def _release_story_agent_session_lock(session_id: int, db: AsyncSession) -> None:
    try:
        await db.execute(
            text("SELECT RELEASE_LOCK(:lock_name)"),
            {"lock_name": f"story-agent-session:{session_id}"},
        )
    except Exception as exc:
        logger.warning("failed to release story agent session lock: %s", exc)


async def _get_existing_turn_messages(
    session_id: int,
    client_message_id: str,
    db: AsyncSession,
) -> list[dict[str, Any]] | None:
    result = await db.execute(
        text(
            """
            SELECT
                message_id AS messageId,
                role,
                content,
                DATE_FORMAT(created_date, '%Y-%m-%d %H:%i:%s') AS createdDate
            FROM tb_story_agent_message
            WHERE session_id = :session_id
              AND client_message_id = :client_message_id
            ORDER BY message_id ASC
            """
        ),
        {
            "session_id": session_id,
            "client_message_id": client_message_id,
        },
    )
    rows = [dict(row) for row in result.mappings().all()]
    if not rows:
        return None
    if len(rows) != 2:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message="이전 메시지가 아직 처리 중입니다. 잠시 후 다시 시도해주세요.",
        )
    return rows


async def _get_session_row(
    session_id: int,
    user_id: int | None,
    guest_key: str | None,
    db: AsyncSession,
) -> dict[str, Any]:
    owner_where = "AND user_id = :user_id" if user_id is not None else "AND guest_key = :guest_key"
    params: dict[str, Any] = {"session_id": session_id}
    if user_id is not None:
        params["user_id"] = user_id
    else:
        params["guest_key"] = guest_key

    query = text(
        f"""
        SELECT session_id, product_id, title, created_date, updated_date
        FROM tb_story_agent_session
        WHERE session_id = :session_id
          AND deleted_yn = 'N'
          {owner_where}
        LIMIT 1
        """
    )
    result = await db.execute(query, params)
    row = result.mappings().one_or_none()
    if not row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="스토리 에이전트 세션을 찾을 수 없습니다.",
        )
    return dict(row)


@handle_exceptions
async def search_products(
    keyword: str,
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
):
    normalized_keyword = (keyword or "").strip()
    if not normalized_keyword:
        return {"data": []}

    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn=adult_yn,
        db=db,
    )
    ratings_filter = "" if effective_adult_yn == "Y" else "AND p.ratings_code = 'all'"
    query = text(
        f"""
        SELECT
            p.product_id AS productId,
            p.title,
            p.author_name AS authorNickname,
            {get_file_path_sub_query('p.thumbnail_file_id', 'coverImagePath')},
            p.status_code AS statusCode,
            COALESCE(MAX(e.episode_no), 0) AS latestEpisodeNo
        FROM tb_product p
        LEFT JOIN tb_product_episode e
          ON e.product_id = p.product_id
         AND e.use_yn = 'Y'
         AND e.open_yn = 'Y'
        WHERE p.price_type = 'free'
          AND p.open_yn = 'Y'
          AND p.blind_yn = 'N'
          AND p.contract_yn = 'N'
          {ratings_filter}
          AND (
            p.title LIKE :keyword
            OR p.author_name LIKE :keyword
          )
        GROUP BY p.product_id, p.title, p.author_name, p.thumbnail_file_id, p.status_code
        ORDER BY
          CASE WHEN p.title LIKE :prefix_keyword THEN 0 ELSE 1 END,
          p.updated_date DESC,
          p.product_id DESC
        LIMIT 20
        """
    )
    params = {
        "keyword": f"%{normalized_keyword}%",
        "prefix_keyword": f"{normalized_keyword}%",
    }
    result = await db.execute(query, params)
    rows = [dict(row) for row in result.mappings().all()]
    return {"data": rows}


@handle_exceptions
async def get_sessions(
    kc_user_id: str | None,
    guest_key: str | None,
    product_id: int | None,
    adult_yn: str,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn=adult_yn,
        db=db,
    )

    where_parts = ["deleted_yn = 'N'"]
    params: dict[str, Any] = {}
    if user_id is not None:
        where_parts.append("user_id = :user_id")
        params["user_id"] = user_id
    else:
        where_parts.append("guest_key = :guest_key")
        params["guest_key"] = resolved_guest_key

    if product_id:
        product_row = await _get_story_agent_product(
            product_id=product_id,
            adult_yn=effective_adult_yn,
            db=db,
        )
        if not product_row:
            return {"data": []}
        where_parts.append("product_id = :product_id")
        params["product_id"] = product_id

    query = text(
        f"""
        SELECT
            session_id AS sessionId,
            product_id AS productId,
            title,
            DATE_FORMAT(created_date, '%Y-%m-%d %H:%i:%s') AS createdDate,
            DATE_FORMAT(updated_date, '%Y-%m-%d %H:%i:%s') AS updatedDate
        FROM tb_story_agent_session
        WHERE {' AND '.join(where_parts)}
        ORDER BY updated_date DESC, session_id DESC
        LIMIT 50
        """
    )
    result = await db.execute(query, params)
    return {"data": [dict(row) for row in result.mappings().all()]}


@handle_exceptions
async def get_messages(
    session_id: int,
    kc_user_id: str | None,
    guest_key: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)

    query = text(
        """
        SELECT
            message_id AS messageId,
            role,
            content,
            DATE_FORMAT(created_date, '%Y-%m-%d %H:%i:%s') AS createdDate
        FROM tb_story_agent_message
        WHERE session_id = :session_id
        ORDER BY message_id ASC
        """
    )
    result = await db.execute(query, {"session_id": session_id})
    messages = [dict(row) for row in result.mappings().all()]
    return {
        "data": {
            "session": {
                "sessionId": session_row["session_id"],
                "productId": session_row["product_id"],
                "title": session_row["title"],
                "createdDate": (
                    session_row["created_date"].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(session_row["created_date"], datetime)
                    else str(session_row["created_date"])
                ),
                "updatedDate": (
                    session_row["updated_date"].strftime("%Y-%m-%d %H:%M:%S")
                    if isinstance(session_row["updated_date"], datetime)
                    else str(session_row["updated_date"])
                ),
            },
            "messages": messages,
        }
    }


@handle_exceptions
async def create_session(
    req_body: PostStoryAgentSessionReqBody,
    kc_user_id: str | None,
    adult_yn: str,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn=adult_yn,
        db=db,
    )
    product_row = await _get_story_agent_product(
        product_id=req_body.product_id,
        adult_yn=effective_adult_yn,
        db=db,
    )
    if not product_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCT,
        )

    title = (req_body.title or STORY_AGENT_DEFAULT_TITLE).strip()[:120]
    query = text(
        """
        INSERT INTO tb_story_agent_session
        (product_id, user_id, guest_key, title, deleted_yn, created_id, updated_id)
        VALUES (:product_id, :user_id, :guest_key, :title, 'N', :created_id, :updated_id)
        """
    )
    created_id = user_id if user_id is not None else settings.DB_DML_DEFAULT_ID
    result = await db.execute(
        query,
        {
            "product_id": req_body.product_id,
            "user_id": user_id,
            "guest_key": resolved_guest_key,
            "title": title,
            "created_id": created_id,
            "updated_id": created_id,
        },
    )
    session_id = result.lastrowid

    return {
        "data": {
            "sessionId": int(session_id),
            "productId": req_body.product_id,
            "title": title,
            "product": product_row,
        }
    }


@handle_exceptions
async def patch_session(
    session_id: int,
    req_body: PatchStoryAgentSessionReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    await _get_session_row(session_id, user_id, resolved_guest_key, db)

    query = text(
        """
        UPDATE tb_story_agent_session
        SET title = :title,
            updated_id = :updated_id,
            updated_date = NOW()
        WHERE session_id = :session_id
        """
    )
    await db.execute(
        query,
        {
            "title": req_body.title,
            "updated_id": user_id if user_id is not None else settings.DB_DML_DEFAULT_ID,
            "session_id": session_id,
        },
    )

    return {"data": {"sessionId": session_id, "title": req_body.title}}


@handle_exceptions
async def delete_session(
    session_id: int,
    guest_key: str | None,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, guest_key, db)
    await _get_session_row(session_id, user_id, resolved_guest_key, db)

    query = text(
        """
        UPDATE tb_story_agent_session
        SET deleted_yn = 'Y',
            updated_id = :updated_id,
            updated_date = NOW()
        WHERE session_id = :session_id
        """
    )
    await db.execute(
        query,
        {
            "updated_id": user_id if user_id is not None else settings.DB_DML_DEFAULT_ID,
            "session_id": session_id,
        },
    )
    return {"data": {"sessionId": session_id, "deletedYn": "Y"}}


@handle_exceptions
async def post_message(
    session_id: int,
    req_body: PostStoryAgentMessageReqBody,
    kc_user_id: str | None,
    db: AsyncSession,
):
    user_id, resolved_guest_key = await _resolve_actor(kc_user_id, req_body.guest_key, db)
    session_row = await _get_session_row(session_id, user_id, resolved_guest_key, db)
    effective_adult_yn = await _resolve_effective_adult_yn(
        kc_user_id=kc_user_id,
        adult_yn="Y",
        db=db,
    )
    product_row = await _get_story_agent_product(
        product_id=int(session_row["product_id"]),
        adult_yn=effective_adult_yn,
        db=db,
    )
    if not product_row:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message=ErrorMessages.NOT_FOUND_PRODUCT,
        )

    assistant_reply = STORY_AGENT_PLACEHOLDER_TEMPLATE.format(
        title=product_row.get("title") or "작품",
        user_prompt=req_body.content[:120],
    )
    created_id = user_id if user_id is not None else settings.DB_DML_DEFAULT_ID

    lock_acquired = False
    try:
        lock_acquired = await _acquire_story_agent_session_lock(session_id=session_id, db=db)
        if not lock_acquired:
            raise CustomResponseException(
                status_code=status.HTTP_409_CONFLICT,
                message="같은 세션에서 다른 메시지를 처리 중입니다. 잠시 후 다시 시도해주세요.",
            )

        existing_messages = await _get_existing_turn_messages(
            session_id=session_id,
            client_message_id=req_body.client_message_id,
            db=db,
        )
        if existing_messages:
            return {
                "data": {
                    "sessionId": session_id,
                    "messages": existing_messages,
                }
            }

        insert_query = text(
            """
            INSERT INTO tb_story_agent_message (
                session_id, role, client_message_id, content, created_id
            )
            VALUES (
                :session_id, :role, :client_message_id, :content, :created_id
            )
            """
        )
        user_result = await db.execute(
            insert_query,
            {
                "session_id": session_id,
                "role": "user",
                "client_message_id": req_body.client_message_id,
                "content": req_body.content,
                "created_id": created_id,
            },
        )
        assistant_result = await db.execute(
            insert_query,
            {
                "session_id": session_id,
                "role": "assistant",
                "client_message_id": req_body.client_message_id,
                "content": assistant_reply,
                "created_id": settings.DB_DML_DEFAULT_ID,
            },
        )

        update_title_query = text(
            """
            UPDATE tb_story_agent_session
            SET title = CASE
                    WHEN title = :default_title THEN :next_title
                    ELSE title
                END,
                updated_id = :updated_id,
                updated_date = NOW()
            WHERE session_id = :session_id
            """
        )
        await db.execute(
            update_title_query,
            {
                "default_title": STORY_AGENT_DEFAULT_TITLE,
                "next_title": req_body.content[:40],
                "updated_id": created_id,
                "session_id": session_id,
            },
        )

        return {
            "data": {
                "sessionId": session_id,
                "messages": [
                    {
                        "messageId": int(user_result.lastrowid),
                        "role": "user",
                        "content": req_body.content,
                    },
                    {
                        "messageId": int(assistant_result.lastrowid),
                        "role": "assistant",
                        "content": assistant_reply,
                    },
                ],
            }
        }
    finally:
        if lock_acquired:
            await _release_story_agent_session_lock(session_id=session_id, db=db)
