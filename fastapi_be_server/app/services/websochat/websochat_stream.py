from __future__ import annotations

from contextvars import ContextVar, Token
from typing import Any, Awaitable, Callable

WebsochatStreamEmitter = Callable[[str], Awaitable[None]]

_websochat_stream_emitter_var: ContextVar[WebsochatStreamEmitter | None] = ContextVar(
    "websochat_stream_emitter",
    default=None,
)
_websochat_stream_state_var: ContextVar[dict[str, Any] | None] = ContextVar(
    "websochat_stream_state",
    default=None,
)
_websochat_stream_deferred_chunks_var: ContextVar[list[str] | None] = ContextVar(
    "websochat_stream_deferred_chunks",
    default=None,
)


def set_websochat_stream_emitter(
    emitter: WebsochatStreamEmitter | None,
) -> tuple[Token, Token]:
    emitter_token = _websochat_stream_emitter_var.set(emitter)
    state_token = _websochat_stream_state_var.set({"emitted": False})
    return emitter_token, state_token


def reset_websochat_stream_emitter(tokens: tuple[Token, Token]) -> None:
    emitter_token, state_token = tokens
    _websochat_stream_emitter_var.reset(emitter_token)
    _websochat_stream_state_var.reset(state_token)


def has_websochat_stream_emitted() -> bool:
    state = _websochat_stream_state_var.get()
    return bool(state and state.get("emitted"))


def is_websochat_stream_enabled() -> bool:
    return _websochat_stream_emitter_var.get() is not None


def defer_websochat_stream_output() -> Token:
    return _websochat_stream_deferred_chunks_var.set([])


def reset_websochat_stream_output(token: Token) -> None:
    _websochat_stream_deferred_chunks_var.reset(token)


def replace_deferred_websochat_stream_output(text: str) -> bool:
    chunks = _websochat_stream_deferred_chunks_var.get()
    if chunks is None:
        return False
    value = str(text or "")
    chunks.clear()
    if value:
        chunks.append(value)
    return True


async def flush_deferred_websochat_stream_output() -> None:
    chunks = _websochat_stream_deferred_chunks_var.get()
    emitter = _websochat_stream_emitter_var.get()
    if chunks is None or emitter is None:
        return
    value = "".join(chunks)
    chunks.clear()
    if value:
        await emitter(value)


async def emit_websochat_stream_delta(text: str, *, chunk_size: int = 48) -> None:
    emitter = _websochat_stream_emitter_var.get()
    if emitter is None:
        return
    value = str(text or "")
    if not value:
        return
    state = _websochat_stream_state_var.get()
    if state is not None:
        state["emitted"] = True
    deferred_chunks = _websochat_stream_deferred_chunks_var.get()
    if deferred_chunks is not None:
        deferred_chunks.append(value)
        return
    if chunk_size <= 0 or len(value) <= chunk_size:
        await emitter(value)
        return
    for start in range(0, len(value), chunk_size):
        part = value[start : start + chunk_size]
        if part:
            await emitter(part)


async def emit_websochat_stream_text_if_needed(text: str) -> None:
    if has_websochat_stream_emitted():
        return
    await emit_websochat_stream_delta(text)
