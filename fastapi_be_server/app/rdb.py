from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.const import settings

likenovel_db_engine = create_async_engine(
    settings.LIKENOVEL_DB_URL,
    future=True,
    pool_pre_ping=True,  # 연결 상태 확인 후 재연결
    pool_recycle=3600,  # 1시간마다 연결 갱신
    pool_size=10,  # 커넥션 풀 크기
    max_overflow=20,  # 추가 연결 허용 수
)
likenovel_db_session = sessionmaker(
    bind=likenovel_db_engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


# 재사용 가능한 sessionmaker 활용
async def get_likenovel_db():
    async with likenovel_db_session() as likenovel_session:
        yield likenovel_session
        await likenovel_session.commit()
