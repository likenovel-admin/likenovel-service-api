from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.const import settings
from app.rdb import Base


class Notice(Base):
    __tablename__ = "tb_notice"  # 공지사항

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="공지 제목"
    )
    content: Mapped[str] = mapped_column(
        String(20000), nullable=True, comment="공지 내용"
    )
    primary_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        index=True,
        server_default="N",
        comment="우선순위 여부",
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=0, comment="조회수"
    )
    file_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="파일 id"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class Faq(Base):
    __tablename__ = "tb_faq"  # FAQ

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    faq_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="FAQ 타입 - 회원문의, 이용문의, 결제및환불, 사이트이용문의, 서비스이용문의",
    )
    subject: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="FAQ 제목"
    )
    content: Mapped[str] = mapped_column(
        String(20000), nullable=True, comment="FAQ 내용"
    )
    primary_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="우선순위 여부"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    view_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=0, comment="조회수"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class Qna(Base):
    __tablename__ = "tb_qna"  # QnA

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="분류 - 서비스문의, 결제문의, 정산문의, 바라는점, 회원상태문의, 버그리포팅, 제휴문의, 작품신고, 악성유저신고, 게시물신고",
    )
    subject: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="QnA 제목"
    )
    content: Mapped[str] = mapped_column(
        String(20000), nullable=True, comment="QnA 내용"
    )
    email: Mapped[str] = mapped_column(
        String(100), nullable=True, comment="회신받을 이메일"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    attach_file_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="첨부파일"
    )
    created_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
