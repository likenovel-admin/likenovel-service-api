from datetime import datetime

from sqlalchemy import BigInteger, Integer, String, Text, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from app.rdb import Base


class WebsochatSession(Base):
    __tablename__ = "tb_story_agent_session"

    session_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, index=True, nullable=False, comment="작품 ID")
    user_id: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True, comment="로그인 사용자 ID")
    guest_key: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True, comment="비로그인 식별 키")
    title: Mapped[str] = mapped_column(String(120), nullable=False, server_default="새 대화", comment="세션 제목")
    session_memory_json: Mapped[str | None] = mapped_column(Text, nullable=True, comment="RP/세션 메모리 JSON")
    deleted_yn: Mapped[str] = mapped_column(String(1), nullable=False, server_default="N", comment="삭제 여부")
    expires_at: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, comment="세션 만료 시각")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 갱신한 id")
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class WebsochatMessage(Base):
    __tablename__ = "tb_story_agent_message"

    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="세션 ID")
    role: Mapped[str] = mapped_column(String(20), nullable=False, comment="user | assistant")
    client_message_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        comment="클라이언트 메시지 ID",
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="메시지 본문")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class WebsochatContextProduct(Base):
    __tablename__ = "tb_story_agent_context_product"

    product_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, comment="작품 ID")
    context_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="pending | processing | ready | failed",
    )
    total_episode_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="대상 회차 수",
    )
    ready_episode_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="적재 완료 회차 수",
    )
    active_product_summary_id: Mapped[int | None] = mapped_column(
        BigInteger,
        nullable=True,
        comment="현재 활성 작품 요약 summary_id",
    )
    last_built_at: Mapped[datetime | None] = mapped_column(
        TIMESTAMP,
        nullable=True,
        comment="마지막 성공 빌드 시각",
    )
    last_error_message: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="마지막 실패 메시지",
    )
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    updated_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 갱신한 id")
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class WebsochatContextDoc(Base):
    __tablename__ = "tb_story_agent_context_doc"

    context_doc_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="작품 ID")
    episode_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="회차 ID")
    episode_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="회차 번호")
    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="episode_content | epub_fallback",
    )
    source_locator: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        comment="원문 출처 식별자(epub file_name 등)",
    )
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="정규화 원문 해시")
    source_text_length: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="정규화 원문 길이",
    )
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="에피소드 내 버전")
    is_active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y", comment="활성 여부")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class WebsochatContextChunk(Base):
    __tablename__ = "tb_story_agent_context_chunk"

    chunk_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    context_doc_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="context_doc_id")
    product_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="작품 ID")
    episode_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="회차 ID")
    episode_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="회차 번호")
    chunk_no: Mapped[int] = mapped_column(Integer, nullable=False, comment="청크 번호")
    text_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="청크 텍스트 해시")
    char_start: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="시작 위치")
    char_end: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="종료 위치")
    text: Mapped[str] = mapped_column(Text, nullable=False, comment="청크 본문")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class WebsochatContextSummary(Base):
    __tablename__ = "tb_story_agent_context_summary"

    summary_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False, comment="작품 ID")
    summary_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        comment="episode_summary | range_summary | product_summary | character_snapshot | relation_snapshot | world_snapshot | character_rp_profile | character_rp_examples",
    )
    scope_key: Mapped[str] = mapped_column(String(80), nullable=False, comment="요약 scope key")
    episode_from: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="시작 회차")
    episode_to: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="종료 회차")
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, comment="요약 입력 해시")
    source_doc_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0", comment="입력 문서 수")
    version_no: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1", comment="scope 내 버전")
    is_active: Mapped[str] = mapped_column(String(1), nullable=False, server_default="Y", comment="활성 여부")
    summary_text: Mapped[str] = mapped_column(Text, nullable=False, comment="요약 본문")
    created_id: Mapped[int | None] = mapped_column(Integer, nullable=True, comment="row를 생성한 id")
    created_date: Mapped[datetime] = mapped_column(TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
