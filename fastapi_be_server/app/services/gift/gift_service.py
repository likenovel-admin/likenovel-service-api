from sqlalchemy.ext.asyncio import AsyncSession

import app.services.common.statistics_service as statistics_service

"""
gifts 도메인 개별 서비스 함수 모음
"""


async def get_gifts(category: str, kc_user_id: str, db: AsyncSession):
    return


async def put_gifts_gift_id_collection(gift_id: str, kc_user_id: str, db: AsyncSession):
    await statistics_service.insert_site_statistics_log(
        db=db, type="active", user_id=kc_user_id
    )
    return
