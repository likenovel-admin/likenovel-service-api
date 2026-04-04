from __future__ import annotations

import re
from typing import Any


def build_story_agent_recent_context_message(
    recent_messages: list[dict[str, str]],
) -> str:
    if not recent_messages:
        return ""

    lines: list[str] = []
    for message in recent_messages[-4:]:
        role = "사용자" if str(message.get("role") or "").strip() == "user" else "이전 답변"
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if not content:
            continue
        lines.append(f"- {role}: {content[:220]}")

    if not lines:
        return ""

    return (
        "아래는 이번 질문 직전까지의 최근 대화 핵심이다. "
        "지시대명사 질문이면 가장 최근에 언급된 장면·선택·인물을 우선 참조하라.\n"
        + "\n".join(lines)
    )


def build_story_agent_context_block(
    summary_rows: list[dict[str, Any]],
    chunk_rows: list[dict[str, Any]],
) -> str:
    lines: list[str] = []
    if summary_rows:
        lines.append("관련 회차 요약:")
        for row in summary_rows[:3]:
            summary_text = str(row.get("summaryText") or "").strip()
            if not summary_text:
                continue
            lines.append(summary_text)

    if chunk_rows:
        lines.append("원문 미리보기:")
        for row in chunk_rows[:3]:
            preview = re.sub(r"\s+", " ", str(row.get("chunkText") or "")).strip()
            if not preview:
                continue
            preview = preview[:180]
            lines.append(f"- {int(row.get('episodeNo') or 0)}화 일부: {preview}")

    if not lines:
        return "아직 관련 회차 요약이나 원문 미리보기를 찾지 못했습니다."
    return "\n".join(lines)


def build_story_agent_gemini_context_block(
    *,
    product_row: dict[str, Any],
    summary_rows: list[dict[str, Any]],
    episode_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
    episode_limit: int,
    preview_chars: int,
) -> str:
    lines: list[str] = [
        "[작품 정보]",
        f"- 제목: {str(product_row.get('title') or '').strip()}",
        f"- 작가: {str(product_row.get('authorNickname') or '').strip()}",
        f"- 최신 공개 회차: {int(product_row.get('latestEpisodeNo') or 0)}화",
    ]

    if summary_rows:
        lines.append("[관련 회차 요약]")
        for row in summary_rows[:3]:
            summary_text = str(row.get("summaryText") or "").strip()
            if summary_text:
                lines.append(summary_text)

    if episode_rows:
        lines.append("[관련 공개 원문]")
        for row in episode_rows[:episode_limit]:
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            lines.append(
                f"{int(row.get('episodeNo') or 0)}화 원문:\n{content[:preview_chars]}"
            )

    if search_rows:
        lines.append("[추가 원문 단서]")
        for row in search_rows[:4]:
            preview = re.sub(r"\s+", " ", str(row.get("chunkText") or "")).strip()
            if preview:
                lines.append(f"- {int(row.get('episodeNo') or 0)}화 일부: {preview[:220]}")

    return "\n".join(lines)
