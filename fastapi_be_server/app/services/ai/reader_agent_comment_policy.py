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
# The limits above are per episode, so one reader could still greet every episode
# of a work in a single sitting. Bound the reader on the work as well.
READER_COMMENT_24H_LIMIT = 2
READER_COMMENT_MIN_INTERVAL_SECONDS = 1800
# A comment under a near-empty view count looks artificial to readers, so the
# episode must already have a plausible audience before an AI reader comments.
COMMENT_MIN_EPISODE_VIEW_COUNT = 5
# Real drop-in readers overwhelmingly comment while sampling the opening run, so
# occasional readers keep a normal rate there and taper off deeper into a work.
COMMENT_EARLY_EPISODE_LIMIT = 25
QUIET_EARLY_CHANCE = 100
QUIET_MID_CHANCE = 40
QUIET_LATE_CHANCE = 15


def _quiet_chance(episode_no: int | None) -> int:
    """Per-episode chance in 1/10000 units for an occasional reader."""
    if episode_no is None or episode_no <= COMMENT_EARLY_EPISODE_LIMIT:
        return QUIET_EARLY_CHANCE
    if episode_no <= 50:
        return QUIET_MID_CHANCE
    return QUIET_LATE_CHANCE


def is_regular_commenter(user_id: int, product_id: int) -> bool:
    digest = hashlib.sha256(f"reader-comment-cohort|{user_id}|{product_id}".encode()).hexdigest()
    return int(digest[:8], 16) % 100 < 10


def choose_comment(
    user_id: int, product_id: int, episode_id: int, *, first_read: bool, finished: bool,
    episode_no: int | None = None,
) -> tuple[str, int] | None:
    work_digest = hashlib.sha256(f"reader-comment-style|{user_id}|{product_id}".encode()).hexdigest()
    episode_digest = hashlib.sha256(
        f"reader-comment-chance|{user_id}|{product_id}|{episode_id}".encode()
    ).hexdigest()
    regular = is_regular_commenter(user_id, product_id)
    threshold = (
        (10000 if first_read else 8000) if regular else _quiet_chance(episode_no)
    )
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
