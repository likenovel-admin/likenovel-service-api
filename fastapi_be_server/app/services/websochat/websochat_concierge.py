from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.ai.recommendation_service import (
    _compute_taste_match,
    get_product_ai_metadata,
    get_user_taste_profile,
)
from app.services.websochat.websochat_contracts import (
    WebsochatCtaCard,
    WebsochatReasonCard,
    WebsochatStarterAction,
)

WEBSOCHAT_CONCIERGE_REASON_LIMIT = 3
WEBSOCHAT_CONCIERGE_TOPIC_MATCH_KEYWORDS = (
    "왜 나한테 맞",
    "왜 나랑 맞",
    "내 취향",
    "취향",
    "추천해",
    "추천해줘",
    "맞을지",
)
WEBSOCHAT_CONCIERGE_TOPIC_MOOD_KEYWORDS = (
    "분위기",
    "무드",
    "느낌",
    "결이",
    "결은",
    "작풍",
    "톤",
)
WEBSOCHAT_CONCIERGE_TOPIC_ENTRY_KEYWORDS = (
    "입문",
    "왜 봐야",
    "영업",
    "시작",
    "어디부터",
    "달릴만",
    "볼만",
)
WEBSOCHAT_CONCIERGE_TOPIC_SPOILER_KEYWORDS = (
    "결말",
    "반전",
    "흑막",
    "정체",
    "범인",
    "누가 죽",
    "죽어",
    "마지막",
    "스포",
)


def _normalize_websochat_concierge_text(raw_value: Any) -> str:
    return str(raw_value or "").strip()


def _contains_websochat_concierge_keyword(
    content: str,
    keywords: tuple[str, ...],
) -> bool:
    return any(keyword in content for keyword in keywords)


async def _get_websochat_recent_read_titles(
    *,
    user_id: int | None,
    product_id: int,
    db: AsyncSession,
    limit: int = 3,
) -> list[str]:
    if not user_id:
        return []

    safe_limit = max(1, min(int(limit), 5))
    result = await db.execute(
        text(
            f"""
            SELECT
                p.title
            FROM tb_user_product_usage u
            INNER JOIN tb_product p ON p.product_id = u.product_id
            WHERE u.user_id = :user_id
              AND u.use_yn = 'Y'
              AND u.product_id != :product_id
              AND p.open_yn = 'Y'
            GROUP BY u.product_id, p.title
            ORDER BY MAX(u.updated_date) DESC
            LIMIT {safe_limit}
            """
        ),
        {
            "user_id": user_id,
            "product_id": product_id,
        },
    )
    titles: list[str] = []
    for row in result.mappings().all():
        title = str(row.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
    return titles


def _append_websochat_reason_card(
    cards: list[WebsochatReasonCard],
    *,
    title: str,
    description: str,
) -> None:
    normalized_title = str(title or "").strip()
    normalized_description = str(description or "").strip()
    if not normalized_title or not normalized_description:
        return
    if any(card["title"] == normalized_title for card in cards):
        return
    cards.append(
        {
            "title": normalized_title,
            "description": normalized_description,
        }
    )


def _normalize_websochat_tag_list(raw_value: Any, *, limit: int = 3) -> list[str]:
    tags: list[str] = []
    for value in raw_value or []:
        normalized = str(value or "").strip()
        if not normalized or normalized in tags:
            continue
        tags.append(normalized)
        if len(tags) >= limit:
            break
    return tags


def _build_websochat_concierge_reason_cards(
    *,
    product_row: dict[str, Any],
    product_metadata: dict[str, Any] | None,
    taste_match: dict[str, Any] | None,
    recent_read_titles: list[str],
) -> list[WebsochatReasonCard]:
    cards: list[WebsochatReasonCard] = []

    mood = str((product_metadata or {}).get("mood") or "").strip()
    protagonist_type = str((product_metadata or {}).get("protagonist_type") or "").strip()
    taste_tags = _normalize_websochat_tag_list((product_metadata or {}).get("taste_tags"))
    worldview_tags = _normalize_websochat_tag_list((product_metadata or {}).get("worldview_tags"))

    top_axis = None
    if taste_match:
        top_axis = max(
            (
                ("protagonist", float(taste_match.get("protagonist") or 0.0)),
                ("mood", float(taste_match.get("mood") or 0.0)),
                ("pacing", float(taste_match.get("pacing") or 0.0)),
            ),
            key=lambda item: item[1],
        )
        if top_axis[1] <= 0:
            top_axis = None

    if top_axis:
        axis, _ = top_axis
        if axis == "protagonist" and protagonist_type:
            _append_websochat_reason_card(
                cards,
                title="취향 적중",
                description=f"최근 취향 기준으로 {protagonist_type} 계열 주인공 축이 잘 맞을 가능성이 높아요.",
            )
        elif axis == "mood" and mood:
            _append_websochat_reason_card(
                cards,
                title="무드 적합",
                description=f"최근 취향에서 {mood} 무드를 선호한 흐름과 이 작품의 결이 겹쳐요.",
            )
        elif axis == "pacing":
            _append_websochat_reason_card(
                cards,
                title="호흡 적합",
                description="읽기 호흡이 최근 취향과 크게 어긋나지 않을 가능성이 높아요.",
            )

    if taste_tags:
        _append_websochat_reason_card(
            cards,
            title="작품 결",
            description=f"{', '.join(taste_tags)} 쪽 결을 먼저 기대하고 들어가면 맞는지 판단하기 쉬워요.",
        )

    if protagonist_type or mood:
        fragments = [fragment for fragment in [protagonist_type, mood] if fragment]
        if fragments:
            _append_websochat_reason_card(
                cards,
                title="입문 포인트",
                description=f"주요 체감 축은 {' / '.join(fragments[:2])} 쪽이에요.",
            )

    if worldview_tags:
        _append_websochat_reason_card(
            cards,
            title="세계관 포인트",
            description=f"{', '.join(worldview_tags)} 요소를 좋아하면 초반 적응이 빠를 수 있어요.",
        )

    if recent_read_titles:
        joined_titles = ", ".join(recent_read_titles[:2])
        _append_websochat_reason_card(
            cards,
            title="최근 읽은 흐름 연결",
            description=f"최근 본 {joined_titles} 같은 흐름을 좋아했다면 이어서 보기 편한 편이에요.",
        )

    if not cards:
        _append_websochat_reason_card(
            cards,
            title="입문 추천",
            description=(
                f"{str(product_row.get('title') or '이 작품').strip()}는 스포일러 없이 작품 결과 분위기부터 "
                "가볍게 잡아보기 좋은 편이에요."
            ),
        )

    return cards[:WEBSOCHAT_CONCIERGE_REASON_LIMIT]


def _resolve_websochat_concierge_topic(user_prompt: str | None) -> str:
    normalized_prompt = _normalize_websochat_concierge_text(user_prompt).lower()
    if not normalized_prompt:
        return "intro"
    if _contains_websochat_concierge_keyword(
        normalized_prompt, WEBSOCHAT_CONCIERGE_TOPIC_SPOILER_KEYWORDS
    ):
        return "spoiler_guard"
    if _contains_websochat_concierge_keyword(
        normalized_prompt, WEBSOCHAT_CONCIERGE_TOPIC_MATCH_KEYWORDS
    ):
        return "match"
    if _contains_websochat_concierge_keyword(
        normalized_prompt, WEBSOCHAT_CONCIERGE_TOPIC_MOOD_KEYWORDS
    ):
        return "mood"
    if _contains_websochat_concierge_keyword(
        normalized_prompt, WEBSOCHAT_CONCIERGE_TOPIC_ENTRY_KEYWORDS
    ):
        return "entry"
    return "intro"


def _build_websochat_concierge_signal_bundle(
    *,
    product_row: dict[str, Any],
    product_metadata: dict[str, Any] | None,
    taste_match: dict[str, Any] | None,
    recent_read_titles: list[str],
    reason_cards: list[WebsochatReasonCard],
) -> dict[str, Any]:
    normalized_product_metadata = product_metadata or {}
    taste_tags = _normalize_websochat_tag_list(
        normalized_product_metadata.get("taste_tags"), limit=4
    )
    worldview_tags = _normalize_websochat_tag_list(
        normalized_product_metadata.get("worldview_tags"), limit=4
    )
    material_tags = _normalize_websochat_tag_list(
        normalized_product_metadata.get("protagonist_material_tags"), limit=3
    )
    protagonist_type = _normalize_websochat_concierge_text(
        normalized_product_metadata.get("protagonist_type")
    )
    protagonist_goal = _normalize_websochat_concierge_text(
        normalized_product_metadata.get("protagonist_goal_primary")
    )
    mood = _normalize_websochat_concierge_text(normalized_product_metadata.get("mood"))
    latest_episode_no = int(product_row.get("latestEpisodeNo") or 0)
    title = _normalize_websochat_concierge_text(product_row.get("title")) or "이 작품"
    top_axis: str | None = None
    if taste_match:
        ordered = sorted(
            (
                ("protagonist", float(taste_match.get("protagonist") or 0.0)),
                ("mood", float(taste_match.get("mood") or 0.0)),
                ("pacing", float(taste_match.get("pacing") or 0.0)),
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        if ordered and ordered[0][1] > 0:
            top_axis = ordered[0][0]
    return {
        "title": title,
        "latestEpisodeNo": latest_episode_no,
        "tasteTags": taste_tags,
        "worldviewTags": worldview_tags,
        "materialTags": material_tags,
        "protagonistType": protagonist_type,
        "protagonistGoal": protagonist_goal,
        "mood": mood,
        "recentReadTitles": recent_read_titles[:2],
        "reasonCards": reason_cards,
        "topAxis": top_axis,
    }


def build_websochat_concierge_actions() -> list[WebsochatStarterAction]:
    return [
        {
            "label": "스포일러 없이 작품 소개",
            "prompt": "아직 안 읽었어. 스포일러 없이 작품 소개부터 해줘",
        },
        {
            "label": "왜 나한테 맞는지",
            "prompt": "아직 안 읽었어. 왜 나한테 맞을지 설명해줘",
        },
        {
            "label": "어떤 분위기인지",
            "prompt": "아직 안 읽었어. 어떤 분위기 작품인지 알려줘",
        },
        {
            "label": "입문 포인트",
            "prompt": "아직 안 읽었어. 입문 포인트만 짚어줘",
        },
    ]


def build_websochat_concierge_cta_cards(*, product_id: int) -> list[WebsochatCtaCard]:
    if product_id <= 0:
        return []
    return [
        {
            "type": "product_detail",
            "label": "작품 상세 보기",
            "product_id": product_id,
        }
    ]


def _build_websochat_concierge_intro_reply(
    *,
    signals: dict[str, Any],
) -> str:
    lines = ["아직 읽기 전이라면 스포일러 없이 감만 먼저 잡아볼게."]
    if signals["tasteTags"]:
        lines.append(
            f"{signals['title']}는 {', '.join(signals['tasteTags'][:3])} 쪽 결을 기대하고 들어가면 맞는지 판단하기 쉬워요."
        )
    elif signals["reasonCards"]:
        lines.append(str(signals["reasonCards"][0]["description"]))
    if signals["protagonistType"] or signals["mood"]:
        fragments = [value for value in [signals["protagonistType"], signals["mood"]] if value]
        lines.append(f"초반 체감 축은 {' / '.join(fragments[:2])} 쪽이에요.")
    if signals["latestEpisodeNo"] >= 20:
        lines.append(
            f"지금 공개 분량이 {signals['latestEpisodeNo']}화까지 쌓여 있어서 취향만 맞으면 바로 달리기 좋은 편이에요."
        )
    lines.append("작품 상세에서 소개글과 태그를 먼저 보고, 맞으면 첫 화부터 들어가는 흐름이 제일 안전해요.")
    return "\n".join(lines)


def _build_websochat_concierge_match_reply(
    *,
    signals: dict[str, Any],
) -> str:
    lines = ["아직 읽기 전 기준으로, 네 취향에 맞는지부터 보수적으로 말할게."]
    if signals["topAxis"] == "protagonist" and signals["protagonistType"]:
        lines.append(
            f"주인공 축으로 보면 {signals['protagonistType']} 계열 감도가 네 최근 취향과 가장 잘 맞을 가능성이 높아요."
        )
    elif signals["topAxis"] == "mood" and signals["mood"]:
        lines.append(
            f"무드 축으로 보면 {signals['mood']} 분위기가 최근 취향과 제일 강하게 겹쳐요."
        )
    elif signals["topAxis"] == "pacing":
        lines.append("호흡 축으로 보면 초반 진입 리듬이 네 취향과 크게 어긋나지 않을 가능성이 높아요.")
    elif signals["reasonCards"]:
        lines.append(str(signals["reasonCards"][0]["description"]))
    if signals["recentReadTitles"]:
        lines.append(
            f"최근에 본 {', '.join(signals['recentReadTitles'])} 쪽 감각을 좋아했다면 이어서 보기 쉬운 편이에요."
        )
    if signals["tasteTags"]:
        lines.append(
            f"특히 {', '.join(signals['tasteTags'][:2])} 키워드에 끌리면 첫인상에서 바로 갈릴 가능성이 큽니다."
        )
    lines.append("더 확실히 보려면 작품 상세의 소개글과 태그를 먼저 확인해보는 게 좋아요.")
    return "\n".join(lines)


def _build_websochat_concierge_mood_reply(
    *,
    signals: dict[str, Any],
) -> str:
    lines = ["스포일러 없이 분위기만 잡아보면 이 작품은 꽤 결이 분명한 편이에요."]
    mood = signals["mood"]
    if mood:
        lines.append(f"기본 무드는 {mood} 쪽으로 읽히고, 가볍게 넘기는 타입보다는 텐션을 붙잡는 쪽에 가까워요.")
    if signals["worldviewTags"]:
        lines.append(
            f"세계관은 {', '.join(signals['worldviewTags'][:3])} 요소가 앞에 서는 편이라 초반 공기부터 선명하게 들어옵니다."
        )
    if signals["materialTags"]:
        lines.append(
            f"소재 체감은 {', '.join(signals['materialTags'][:2])} 쪽이라 설정 맛으로 붙는 독자에게 유리해요."
        )
    lines.append("너무 자세한 줄거리 대신, 상세페이지 소개글만 봐도 이 결이 맞는지 빠르게 감이 올 거예요.")
    return "\n".join(lines)


def _build_websochat_concierge_entry_reply(
    *,
    signals: dict[str, Any],
) -> str:
    lines = ["입문 관점으로만 보면, 이 작품은 초반에 결이 맞는지 꽤 빨리 판별되는 편이에요."]
    if signals["protagonistType"]:
        lines.append(f"주인공 축은 {signals['protagonistType']} 쪽이라 이 타입에 끌리면 진입 장벽이 낮습니다.")
    if signals["protagonistGoal"]:
        lines.append(f"초반엔 주인공의 큰 방향이 {signals['protagonistGoal']} 쪽으로 읽혀서 동력이 비교적 분명한 편이에요.")
    if signals["worldviewTags"]:
        lines.append(
            f"세계관 포인트는 {', '.join(signals['worldviewTags'][:2])} 쪽이 먼저 들어오니, 설정 취향만 맞으면 빠르게 붙어요."
        )
    lines.append("일단 상세페이지에서 소개글과 첫 화 분위기만 확인해도 계속 갈지 판단하기 좋습니다.")
    return "\n".join(lines)


def _build_websochat_concierge_spoiler_guard_reply(
    *,
    signals: dict[str, Any],
) -> str:
    lines = ["아직 읽기 전이면 결말이나 반전 쪽은 아껴두는 게 좋습니다."]
    if signals["reasonCards"]:
        lines.append(f"대신 {signals['title']}가 왜 먹히는지는 {signals['reasonCards'][0]['description']}")
    if signals["tasteTags"]:
        lines.append(
            f"스포일러 없이 보려면 {', '.join(signals['tasteTags'][:2])} 결과 맞는지만 먼저 확인해보는 걸 권해요."
        )
    lines.append("지금은 작품 상세를 보거나, 작품 소개·입문 포인트 쪽으로 이어가는 게 안전합니다.")
    return "\n".join(lines)


def build_websochat_concierge_reply(
    *,
    product_title: str,
    reason_cards: list[WebsochatReasonCard],
    signal_bundle: dict[str, Any] | None = None,
    user_prompt: str | None = None,
) -> str:
    signals = signal_bundle or {
        "title": str(product_title or "").strip() or "이 작품",
        "reasonCards": reason_cards,
        "tasteTags": [],
        "worldviewTags": [],
        "materialTags": [],
        "protagonistType": "",
        "protagonistGoal": "",
        "mood": "",
        "recentReadTitles": [],
        "latestEpisodeNo": 0,
        "topAxis": None,
    }
    topic = _resolve_websochat_concierge_topic(user_prompt)
    if topic == "match":
        return _build_websochat_concierge_match_reply(signals=signals)
    if topic == "mood":
        return _build_websochat_concierge_mood_reply(signals=signals)
    if topic == "entry":
        return _build_websochat_concierge_entry_reply(signals=signals)
    if topic == "spoiler_guard":
        return _build_websochat_concierge_spoiler_guard_reply(signals=signals)
    return _build_websochat_concierge_intro_reply(signals=signals)


async def build_websochat_concierge_payload(
    *,
    product_row: dict[str, Any],
    user_id: int | None,
    db: AsyncSession,
    user_prompt: str | None = None,
) -> dict[str, Any]:
    product_id = int(product_row.get("productId") or 0)
    product_metadata = await get_product_ai_metadata(product_id, db)
    taste_profile = await get_user_taste_profile(int(user_id), db) if user_id is not None else None
    taste_match = _compute_taste_match(product_metadata or {}, taste_profile) if product_metadata else None
    recent_read_titles = await _get_websochat_recent_read_titles(
        user_id=user_id,
        product_id=product_id,
        db=db,
    )
    reason_cards = _build_websochat_concierge_reason_cards(
        product_row=product_row,
        product_metadata=product_metadata,
        taste_match=taste_match,
        recent_read_titles=recent_read_titles,
    )
    signal_bundle = _build_websochat_concierge_signal_bundle(
        product_row=product_row,
        product_metadata=product_metadata,
        taste_match=taste_match,
        recent_read_titles=recent_read_titles,
        reason_cards=reason_cards,
    )

    return {
        "scopeState": "none",
        "reasonCards": reason_cards,
        "actions": build_websochat_concierge_actions(),
        "ctaCards": build_websochat_concierge_cta_cards(product_id=product_id),
        "reply": build_websochat_concierge_reply(
            product_title=str(product_row.get("title") or "").strip(),
            reason_cards=reason_cards,
            signal_bundle=signal_bundle,
            user_prompt=user_prompt,
        ),
    }
