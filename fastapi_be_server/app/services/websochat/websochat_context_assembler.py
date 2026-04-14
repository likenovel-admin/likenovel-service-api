from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.websochat.websochat_contracts import (
    WebsochatEvidenceBundle,
    WebsochatResolvedScope,
)
from app.services.websochat.websochat_context_loader import load_websochat_scope_context
from app.services.websochat.websochat_scope_resolver import _resolve_websochat_scope_read_episode_to

logger = logging.getLogger(__name__)


async def assemble_websochat_scope_context(
    *,
    product_row: dict[str, Any],
    session_memory: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> WebsochatEvidenceBundle:
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    synced_latest_episode_no = max(int(product_row.get("syncedLatestEpisodeNo") or 0), 0)
    conversation_latest_episode_no = (
        min(latest_episode_no, synced_latest_episode_no)
        if latest_episode_no > 0 and synced_latest_episode_no > 0
        else latest_episode_no
    )
    scope_read_episode_to = _resolve_websochat_scope_read_episode_to(
        session_memory=session_memory,
        user_prompt=user_prompt,
        latest_episode_no=conversation_latest_episode_no,
    )

    scoped_product_row = dict(product_row)
    if scope_read_episode_to > 0:
        scoped_product_row["latestEpisodeNo"] = min(
            scope_read_episode_to,
            max(conversation_latest_episode_no, 1),
        )

    scope_context: dict[str, Any] | None = None
    if conversation_latest_episode_no > 0 and scope_read_episode_to > 0:
        try:
            scope_context = await load_websochat_scope_context(
                product_id=int(product_row.get("productId") or 0),
                read_episode_to=scope_read_episode_to,
                latest_episode_no=conversation_latest_episode_no,
                db=db,
            )
            logger.info(
                "websochat qa_scope_context_loaded product_id=%s read_episode_to=%s plot_rows=%s characters=%s relations=%s hooks=%s",
                product_row.get("productId"),
                scope_read_episode_to,
                len(scope_context.get("plot_rows") or []),
                len(scope_context.get("characters") or []),
                len(scope_context.get("relations") or []),
                len(scope_context.get("hooks") or []),
            )
        except Exception as exc:
            logger.warning(
                "websochat qa_scope_context_failed product_id=%s read_episode_to=%s error=%s",
                product_row.get("productId"),
                scope_read_episode_to,
                exc,
            )

    resolved_scope: WebsochatResolvedScope = {
        "read_episode_to": scope_read_episode_to,
        "latest_episode_no": conversation_latest_episode_no,
    }
    return {
        "resolved_scope": resolved_scope,
        "product_row": scoped_product_row,
        "scope_context": scope_context,
    }
