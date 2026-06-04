import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, date, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import status
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

import app.schemas.admin as admin_schema
import app.schemas.auth as auth_schema
from app.const import settings
from app.exceptions import CustomResponseException
from app.services.auth import auth_service
from app.services.ai import reader_agent_persona_service
from app.services.ai import reader_agent_session_service


IMMEDIATE_SCHEDULE_MIN_WINDOW_MINUTES = 30
AI_READER_PROFILE_NICKNAME_POOL = (
    "Stock고수가될꺼야",
    "장투에는낭만이있다",
    "제대로물렸음",
    "마이너스15고인물",
    "flyingDogKR",
    "BabyGoat전사",
    "RghtHipSnpr",
    "뽑이89",
    "vhrhvhrh고수",
    "gkituxgwkfjvgg",
    "퍼플헤이즈",
    "우주방어",
    "꾸깽이",
    "삼십육살아기",
    "리쿠리쿠",
    "나마비루",
    "Sepia",
    "Nikon떼배",
    "urgent16",
    "cheap465",
    "tycoon10",
    "pill6058",
    "listen05",
    "height82",
    "kvwajz0r",
    "kimi0000",
    "거시팀김씨1",
    "오늘도무사히",
    "moSSol",
    "뭉몽이",
    "반반이",
    "주식하는오타쿠",
    "돌리다",
    "독도수면팩",
    "뚀로롱",
    "아주작은개미",
    "사막여우",
    "이몸등장",
    "순카기",
    "삿포로특파원",
    "조선닌자핫토리",
    "BURGERKING",
    "오릭스히타치",
    "팔중앵",
    "터키튀르키예",
    "오백원짜리CD",
    "넨도",
    "기미김",
    "쿠라쿠라",
    "최하영",
    "NEWS",
    "자산운용사",
    "Mistea",
    "또사때야",
    "milan",
    "진성고수",
    "복뚝분",
    "헤놀로지",
    "TlM",
    "시이나링고잼",
    "까모투자증권",
    "asodmd",
    "서비",
    "프로켈",
    "이응미음",
    "알타리무배추",
    "OTC",
    "투어독러버",
    "Stock고인물",
    "마이너스15전사",
    "flyingDog고수",
    "BabyGoat고인물",
    "RghtHipSnprKR",
    "vhrhvhrh러너",
    "gkituxgwkfjvgg고수",
    "퍼플헤이즈고인물",
    "우주방어1337",
    "꾸깽이워리어",
    "삼십육살아기고인물",
    "Nikon떼배고수",
    "tycoon10고인물",
    "pill6058전사",
    "오늘도손절",
    "내일은반등",
    "차트보는밤",
    "물린개미",
    "초단타금지",
    "배당먹는사람",
    "종가매수러",
    "시장은몰라",
    "빨간봉기원",
    "파란봉친구",
    "계좌방어중",
    "본전만찾자",
    "소액장투러",
    "호가창멍때림",
    "커피값수익",
    "새벽독서러",
    "회차수집가",
    "다음화못참음",
)


def _now_in_kst() -> datetime:
    return datetime.now(ZoneInfo(settings.KOREA_TIMEZONE)).replace(tzinfo=None)


def _parse_schedule_date(value: str | None) -> date:
    if not value:
        return _now_in_kst().date()
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="schedule_date must be YYYY-MM-DD.",
        ) from exc


def _schedule_dates_for_duration(start_date: date, duration_days: int) -> list[date]:
    return [
        start_date + timedelta(days=index)
        for index in range(int(duration_days))
    ]


def _parse_json_field(value: Any, fallback: Any) -> Any:
    if value is None:
        return fallback
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return fallback
    return fallback


def _schedule_window_payload(
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow],
) -> list[dict[str, Any]]:
    return [
        {
            "active_start_at": window.active_start_at.isoformat(sep=" "),
            "active_end_at": window.active_end_at.isoformat(sep=" "),
            "session_budget": window.session_budget,
        }
        for window in windows
    ]


def _format_schedule_datetime(value: datetime) -> str:
    return value.isoformat(sep=" ")


def _parse_immediate_schedule_start_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("T", " ")).replace(tzinfo=None)
    except ValueError as exc:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="immediate_schedule_start_at must be ISO datetime.",
        ) from exc


def _round_up_to_next_five_minutes(value: datetime) -> datetime:
    normalized = value.replace(second=0, microsecond=0)
    remainder = normalized.minute % 5
    if remainder == 0 and value.second == 0 and value.microsecond == 0:
        return normalized
    minutes_to_add = 5 - remainder if remainder else 5
    return normalized + timedelta(minutes=minutes_to_add)


def _build_immediate_schedule_batches(
    *,
    agent_count: int,
    schedule_date: date,
    start_immediately: bool,
    batch_size: int,
    batch_interval_minutes: int,
    now: datetime | None = None,
    immediate_schedule_start_at: datetime | None = None,
) -> list[dict[str, Any]]:
    if not start_immediately or agent_count <= 0:
        return []
    current_time = now or _now_in_kst()
    if schedule_date != current_time.date():
        return []

    normalized_batch_size = max(1, min(100, int(batch_size)))
    normalized_interval = max(1, min(120, int(batch_interval_minutes)))
    window_minutes = max(IMMEDIATE_SCHEDULE_MIN_WINDOW_MINUTES, normalized_interval)
    first_start_at = immediate_schedule_start_at or _round_up_to_next_five_minutes(
        current_time
    )

    batches: list[dict[str, Any]] = []
    remaining_count = agent_count
    batch_index = 0
    while remaining_count > 0:
        batch_agent_count = min(normalized_batch_size, remaining_count)
        active_start_at = first_start_at + timedelta(
            minutes=batch_index * normalized_interval
        )
        batches.append(
            {
                "active_start_at": active_start_at,
                "active_end_at": active_start_at + timedelta(minutes=window_minutes),
                "agent_count": batch_agent_count,
            }
        )
        remaining_count -= batch_agent_count
        batch_index += 1
    return batches


def _immediate_schedule_preview_payload(
    batches: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "active_start_at": _format_schedule_datetime(batch["active_start_at"]),
            "active_end_at": _format_schedule_datetime(batch["active_end_at"]),
            "agent_count": int(batch["agent_count"]),
        }
        for batch in batches
    ]


def _time_blocks_payload(time_blocks: Any) -> list[dict[str, Any]] | None:
    if not time_blocks:
        return None
    payload: list[dict[str, Any]] = []
    for block in time_blocks:
        raw = block.model_dump() if hasattr(block, "model_dump") else dict(block)
        item = {
            "start_hour": int(raw["start_hour"]),
            "end_hour": int(raw["end_hour"]),
            "sessions_per_agent": int(raw.get("sessions_per_agent") or 1),
        }
        label = raw.get("label")
        if label:
            item["label"] = str(label)
        payload.append(item)
    return payload


def _operation_auto_pause_after(
    *,
    schedule_end_date: date,
    immediate_batches: list[dict[str, Any]],
) -> datetime:
    operation_end_at = datetime.combine(
        schedule_end_date + timedelta(days=1),
        datetime.min.time(),
    )
    for batch in immediate_batches:
        active_end_at = batch.get("active_end_at")
        if isinstance(active_end_at, datetime):
            operation_end_at = max(operation_end_at, active_end_at)
    return operation_end_at


def _activity_pattern_with_auto_pause_after(
    pattern_value: Any,
    auto_pause_after: datetime | None,
    auto_pause_schedule_end_date: date | None = None,
    time_blocks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    pattern = _parse_json_field(pattern_value, {})
    if not isinstance(pattern, dict):
        pattern = {}
    if time_blocks is not None:
        pattern = {
            **pattern,
            "time_blocks": time_blocks,
        }
    if auto_pause_after is not None:
        pattern = {
            **pattern,
            "auto_pause_after": _format_schedule_datetime(auto_pause_after),
        }
        if auto_pause_schedule_end_date is not None:
            pattern["auto_pause_schedule_end_date"] = (
                auto_pause_schedule_end_date.isoformat()
            )
    return pattern


def _build_immediate_reader_schedule_windows(
    *,
    ai_reader_agent_ids: list[int],
    schedule_date: date,
    start_immediately: bool,
    batch_size: int,
    batch_interval_minutes: int,
    now: datetime | None = None,
    immediate_schedule_start_at: datetime | None = None,
) -> list[reader_agent_session_service.ReaderDailyScheduleWindow]:
    batches = _build_immediate_schedule_batches(
        agent_count=len(ai_reader_agent_ids),
        schedule_date=schedule_date,
        start_immediately=start_immediately,
        batch_size=batch_size,
        batch_interval_minutes=batch_interval_minutes,
        now=now,
        immediate_schedule_start_at=immediate_schedule_start_at,
    )
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
    cursor = 0
    for batch in batches:
        batch_agent_ids = ai_reader_agent_ids[cursor: cursor + int(batch["agent_count"])]
        cursor += len(batch_agent_ids)
        for ai_reader_agent_id in batch_agent_ids:
            windows.append(
                reader_agent_session_service.ReaderDailyScheduleWindow(
                    ai_reader_agent_id=ai_reader_agent_id,
                    schedule_date=schedule_date,
                    active_start_at=batch["active_start_at"],
                    active_end_at=batch["active_end_at"],
                    session_budget=1,
                )
            )
    return windows


def _sleep_hours(active_hours: list[int]) -> list[int]:
    active_set = set(active_hours)
    return [hour for hour in range(24) if hour not in active_set]


def _allowed_ai_reader_account_domains() -> list[str]:
    return [
        domain.strip().lower()
        for domain in settings.AI_READER_ACCOUNT_ALLOWED_DOMAINS.split(",")
        if domain.strip()
    ]


def _provision_ai_reader_account_domain(allowed_domains: list[str]) -> str:
    frontend_url = (settings.SERVICE_FRONTEND_URL or "").lower()
    preferred_suffix = ".dev" if ".dev" in frontend_url else ".net"
    for domain in allowed_domains:
        if domain.endswith(preferred_suffix):
            return domain
    return allowed_domains[0]


def _generate_ai_reader_account_password() -> str:
    return f"Ai{secrets.randbelow(10_000_000_000):010d}!"


def _combined_ai_reader_profile_nickname_pool(
    profile_nickname_pool: list[str] | None = None,
) -> list[str]:
    combined: list[str] = []
    seen: set[str] = set()
    for nickname in [
        *AI_READER_PROFILE_NICKNAME_POOL,
        *(profile_nickname_pool or []),
    ]:
        normalized_nickname = str(nickname).strip()
        if not normalized_nickname or normalized_nickname in seen:
            continue
        combined.append(normalized_nickname)
        seen.add(normalized_nickname)
    return combined


def _ai_reader_profile_nickname_start_index(email: str, *, pool_size: int) -> int:
    if pool_size <= 0:
        return 0
    local_part = email.split("@", 1)[0]
    match = re.search(r"(\d+)$", local_part)
    if not match:
        return 0
    suffix_number = int(match.group(1))
    return max(0, suffix_number - 1) % pool_size


def _ai_reader_profile_nickname_candidates(
    email: str,
    *,
    profile_nickname_pool: list[str] | None = None,
) -> list[str]:
    nickname_pool = _combined_ai_reader_profile_nickname_pool(profile_nickname_pool)
    start_index = _ai_reader_profile_nickname_start_index(
        email,
        pool_size=len(nickname_pool),
    )
    return [
        *nickname_pool[start_index:],
        *nickname_pool[:start_index],
    ]


async def _assign_ai_reader_profile_nickname(
    db: AsyncSession,
    *,
    user_id: int,
    email: str,
    profile_nickname_pool: list[str] | None = None,
) -> str:
    for nickname in _ai_reader_profile_nickname_candidates(
        email,
        profile_nickname_pool=profile_nickname_pool,
    ):
        duplicate_result = await db.execute(
            text("""
                select profile_id
                  from tb_user_profile
                 where nickname = :nickname
                   and user_id <> :user_id
                 limit 1
            """),
            {
                "nickname": nickname,
                "user_id": user_id,
            },
        )
        if duplicate_result.mappings().one_or_none():
            continue

        update_result = await db.execute(
            text("""
                update tb_user_profile
                   set nickname = :nickname,
                       updated_id = :updated_id,
                       updated_date = current_timestamp
                 where user_id = :user_id
                   and default_yn = 'Y'
                   and role_type = 'user'
            """),
            {
                "nickname": nickname,
                "updated_id": settings.DB_DML_DEFAULT_ID,
                "user_id": user_id,
            },
        )
        if int(getattr(update_result, "rowcount", 0) or 0) <= 0:
            raise CustomResponseException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                message=f"AI reader profile was not found for user: {user_id}",
            )
        return nickname

    raise CustomResponseException(
        status_code=status.HTTP_409_CONFLICT,
        message="AI reader nickname pool is exhausted.",
    )


async def _fetch_bootstrap_candidate_users(
    db: AsyncSession,
    *,
    email_prefix: str,
    allowed_domains: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    user_result = await db.execute(
        text("""
            select
                user_id,
                email
              from tb_user
             where use_yn = 'Y'
               and role_type = 'normal'
               and email like :email_like
               and lower(substring_index(email, '@', -1)) in :allowed_domains
               and not exists (
                       select 1
                         from tb_user_social us
                        where us.user_id = tb_user.user_id
                   )
               and not exists (
                       select 1
                         from tb_ai_reader_agent ar
                        where ar.user_id = tb_user.user_id
                   )
             order by email asc, user_id asc
             limit :limit
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {
            "email_like": f"{email_prefix}%",
            "allowed_domains": allowed_domains,
            "limit": limit,
        },
    )
    return [dict(row) for row in user_result.mappings().all()]


async def _create_ai_reader_dedicated_user(
    db: AsyncSession,
    *,
    email: str,
    profile_nickname_pool: list[str] | None = None,
) -> int:
    await auth_service.post_auth_signup(
        req_body=auth_schema.SignupReqBody(
            email=email,
            password=_generate_ai_reader_account_password(),
            birthdate="2000-01-01",
            gender="M",
            ad_info_agree_yn="N",
        ),
        db=db,
    )
    user_result = await db.execute(
        text("""
            select user_id
              from tb_user
             where email = :email
               and use_yn = 'Y'
             order by user_id desc
             limit 1
        """),
        {"email": email},
    )
    user_row = user_result.mappings().one_or_none()
    if not user_row:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message=f"AI reader account was created but user row was not found: {email}",
        )
    user_id = int(user_row["user_id"])
    await _assign_ai_reader_profile_nickname(
        db,
        user_id=user_id,
        email=email,
        profile_nickname_pool=profile_nickname_pool,
    )
    await db.execute(
        text("""
            delete from tb_user_social
             where user_id = :user_id
               and sns_type = 'likenovel'
        """),
        {"user_id": user_id},
    )
    await db.commit()
    return user_id


async def _provision_missing_ai_reader_users(
    db: AsyncSession,
    *,
    email_prefix: str,
    missing_count: int,
    allowed_domains: list[str],
    profile_nickname_pool: list[str] | None = None,
) -> int:
    if missing_count <= 0:
        return 0
    domain = _provision_ai_reader_account_domain(allowed_domains)
    await db.commit()
    existing_result = await db.execute(
        text("""
            select lower(email) as email
              from tb_user
             where email like :email_like
               and lower(substring_index(email, '@', -1)) = :domain
        """),
        {
            "email_like": f"{email_prefix}%@{domain}",
            "domain": domain,
        },
    )
    used_emails = {
        str(row["email"]).lower()
        for row in existing_result.mappings().all()
        if row.get("email")
    }
    await db.commit()
    created_count = 0
    next_index = 1
    while created_count < missing_count:
        if next_index > 999_999:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message="AI reader account email suffix range is exhausted.",
            )
        email = f"{email_prefix}{next_index:04d}@{domain}"
        next_index += 1
        if len(email) > 100 or email.lower() in used_emails:
            continue
        try:
            await _create_ai_reader_dedicated_user(
                db,
                email=email,
                profile_nickname_pool=profile_nickname_pool,
            )
        except CustomResponseException as exc:
            if exc.status_code == status.HTTP_409_CONFLICT:
                used_emails.add(email.lower())
                continue
            raise
        used_emails.add(email.lower())
        created_count += 1
    return created_count


def build_ai_reader_bootstrap_dry_run_token(
    *,
    email_prefix: str,
    agent_count: int,
    schedule_date: str,
    schedule_duration_days: int = 30,
    allow_partial: bool,
    agent_index_offset: int,
    daily_llm_budget: int,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
    time_blocks: list[dict[str, Any]] | None = None,
    start_immediately: bool = False,
    immediate_batch_size: int = 20,
    immediate_batch_interval_minutes: int = 10,
    immediate_schedule_start_at: str | None = None,
    age_group_ratios: dict[str, int] | None = None,
    gender_ratios: dict[str, int] | None = None,
    profile_nickname_pool: list[str] | None = None,
    user_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    normalized_active_hours = active_hours or list(admin_schema.DEFAULT_AI_READER_ACTIVE_HOURS)
    normalized_age_group_ratios = age_group_ratios or dict(
        admin_schema.DEFAULT_AI_READER_AGE_GROUP_RATIOS
    )
    normalized_gender_ratios = gender_ratios or dict(
        admin_schema.DEFAULT_AI_READER_GENDER_RATIOS
    )
    payload = {
        "v": 4,
        "email_prefix": email_prefix,
        "agent_count": agent_count,
        "schedule_date": schedule_date,
        "schedule_duration_days": schedule_duration_days,
        "allow_partial": allow_partial,
        "agent_index_offset": agent_index_offset,
        "daily_llm_budget": daily_llm_budget,
        "active_hours": sorted(normalized_active_hours),
        "daily_session_target": daily_session_target or 2,
        "time_blocks": time_blocks,
        "start_immediately": bool(start_immediately),
        "immediate_batch_size": immediate_batch_size,
        "immediate_batch_interval_minutes": immediate_batch_interval_minutes,
        "immediate_schedule_start_at": immediate_schedule_start_at,
        "age_group_ratios": normalized_age_group_ratios,
        "gender_ratios": normalized_gender_ratios,
        "profile_nickname_pool": profile_nickname_pool or [],
        "user_fingerprints": sorted(
            user_fingerprints or [],
            key=lambda item: (str(item.get("agent_key")), int(item.get("user_id") or 0)),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = (
        settings.KC_CLIENT_SECRET
        or settings.DB_USER_PW
        or "likenovel-ai-reader-bootstrap-dry-run"
    )
    return hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _expected_bootstrap_dry_run_token(
    req_body: admin_schema.PostAiReaderBootstrapReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    user_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    return build_ai_reader_bootstrap_dry_run_token(
        email_prefix=req_body.email_prefix,
        agent_count=req_body.agent_count,
        schedule_date=schedule_date.isoformat(),
        schedule_duration_days=req_body.schedule_duration_days,
        allow_partial=req_body.allow_partial,
        agent_index_offset=req_body.agent_index_offset,
        daily_llm_budget=req_body.daily_llm_budget,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
        time_blocks=_time_blocks_payload(req_body.time_blocks),
        start_immediately=req_body.start_immediately,
        immediate_batch_size=req_body.immediate_batch_size,
        immediate_batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        immediate_schedule_start_at=immediate_schedule_start_at,
        age_group_ratios=req_body.age_group_ratios,
        gender_ratios=req_body.gender_ratios,
        profile_nickname_pool=req_body.profile_nickname_pool,
        user_fingerprints=user_fingerprints,
    )


def _assert_matching_bootstrap_dry_run_token(
    req_body: admin_schema.PostAiReaderBootstrapReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    user_fingerprints: list[dict[str, Any]] | None = None,
) -> None:
    expected_token = _expected_bootstrap_dry_run_token(
        req_body,
        schedule_date=schedule_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        user_fingerprints=user_fingerprints,
    )
    if not req_body.dry_run_token or not hmac.compare_digest(
        req_body.dry_run_token,
        expected_token,
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="matching dry-run token is required before AI reader bootstrap apply.",
        )


def build_ai_reader_resume_paused_dry_run_token(
    *,
    agent_count: int,
    schedule_date: str,
    schedule_duration_days: int = 30,
    start_immediately: bool = False,
    immediate_batch_size: int = 20,
    immediate_batch_interval_minutes: int = 10,
    immediate_schedule_start_at: str | None = None,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
    time_blocks: list[dict[str, Any]] | None = None,
    daily_llm_budget: int | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "v": 3,
        "agent_count": agent_count,
        "schedule_date": schedule_date,
        "schedule_duration_days": schedule_duration_days,
        "start_immediately": bool(start_immediately),
        "immediate_batch_size": immediate_batch_size,
        "immediate_batch_interval_minutes": immediate_batch_interval_minutes,
        "immediate_schedule_start_at": immediate_schedule_start_at,
        "active_hours": sorted(active_hours) if active_hours else None,
        "daily_session_target": daily_session_target,
        "time_blocks": time_blocks,
        "daily_llm_budget": daily_llm_budget,
        "agent_fingerprints": sorted(
            agent_fingerprints or [],
            key=lambda item: int(item.get("ai_reader_agent_id") or 0),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = (
        settings.KC_CLIENT_SECRET
        or settings.DB_USER_PW
        or "likenovel-ai-reader-resume-paused-dry-run"
    )
    return hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _expected_resume_paused_dry_run_token(
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    return build_ai_reader_resume_paused_dry_run_token(
        agent_count=req_body.agent_count,
        schedule_date=schedule_date.isoformat(),
        schedule_duration_days=req_body.schedule_duration_days,
        start_immediately=req_body.start_immediately,
        immediate_batch_size=req_body.immediate_batch_size,
        immediate_batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        immediate_schedule_start_at=immediate_schedule_start_at,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
        time_blocks=_time_blocks_payload(req_body.time_blocks),
        daily_llm_budget=req_body.daily_llm_budget,
        agent_fingerprints=agent_fingerprints,
    )


def _assert_matching_resume_paused_dry_run_token(
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> None:
    expected_token = _expected_resume_paused_dry_run_token(
        req_body,
        schedule_date=schedule_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )
    if not req_body.dry_run_token or not hmac.compare_digest(
        req_body.dry_run_token,
        expected_token,
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="matching dry-run token is required before paused AI reader resume apply.",
        )


def build_ai_reader_refresh_schedules_dry_run_token(
    *,
    agent_count: int,
    schedule_date: str,
    schedule_duration_days: int = 30,
    start_immediately: bool = False,
    immediate_batch_size: int = 20,
    immediate_batch_interval_minutes: int = 10,
    immediate_schedule_start_at: str | None = None,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
    time_blocks: list[dict[str, Any]] | None = None,
    daily_llm_budget: int | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "v": 1,
        "operation": "refresh_active_schedules",
        "agent_count": agent_count,
        "schedule_date": schedule_date,
        "schedule_duration_days": schedule_duration_days,
        "start_immediately": bool(start_immediately),
        "immediate_batch_size": immediate_batch_size,
        "immediate_batch_interval_minutes": immediate_batch_interval_minutes,
        "immediate_schedule_start_at": immediate_schedule_start_at,
        "active_hours": sorted(active_hours) if active_hours else None,
        "daily_session_target": daily_session_target,
        "time_blocks": time_blocks,
        "daily_llm_budget": daily_llm_budget,
        "agent_fingerprints": sorted(
            agent_fingerprints or [],
            key=lambda item: int(item.get("ai_reader_agent_id") or 0),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = (
        settings.KC_CLIENT_SECRET
        or settings.DB_USER_PW
        or "likenovel-ai-reader-refresh-schedules-dry-run"
    )
    return hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _expected_refresh_schedules_dry_run_token(
    req_body: admin_schema.PostAiReaderRefreshSchedulesReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    return build_ai_reader_refresh_schedules_dry_run_token(
        agent_count=req_body.agent_count,
        schedule_date=schedule_date.isoformat(),
        schedule_duration_days=req_body.schedule_duration_days,
        start_immediately=req_body.start_immediately,
        immediate_batch_size=req_body.immediate_batch_size,
        immediate_batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        immediate_schedule_start_at=immediate_schedule_start_at,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
        time_blocks=_time_blocks_payload(req_body.time_blocks),
        daily_llm_budget=req_body.daily_llm_budget,
        agent_fingerprints=agent_fingerprints,
    )


def _assert_matching_refresh_schedules_dry_run_token(
    req_body: admin_schema.PostAiReaderRefreshSchedulesReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> None:
    expected_token = _expected_refresh_schedules_dry_run_token(
        req_body,
        schedule_date=schedule_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )
    if not req_body.dry_run_token or not hmac.compare_digest(
        req_body.dry_run_token,
        expected_token,
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="matching dry-run token is required before active AI reader schedule refresh apply.",
        )


def build_ai_reader_restart_dry_run_token(
    *,
    agent_count: int,
    schedule_date: str,
    schedule_duration_days: int = 30,
    start_immediately: bool = False,
    immediate_batch_size: int = 20,
    immediate_batch_interval_minutes: int = 10,
    immediate_schedule_start_at: str | None = None,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
    time_blocks: list[dict[str, Any]] | None = None,
    daily_llm_budget: int | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    payload = {
        "v": 1,
        "operation": "restart_ai_readers",
        "agent_count": agent_count,
        "schedule_date": schedule_date,
        "schedule_duration_days": schedule_duration_days,
        "start_immediately": bool(start_immediately),
        "immediate_batch_size": immediate_batch_size,
        "immediate_batch_interval_minutes": immediate_batch_interval_minutes,
        "immediate_schedule_start_at": immediate_schedule_start_at,
        "active_hours": sorted(active_hours) if active_hours else None,
        "daily_session_target": daily_session_target,
        "time_blocks": time_blocks,
        "daily_llm_budget": daily_llm_budget,
        "agent_fingerprints": sorted(
            agent_fingerprints or [],
            key=lambda item: int(item.get("ai_reader_agent_id") or 0),
        ),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    secret = (
        settings.KC_CLIENT_SECRET
        or settings.DB_USER_PW
        or "likenovel-ai-reader-restart-dry-run"
    )
    return hmac.new(
        secret.encode("utf-8"),
        raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _expected_restart_dry_run_token(
    req_body: admin_schema.PostAiReaderRestartReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> str:
    return build_ai_reader_restart_dry_run_token(
        agent_count=req_body.agent_count,
        schedule_date=schedule_date.isoformat(),
        schedule_duration_days=req_body.schedule_duration_days,
        start_immediately=req_body.start_immediately,
        immediate_batch_size=req_body.immediate_batch_size,
        immediate_batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        immediate_schedule_start_at=immediate_schedule_start_at,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
        time_blocks=_time_blocks_payload(req_body.time_blocks),
        daily_llm_budget=req_body.daily_llm_budget,
        agent_fingerprints=agent_fingerprints,
    )


def _assert_matching_restart_dry_run_token(
    req_body: admin_schema.PostAiReaderRestartReqBody,
    *,
    schedule_date: date,
    immediate_schedule_start_at: str | None = None,
    agent_fingerprints: list[dict[str, Any]] | None = None,
) -> None:
    expected_token = _expected_restart_dry_run_token(
        req_body,
        schedule_date=schedule_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )
    if not req_body.dry_run_token or not hmac.compare_digest(
        req_body.dry_run_token,
        expected_token,
    ):
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="matching dry-run token is required before AI reader restart apply.",
        )


def _resume_paused_agent_fingerprints(
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
            "agent_key": str(agent["agent_key"]),
            "user_id": int(agent["user_id"]),
        }
        for agent in agents
    ]


def _resume_activity_pattern_for_agent(
    agent: dict[str, Any],
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    *,
    auto_pause_after: datetime | None = None,
    auto_pause_schedule_end_date: date | None = None,
) -> dict[str, Any]:
    current_pattern = _parse_json_field(agent.get("activity_pattern_json"), {})
    if not isinstance(current_pattern, dict):
        current_pattern = {}
    active_hours = list(
        req_body.active_hours
        or current_pattern.get("active_hours")
        or admin_schema.DEFAULT_AI_READER_ACTIVE_HOURS
    )
    daily_session_target = (
        req_body.daily_session_target
        or current_pattern.get("daily_session_target")
        or 2
    )
    next_pattern = {
        **current_pattern,
        "active_hours": active_hours,
        "sleep_hours": _sleep_hours(active_hours),
        "daily_session_target": int(daily_session_target),
    }
    requested_time_blocks = _time_blocks_payload(req_body.time_blocks)
    if requested_time_blocks is not None:
        next_pattern["time_blocks"] = requested_time_blocks
    elif req_body.active_hours is not None:
        next_pattern.pop("time_blocks", None)
    if auto_pause_after is not None:
        next_pattern["auto_pause_after"] = _format_schedule_datetime(auto_pause_after)
        if auto_pause_schedule_end_date is not None:
            next_pattern["auto_pause_schedule_end_date"] = (
                auto_pause_schedule_end_date.isoformat()
            )
    return next_pattern


def _resume_daily_llm_budget_for_agent(
    agent: dict[str, Any],
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
) -> int:
    return int(req_body.daily_llm_budget or agent.get("daily_llm_budget") or 8)


def _resume_paused_agent_preview(
    agents: list[dict[str, Any]],
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    *,
    auto_pause_after: datetime | None = None,
    auto_pause_schedule_end_date: date | None = None,
) -> list[dict[str, Any]]:
    return [
        {
            "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
            "agent_key": agent["agent_key"],
            "user_id": int(agent["user_id"]),
            "age_group": agent["age_group"],
            "gender": agent["gender"],
            "daily_llm_budget": _resume_daily_llm_budget_for_agent(agent, req_body),
            "activity_pattern": _resume_activity_pattern_for_agent(
                agent,
                req_body,
                auto_pause_after=auto_pause_after,
                auto_pause_schedule_end_date=auto_pause_schedule_end_date,
            ),
        }
        for agent in agents
    ]


async def replace_reader_daily_schedule_windows(
    db: AsyncSession,
    *,
    ai_reader_agent_id: int,
    schedule_date: date,
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow],
    replace_running: bool = False,
) -> dict[str, int]:
    if replace_running:
        await db.execute(
            text("""
                update tb_ai_reader_daily_schedule
                   set status = 'done',
                       locked_by = null,
                       locked_at = null,
                       error_message = 'replaced by admin schedule adjustment',
                       updated_date = current_timestamp
                 where ai_reader_agent_id = :ai_reader_agent_id
                   and schedule_date = :schedule_date
                   and status = 'running'
            """),
            {
                "ai_reader_agent_id": ai_reader_agent_id,
                "schedule_date": schedule_date,
            },
        )

    retire_result = await db.execute(
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'done',
                   locked_by = null,
                   locked_at = null,
                   error_message = 'retired by admin schedule adjustment',
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
               and schedule_date = :schedule_date
               and status = 'ready'
               and used_session_count > 0
        """),
        {
            "ai_reader_agent_id": ai_reader_agent_id,
            "schedule_date": schedule_date,
        },
    )

    delete_result = await db.execute(
        text("""
            delete from tb_ai_reader_daily_schedule
             where ai_reader_agent_id = :ai_reader_agent_id
               and schedule_date = :schedule_date
               and status in ('ready', 'done')
               and used_session_count = 0
        """),
        {
            "ai_reader_agent_id": ai_reader_agent_id,
            "schedule_date": schedule_date,
        },
    )
    upserted_count = await reader_agent_session_service.upsert_reader_daily_schedule_windows(
        db,
        windows,
    )
    return {
        "retired_count": int(getattr(retire_result, "rowcount", 0) or 0),
        "deleted_count": int(getattr(delete_result, "rowcount", 0) or 0),
        "upserted_count": upserted_count,
    }


async def replace_reader_daily_schedule_windows_bulk(
    db: AsyncSession,
    *,
    ai_reader_agent_ids: list[int],
    schedule_date: date,
    windows: list[reader_agent_session_service.ReaderDailyScheduleWindow],
) -> dict[str, int]:
    if not ai_reader_agent_ids:
        return {"retired_count": 0, "deleted_count": 0, "upserted_count": 0}

    retire_stmt = (
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'done',
                   locked_by = null,
                   locked_at = null,
                   error_message = 'retired by admin schedule adjustment',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and schedule_date = :schedule_date
               and status = 'ready'
               and used_session_count > 0
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    retire_result = await db.execute(
        retire_stmt,
        {
            "ai_reader_agent_ids": ai_reader_agent_ids,
            "schedule_date": schedule_date,
        },
    )

    delete_stmt = (
        text("""
            delete from tb_ai_reader_daily_schedule
             where ai_reader_agent_id in :ai_reader_agent_ids
               and schedule_date = :schedule_date
               and status in ('ready', 'done')
               and used_session_count = 0
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    delete_result = await db.execute(
        delete_stmt,
        {
            "ai_reader_agent_ids": ai_reader_agent_ids,
            "schedule_date": schedule_date,
        },
    )
    upserted_count = await reader_agent_session_service.upsert_reader_daily_schedule_windows(
        db,
        windows,
    )
    return {
        "retired_count": int(getattr(retire_result, "rowcount", 0) or 0),
        "deleted_count": int(getattr(delete_result, "rowcount", 0) or 0),
        "upserted_count": upserted_count,
    }


async def pause_all_ai_reader_agents(
    *,
    db: AsyncSession,
) -> dict[str, int]:
    active_result = await db.execute(
        text("""
            select ai_reader_agent_id
              from tb_ai_reader_agent
             where status in ('active', 'paused')
             order by ai_reader_agent_id asc
             for update
        """)
    )
    ai_reader_agent_ids = [
        int(row["ai_reader_agent_id"])
        for row in active_result.mappings().all()
    ]
    if not ai_reader_agent_ids:
        await db.commit()
        return {
            "paused_agent_count": 0,
            "retired_schedule_count": 0,
            "cancelled_action_count": 0,
        }

    update_agent_stmt = (
        text("""
            update tb_ai_reader_agent
               set status = 'paused',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status = 'active'
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    update_agent_result = await db.execute(
        update_agent_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    retire_schedule_stmt = (
        text("""
            update tb_ai_reader_daily_schedule
               set status = 'done',
                   locked_by = null,
                   locked_at = null,
                   error_message = 'paused by admin bulk pause',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status in ('ready', 'running')
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    retire_schedule_result = await db.execute(
        retire_schedule_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    cancel_action_stmt = (
        text("""
            update tb_ai_reader_action_queue
               set status = 'failed',
                   active_scope_key = null,
                   locked_by = null,
                   locked_at = null,
                   error_message = 'cancelled by admin bulk pause',
                   updated_date = current_timestamp
             where ai_reader_agent_id in :ai_reader_agent_ids
               and status in ('queued', 'running')
        """)
        .bindparams(bindparam("ai_reader_agent_ids", expanding=True))
    )
    cancel_action_result = await db.execute(
        cancel_action_stmt,
        {"ai_reader_agent_ids": ai_reader_agent_ids},
    )

    await db.commit()
    return {
        "paused_agent_count": int(getattr(update_agent_result, "rowcount", 0) or 0),
        "retired_schedule_count": int(getattr(retire_schedule_result, "rowcount", 0) or 0),
        "cancelled_action_count": int(getattr(cancel_action_result, "rowcount", 0) or 0),
    }


async def resume_paused_ai_reader_agents(
    *,
    req_body: admin_schema.PostAiReaderResumePausedReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(req_body.schedule_date)
    schedule_dates = _schedule_dates_for_duration(
        target_date,
        req_body.schedule_duration_days,
    )
    schedule_end_date = schedule_dates[-1]
    allowed_domains = _allowed_ai_reader_account_domains()
    if not allowed_domains:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="AI reader account allowed domains are not configured.",
        )
    count_result = await db.execute(
        text("""
            select count(*) as available_agent_count
              from tb_ai_reader_agent a
              join tb_user u on u.user_id = a.user_id
             where a.status = 'paused'
               and u.use_yn = 'Y'
               and lower(substring_index(u.email, '@', -1)) in :allowed_domains
               and not exists (
                       select 1
                         from tb_user_social us
                        where us.user_id = u.user_id
                   )
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        {"allowed_domains": allowed_domains},
    )
    available_agent_count = int(count_result.scalar() or 0)

    select_sql = """
        select
            a.ai_reader_agent_id,
            a.agent_key,
            a.user_id,
            a.age_group,
            a.gender,
            a.activity_pattern_json,
            a.daily_llm_budget
          from tb_ai_reader_agent a
          join tb_user u on u.user_id = a.user_id
         where a.status = 'paused'
           and u.use_yn = 'Y'
           and lower(substring_index(u.email, '@', -1)) in :allowed_domains
           and not exists (
                   select 1
                     from tb_user_social us
                    where us.user_id = u.user_id
               )
         order by a.updated_date desc, a.ai_reader_agent_id asc
         limit :limit
    """
    if req_body.apply:
        select_sql += " for update"
    paused_result = await db.execute(
        text(select_sql).bindparams(bindparam("allowed_domains", expanding=True)),
        {"allowed_domains": allowed_domains, "limit": req_body.agent_count},
    )
    agents = [dict(row) for row in paused_result.mappings().all()]
    schedule_now = _now_in_kst()
    requested_immediate_schedule_start_at = _parse_immediate_schedule_start_at(
        req_body.immediate_schedule_start_at
    )
    immediate_batches = _build_immediate_schedule_batches(
        agent_count=len(agents),
        schedule_date=target_date,
        start_immediately=req_body.start_immediately,
        batch_size=req_body.immediate_batch_size,
        batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        now=schedule_now,
        immediate_schedule_start_at=requested_immediate_schedule_start_at,
    )
    immediate_schedule_preview = _immediate_schedule_preview_payload(
        immediate_batches
    )
    immediate_schedule_start_at = (
        immediate_schedule_preview[0]["active_start_at"]
        if immediate_schedule_preview
        else None
    )
    auto_pause_after = _operation_auto_pause_after(
        schedule_end_date=schedule_end_date,
        immediate_batches=immediate_batches,
    )
    agent_fingerprints = _resume_paused_agent_fingerprints(agents)
    dry_run_token = _expected_resume_paused_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )
    preview = _resume_paused_agent_preview(
        agents,
        req_body,
        auto_pause_after=auto_pause_after,
        auto_pause_schedule_end_date=schedule_end_date,
    )

    if not req_body.apply:
        return {
            "applied": False,
            "schedule_date": target_date.isoformat(),
            "schedule_duration_days": req_body.schedule_duration_days,
            "schedule_end_date": schedule_end_date.isoformat(),
            "requested_count": req_body.agent_count,
            "available_agent_count": available_agent_count,
            "missing_agent_count": max(0, req_body.agent_count - available_agent_count),
            "dry_run_token": dry_run_token,
            "preview": preview,
            "immediate_schedule_preview": immediate_schedule_preview,
            "immediate_schedule_start_at": immediate_schedule_start_at,
        }

    if len(agents) < req_body.agent_count:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=(
                "paused AI reader resume requires "
                f"{req_body.agent_count} paused agents, found {len(agents)}."
            ),
        )
    _assert_matching_resume_paused_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )

    ai_reader_agent_ids = [int(agent["ai_reader_agent_id"]) for agent in agents]
    update_agent_stmt = text("""
            update tb_ai_reader_agent
               set status = 'active',
                   activity_pattern_json = :activity_pattern_json,
                   daily_llm_budget = :daily_llm_budget,
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
               and status = 'paused'
        """)
    update_agent_result = await db.execute(
        update_agent_stmt,
        [
            {
                "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
                "activity_pattern_json": json.dumps(
                    _resume_activity_pattern_for_agent(
                        agent,
                        req_body,
                        auto_pause_after=auto_pause_after,
                        auto_pause_schedule_end_date=schedule_end_date,
                    ),
                    ensure_ascii=False,
                ),
                "daily_llm_budget": _resume_daily_llm_budget_for_agent(agent, req_body),
            }
            for agent in agents
        ],
    )

    replace_result = {
        "retired_count": 0,
        "deleted_count": 0,
        "upserted_count": 0,
    }
    for schedule_date in schedule_dates:
        all_windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
        for agent in agents:
            all_windows.extend(
                reader_agent_session_service.build_reader_daily_schedule_windows(
                    ai_reader_agent_id=int(agent["ai_reader_agent_id"]),
                    schedule_date=schedule_date,
                    activity_pattern=_resume_activity_pattern_for_agent(
                        agent,
                        req_body,
                        auto_pause_after=auto_pause_after,
                        auto_pause_schedule_end_date=schedule_end_date,
                    ),
                )
            )
        if schedule_date == target_date:
            all_windows.extend(
                _build_immediate_reader_schedule_windows(
                    ai_reader_agent_ids=ai_reader_agent_ids,
                    schedule_date=schedule_date,
                    start_immediately=req_body.start_immediately,
                    batch_size=req_body.immediate_batch_size,
                    batch_interval_minutes=req_body.immediate_batch_interval_minutes,
                    now=schedule_now,
                    immediate_schedule_start_at=requested_immediate_schedule_start_at,
                )
            )
        current_replace_result = await replace_reader_daily_schedule_windows_bulk(
            db,
            ai_reader_agent_ids=ai_reader_agent_ids,
            schedule_date=schedule_date,
            windows=all_windows,
        )
        replace_result["retired_count"] += current_replace_result["retired_count"]
        replace_result["deleted_count"] += current_replace_result["deleted_count"]
        replace_result["upserted_count"] += current_replace_result["upserted_count"]

    await db.commit()
    return {
        "applied": True,
        "schedule_date": target_date.isoformat(),
        "schedule_duration_days": req_body.schedule_duration_days,
        "schedule_end_date": schedule_end_date.isoformat(),
        "requested_count": req_body.agent_count,
        "available_agent_count": available_agent_count,
        "reactivated_agent_count": int(getattr(update_agent_result, "rowcount", 0) or 0),
        "retired_schedule_count": replace_result["retired_count"],
        "deleted_schedule_count": replace_result["deleted_count"],
        "schedule_count": replace_result["upserted_count"],
        "preview": preview,
        "immediate_schedule_preview": immediate_schedule_preview,
        "immediate_schedule_start_at": immediate_schedule_start_at,
    }


async def refresh_active_ai_reader_schedules(
    *,
    req_body: admin_schema.PostAiReaderRefreshSchedulesReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(req_body.schedule_date)
    schedule_dates = _schedule_dates_for_duration(
        target_date,
        req_body.schedule_duration_days,
    )
    schedule_end_date = schedule_dates[-1]
    schedule_now = _now_in_kst()
    allowed_domains = _allowed_ai_reader_account_domains()
    if not allowed_domains:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="AI reader account allowed domains are not configured.",
        )

    idle_active_filter = """
        a.status = 'active'
        and u.use_yn = 'Y'
        and lower(substring_index(u.email, '@', -1)) in :allowed_domains
        and not exists (
                select 1
                  from tb_user_social us
                 where us.user_id = u.user_id
            )
        and not exists (
                select 1
                 from tb_ai_reader_daily_schedule s
                 where s.ai_reader_agent_id = a.ai_reader_agent_id
                   and s.status in ('ready', 'running')
                   and s.active_end_at > current_timestamp
            )
    """
    query_params = {
        "allowed_domains": allowed_domains,
    }
    count_result = await db.execute(
        text(f"""
            select count(*) as available_agent_count
              from tb_ai_reader_agent a
              join tb_user u on u.user_id = a.user_id
             where {idle_active_filter}
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        query_params,
    )
    available_agent_count = int(count_result.scalar() or 0)

    select_sql = f"""
        select
            a.ai_reader_agent_id,
            a.agent_key,
            a.user_id,
            a.age_group,
            a.gender,
            a.activity_pattern_json,
            a.daily_llm_budget
          from tb_ai_reader_agent a
          join tb_user u on u.user_id = a.user_id
         where {idle_active_filter}
         order by a.updated_date desc, a.ai_reader_agent_id asc
         limit :limit
    """
    if req_body.apply:
        select_sql += " for update"
    active_result = await db.execute(
        text(select_sql).bindparams(bindparam("allowed_domains", expanding=True)),
        {**query_params, "limit": req_body.agent_count},
    )
    agents = [dict(row) for row in active_result.mappings().all()]

    requested_immediate_schedule_start_at = _parse_immediate_schedule_start_at(
        req_body.immediate_schedule_start_at
    )
    immediate_batches = _build_immediate_schedule_batches(
        agent_count=len(agents),
        schedule_date=target_date,
        start_immediately=req_body.start_immediately,
        batch_size=req_body.immediate_batch_size,
        batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        now=schedule_now,
        immediate_schedule_start_at=requested_immediate_schedule_start_at,
    )
    immediate_schedule_preview = _immediate_schedule_preview_payload(
        immediate_batches
    )
    immediate_schedule_start_at = (
        immediate_schedule_preview[0]["active_start_at"]
        if immediate_schedule_preview
        else None
    )
    auto_pause_after = _operation_auto_pause_after(
        schedule_end_date=schedule_end_date,
        immediate_batches=immediate_batches,
    )
    agent_fingerprints = _resume_paused_agent_fingerprints(agents)
    dry_run_token = _expected_refresh_schedules_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )
    preview = _resume_paused_agent_preview(
        agents,
        req_body,
        auto_pause_after=auto_pause_after,
        auto_pause_schedule_end_date=schedule_end_date,
    )

    if not req_body.apply:
        return {
            "applied": False,
            "schedule_date": target_date.isoformat(),
            "schedule_duration_days": req_body.schedule_duration_days,
            "schedule_end_date": schedule_end_date.isoformat(),
            "requested_count": req_body.agent_count,
            "available_agent_count": available_agent_count,
            "missing_agent_count": max(0, req_body.agent_count - available_agent_count),
            "dry_run_token": dry_run_token,
            "preview": preview,
            "immediate_schedule_preview": immediate_schedule_preview,
            "immediate_schedule_start_at": immediate_schedule_start_at,
        }

    if len(agents) < req_body.agent_count:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=(
                "active AI reader schedule refresh requires "
                f"{req_body.agent_count} idle active agents, found {len(agents)}."
            ),
        )
    _assert_matching_refresh_schedules_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )

    ai_reader_agent_ids = [int(agent["ai_reader_agent_id"]) for agent in agents]
    update_agent_stmt = text("""
            update tb_ai_reader_agent
               set status = 'active',
                   activity_pattern_json = :activity_pattern_json,
                   daily_llm_budget = :daily_llm_budget,
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
               and status = 'active'
        """)
    update_agent_result = await db.execute(
        update_agent_stmt,
        [
            {
                "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
                "activity_pattern_json": json.dumps(
                    _resume_activity_pattern_for_agent(
                        agent,
                        req_body,
                        auto_pause_after=auto_pause_after,
                        auto_pause_schedule_end_date=schedule_end_date,
                    ),
                    ensure_ascii=False,
                ),
                "daily_llm_budget": _resume_daily_llm_budget_for_agent(agent, req_body),
            }
            for agent in agents
        ],
    )

    replace_result = {
        "retired_count": 0,
        "deleted_count": 0,
        "upserted_count": 0,
    }
    for schedule_date in schedule_dates:
        all_windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
        for agent in agents:
            all_windows.extend(
                reader_agent_session_service.build_reader_daily_schedule_windows(
                    ai_reader_agent_id=int(agent["ai_reader_agent_id"]),
                    schedule_date=schedule_date,
                    activity_pattern=_resume_activity_pattern_for_agent(
                        agent,
                        req_body,
                        auto_pause_after=auto_pause_after,
                        auto_pause_schedule_end_date=schedule_end_date,
                    ),
                )
            )
        if schedule_date == target_date:
            all_windows.extend(
                _build_immediate_reader_schedule_windows(
                    ai_reader_agent_ids=ai_reader_agent_ids,
                    schedule_date=schedule_date,
                    start_immediately=req_body.start_immediately,
                    batch_size=req_body.immediate_batch_size,
                    batch_interval_minutes=req_body.immediate_batch_interval_minutes,
                    now=schedule_now,
                    immediate_schedule_start_at=requested_immediate_schedule_start_at,
                )
            )
        current_replace_result = await replace_reader_daily_schedule_windows_bulk(
            db,
            ai_reader_agent_ids=ai_reader_agent_ids,
            schedule_date=schedule_date,
            windows=all_windows,
        )
        replace_result["retired_count"] += current_replace_result["retired_count"]
        replace_result["deleted_count"] += current_replace_result["deleted_count"]
        replace_result["upserted_count"] += current_replace_result["upserted_count"]

    await db.commit()
    return {
        "applied": True,
        "schedule_date": target_date.isoformat(),
        "schedule_duration_days": req_body.schedule_duration_days,
        "schedule_end_date": schedule_end_date.isoformat(),
        "requested_count": req_body.agent_count,
        "available_agent_count": available_agent_count,
        "refreshed_agent_count": int(getattr(update_agent_result, "rowcount", 0) or 0),
        "retired_schedule_count": replace_result["retired_count"],
        "deleted_schedule_count": replace_result["deleted_count"],
        "schedule_count": replace_result["upserted_count"],
        "preview": preview,
        "immediate_schedule_preview": immediate_schedule_preview,
        "immediate_schedule_start_at": immediate_schedule_start_at,
    }


async def restart_ai_reader_agents(
    *,
    req_body: admin_schema.PostAiReaderRestartReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(req_body.schedule_date)
    schedule_dates = _schedule_dates_for_duration(
        target_date,
        req_body.schedule_duration_days,
    )
    schedule_end_date = schedule_dates[-1]
    schedule_now = _now_in_kst()
    allowed_domains = _allowed_ai_reader_account_domains()
    if not allowed_domains:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="AI reader account allowed domains are not configured.",
        )

    eligible_filter = """
        a.status in ('active', 'paused')
        and u.use_yn = 'Y'
        and lower(substring_index(u.email, '@', -1)) in :allowed_domains
        and not exists (
                select 1
                  from tb_user_social us
                 where us.user_id = u.user_id
            )
    """
    if req_body.apply:
        all_agent_result = await db.execute(
            text("""
                select ai_reader_agent_id
                  from tb_ai_reader_agent
                 where status in ('active', 'paused')
                 order by ai_reader_agent_id asc
                 for update
            """)
        )
        all_ai_reader_agent_ids = [
            int(row["ai_reader_agent_id"])
            for row in all_agent_result.mappings().all()
        ]
    else:
        all_ai_reader_agent_ids = []

    query_params = {"allowed_domains": allowed_domains}
    count_result = await db.execute(
        text(f"""
            select count(*) as available_agent_count
              from tb_ai_reader_agent a
              join tb_user u on u.user_id = a.user_id
             where {eligible_filter}
        """).bindparams(bindparam("allowed_domains", expanding=True)),
        query_params,
    )
    available_agent_count = int(count_result.scalar() or 0)

    select_sql = f"""
        select
            a.ai_reader_agent_id,
            a.agent_key,
            a.user_id,
            a.age_group,
            a.gender,
            a.activity_pattern_json,
            a.daily_llm_budget
          from tb_ai_reader_agent a
          join tb_user u on u.user_id = a.user_id
         where {eligible_filter}
         order by case when a.status = 'active' then 0 else 1 end,
                  a.updated_date desc,
                  a.ai_reader_agent_id asc
         limit :limit
    """
    agents_result = await db.execute(
        text(select_sql).bindparams(bindparam("allowed_domains", expanding=True)),
        {**query_params, "limit": req_body.agent_count},
    )
    agents = [dict(row) for row in agents_result.mappings().all()]

    requested_immediate_schedule_start_at = _parse_immediate_schedule_start_at(
        req_body.immediate_schedule_start_at
    )
    immediate_batches = _build_immediate_schedule_batches(
        agent_count=len(agents),
        schedule_date=target_date,
        start_immediately=req_body.start_immediately,
        batch_size=req_body.immediate_batch_size,
        batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        now=schedule_now,
        immediate_schedule_start_at=requested_immediate_schedule_start_at,
    )
    immediate_schedule_preview = _immediate_schedule_preview_payload(
        immediate_batches
    )
    immediate_schedule_start_at = (
        immediate_schedule_preview[0]["active_start_at"]
        if immediate_schedule_preview
        else None
    )
    auto_pause_after = _operation_auto_pause_after(
        schedule_end_date=schedule_end_date,
        immediate_batches=immediate_batches,
    )
    agent_fingerprints = _resume_paused_agent_fingerprints(agents)
    dry_run_token = _expected_restart_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )
    preview = _resume_paused_agent_preview(
        agents,
        req_body,
        auto_pause_after=auto_pause_after,
        auto_pause_schedule_end_date=schedule_end_date,
    )

    if not req_body.apply:
        return {
            "applied": False,
            "schedule_date": target_date.isoformat(),
            "schedule_duration_days": req_body.schedule_duration_days,
            "schedule_end_date": schedule_end_date.isoformat(),
            "requested_count": req_body.agent_count,
            "available_agent_count": available_agent_count,
            "missing_agent_count": max(0, req_body.agent_count - available_agent_count),
            "dry_run_token": dry_run_token,
            "preview": preview,
            "immediate_schedule_preview": immediate_schedule_preview,
            "immediate_schedule_start_at": immediate_schedule_start_at,
        }

    if len(agents) < req_body.agent_count:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message=(
                "AI reader restart requires "
                f"{req_body.agent_count} eligible agents, found {len(agents)}."
            ),
        )
    _assert_matching_restart_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=immediate_schedule_start_at,
        agent_fingerprints=agent_fingerprints,
    )

    ai_reader_agent_ids = [int(agent["ai_reader_agent_id"]) for agent in agents]
    update_agent_stmt = text("""
            update tb_ai_reader_agent
               set status = 'active',
                   activity_pattern_json = :activity_pattern_json,
                   daily_llm_budget = :daily_llm_budget,
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
               and status in ('active', 'paused')
        """)
    update_agent_result = await db.execute(
        update_agent_stmt,
        [
            {
                "ai_reader_agent_id": int(agent["ai_reader_agent_id"]),
                "activity_pattern_json": json.dumps(
                    _resume_activity_pattern_for_agent(
                        agent,
                        req_body,
                        auto_pause_after=auto_pause_after,
                        auto_pause_schedule_end_date=schedule_end_date,
                    ),
                    ensure_ascii=False,
                ),
                "daily_llm_budget": _resume_daily_llm_budget_for_agent(agent, req_body),
            }
            for agent in agents
        ],
    )

    pause_result = await db.execute(
        (
            text("""
                update tb_ai_reader_agent
                   set status = 'paused',
                       updated_date = current_timestamp
                 where status = 'active'
                   and ai_reader_agent_id in :all_ai_reader_agent_ids
                   and ai_reader_agent_id not in :ai_reader_agent_ids
            """)
            .bindparams(
                bindparam("all_ai_reader_agent_ids", expanding=True),
                bindparam("ai_reader_agent_ids", expanding=True),
            )
        ),
        {
            "all_ai_reader_agent_ids": all_ai_reader_agent_ids,
            "ai_reader_agent_ids": ai_reader_agent_ids,
        },
    )

    retire_schedule_result = await db.execute(
        (
            text("""
                update tb_ai_reader_daily_schedule
                   set status = 'done',
                       locked_by = null,
                       locked_at = null,
                       error_message = 'restarted by admin clean restart',
                       updated_date = current_timestamp
                 where ai_reader_agent_id in :all_ai_reader_agent_ids
                   and status in ('ready', 'running')
            """)
            .bindparams(bindparam("all_ai_reader_agent_ids", expanding=True))
        ),
        {"all_ai_reader_agent_ids": all_ai_reader_agent_ids},
    )

    cancel_action_result = await db.execute(
        (
            text("""
                update tb_ai_reader_action_queue
                   set status = 'failed',
                       active_scope_key = null,
                       locked_by = null,
                       locked_at = null,
                       error_message = 'cancelled by admin clean restart',
                       updated_date = current_timestamp
                 where ai_reader_agent_id in :all_ai_reader_agent_ids
                   and status in ('queued', 'running')
            """)
            .bindparams(bindparam("all_ai_reader_agent_ids", expanding=True))
        ),
        {"all_ai_reader_agent_ids": all_ai_reader_agent_ids},
    )

    replace_result = {
        "retired_count": 0,
        "deleted_count": 0,
        "upserted_count": 0,
    }
    for schedule_date in schedule_dates:
        all_windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
        for agent in agents:
            all_windows.extend(
                reader_agent_session_service.build_reader_daily_schedule_windows(
                    ai_reader_agent_id=int(agent["ai_reader_agent_id"]),
                    schedule_date=schedule_date,
                    activity_pattern=_resume_activity_pattern_for_agent(
                        agent,
                        req_body,
                        auto_pause_after=auto_pause_after,
                        auto_pause_schedule_end_date=schedule_end_date,
                    ),
                )
            )
        if schedule_date == target_date:
            all_windows.extend(
                _build_immediate_reader_schedule_windows(
                    ai_reader_agent_ids=ai_reader_agent_ids,
                    schedule_date=schedule_date,
                    start_immediately=req_body.start_immediately,
                    batch_size=req_body.immediate_batch_size,
                    batch_interval_minutes=req_body.immediate_batch_interval_minutes,
                    now=schedule_now,
                    immediate_schedule_start_at=requested_immediate_schedule_start_at,
                )
            )
        current_replace_result = await replace_reader_daily_schedule_windows_bulk(
            db,
            ai_reader_agent_ids=ai_reader_agent_ids,
            schedule_date=schedule_date,
            windows=all_windows,
        )
        replace_result["retired_count"] += current_replace_result["retired_count"]
        replace_result["deleted_count"] += current_replace_result["deleted_count"]
        replace_result["upserted_count"] += current_replace_result["upserted_count"]

    await db.commit()
    return {
        "applied": True,
        "schedule_date": target_date.isoformat(),
        "schedule_duration_days": req_body.schedule_duration_days,
        "schedule_end_date": schedule_end_date.isoformat(),
        "requested_count": req_body.agent_count,
        "available_agent_count": available_agent_count,
        "restarted_agent_count": int(getattr(update_agent_result, "rowcount", 0) or 0),
        "paused_agent_count": int(getattr(pause_result, "rowcount", 0) or 0),
        "retired_schedule_count": int(getattr(retire_schedule_result, "rowcount", 0) or 0) + replace_result["retired_count"],
        "deleted_schedule_count": replace_result["deleted_count"],
        "cancelled_action_count": int(getattr(cancel_action_result, "rowcount", 0) or 0),
        "schedule_count": replace_result["upserted_count"],
        "preview": preview,
        "immediate_schedule_preview": immediate_schedule_preview,
        "immediate_schedule_start_at": immediate_schedule_start_at,
    }


async def _assert_ai_reader_identity_available(
    db: AsyncSession,
    *,
    expected_pairs: list[dict[str, Any]],
) -> None:
    if not expected_pairs:
        return

    expected_user_by_key = {
        str(pair["agent_key"]): int(pair["user_id"]) for pair in expected_pairs
    }
    expected_key_by_user = {
        int(pair["user_id"]): str(pair["agent_key"]) for pair in expected_pairs
    }
    stmt = (
        text("""
            select
                agent_key,
                user_id
              from tb_ai_reader_agent
             where agent_key in :agent_keys
                or user_id in :user_ids
        """)
        .bindparams(
            bindparam("agent_keys", expanding=True),
            bindparam("user_ids", expanding=True),
        )
    )
    result = await db.execute(
        stmt,
        {
            "agent_keys": list(expected_user_by_key.keys()),
            "user_ids": list(expected_key_by_user.keys()),
        },
    )
    conflicts: list[str] = []
    for row in result.mappings().all():
        agent_key = str(row.get("agent_key") or "")
        user_id = int(row.get("user_id") or 0)
        if expected_user_by_key.get(agent_key, user_id) != user_id:
            conflicts.append(f"{agent_key}:{user_id}")
            continue
        if expected_key_by_user.get(user_id, agent_key) != agent_key:
            conflicts.append(f"{agent_key}:{user_id}")

    if conflicts:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=(
                "AI reader agent identity conflict: "
                + ", ".join(sorted(conflicts)[:5])
            ),
        )


def _assert_ai_reader_agent_rows_match_expected(
    agents: list[dict[str, Any]],
    *,
    expected_pairs: list[dict[str, Any]],
) -> None:
    expected_user_by_key = {
        str(pair["agent_key"]): int(pair["user_id"]) for pair in expected_pairs
    }
    actual_user_by_key = {
        str(row.get("agent_key") or ""): int(row.get("user_id") or 0)
        for row in agents
    }
    mismatches = [
        f"{agent_key}:{actual_user_by_key.get(agent_key, 'missing')}"
        for agent_key, expected_user_id in expected_user_by_key.items()
        if actual_user_by_key.get(agent_key) != expected_user_id
    ]
    extra_keys = sorted(set(actual_user_by_key) - set(expected_user_by_key))
    if mismatches or extra_keys:
        raise CustomResponseException(
            status_code=status.HTTP_409_CONFLICT,
            message=(
                "AI reader agent post-write mismatch: "
                + ", ".join((mismatches + extra_keys)[:5])
            ),
        )


async def list_ai_reader_agents(
    *,
    schedule_date: str | None,
    status_filter: str,
    page: int,
    count_per_page: int,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(schedule_date)
    page = max(1, page)
    count_per_page = min(max(1, count_per_page), 200)
    offset = (page - 1) * count_per_page

    where_clauses = ["1 = 1"]
    params: dict[str, Any] = {
        "schedule_date": target_date,
        "limit": count_per_page,
        "offset": offset,
    }
    if status_filter and status_filter != "all":
        where_clauses.append("a.status = :status")
        params["status"] = status_filter
    where_sql = " and ".join(where_clauses)

    count_result = await db.execute(
        text(f"""
            select count(*) as total_count
              from tb_ai_reader_agent a
             where {where_sql}
        """),
        params,
    )
    total_count = int((count_result.mappings().one_or_none() or {}).get("total_count") or 0)

    agent_result = await db.execute(
        text(f"""
            select
                a.ai_reader_agent_id,
                a.agent_key,
                a.user_id,
                u.email,
                a.age_group,
                a.gender,
                a.activity_pattern_json,
                a.daily_llm_budget,
                a.status,
                coalesce(sum(s.session_budget), 0) as schedule_session_budget,
                coalesce(sum(s.used_session_count), 0) as used_session_count,
                count(s.ai_reader_schedule_id) as schedule_window_count,
                min(s.active_start_at) as first_active_start_at,
                max(s.active_end_at) as last_active_end_at
              from tb_ai_reader_agent a
              left join tb_user u
                on u.user_id = a.user_id
              left join tb_ai_reader_daily_schedule s
                on s.ai_reader_agent_id = a.ai_reader_agent_id
               and s.schedule_date = :schedule_date
             where {where_sql}
             group by
                a.ai_reader_agent_id,
                a.agent_key,
                a.user_id,
                u.email,
                a.age_group,
                a.gender,
                a.activity_pattern_json,
                a.daily_llm_budget,
                a.status
             order by a.agent_key asc
             limit :limit offset :offset
        """),
        params,
    )
    rows = [dict(row) for row in agent_result.mappings().all()]
    agent_ids = [row["ai_reader_agent_id"] for row in rows]
    schedule_by_agent: dict[int, list[dict[str, Any]]] = {agent_id: [] for agent_id in agent_ids}
    if agent_ids:
        schedule_stmt = (
            text("""
                select
                    ai_reader_agent_id,
                    active_start_at,
                    active_end_at,
                    session_budget,
                    used_session_count,
                    status
                  from tb_ai_reader_daily_schedule
                 where schedule_date = :schedule_date
                   and ai_reader_agent_id in :agent_ids
                 order by ai_reader_agent_id asc, active_start_at asc
            """)
            .bindparams(bindparam("agent_ids", expanding=True))
        )
        schedule_result = await db.execute(
            schedule_stmt,
            {
                "schedule_date": target_date,
                "agent_ids": agent_ids,
            },
        )
        for schedule_row in schedule_result.mappings().all():
            item = dict(schedule_row)
            agent_id = int(item.pop("ai_reader_agent_id"))
            schedule_by_agent.setdefault(agent_id, []).append(item)

    items = []
    for row in rows:
        activity_pattern = _parse_json_field(row.get("activity_pattern_json"), {})
        active_hours = activity_pattern.get("active_hours") if isinstance(activity_pattern, dict) else []
        daily_session_target = (
            activity_pattern.get("daily_session_target") if isinstance(activity_pattern, dict) else None
        )
        agent_id = int(row["ai_reader_agent_id"])
        items.append(
            {
                **row,
                "activity_pattern": activity_pattern,
                "active_hours": active_hours or [],
                "daily_session_target": daily_session_target,
                "schedules": schedule_by_agent.get(agent_id, []),
            }
        )

    return {
        "schedule_date": target_date.isoformat(),
        "total_count": total_count,
        "page": page,
        "count_per_page": count_per_page,
        "items": items,
    }


async def bootstrap_ai_reader_agents(
    *,
    req_body: admin_schema.PostAiReaderBootstrapReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    target_date = _parse_schedule_date(req_body.schedule_date)
    schedule_dates = _schedule_dates_for_duration(
        target_date,
        req_body.schedule_duration_days,
    )
    schedule_end_date = schedule_dates[-1]
    allowed_domains = _allowed_ai_reader_account_domains()
    if not allowed_domains:
        raise CustomResponseException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            message="AI reader account allowed domains are not configured.",
        )
    users = await _fetch_bootstrap_candidate_users(
        db,
        email_prefix=req_body.email_prefix,
        allowed_domains=allowed_domains,
        limit=req_body.agent_count,
    )
    initial_users = users[: req_body.agent_count]
    initial_seeds = reader_agent_persona_service.generate_reader_agent_seeds(
        count=len(initial_users),
        index_offset=req_body.agent_index_offset,
        age_group_ratios=req_body.age_group_ratios,
        gender_ratios=req_body.gender_ratios,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
    )
    initial_user_fingerprints = [
        {
            "user_id": int(user["user_id"]),
            "email": str(user.get("email") or ""),
            "agent_key": seed.agent_key,
        }
        for user, seed in zip(initial_users, initial_seeds, strict=True)
    ]
    schedule_now = _now_in_kst()
    requested_immediate_schedule_start_at = _parse_immediate_schedule_start_at(
        req_body.immediate_schedule_start_at
    )
    initial_immediate_batches = _build_immediate_schedule_batches(
        agent_count=len(initial_users),
        schedule_date=target_date,
        start_immediately=req_body.start_immediately,
        batch_size=req_body.immediate_batch_size,
        batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        now=schedule_now,
        immediate_schedule_start_at=requested_immediate_schedule_start_at,
    )
    initial_immediate_schedule_preview = _immediate_schedule_preview_payload(
        initial_immediate_batches
    )
    initial_immediate_schedule_start_at = (
        initial_immediate_schedule_preview[0]["active_start_at"]
        if initial_immediate_schedule_preview
        else None
    )
    initial_auto_pause_after = _operation_auto_pause_after(
        schedule_end_date=schedule_end_date,
        immediate_batches=initial_immediate_batches,
    )
    requested_time_blocks = _time_blocks_payload(req_body.time_blocks)
    dry_run_token = _expected_bootstrap_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=initial_immediate_schedule_start_at,
        user_fingerprints=initial_user_fingerprints,
    )
    preview = [
        {
            "user_id": user["user_id"],
            "email": user["email"],
            "agent_key": seed.agent_key,
            "age_group": seed.age_group,
            "gender": seed.gender,
            "activity_pattern": _activity_pattern_with_auto_pause_after(
                seed.activity_pattern_json,
                initial_auto_pause_after,
                schedule_end_date,
                requested_time_blocks,
            ),
        }
        for user, seed in zip(initial_users, initial_seeds, strict=True)
    ]
    if not req_body.apply:
        return {
            "applied": False,
            "schedule_date": target_date.isoformat(),
            "schedule_duration_days": req_body.schedule_duration_days,
            "schedule_end_date": schedule_end_date.isoformat(),
            "requested_count": req_body.agent_count,
            "available_user_count": len(users),
            "missing_user_count": max(0, req_body.agent_count - len(users)),
            "dry_run_token": dry_run_token,
            "preview": preview,
            "immediate_schedule_preview": initial_immediate_schedule_preview,
            "immediate_schedule_start_at": initial_immediate_schedule_start_at,
            "provisioned_user_count": 0,
        }

    _assert_matching_bootstrap_dry_run_token(
        req_body,
        schedule_date=target_date,
        immediate_schedule_start_at=initial_immediate_schedule_start_at,
        user_fingerprints=initial_user_fingerprints,
    )
    provisioned_user_count = 0
    if len(users) < req_body.agent_count and not req_body.allow_partial:
        if not req_body.auto_provision_missing_users:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=(
                    "AI reader bootstrap requires "
                    f"{req_body.agent_count} existing users for prefix {req_body.email_prefix}, "
                    f"found {len(users)}."
                ),
            )
        provisioned_user_count = await _provision_missing_ai_reader_users(
            db,
            email_prefix=req_body.email_prefix,
            missing_count=req_body.agent_count - len(users),
            allowed_domains=allowed_domains,
            profile_nickname_pool=req_body.profile_nickname_pool,
        )
        users = await _fetch_bootstrap_candidate_users(
            db,
            email_prefix=req_body.email_prefix,
            allowed_domains=allowed_domains,
            limit=req_body.agent_count,
        )
        if len(users) < req_body.agent_count:
            raise CustomResponseException(
                status_code=status.HTTP_400_BAD_REQUEST,
                message=(
                    "AI reader bootstrap auto-provision did not create enough users: "
                    f"required {req_body.agent_count}, found {len(users)}."
                ),
            )

    target_users = users[: req_body.agent_count]
    seeds = reader_agent_persona_service.generate_reader_agent_seeds(
        count=len(target_users),
        index_offset=req_body.agent_index_offset,
        age_group_ratios=req_body.age_group_ratios,
        gender_ratios=req_body.gender_ratios,
        active_hours=req_body.active_hours,
        daily_session_target=req_body.daily_session_target,
    )
    expected_pairs = [
        {"user_id": user["user_id"], "agent_key": seed.agent_key}
        for user, seed in zip(target_users, seeds, strict=True)
    ]
    immediate_batches = _build_immediate_schedule_batches(
        agent_count=len(target_users),
        schedule_date=target_date,
        start_immediately=req_body.start_immediately,
        batch_size=req_body.immediate_batch_size,
        batch_interval_minutes=req_body.immediate_batch_interval_minutes,
        now=schedule_now,
        immediate_schedule_start_at=requested_immediate_schedule_start_at,
    )
    immediate_schedule_preview = _immediate_schedule_preview_payload(
        immediate_batches
    )
    immediate_schedule_start_at = (
        immediate_schedule_preview[0]["active_start_at"]
        if immediate_schedule_preview
        else None
    )
    auto_pause_after = _operation_auto_pause_after(
        schedule_end_date=schedule_end_date,
        immediate_batches=immediate_batches,
    )
    await _assert_ai_reader_identity_available(
        db,
        expected_pairs=expected_pairs,
    )
    preview = [
        {
            "user_id": user["user_id"],
            "email": user["email"],
            "agent_key": seed.agent_key,
            "age_group": seed.age_group,
            "gender": seed.gender,
            "activity_pattern": _activity_pattern_with_auto_pause_after(
                seed.activity_pattern_json,
                auto_pause_after,
                schedule_end_date,
                requested_time_blocks,
            ),
        }
        for user, seed in zip(target_users, seeds, strict=True)
    ]

    if not target_users:
        return {
            "applied": True,
            "schedule_date": target_date.isoformat(),
            "schedule_duration_days": req_body.schedule_duration_days,
            "schedule_end_date": schedule_end_date.isoformat(),
            "requested_count": req_body.agent_count,
            "applied_count": 0,
            "schedule_count": 0,
            "preview": [],
            "immediate_schedule_preview": [],
            "immediate_schedule_start_at": None,
            "provisioned_user_count": provisioned_user_count,
        }

    await db.execute(
        text("""
            insert into tb_ai_reader_agent
                (
                    user_id,
                    agent_key,
                    age_group,
                    gender,
                    persona_json,
                    taste_memory_json,
                    activity_pattern_json,
                    status,
                    daily_llm_budget
                )
            values
                (
                    :user_id,
                    :agent_key,
                    :age_group,
                    :gender,
                    :persona_json,
                    :taste_memory_json,
                    :activity_pattern_json,
                    'active',
                    :daily_llm_budget
                )
            on duplicate key update
                age_group = values(age_group),
                gender = values(gender),
                persona_json = values(persona_json),
                taste_memory_json = values(taste_memory_json),
                activity_pattern_json = values(activity_pattern_json),
                status = 'active',
                daily_llm_budget = values(daily_llm_budget),
                updated_date = current_timestamp
        """),
        [
            {
                "user_id": user["user_id"],
                "agent_key": seed.agent_key,
                "age_group": seed.age_group,
                "gender": seed.gender,
                "persona_json": seed.persona_json,
                "taste_memory_json": seed.taste_memory_json,
                "activity_pattern_json": json.dumps(
                    _activity_pattern_with_auto_pause_after(
                        seed.activity_pattern_json,
                        auto_pause_after,
                        schedule_end_date,
                        requested_time_blocks,
                    ),
                    ensure_ascii=False,
                ),
                "daily_llm_budget": req_body.daily_llm_budget,
            }
            for user, seed in zip(target_users, seeds, strict=True)
        ],
    )

    agent_keys = [seed.agent_key for seed in seeds]
    agent_stmt = (
        text("""
            select
                ai_reader_agent_id,
                agent_key,
                user_id,
                activity_pattern_json
              from tb_ai_reader_agent
             where agent_key in :agent_keys
        """)
        .bindparams(bindparam("agent_keys", expanding=True))
    )
    agent_result = await db.execute(agent_stmt, {"agent_keys": agent_keys})
    agents = [dict(row) for row in agent_result.mappings().all()]
    _assert_ai_reader_agent_rows_match_expected(
        agents,
        expected_pairs=expected_pairs,
    )

    ai_reader_agent_ids = [int(agent["ai_reader_agent_id"]) for agent in agents]
    replace_result = {
        "retired_count": 0,
        "deleted_count": 0,
        "upserted_count": 0,
    }
    for schedule_date in schedule_dates:
        all_windows: list[reader_agent_session_service.ReaderDailyScheduleWindow] = []
        for agent in agents:
            all_windows.extend(
                reader_agent_session_service.build_reader_daily_schedule_windows(
                    ai_reader_agent_id=int(agent["ai_reader_agent_id"]),
                    schedule_date=schedule_date,
                    activity_pattern=agent["activity_pattern_json"],
                )
            )
        if schedule_date == target_date:
            all_windows.extend(
                _build_immediate_reader_schedule_windows(
                    ai_reader_agent_ids=ai_reader_agent_ids,
                    schedule_date=schedule_date,
                    start_immediately=req_body.start_immediately,
                    batch_size=req_body.immediate_batch_size,
                    batch_interval_minutes=req_body.immediate_batch_interval_minutes,
                    now=schedule_now,
                    immediate_schedule_start_at=requested_immediate_schedule_start_at,
                )
            )
        current_replace_result = await replace_reader_daily_schedule_windows_bulk(
            db,
            ai_reader_agent_ids=ai_reader_agent_ids,
            schedule_date=schedule_date,
            windows=all_windows,
        )
        replace_result["retired_count"] += current_replace_result["retired_count"]
        replace_result["deleted_count"] += current_replace_result["deleted_count"]
        replace_result["upserted_count"] += current_replace_result["upserted_count"]

    await db.commit()
    return {
        "applied": True,
        "schedule_date": target_date.isoformat(),
        "schedule_duration_days": req_body.schedule_duration_days,
        "schedule_end_date": schedule_end_date.isoformat(),
        "requested_count": req_body.agent_count,
        "available_user_count": len(users),
        "provisioned_user_count": provisioned_user_count,
        "applied_count": len(agents),
        "schedule_count": replace_result["upserted_count"],
        "preview": preview,
        "immediate_schedule_preview": immediate_schedule_preview,
        "immediate_schedule_start_at": immediate_schedule_start_at,
    }


async def update_ai_reader_agent_schedule(
    *,
    ai_reader_agent_id: int,
    req_body: admin_schema.PutAiReaderScheduleReqBody,
    db: AsyncSession,
) -> dict[str, Any]:
    if req_body.replace_running:
        raise CustomResponseException(
            status_code=status.HTTP_400_BAD_REQUEST,
            message="replace_running is not allowed for AI reader schedule updates.",
        )
    target_date = _parse_schedule_date(req_body.schedule_date)
    agent_result = await db.execute(
        text("""
            select
                ai_reader_agent_id,
                agent_key,
                user_id,
                age_group,
                gender,
                activity_pattern_json,
                daily_llm_budget,
                status
              from tb_ai_reader_agent
             where ai_reader_agent_id = :ai_reader_agent_id
             limit 1
        """),
        {"ai_reader_agent_id": ai_reader_agent_id},
    )
    agent = agent_result.mappings().one_or_none()
    if not agent:
        raise CustomResponseException(
            status_code=status.HTTP_404_NOT_FOUND,
            message="AI reader agent not found.",
        )

    current_pattern = _parse_json_field(agent.get("activity_pattern_json"), {})
    if not isinstance(current_pattern, dict):
        current_pattern = {}
    active_hours = list(req_body.active_hours)
    auto_pause_after = datetime.combine(
        target_date + timedelta(days=1),
        datetime.min.time(),
    )
    next_pattern = {
        **current_pattern,
        "active_hours": active_hours,
        "sleep_hours": _sleep_hours(active_hours),
        "daily_session_target": req_body.daily_session_target,
        "auto_pause_after": _format_schedule_datetime(auto_pause_after),
        "auto_pause_schedule_end_date": target_date.isoformat(),
    }
    requested_time_blocks = _time_blocks_payload(req_body.time_blocks)
    if requested_time_blocks is not None:
        next_pattern["time_blocks"] = requested_time_blocks
    else:
        next_pattern.pop("time_blocks", None)
    next_status = req_body.status or agent.get("status") or "active"
    next_daily_llm_budget = req_body.daily_llm_budget or int(agent.get("daily_llm_budget") or 8)

    await db.execute(
        text("""
            update tb_ai_reader_agent
               set activity_pattern_json = :activity_pattern_json,
                   daily_llm_budget = :daily_llm_budget,
                   status = :status,
                   updated_date = current_timestamp
             where ai_reader_agent_id = :ai_reader_agent_id
        """),
        {
            "activity_pattern_json": json.dumps(next_pattern, ensure_ascii=False),
            "daily_llm_budget": next_daily_llm_budget,
            "status": next_status,
            "ai_reader_agent_id": ai_reader_agent_id,
        },
    )

    windows = reader_agent_session_service.build_reader_daily_schedule_windows(
        ai_reader_agent_id=ai_reader_agent_id,
        schedule_date=target_date,
        activity_pattern=next_pattern,
    )
    replace_result = await replace_reader_daily_schedule_windows(
        db,
        ai_reader_agent_id=ai_reader_agent_id,
        schedule_date=target_date,
        windows=windows,
        replace_running=req_body.replace_running,
    )
    await db.commit()
    return {
        "schedule_date": target_date.isoformat(),
        "agent": {
            "ai_reader_agent_id": ai_reader_agent_id,
            "agent_key": agent.get("agent_key"),
            "user_id": agent.get("user_id"),
            "age_group": agent.get("age_group"),
            "gender": agent.get("gender"),
            "active_hours": active_hours,
            "daily_session_target": req_body.daily_session_target,
            "daily_llm_budget": next_daily_llm_budget,
            "status": next_status,
        },
        "schedule_count": len(windows),
        "deleted_schedule_count": replace_result["deleted_count"],
        "upserted_schedule_count": replace_result["upserted_count"],
        "schedules": _schedule_window_payload(windows),
    }
