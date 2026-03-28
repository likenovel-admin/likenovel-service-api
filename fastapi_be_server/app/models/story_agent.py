from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Text, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.rdb import Base


class StoryAgentSession(Base):
    __tablename__ = "tb_story_agent_session"

    session_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False, comment="작품 ID")
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True, comment="로그인 사용자 ID")
    guest_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, comment="비로그인 식별 키")
    title: Mapped[str] = mapped_column(String(120), nullable=False, server_default="새 대화", comment="세션 제목")
    deleted_yn: Mapped[str] = mapped_column(String(1), nullable=False, server_default="N", comment="삭제 여부")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 갱신한 id")
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class StoryAgentMessage(Base):
    __tablename__ = "tb_story_agent_message"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="세션 ID")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="user | assistant")
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="메시지 본문")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
