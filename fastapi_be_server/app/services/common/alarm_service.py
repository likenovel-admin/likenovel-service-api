from sqlalchemy.ext.asyncio import AsyncSession

"""
alarms 도메인 개별 서비스 함수 모음
"""


async def get_alarms_unread(kc_user_id: str, db: AsyncSession):
    return


async def put_alarms_mark_as_read(kc_user_id: str, db: AsyncSession):
    return
