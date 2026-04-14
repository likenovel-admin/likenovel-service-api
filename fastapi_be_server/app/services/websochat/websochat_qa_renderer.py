from __future__ import annotations

import re
from typing import Any


def build_websochat_recent_context_message(
    recent_messages: list[dict[str, str]],
    *,
    qa_recent_notes: list[str] | None = None,
    qa_corrections: list[dict[str, str]] | None = None,
    current_qa_corrections: list[dict[str, str]] | None = None,
) -> str:
    if not recent_messages and not qa_recent_notes and not qa_corrections and not current_qa_corrections:
        return ""

    lines: list[str] = []
    if current_qa_corrections:
        lines.append("이번 턴에서 사용자가 방금 직전 설명을 바로잡았다:")
        for item in current_qa_corrections[-3:]:
            subject = re.sub(r"\s+", " ", str(item.get("subject") or "")).strip()
            correct_value = re.sub(r"\s+", " ", str(item.get("correct_value") or "")).strip()
            incorrect_value = re.sub(r"\s+", " ", str(item.get("incorrect_value") or "")).strip()
            if not subject or not correct_value:
                continue
            if incorrect_value:
                lines.append(f"- {subject}: {correct_value} (방금의 {incorrect_value} 진술은 다시 사실처럼 반복하지 말 것)")
            else:
                lines.append(f"- {subject}: {correct_value}")
    if qa_corrections:
        lines.append("이번 세션에서 이미 바로잡힌 사실:")
        for item in qa_corrections[-4:]:
            subject = re.sub(r"\s+", " ", str(item.get("subject") or "")).strip()
            correct_value = re.sub(r"\s+", " ", str(item.get("correct_value") or "")).strip()
            incorrect_value = re.sub(r"\s+", " ", str(item.get("incorrect_value") or "")).strip()
            if not subject or not correct_value:
                continue
            if incorrect_value:
                lines.append(f"- {subject}: {correct_value} (이전의 {incorrect_value} 해석은 다시 단정하지 말 것)")
            else:
                lines.append(f"- {subject}: {correct_value}")
    if qa_recent_notes:
        lines.append("최근 대화에서 붙잡고 있던 논의 축:")
        for item in qa_recent_notes[-6:]:
            normalized = re.sub(r"\s+", " ", str(item or "")).strip()
            if normalized:
                lines.append(f"- {normalized[:220]}")
    for message in recent_messages[-10:]:
        role = "사용자" if str(message.get("role") or "").strip() == "user" else "이전 답변"
        content = re.sub(r"\s+", " ", str(message.get("content") or "")).strip()
        if not content:
            continue
        lines.append(f"- {role}: {content[:320]}")

    if not lines:
        return ""

    return (
        "아래는 이번 질문 직전까지의 대화 흐름 참고다. "
        "최근에 붙잡고 있던 논의 축과 직전 메시지를 참고하되, 이 내용을 사용자에게 다시 메타하게 설명하거나 '정리하면', '우리가 방금', '다시 말해'처럼 풀지 말고 그냥 자연스럽게 이어서 답하라. 이번 턴 정정과 세션 정정은 우선 반영하고 작품 사실관계는 공개 컨텍스트를 더 우선하라.\n"
        + "\n".join(lines)
    )


def build_websochat_context_block(
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


def build_websochat_gemini_context_block(
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

    if summary_rows:
        lines.append("[관련 회차 요약]")
        for row in summary_rows[:3]:
            summary_text = str(row.get("summaryText") or "").strip()
            if summary_text:
                lines.append(summary_text)

    return "\n".join(lines)
