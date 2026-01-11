from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.const import settings
from app.rdb import Base


class CommonCode(Base):
    __tablename__ = "tb_common_code"  # 공통 코드

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    code_group: Mapped[str] = mapped_column(
        String(20), index=True, nullable=True, comment="코드 그룹"
    )
    code_key: Mapped[str] = mapped_column(
        String(30), index=True, nullable=False, comment="코드 키"
    )
    code_value: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="코드 키값"
    )
    code_desc: Mapped[str] = mapped_column(
        String(80), nullable=True, comment="코드 키값 설명"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
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


class StandardKeyword(Base):
    __tablename__ = "tb_standard_keyword"  # 장르, 태그 등

    # column
    keyword_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    keyword_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        unique=True,
        nullable=False,
        comment="키워드 이름",
    )
    major_genre_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="1차, 2차 키워드 여부",
    )
    filter_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="작품 필터 키워드 여부",
    )
    category_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="카테고리 아이디"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
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


class StandardKeywordCategory(Base):
    __tablename__ = "tb_standard_keyword_category"  # 장르, 태그 등 카테고리

    # column
    category_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    category_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="카테고리 코드",
    )
    category_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="카테고리 이름"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
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


class CommonFile(Base):
    __tablename__ = "tb_common_file"  # 공통 파일

    # column
    file_group_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    group_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="그룹 타입",
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
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


class CommonFileItem(Base):
    __tablename__ = "tb_common_file_item"  # 공통 파일 상세

    # column
    file_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_group_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="파일 그룹 아이디"
    )
    file_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="uuid 파일명"
    )
    file_org_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="원본 파일명"
    )
    file_size: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="파일 사이즈"
    )
    file_path: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="파일 경로"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
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


class Badge(Base):
    __tablename__ = "tb_badge"  # 뱃지

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    badge_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="뱃지명"
    )
    promotion_conditions: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="승급 조건"
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


class CommPopup(Base):
    __tablename__ = "tb_comm_popup"  # 공통 팝업 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False, comment="팝업 제목")
    content: Mapped[str] = mapped_column(
        String(2000), nullable=False, comment="팝업 내용"
    )
    image_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="이미지 파일 id"
    )
    start_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="노출 시작일"
    )
    end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="노출 종료일"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    url: Mapped[str] = mapped_column(String(2000), nullable=True, comment="url")
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
