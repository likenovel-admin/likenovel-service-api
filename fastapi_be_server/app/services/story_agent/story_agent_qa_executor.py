from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, TypedDict

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.ai_chat_service import _call_claude_messages, _extract_text, _extract_tool_use_blocks, _to_json_safe
from app.services.story_agent.story_agent_contracts import (
    StoryAgentEvidenceBundle,
    StoryAgentQaExecutionResult,
    StoryAgentResponsePlan,
)
from app.services.story_agent.story_agent_context_loader import build_story_agent_scope_context_message
from app.services.story_agent.story_agent_llm import STORY_AGENT_REPLY_MAX_TOKENS, call_story_agent_gemini, to_story_agent_gemini_contents
from app.services.story_agent.story_agent_qa_renderer import (
    build_story_agent_gemini_context_block,
    build_story_agent_recent_context_message,
)


class StoryAgentQaExecutionHooks(TypedDict):
    resolve_summary_mode: Callable[..., tuple[str, int | None, Any, Any]]
    resolve_exact_episode_no: Callable[..., Awaitable[int | None]]
    extract_keywords: Callable[[str], list[str]]
    get_summary_candidates: Callable[..., Awaitable[list[dict[str, Any]]]]
    get_broad_summary_context_rows: Callable[..., Awaitable[list[dict[str, Any]]]]
    resolve_reference: Callable[..., Awaitable[dict[str, Any]]]
    build_reference_resolution_message: Callable[[dict[str, Any]], str]
    get_episode_contents: Callable[..., Awaitable[list[dict[str, Any]]]]
    search_episode_contents: Callable[..., Awaitable[list[dict[str, Any]]]]
    build_system_prompt: Callable[[dict[str, Any]], str]
    build_summary_context_message: Callable[[list[dict[str, Any]]], str]
    is_ambiguous_reference_query: Callable[[str], bool]
    dispatch_tool: Callable[..., Awaitable[dict[str, Any]]]


async def _generate_story_agent_reply_with_gemini(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    resolved_mode: str,
    evidence_bundle: StoryAgentEvidenceBundle,
    recent_messages: list[dict[str, str]],
    db: AsyncSession,
    hooks: StoryAgentQaExecutionHooks,
    gemini_context_episode_limit: int,
    prefetch_context_chars: int,
) -> str:
    scope_read_episode_to = evidence_bundle["resolved_scope"]["read_episode_to"]
    scope_context = evidence_bundle["scope_context"]
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    effective_latest_episode_no = min(max(int(scope_read_episode_to or 0), 1), max(latest_episode_no, 1))
    resolved_mode, exact_episode_no, _, _ = hooks["resolve_summary_mode"](
        query_text=user_prompt,
        latest_episode_no=effective_latest_episode_no,
        mode=resolved_mode,
    )
    resolved_episode_no = None
    if resolved_mode == "exact":
        resolved_episode_no = await hooks["resolve_exact_episode_no"](
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=effective_latest_episode_no,
            query_text=user_prompt,
            fallback_episode_no=exact_episode_no,
            db=db,
        )

    keywords = hooks["extract_keywords"](user_prompt)
    if resolved_mode == "exact":
        summary_rows = await hooks["get_summary_candidates"](
            product_id=int(product_row.get("productId") or 0),
            keywords=keywords,
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            mode=resolved_mode,
            episode_no=resolved_episode_no,
            db=db,
        )
    else:
        summary_rows = await hooks["get_broad_summary_context_rows"](
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            resolved_mode=resolved_mode,
            db=db,
        )

    reference_resolution = await hooks["resolve_reference"](
        product_row=product_row,
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        summary_rows=summary_rows,
    )

    episode_rows: list[dict[str, Any]] = []
    search_rows: list[dict[str, Any]] = []
    if resolved_episode_no:
        episode_rows = await hooks["get_episode_contents"](
            product_id=int(product_row.get("productId") or 0),
            episode_from=resolved_episode_no,
            episode_to=resolved_episode_no,
            latest_episode_no=effective_latest_episode_no,
            db=db,
        )
    else:
        target_episode_nos: list[int] = []
        for row in summary_rows[:gemini_context_episode_limit]:
            episode_no = int(row.get("episodeTo") or row.get("episodeFrom") or 0)
            if episode_no > 0 and episode_no not in target_episode_nos:
                target_episode_nos.append(episode_no)
        for episode_no in target_episode_nos[:gemini_context_episode_limit]:
            episode_rows.extend(
                await hooks["get_episode_contents"](
                    product_id=int(product_row.get("productId") or 0),
                    episode_from=episode_no,
                    episode_to=episode_no,
                    latest_episode_no=effective_latest_episode_no,
                    db=db,
                )
            )
        search_rows = await hooks["search_episode_contents"](
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            db=db,
        )

    system_prompt = (
        hooks["build_system_prompt"](product_row)
        + " 이번 응답은 확장형 질문용 응답이다. 제공된 공개 컨텍스트만으로 잘 놀아주되, 근거 없는 설정을 단정하지 마라."
        + " 비교/시뮬레이션 답변이라도 근거가 되는 회차나 장면을 1개 이상 자연스럽게 인용하라."
        + " 원문에 없는 추론은 '작품 내 직접 묘사는 없지만'처럼 추론임을 분명히 밝혀라."
        + " 능력, 범위, 지속시간, 거리, 숫자 같은 수치 정보가 공개 범위에 있으면 가능한 한 포함하라."
    )
    context_block = build_story_agent_gemini_context_block(
        product_row=product_row,
        summary_rows=summary_rows,
        episode_rows=episode_rows,
        search_rows=search_rows,
        episode_limit=gemini_context_episode_limit,
        preview_chars=prefetch_context_chars,
    )
    messages = list(recent_messages)
    scope_context_message = build_story_agent_scope_context_message(scope_context or {})
    if scope_context_message:
        messages.append(
            {
                "role": "user",
                "content": (
                    "아래는 현재 공개 범위 기준으로 미리 정리된 작품 컨텍스트다. "
                    "인물 비중, 관계, 미해결 훅을 설명할 때 우선 참고하라.\n\n"
                    f"{scope_context_message}"
                ),
            }
        )
    if hooks["is_ambiguous_reference_query"](user_prompt):
        recent_context_message = build_story_agent_recent_context_message(recent_messages)
        if recent_context_message:
            messages.append({"role": "user", "content": recent_context_message})
        reference_message = hooks["build_reference_resolution_message"](reference_resolution or {})
        if reference_message:
            messages.append({"role": "user", "content": reference_message})
    messages.append(
        {
            "role": "user",
            "content": (
                "아래 공개 컨텍스트를 우선 참고해 답하라.\n\n"
                f"{context_block}\n\n"
                f"질문: {user_prompt}"
            ),
        }
    )
    return await call_story_agent_gemini(
        system_prompt=system_prompt,
        messages=to_story_agent_gemini_contents(messages),
        max_tokens=STORY_AGENT_REPLY_MAX_TOKENS,
    )


async def _generate_story_agent_reply_with_claude(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    resolved_mode: str,
    evidence_bundle: StoryAgentEvidenceBundle,
    recent_messages: list[dict[str, str]],
    db: AsyncSession,
    hooks: StoryAgentQaExecutionHooks,
    max_tool_rounds: int,
    tools: list[dict[str, Any]],
    prefetch_context_chars: int,
) -> str:
    scope_read_episode_to = evidence_bundle["resolved_scope"]["read_episode_to"]
    scope_context = evidence_bundle["scope_context"]
    system_prompt = hooks["build_system_prompt"](product_row)
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    effective_latest_episode_no = min(max(int(scope_read_episode_to or 0), 1), max(latest_episode_no, 1))
    messages = list(recent_messages)
    scope_context_message = build_story_agent_scope_context_message(scope_context or {})
    if scope_context_message:
        messages.append(
            {
                "role": "user",
                "content": (
                    "아래는 현재 공개 범위 기준으로 미리 정리된 작품 컨텍스트다. "
                    "인물 비중, 관계, 미해결 훅을 설명할 때 우선 참고하라.\n\n"
                    f"{scope_context_message}"
                ),
            }
        )
    resolved_mode, exact_episode_no, _, _ = hooks["resolve_summary_mode"](
        query_text=user_prompt,
        latest_episode_no=effective_latest_episode_no,
        mode=resolved_mode,
    )
    if resolved_mode == "exact":
        resolved_episode_no = await hooks["resolve_exact_episode_no"](
            product_id=int(product_row.get("productId") or 0),
            latest_episode_no=effective_latest_episode_no,
            query_text=user_prompt,
            fallback_episode_no=exact_episode_no,
            db=db,
        )
    else:
        resolved_episode_no = None

    prefetched_summary_rows: list[dict[str, Any]] = []
    if resolved_mode != "exact":
        prefetched_summary_rows = await hooks["get_broad_summary_context_rows"](
            product_id=int(product_row.get("productId") or 0),
            query_text=user_prompt,
            latest_episode_no=effective_latest_episode_no,
            resolved_mode=resolved_mode,
            db=db,
        )
        summary_context_message = hooks["build_summary_context_message"](prefetched_summary_rows)
        if summary_context_message:
            messages.append({"role": "user", "content": summary_context_message})

    reference_resolution = await hooks["resolve_reference"](
        product_row=product_row,
        user_prompt=user_prompt,
        recent_messages=recent_messages,
        summary_rows=prefetched_summary_rows,
    )
    if hooks["is_ambiguous_reference_query"](user_prompt):
        recent_context_message = build_story_agent_recent_context_message(recent_messages)
        if recent_context_message:
            messages.append({"role": "user", "content": recent_context_message})
        reference_message = hooks["build_reference_resolution_message"](reference_resolution or {})
        if reference_message:
            messages.append({"role": "user", "content": reference_message})

    if resolved_mode == "exact" and resolved_episode_no:
        prefetched_rows = await hooks["get_episode_contents"](
            product_id=int(product_row.get("productId") or 0),
            episode_from=resolved_episode_no,
            episode_to=resolved_episode_no,
            latest_episode_no=effective_latest_episode_no,
            db=db,
        )
        prefetched_blocks: list[str] = []
        for row in prefetched_rows:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            prefetched_blocks.append(f"[질문 관련 공개 원문]\n{content[:prefetch_context_chars]}")
        if prefetched_blocks:
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "아래는 이번 질문과 직접 관련된 공개 원문이다. "
                        "명시된 회차 사실 질문에서는 이 원문을 최우선 근거로 사용하고, 내부 회차 매핑 과정은 설명하지 마라.\n\n"
                        + "\n\n".join(prefetched_blocks)
                    ),
                }
            )
    messages.append({"role": "user", "content": user_prompt})

    for _ in range(max_tool_rounds):
        response = await _call_claude_messages(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            max_tokens=STORY_AGENT_REPLY_MAX_TOKENS,
        )
        content = response.get("content") or []
        text_reply = _extract_text(content)
        tool_uses = _extract_tool_use_blocks(content)
        if not tool_uses:
            return text_reply.strip() or "지금 공개 범위에서 바로 짚을 수 있는 핵심은 아직 제한적입니다. 우선 어떤 축이 궁금한지 말씀해 주세요. 예를 들면 능력 규칙, 세력 질서, 인물 관계, 전투 상성 중 하나로 좁히면 더 정확하게 이어서 답할 수 있습니다."

        messages.append({"role": "assistant", "content": content})
        tool_results: list[dict[str, Any]] = []
        for block in tool_uses:
            tool_name = str(block.get("name") or "")
            tool_input = block.get("input") or {}
            try:
                tool_result = await hooks["dispatch_tool"](
                    tool_name=tool_name,
                    tool_input=tool_input if isinstance(tool_input, dict) else {},
                    product_id=int(product_row.get("productId") or 0),
                    product_row=product_row,
                    db=db,
                )
            except Exception as exc:
                tool_result = {"error": str(exc)}
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block.get("id"),
                    "content": json.dumps(_to_json_safe(tool_result), ensure_ascii=False),
                }
            )
        messages.append({"role": "user", "content": tool_results})

    return "지금 공개 범위에서 바로 단정할 수 있는 근거는 충분하지 않습니다. 다만 질문을 더 잘게 나누면 바로 이어서 볼 수 있습니다. 능력 규칙, 세력 질서, 인물 관계, 전투 상성 중 어느 쪽이 궁금한지 한 가지로 좁혀 주세요."


async def execute_story_agent_qa(
    *,
    product_row: dict[str, Any],
    user_prompt: str,
    qa_plan: StoryAgentResponsePlan,
    evidence_bundle: StoryAgentEvidenceBundle,
    recent_messages: list[dict[str, str]],
    db: AsyncSession,
    hooks: StoryAgentQaExecutionHooks,
    max_tool_rounds: int,
    gemini_context_episode_limit: int,
    prefetch_context_chars: int,
    tools: list[dict[str, Any]],
) -> StoryAgentQaExecutionResult:
    fallback_used = False
    if qa_plan["preferred_model"] == "gemini":
        try:
            reply = await _generate_story_agent_reply_with_gemini(
                product_row=product_row,
                user_prompt=user_prompt,
                resolved_mode=qa_plan["route_mode"],
                evidence_bundle=evidence_bundle,
                recent_messages=recent_messages,
                db=db,
                hooks=hooks,
                gemini_context_episode_limit=gemini_context_episode_limit,
                prefetch_context_chars=prefetch_context_chars,
            )
            return {
                "reply": reply,
                "model_used": "gemini",
                "fallback_used": False,
                "route_mode": qa_plan["route_mode"],
                "intent": qa_plan["intent"],
            }
        except Exception:
            fallback_used = True

    reply = await _generate_story_agent_reply_with_claude(
        product_row=product_row,
        user_prompt=user_prompt,
        resolved_mode=qa_plan["route_mode"],
        evidence_bundle=evidence_bundle,
        recent_messages=recent_messages,
        db=db,
        hooks=hooks,
        max_tool_rounds=max_tool_rounds,
        tools=tools,
        prefetch_context_chars=prefetch_context_chars,
    )
    return {
        "reply": reply,
        "model_used": "haiku",
        "fallback_used": fallback_used,
        "route_mode": qa_plan["route_mode"],
        "intent": qa_plan["intent"],
    }
