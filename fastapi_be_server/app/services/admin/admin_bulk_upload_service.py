"""일괄 작품 업로드 서비스.

엑셀(xlsx) + 회차 zip → 계정 생성 + 작품 생성 + 회차 생성 + 예약공개.
"""

import io
import json
import logging
import secrets
import string
import tempfile
import zipfile
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pandas as pd
from bs4 import BeautifulSoup
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.services.common import comm_service

logger = logging.getLogger(__name__)

# ─── 요일 매핑 ────────────────────────────────────────────────
DAY_MAP = {
    "월": "MON", "화": "TUE", "수": "WED", "목": "THU",
    "금": "FRI", "토": "SAT", "일": "SUN",
}
DAY_INDEX = {"MON": 0, "TUE": 1, "WED": 2, "THU": 3, "FRI": 4, "SAT": 5, "SUN": 6}


# ─── 헬퍼 ─────────────────────────────────────────────────────

def _generate_password(length: int = 12) -> str:
    chars = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(chars) for _ in range(length))


def _parse_publish_days(raw: str) -> dict:
    """'월화수목금토일' → {"MON":"Y","TUE":"Y",...}"""
    result = {v: "N" for v in DAY_MAP.values()}
    for ch in raw.strip():
        eng = DAY_MAP.get(ch)
        if eng:
            result[eng] = "Y"
    return result


def _active_days_sorted(publish_days: dict) -> list[int]:
    """활성 요일의 weekday index 정렬 리스트."""
    return sorted(DAY_INDEX[k] for k, v in publish_days.items() if v == "Y")


def _next_publish_date(base: datetime, active_weekdays: list[int], offset: int) -> datetime:
    """base 기준으로 offset번째 활성 요일 날짜를 반환."""
    count = 0
    d = base
    while True:
        if d.weekday() in active_weekdays:
            if count == offset:
                return d
            count += 1
        d += timedelta(days=1)


def _txt_to_html(txt: str) -> str:
    """txt 본문을 간단한 HTML로 변환."""
    paragraphs = txt.split("\n")
    parts = []
    for p in paragraphs:
        stripped = p.strip()
        if stripped:
            parts.append(f"<p>{stripped}</p>")
        else:
            parts.append("<p><br/></p>")
    return "".join(parts)


# ─── 미리보기 ──────────────────────────────────────────────────

async def preview_bulk_upload(
    excel_bytes: bytes,
    zip_bytes: bytes | None,
    db: AsyncSession,
) -> dict:
    """엑셀 파싱 + zip 회차 수 카운트 → 미리보기 리스트."""
    df = pd.read_excel(io.BytesIO(excel_bytes), engine="openpyxl", dtype=str)
    df = df.fillna("")

    expected_cols = [
        "작가이메일", "작가닉네임", "작품제목", "1차장르", "2차장르", "태그",
        "연령등급", "독점여부", "계약여부", "공개여부", "시놉시스",
        "연재주기", "최초공개회차", "예약공개시작일",
    ]
    missing = [c for c in expected_cols if c not in df.columns]
    if missing:
        return {"error": f"누락 컬럼: {', '.join(missing)}", "results": []}

    # zip에서 폴더별 파일 수 카운트 + 표지 감지
    episode_counts: dict[str, int] = {}
    cover_exists: dict[str, bool] = {}
    if zip_bytes:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            for name in zf.namelist():
                if name.endswith("/") or name.startswith("__MACOSX"):
                    continue
                parts = Path(name).parts
                if len(parts) >= 2:
                    folder = parts[0]
                    fname_lower = parts[-1].lower()
                    if fname_lower.endswith(".txt"):
                        episode_counts[folder] = episode_counts.get(folder, 0) + 1
                    elif fname_lower.startswith("cover") and fname_lower.endswith(
                        (".jpg", ".jpeg", ".png", ".webp")
                    ):
                        cover_exists[folder] = True

    # 장르 name → id 매핑 로드
    genre_map = await _load_genre_map(db)

    # 기존 이메일 조회
    existing_emails = await _load_existing_emails(db)

    results = []
    for idx, row in df.iterrows():
        email = str(row.get("작가이메일", "")).strip()
        title = str(row.get("작품제목", "")).strip()
        genre1 = str(row.get("1차장르", "")).strip()
        genre2 = str(row.get("2차장르", "")).strip()
        schedule_days = str(row.get("연재주기", "")).strip()
        first_open = str(row.get("최초공개회차", "1")).strip()
        start_date = str(row.get("예약공개시작일", "")).strip()

        errors = []
        if not email:
            errors.append("작가이메일 필수")
        if not title:
            errors.append("작품제목 필수")
        if not genre1:
            errors.append("1차장르 필수")
        elif genre1 not in genre_map:
            errors.append(f"1차장르 '{genre1}' 없음")
        if genre2 and genre2 not in genre_map:
            errors.append(f"2차장르 '{genre2}' 없음")
        if not schedule_days:
            errors.append("연재주기 필수")
        else:
            parsed = _parse_publish_days(schedule_days)
            if not any(v == "Y" for v in parsed.values()):
                errors.append("연재주기에 유효한 요일(월~일)이 없음")

        ep_count = episode_counts.get(title, 0)
        has_cover = cover_exists.get(title, False)
        account_exists = email.lower() in existing_emails

        results.append({
            "row": idx + 2,
            "email": email,
            "nickname": str(row.get("작가닉네임", "")).strip(),
            "title": title,
            "genre1": genre1,
            "genre2": genre2,
            "tags": str(row.get("태그", "")).strip(),
            "rating": str(row.get("연령등급", "all")).strip(),
            "monopoly": str(row.get("독점여부", "N")).strip().upper(),
            "contract": str(row.get("계약여부", "N")).strip().upper(),
            "open_yn": str(row.get("공개여부", "N")).strip().upper(),
            "synopsis": str(row.get("시놉시스", "")).strip(),
            "schedule_days": schedule_days,
            "first_open_ep": int(first_open) if first_open.isdigit() else 1,
            "start_date": start_date,
            "episode_count": ep_count,
            "has_cover": has_cover,
            "account_exists": account_exists,
            "errors": errors,
        })

    return {"error": None, "results": results}


# ─── 일괄 생성 ─────────────────────────────────────────────────

async def execute_bulk_upload(
    excel_bytes: bytes,
    zip_bytes: bytes,
    db: AsyncSession,
) -> dict:
    """미리보기 데이터를 기반으로 계정+작품+회차 일괄 생성."""
    preview = await preview_bulk_upload(excel_bytes, zip_bytes, db)
    if preview.get("error"):
        return {"success": False, "message": preview["error"], "results": []}

    rows = preview["results"]
    if not rows:
        return {"success": False, "message": "처리할 데이터가 없습니다.", "results": []}

    # zip 풀기
    episode_files: dict[str, dict[int, str]] = {}  # {title: {ep_no: content}}
    cover_files: dict[str, bytes] = {}  # {title: image_bytes}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        for name in zf.namelist():
            if name.endswith("/") or name.startswith("__MACOSX"):
                continue
            parts = Path(name).parts
            if len(parts) >= 2:
                folder = parts[0]
                fname_lower = parts[-1].lower()
                if fname_lower.endswith(".txt"):
                    ep_no = _extract_episode_no(parts[-1])
                    if ep_no is not None:
                        content = zf.read(name).decode("utf-8-sig")
                        episode_files.setdefault(folder, {})[ep_no] = content
                elif fname_lower.startswith("cover") and fname_lower.endswith(
                    (".jpg", ".jpeg", ".png", ".webp")
                ):
                    cover_files[folder] = zf.read(name)

    genre_map = await _load_genre_map(db)
    keyword_map = await _load_keyword_map(db)
    admin_token = await _get_admin_token()

    results = []
    for row in rows:
        if row["errors"]:
            results.append({**row, "status": "skipped", "message": ", ".join(row["errors"])})
            continue

        try:
            # 1) 계정 생성/조회
            user_id = await _ensure_user(
                email=row["email"],
                nickname=row["nickname"],
                admin_token=admin_token,
                db=db,
            )

            # 2) 작품 생성
            cover_bytes = cover_files.get(row["title"])
            product_id = await _create_product(
                user_id=user_id,
                row=row,
                genre_map=genre_map,
                keyword_map=keyword_map,
                cover_bytes=cover_bytes,
                db=db,
            )

            # 3) 회차 생성 + 예약공개
            eps = episode_files.get(row["title"], {})
            ep_count = await _create_episodes(
                product_id=product_id,
                user_id=user_id,
                episodes=eps,
                row=row,
                db=db,
            )

            await db.commit()
            results.append({
                **row,
                "status": "created",
                "user_id": user_id,
                "product_id": product_id,
                "episodes_created": ep_count,
            })
        except Exception as e:
            await db.rollback()
            logger.exception(f"Bulk upload failed for: {row['title']}")
            results.append({**row, "status": "failed", "message": f"{type(e).__name__}: {e}"})

    success_count = sum(1 for r in results if r.get("status") == "created")
    return {
        "success": True,
        "message": f"{success_count}/{len(results)}건 생성 완료",
        "results": results,
    }


# ─── 내부 함수 ─────────────────────────────────────────────────

def _extract_episode_no(filename: str) -> int | None:
    """'작품명 3화.txt' → 3"""
    name = filename.rsplit(".", 1)[0]  # 확장자 제거
    for part in reversed(name.split()):
        cleaned = part.replace("화", "")
        if cleaned.isdigit():
            return int(cleaned)
    return None


async def _load_genre_map(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(text(
        "SELECT keyword_id, keyword_name FROM tb_standard_keyword "
        "WHERE category_id = 1 AND use_yn = 'Y'"
    ))
    return {r["keyword_name"]: r["keyword_id"] for r in result.mappings().all()}


async def _load_keyword_map(db: AsyncSession) -> dict[str, int]:
    result = await db.execute(text(
        "SELECT keyword_id, keyword_name FROM tb_standard_keyword WHERE use_yn = 'Y'"
    ))
    return {r["keyword_name"]: r["keyword_id"] for r in result.mappings().all()}


async def _load_existing_emails(db: AsyncSession) -> set[str]:
    result = await db.execute(text("SELECT LOWER(email) AS email FROM tb_user"))
    return {r["email"] for r in result.mappings().all()}


async def _get_admin_token() -> str:
    token_res = await comm_service.kc_token_endpoint(
        method="POST", type="client_normal"
    )
    return token_res["access_token"]


async def _ensure_user(
    email: str,
    nickname: str,
    admin_token: str,
    db: AsyncSession,
) -> int:
    """이메일로 기존 계정 조회, 없으면 Keycloak + DB 생성."""
    result = await db.execute(
        text("SELECT user_id FROM tb_user WHERE LOWER(email) = :email"),
        {"email": email.lower()},
    )
    existing = result.mappings().first()
    if existing:
        return existing["user_id"]

    # Keycloak 계정 생성 (이미 존재하면 조회로 전환)
    password = _generate_password()
    try:
        kc_user_id = await comm_service.kc_users_endpoint(
            method="POST",
            admin_acc_token=admin_token,
            data_dict={
                "username": email,
                "email": email,
                "enabled": True,
                "credentials": [{"type": "password", "value": password, "temporary": False}],
            },
        )
    except Exception as e:
        if getattr(e, "status_code", None) == 409:
            # Keycloak에 이미 존재 → 조회
            kc_users = await comm_service.kc_users_endpoint(
                method="GET",
                admin_acc_token=admin_token,
                params_dict={"email": email},
            )
            if kc_users:
                kc_user_id = kc_users[0]["id"]
            else:
                raise
        else:
            raise

    # tb_user
    await db.execute(
        text("""
            INSERT INTO tb_user (kc_user_id, email, gender, birthdate, latest_signed_type, created_id, updated_id)
            VALUES (:kc_user_id, :email, '', '1990-01-01', 'likenovel', 0, 0)
        """),
        {"kc_user_id": kc_user_id, "email": email},
    )
    user_id_result = await db.execute(text("SELECT LAST_INSERT_ID() AS id"))
    user_id = user_id_result.scalar()

    # tb_user_profile (작가 역할)
    nick = nickname or comm_service.make_rand_nickname()
    await db.execute(
        text("""
            INSERT INTO tb_user_profile (user_id, nickname, default_yn, role_type, profile_image_id, created_id, updated_id)
            VALUES (:user_id, :nickname, 'Y', 'user', :profile_image, 0, 0)
        """),
        {"user_id": user_id, "nickname": nick, "profile_image": settings.R2_PROFILE_DEFAULT_IMAGE},
    )

    # tb_user_notification (기본 알림 설정)
    for noti_type in ("benefit", "comment", "system", "event", "marketing"):
        await db.execute(
            text("""
                INSERT INTO tb_user_notification (user_id, noti_type, noti_yn, created_id, updated_id)
                VALUES (:user_id, :noti_type, 'N', 0, 0)
            """),
            {"user_id": user_id, "noti_type": noti_type},
        )

    # tb_algorithm_recommend_user
    await db.execute(
        text("""
            INSERT IGNORE INTO tb_algorithm_recommend_user (user_id, created_id, updated_id)
            VALUES (:user_id, 0, 0)
        """),
        {"user_id": user_id},
    )

    logger.info(f"Bulk upload: created user {user_id} ({email}), password={password}")
    return user_id


async def _create_product(
    user_id: int,
    row: dict,
    genre_map: dict[str, int],
    keyword_map: dict[str, int],
    db: AsyncSession,
    cover_bytes: bytes | None = None,
) -> int:
    """작품 생성 + 키워드 매핑 + 표지 업로드."""
    primary_genre_id = genre_map.get(row["genre1"], 0)
    sub_genre_id = genre_map.get(row["genre2"]) if row["genre2"] else None
    ratings_code = "adult" if row["rating"] == "19" else ("15" if row["rating"] == "15" else "all")
    publish_days = _parse_publish_days(row["schedule_days"])

    # 표지 업로드 (있으면)
    thumbnail_file_id = None
    if cover_bytes:
        try:
            thumbnail_file_id = await _upload_cover_image(cover_bytes, db)
        except Exception as e:
            logger.warning(f"Cover upload failed for {row['title']}: {e}")

    await db.execute(
        text("""
            INSERT INTO tb_product (
                title, price_type, product_type, status_code, ratings_code,
                synopsis_text, user_id, author_id, author_name,
                publish_regular_yn, publish_days,
                primary_genre_id, sub_genre_id, thumbnail_file_id,
                open_yn, blind_yn, monopoly_yn, contract_yn,
                series_regular_price, single_regular_price, single_rental_price,
                created_id, updated_id
            ) VALUES (
                :title, 'free', 'normal', 'ongoing', :ratings_code,
                :synopsis, :user_id, :user_id, :author_name,
                'Y', :publish_days,
                :primary_genre_id, :sub_genre_id, :thumbnail_file_id,
                :open_yn, 'N', :monopoly_yn, :contract_yn,
                0, 0, 0,
                :user_id, :user_id
            )
        """),
        {
            "title": row["title"],
            "ratings_code": ratings_code,
            "synopsis": row["synopsis"],
            "user_id": user_id,
            "author_name": row["nickname"],
            "publish_days": json.dumps(publish_days),
            "primary_genre_id": primary_genre_id,
            "sub_genre_id": sub_genre_id,
            "thumbnail_file_id": thumbnail_file_id,
            "open_yn": row.get("open_yn", "N"),
            "monopoly_yn": row.get("monopoly", "N"),
            "contract_yn": row.get("contract", "N"),
        },
    )
    product_id_result = await db.execute(text("SELECT LAST_INSERT_ID() AS id"))
    product_id = product_id_result.scalar()

    # 키워드 매핑
    tags = [t.strip() for t in row.get("tags", "").split(",") if t.strip()]
    for tag_name in tags:
        kid = keyword_map.get(tag_name)
        if kid:
            await db.execute(
                text("""
                    INSERT INTO tb_mapped_product_keyword (product_id, keyword_id, created_id, updated_id)
                    VALUES (:product_id, :keyword_id, :user_id, :user_id)
                """),
                {"product_id": product_id, "keyword_id": kid, "user_id": user_id},
            )

    # tb_product_trend_index
    await db.execute(
        text("""
            INSERT INTO tb_product_trend_index (product_id, created_id, updated_id)
            VALUES (:product_id, 0, 0)
        """),
        {"product_id": product_id},
    )

    # tb_ptn_product_statistics
    await db.execute(
        text("""
            INSERT INTO tb_ptn_product_statistics (product_id, created_id, updated_id)
            VALUES (:product_id, 0, 0)
        """),
        {"product_id": product_id},
    )

    return product_id


async def _create_episodes(
    product_id: int,
    user_id: int,
    episodes: dict[int, str],  # {ep_no: txt_content}
    row: dict,
    db: AsyncSession,
) -> int:
    """회차 생성 + EPUB 변환 + R2 업로드 + 예약공개 설정."""
    if not episodes:
        return 0

    first_open_ep = row.get("first_open_ep", 1)
    publish_days = _parse_publish_days(row["schedule_days"])
    active_weekdays = _active_days_sorted(publish_days)

    start_date_str = row.get("start_date", "")
    try:
        start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
    except (ValueError, TypeError):
        start_date = datetime.now() + timedelta(days=1)

    sorted_eps = sorted(episodes.items())
    schedule_offset = 0

    for ep_no, txt_content in sorted_eps:
        html_content = _txt_to_html(txt_content)
        text_count = len(BeautifulSoup(html_content, "html.parser").get_text(strip=True))

        # open_yn + publish_reserve_date 결정
        if ep_no <= first_open_ep:
            open_yn = "Y"
            reserve_date = None
        else:
            open_yn = "N"
            reserve_date = _next_publish_date(start_date, active_weekdays, schedule_offset)
            schedule_offset += 1

        ep_title = f"{row['title']} {ep_no}화"

        # INSERT episode
        await db.execute(
            text("""
                INSERT INTO tb_product_episode (
                    product_id, price_type, episode_no, episode_title,
                    episode_text_count, episode_content, author_comment,
                    comment_open_yn, evaluation_open_yn,
                    publish_reserve_date, open_yn,
                    created_id, updated_id
                ) VALUES (
                    :product_id, 'free', :episode_no, :episode_title,
                    :text_count, :content, '',
                    'Y', 'Y',
                    :reserve_date, :open_yn,
                    :user_id, :user_id
                )
            """),
            {
                "product_id": product_id,
                "episode_no": ep_no,
                "episode_title": ep_title,
                "text_count": text_count,
                "content": html_content,
                "reserve_date": reserve_date,
                "open_yn": open_yn,
                "user_id": user_id,
            },
        )
        episode_id_result = await db.execute(text("SELECT LAST_INSERT_ID() AS id"))
        episode_id = episode_id_result.scalar()

        # EPUB 생성 + R2 업로드
        try:
            await _generate_and_upload_epub(
                episode_id=episode_id,
                episode_title=ep_title,
                html_content=html_content,
                db=db,
            )
        except Exception as e:
            logger.warning(f"EPUB upload failed for episode {episode_id}: {e}")
            # EPUB 실패해도 episode_content로 대체 가능하므로 계속 진행

    return len(sorted_eps)


async def _upload_cover_image(image_bytes: bytes, db: AsyncSession) -> int:
    """표지 이미지를 R2에 업로드하고 tb_common_file 레코드를 생성, file_group_id 반환."""
    file_uuid = f"{uuid4()}.webp"

    # presigned URL 생성
    presigned_url = comm_service.make_r2_presigned_url(
        type="upload",
        bucket_name=settings.R2_SC_IMAGE_BUCKET,
        file_id=f"cover/{file_uuid}",
    )

    # R2에 직접 업로드
    from httpx import AsyncClient
    async with AsyncClient() as ac:
        res = await ac.put(url=presigned_url, content=image_bytes, headers={"Content-Type": "image/webp"})
        res.raise_for_status()

    # tb_common_file
    await db.execute(
        text("INSERT INTO tb_common_file (group_type, use_yn, created_id, updated_id) VALUES ('cover', 'Y', 0, 0)")
    )
    file_group_result = await db.execute(text("SELECT LAST_INSERT_ID() AS id"))
    file_group_id = file_group_result.scalar()

    # tb_common_file_item
    await db.execute(
        text("""
            INSERT INTO tb_common_file_item (file_group_id, file_name, file_org_name, file_path, use_yn, created_id, updated_id)
            VALUES (:file_group_id, :file_name, :file_org_name, :file_path, 'Y', 0, 0)
        """),
        {
            "file_group_id": file_group_id,
            "file_name": file_uuid,
            "file_org_name": f"cover_{file_uuid}",
            "file_path": f"{settings.R2_SC_CDN_URL}/cover/{file_uuid}",
        },
    )

    return file_group_id


async def _generate_and_upload_epub(
    episode_id: int,
    episode_title: str,
    html_content: str,
    db: AsyncSession,
):
    """EPUB 생성 → R2 업로드 → tb_common_file 연결."""
    file_uuid = f"{uuid4()}.epub"

    # EPUB 생성
    await comm_service.make_epub(
        file_org_name=file_uuid,
        cover_image_path="",
        episode_title=episode_title,
        content_db=html_content,
    )

    # R2 presigned URL 생성 + 업로드
    presigned_url = comm_service.make_r2_presigned_url(
        type="upload",
        bucket_name=settings.R2_SC_EPUB_BUCKET,
        file_id=f"epub/{file_uuid}",
    )
    await comm_service.upload_epub_to_r2(url=presigned_url, file_name=file_uuid)

    # tb_common_file
    await db.execute(
        text("""
            INSERT INTO tb_common_file (group_type, use_yn, created_id, updated_id)
            VALUES ('epub', 'Y', 0, 0)
        """)
    )
    file_group_result = await db.execute(text("SELECT LAST_INSERT_ID() AS id"))
    file_group_id = file_group_result.scalar()

    # tb_common_file_item
    await db.execute(
        text("""
            INSERT INTO tb_common_file_item (
                file_group_id, file_name, file_org_name, file_path,
                use_yn, created_id, updated_id
            ) VALUES (
                :file_group_id, :file_name, :file_org_name, :file_path,
                'Y', 0, 0
            )
        """),
        {
            "file_group_id": file_group_id,
            "file_name": file_uuid,
            "file_org_name": f"{episode_id}.epub",
            "file_path": f"{settings.R2_SC_CDN_URL}/epub/{file_uuid}",
        },
    )

    # episode에 epub_file_id 연결
    await db.execute(
        text("""
            UPDATE tb_product_episode
               SET epub_file_id = :file_group_id
             WHERE episode_id = :episode_id
        """),
        {"file_group_id": file_group_id, "episode_id": episode_id},
    )
