from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.story_agent.story_agent_contracts import (
    StoryAgentEvidenceBundle,
    StoryAgentResolvedScope,
)
from app.services.story_agent.story_agent_context_loader import load_story_agent_scope_context
from app.services.story_agent.story_agent_scope_resolver import _resolve_story_agent_scope_read_episode_to

logger = logging.getLogger(__name__)


async def assemble_story_agent_scope_context(
    *,
    product_row: dict[str, Any],
    session_memory: dict[str, Any],
    user_prompt: str,
    db: AsyncSession,
) -> StoryAgentEvidenceBundle:
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    scope_read_episode_to = _resolve_story_agent_scope_read_episode_to(
        session_memory=session_memory,
        user_prompt=user_prompt,
        latest_episode_no=latest_episode_no,
    )

    scoped_product_row = dict(product_row)
    if scope_read_episode_to > 0:
        scoped_product_row["latestEpisodeNo"] = min(scope_read_episode_to, max(latest_episode_no, 1))

    scope_context: dict[str, Any] | None = None
    if latest_episode_no > 0 and scope_read_episode_to > 0:
        try:
            scope_context = await load_story_agent_scope_context(
                product_id=int(product_row.get("productId") or 0),
                read_episode_to=scope_read_episode_to,
                latest_episode_no=latest_episode_no,
                db=db,
            )
            logger.info(
                "story-agent qa_scope_context_loaded product_id=%s read_episode_to=%s plot_rows=%s characters=%s relations=%s hooks=%s",
                product_row.get("productId"),
                scope_read_episode_to,
                len(scope_context.get("plot_rows") or []),
                len(scope_context.get("characters") or []),
                len(scope_context.get("relations") or []),
                len(scope_context.get("hooks") or []),
            )
        except Exception as exc:
            logger.warning(
                "story-agent qa_scope_context_failed product_id=%s read_episode_to=%s error=%s",
                product_row.get("productId"),
                scope_read_episode_to,
                exc,
            )

    resolved_scope: StoryAgentResolvedScope = {
        "read_episode_to": scope_read_episode_to,
        "latest_episode_no": latest_episode_no,
    }
    return {
        "resolved_scope": resolved_scope,
        "product_row": scoped_product_row,
        "scope_context": scope_context,
    }
