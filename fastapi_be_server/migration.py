from sqlalchemy.ext.asyncio import create_async_engine

from app.const import settings

# migration 대상 models
from app.models.comm import Base as CommBase
from app.models.user import Base as UserBase
from app.models.product import Base as ProductBase
from app.models.payment import Base as PaymentBase
from app.models.event_quest_promotion import Base as EventQuestPromotionBase
from app.models.notice_qna import Base as NoticeQnaBase

likenovel_db_engine = create_async_engine(
    settings.LIKENOVEL_DB_URL, echo=True, future=True
)


async def reset_database():
    async with likenovel_db_engine.begin() as conn:
        # await conn.run_sync(CommBase.metadata.drop_all)
        # await conn.run_sync(UserBase.metadata.drop_all)
        # await conn.run_sync(ProductBase.metadata.drop_all)
        # await conn.run_sync(PaymentBase.metadata.drop_all)
        # await conn.run_sync(EventQuestPromotionBase.metadata.drop_all)
        # await conn.run_sync(NoticeQnaBase.metadata.drop_all)

        await conn.run_sync(CommBase.metadata.create_all)
        await conn.run_sync(UserBase.metadata.create_all)
        await conn.run_sync(ProductBase.metadata.create_all)
        await conn.run_sync(PaymentBase.metadata.create_all)
        await conn.run_sync(EventQuestPromotionBase.metadata.create_all)
        await conn.run_sync(NoticeQnaBase.metadata.create_all)


if __name__ == "__main__":
    import asyncio

    asyncio.run(reset_database())
