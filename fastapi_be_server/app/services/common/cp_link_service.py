from typing import Optional

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession


def normalize_cp_nickname(nickname: Optional[str]) -> Optional[str]:
    if nickname is None:
        return None
    normalized = nickname.strip()
    return normalized or None


async def get_accepted_cp_info_by_nickname(
    nickname: Optional[str], db: AsyncSession, *, for_update: bool = False
) -> Optional[dict]:
    normalized_nickname = normalize_cp_nickname(nickname)
    if normalized_nickname is None:
        return None

    suffix = " FOR UPDATE" if for_update else ""
    query = text(
        f"""
        SELECT up.user_id, up.nickname, ranked.company_name
          FROM tb_user_profile up
          INNER JOIN (
                SELECT user_id, company_name
                  FROM (
                        SELECT user_id,
                               company_name,
                               ROW_NUMBER() OVER (
                                   PARTITION BY user_id
                                   ORDER BY approval_date DESC, id DESC
                               ) AS rn
                          FROM tb_user_profile_apply
                         WHERE apply_type = 'cp'
                           AND approval_code = 'accepted'
                           AND approval_date IS NOT NULL
                  ) accepted
                 WHERE rn = 1
          ) ranked ON ranked.user_id = up.user_id
         WHERE up.default_yn = 'Y'
           AND up.nickname = :nickname
         LIMIT 1{suffix}
        """
    )
    result = await db.execute(query, {"nickname": normalized_nickname})
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def get_accepted_cp_info_by_user_id(
    cp_user_id: Optional[int], db: AsyncSession, *, for_update: bool = False
) -> Optional[dict]:
    if cp_user_id is None:
        return None

    suffix = " FOR UPDATE" if for_update else ""
    query = text(
        f"""
        SELECT up.user_id, up.nickname, ranked.company_name
          FROM tb_user_profile up
          INNER JOIN (
                SELECT user_id, company_name
                  FROM (
                        SELECT user_id,
                               company_name,
                               ROW_NUMBER() OVER (
                                   PARTITION BY user_id
                                   ORDER BY approval_date DESC, id DESC
                               ) AS rn
                          FROM tb_user_profile_apply
                         WHERE apply_type = 'cp'
                           AND approval_code = 'accepted'
                           AND approval_date IS NOT NULL
                  ) accepted
                 WHERE rn = 1
          ) ranked ON ranked.user_id = up.user_id
         WHERE up.default_yn = 'Y'
           AND up.user_id = :cp_user_id
         LIMIT 1{suffix}
        """
    )
    result = await db.execute(query, {"cp_user_id": cp_user_id})
    row = result.mappings().one_or_none()
    return dict(row) if row else None


async def get_accepted_cp_info_map_by_user_ids(
    user_ids: list[int], db: AsyncSession
) -> dict[int, dict]:
    normalized_user_ids = sorted({user_id for user_id in user_ids if user_id is not None})
    if not normalized_user_ids:
        return {}

    query = text(
        """
        SELECT up.user_id, up.nickname, ranked.company_name
          FROM tb_user_profile up
          INNER JOIN (
                SELECT user_id, company_name
                  FROM (
                        SELECT user_id,
                               company_name,
                               ROW_NUMBER() OVER (
                                   PARTITION BY user_id
                                   ORDER BY approval_date DESC, id DESC
                               ) AS rn
                          FROM tb_user_profile_apply
                         WHERE apply_type = 'cp'
                           AND approval_code = 'accepted'
                           AND approval_date IS NOT NULL
                           AND user_id IN :user_ids
                  ) accepted
                 WHERE rn = 1
          ) ranked ON ranked.user_id = up.user_id
         WHERE up.default_yn = 'Y'
           AND up.user_id IN :user_ids
        """
    ).bindparams(bindparam("user_ids", expanding=True))
    result = await db.execute(query, {"user_ids": normalized_user_ids})
    rows = result.mappings().all()
    return {
        row["user_id"]: {
            "user_id": row["user_id"],
            "nickname": row["nickname"],
            "company_name": row["company_name"],
        }
        for row in rows
    }
