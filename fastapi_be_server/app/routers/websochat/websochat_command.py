import asyncio
import json
from contextlib import suppress
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db, likenovel_db_session
from app.services.websochat.websochat_stream import (
    reset_websochat_stream_emitter,
    set_websochat_stream_emitter,
)
from app.utils.auth import analysis_logger, chk_cur_user
import app.schemas.websochat as websochat_schema
import app.services.websochat.websochat_service as websochat_service

router = APIRouter(prefix="/websochat")


@router.post(
    "/sessions",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def post_websochat_session(
    req_body: websochat_schema.PostWebsochatSessionReqBody,
    adult_yn: str = "N",
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.create_session(
        req_body=req_body,
        kc_user_id=user.get("sub"),
        adult_yn=adult_yn,
        db=db,
    )


@router.patch(
    "/sessions/{session_id}",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def patch_websochat_session(
    session_id: int,
    req_body: websochat_schema.PatchWebsochatSessionReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.patch_session(
        session_id=session_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.patch(
    "/sessions/{session_id}/read-scope",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def patch_websochat_session_read_scope(
    session_id: int,
    req_body: websochat_schema.PatchWebsochatSessionReadScopeReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.patch_session_read_scope(
        session_id=session_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.patch(
    "/sessions/{session_id}/mode",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def patch_websochat_session_mode(
    session_id: int,
    req_body: websochat_schema.PatchWebsochatSessionModeReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.patch_session_mode(
        session_id=session_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.delete(
    "/sessions/{session_id}",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def delete_websochat_session(
    session_id: int,
    req_body: websochat_schema.DeleteWebsochatSessionReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.delete_session(
        session_id=session_id,
        guest_key=req_body.guest_key,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.post(
    "/sessions/{session_id}/messages",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def post_websochat_message(
    session_id: int,
    req_body: websochat_schema.PostWebsochatMessageReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    return await websochat_service.post_message(
        session_id=session_id,
        req_body=req_body,
        kc_user_id=user.get("sub"),
        db=db,
    )


@router.options(
    "/sessions/{session_id}/messages/stream",
    tags=["웹소챗"],
)
async def post_websochat_message_stream_options(
    session_id: int,
):
    return Response(status_code=204)


@router.post(
    "/sessions/{session_id}/messages/stream",
    tags=["웹소챗"],
    dependencies=[Depends(analysis_logger)],
)
async def post_websochat_message_stream(
    session_id: int,
    req_body: websochat_schema.PostWebsochatMessageReqBody,
    http_request: Request,
    user: Dict[str, Any] = Depends(chk_cur_user),
):
    queue: asyncio.Queue = asyncio.Queue(maxsize=1024)
    done = asyncio.Event()
    client_gone = asyncio.Event()

    async def _queue_event(event_name: str, payload: dict[str, Any]) -> None:
        while True:
            if client_gone.is_set():
                raise asyncio.CancelledError("websochat stream disconnected")
            try:
                await asyncio.wait_for(
                    queue.put({"event": event_name, "data": payload}),
                    timeout=1.0,
                )
                return
            except asyncio.TimeoutError:
                continue

    async def _emit_delta(chunk: str) -> None:
        text = str(chunk or "")
        if not text:
            return
        max_chars = 64
        start = 0

        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                boundary = max(
                    text.rfind("\n", start, end),
                    text.rfind(".", start, end),
                    text.rfind("?", start, end),
                    text.rfind("!", start, end),
                    text.rfind("…", start, end),
                    text.rfind(" ", start, end),
                )
                if boundary > start:
                    end = boundary + 1

            part = text[start:end]
            if part:
                await _queue_event("assistant_delta", {"delta": part})
            start = end

    async def _worker() -> None:
        tokens = set_websochat_stream_emitter(_emit_delta)
        try:
            await _queue_event(
                "assistant_started",
                {
                    "sessionId": session_id,
                    "clientMessageId": req_body.client_message_id,
                },
            )
            async with likenovel_db_session() as stream_db:
                result = await websochat_service.post_message(
                    session_id=session_id,
                    req_body=req_body,
                    kc_user_id=user.get("sub"),
                    db=stream_db,
                )
            await _queue_event("assistant_completed", jsonable_encoder(result.get("data") or {}))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await _queue_event(
                "assistant_error",
                {"detail": str(exc) or "websochat stream failed"},
            )
        finally:
            reset_websochat_stream_emitter(tokens)
            done.set()

    worker_task = asyncio.create_task(_worker())

    async def _event_gen():
        try:
            while True:
                if done.is_set() and queue.empty():
                    break
                try:
                    if await http_request.is_disconnected():
                        client_gone.set()
                        break
                except Exception:
                    pass
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=10.0)
                except asyncio.TimeoutError:
                    if client_gone.is_set():
                        break
                    yield ": keep-alive\n\n"
                    continue

                yield f"event: {item['event']}\n"
                yield f"data: {json.dumps(item['data'], ensure_ascii=False)}\n\n"
        finally:
            client_gone.set()
            if not worker_task.done():
                worker_task.cancel()
                with suppress(BaseException):
                    await worker_task
            try:
                if not await http_request.is_disconnected():
                    yield "event: done\n"
                    yield "data: {}\n\n"
            except Exception:
                pass

    return StreamingResponse(
        _event_gen(),
        media_type="text/event-stream; charset=utf-8",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )
