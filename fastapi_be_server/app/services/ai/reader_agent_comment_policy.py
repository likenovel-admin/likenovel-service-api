"""Stable per-work participation; no persona model or provider request."""

import hashlib


REPEATABLE_GREETINGS = (
    "잘 봤습니다.", "잘 보고 갑니다.", "잘 읽었습니다.",
    "건필하세요.", "응원합니다.", "감사합니다.",
)
COMMENT_TEXTS = REPEATABLE_GREETINGS + (
    "재밌네요.", "다음화 기대됩니다.", "술술 읽히네요.",
    "느낌 좋네요.", "계속 볼게요.",
)
COMMENT_24H_LIMIT = 3
COMMENT_MIN_INTERVAL_SECONDS = 1800
COMMENT_EXPIRY_GRACE_SECONDS = 300


def is_regular_commenter(user_id: int, product_id: int) -> bool:
    digest = hashlib.sha256(f"reader-comment-cohort|{user_id}|{product_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < 10


def choose_comment(
    user_id: int, product_id: int, episode_id: int, *, first_read: bool, finished: bool,
) -> tuple[str, int] | None:
    work_digest = hashlib.sha256(f"reader-comment-style|{user_id}|{product_id}".encode()).hexdigest()
    episode_digest = hashlib.sha256(
        f"reader-comment-chance|{user_id}|{product_id}|{episode_id}".encode()
    ).hexdigest()
    regular = is_regular_commenter(user_id, product_id)
    threshold = (10000 if first_read else 8000) if regular else 100
    if int(episode_digest[:8], 16) % 10000 >= threshold:
        return None
    if regular:
        content = REPEATABLE_GREETINGS[int(work_digest[:8], 16) % len(REPEATABLE_GREETINGS)]
    else:
        candidates = tuple(text for text in COMMENT_TEXTS
                           if not finished or text not in ("다음화 기대됩니다.", "계속 볼게요."))
        content = candidates[int(episode_digest[8:16], 16) % len(candidates)]
    # A stable delay preserves this reader's reading order, including across midnight.
    delay = 600 + int(work_digest[8:16], 16) % 21001
    return content, delay


def is_repeated_comment(content: str, recent_public: list[str]) -> bool:
    allowed = 2 if content in REPEATABLE_GREETINGS else 1
    return len(recent_public) >= allowed and all(
        " ".join(text.split()) == content for text in recent_public[:allowed]
    )
