from sqlalchemy import BigInteger, Date, Double, Index, Integer, String, Text, TIMESTAMP, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import date, datetime

from app.const import settings
from app.rdb import Base


class Product(Base):
    __tablename__ = "tb_product"  # 작품 마스터 (작품 등록에서 ins)

    # column
    product_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    title: Mapped[str] = mapped_column(String(100), nullable=False, comment="작품 제목")
    price_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="가격구분(무료-free, 유료-paid)",
    )
    product_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="구분(자유, 일반",
    )
    status_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="상태코드(연재중-ongoing, 휴재중-rest, 완결-end, 연재중지-stop)",
    )
    ratings_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="연령등급(전체-all, 성인-adult)",
    )
    synopsis_text: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="작품 소개"
    )
    story_agent_setting_text: Mapped[str] = mapped_column(
        String(1000), nullable=True, comment="스토리 에이전트 보조 설정"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    author_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작가 아이디"
    )
    author_name: Mapped[str] = mapped_column(
        String(100), nullable=True, comment="작가 이름"
    )
    illustrator_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="그림작가 아이디"
    )
    illustrator_name: Mapped[str] = mapped_column(
        String(100), nullable=True, comment="그림작가 이름"
    )
    publish_regular_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="정기 여부 - 비정기 체크 시 Y",
    )
    publish_days: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=False, comment="연재 요일"
    )
    thumbnail_file_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="표지 이미지 파일"
    )
    primary_genre_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="1차 장르"
    )
    sub_genre_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="2차 장르"
    )
    count_hit: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="조회수"
    )  # 회차 보기에서 재계산(작품 단위)
    count_cp_hit: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="cp 조회수"
    )  # 회차 보기에서 재계산(작품 단위)
    count_recommend: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="추천수"
    )  # 회차 추천/비추천에서 재계산(작품 단위)
    count_bookmark: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="북마크수"
    )  # 작품 북마크 전체삭제, 작품 북마크/북마크해제에서 재계산(작품 단위)
    count_unbookmark: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="북마크 해제수"
    )  # 작품 북마크 전체삭제, 작품 북마크/북마크해제에서 재계산(작품 단위)
    open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="공개 여부"
    )
    blind_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="관리자 블라인드 여부"
    )
    approval_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="유료 승인 여부"
    )
    monopoly_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="독점 여부"
    )
    contract_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="계약 여부"
    )
    cp_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="담당 CP 사용자 ID"
    )
    paid_open_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="유료회차 시작 일시"
    )
    paid_episode_no: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="유료시작 회차(episode)"
    )
    last_episode_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="최근 회차 일자"
    )
    isbn: Mapped[str] = mapped_column(String(20), nullable=True, comment="isbn 코드")
    uci: Mapped[str] = mapped_column(String(50), nullable=True, comment="uci 코드")
    single_regular_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="단행본 가격"
    )
    single_rental_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="단행본 대여 가격"
    )
    series_regular_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="연재 가격"
    )
    sale_price: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="판매가"
    )
    apply_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="승급 신청 승인 일시"
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


class ProductEpisode(Base):
    __tablename__ = "tb_product_episode"  # 회차 마스터 (회차 저장/등록에서 ins)
    __table_args__ = (
        Index(
            "idx_product_episode_paid_convert",
            "product_id",
            "use_yn",
            "price_type",
            "episode_no",
        ),
    )

    # column
    episode_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    price_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="가격구분 - 무료, 유료",
    )
    episode_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차번호"
    )
    episode_title: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="회차 제목"
    )
    episode_text_count: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차 내용수"
    )
    episode_content: Mapped[str] = mapped_column(
        String(30000), nullable=True, comment="회차 내용"
    )  # 20000자이지만 태그를 고려해 증가
    epub_file_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="epub 파일"
    )
    author_comment: Mapped[str] = mapped_column(
        String(2000), nullable=True, comment="작가의 말"
    )
    comment_open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="댓글 오픈 여부"
    )
    evaluation_open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="평가 오픈 여부"
    )
    publish_reserve_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="예약 설정"
    )
    open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="회차 공개 여부"
    )
    count_hit: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차 조회수"
    )  # 회차 보기에서 재계산(작품 단위)
    count_recommend: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차 좋아요수"
    )  # 회차 추천/비추천에서 재계산(작품 단위)
    count_comment: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차 댓글수"
    )  # 작품 댓글 등록, 작품 댓글 삭제에서 재계산(회차 단위)
    count_evaluation: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차 사용자 평가수"
    )  # 회차 평가에서 재계산(회차 단위)
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


class ProductComment(Base):
    __tablename__ = "tb_product_comment"  # 작품 및 회차 댓글 (작품 댓글 등록에서 ins)

    # column
    comment_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    profile_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="프로필 아이디"
    )
    author_recommend_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="작가 추천 여부"
    )
    content: Mapped[str] = mapped_column(
        String(20000), nullable=True, comment="댓글 내용"
    )
    count_recommend: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="추천수"
    )  # 작품 댓글 공감, 작품 댓글 비공감에서 재계산(댓글 단위)
    count_not_recommend: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="비추천수"
    )  # 작품 댓글 공감, 작품 댓글 비공감에서 재계산(댓글 단위)
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="공개 여부"
    )
    display_top_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="코멘트 상단 고정 여부",
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


class ProductNotice(Base):
    __tablename__ = "tb_product_notice"  # 작품 공지 (작품 공지 저장/등록에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    subject: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="공지 제목"
    )
    content: Mapped[str] = mapped_column(
        String(20000), nullable=True, comment="공지 내용"
    )
    publish_reserve_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="예약 설정"
    )
    open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="작품 공지 공개 여부",
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


class ProductPromotion(Base):
    __tablename__ = "tb_product_promotion"  # 작품 프로모션

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    promotion_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="프로모션 아이디"
    )
    req_status: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="신청 구분 - 신청, 철회, 반려, 승인",
    )
    req_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="신청 일자"
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


class ProductPaidApply(Base):
    __tablename__ = "tb_product_paid_apply"  # 작품 유료전환 신청 (작품 일반승급신청/유료전환신청에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    status_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="상태코드 - 심사중, 반려, 승인",
    )
    req_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="신청한 유저 아이디"
    )
    req_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="신청 일자",
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    approval_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="승인한 유저 아이디"
    )
    approval_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="승인 일자"
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


class ProductEpisodeApply(Base):
    __tablename__ = "tb_product_episode_apply"  # 회차 심사 신청

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    status_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="상태코드 - 심사중, 반려, 승인",
    )
    req_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="신청자 사용자 아이디"
    )
    req_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
        comment="신청 일자",
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    approval_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="승인자 사용자 아이디"
    )
    approval_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="승인 일자"
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


class ProductContractOffer(Base):
    __tablename__ = "tb_product_contract_offer"  # 계약 제안

    # column
    offer_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    profit_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="이익 분배 구분 - 퍼센트, 금액 제시…",
    )
    author_profit: Mapped[float] = mapped_column(
        Double, server_default="0", comment="작가 수익"
    )
    offer_profit: Mapped[float] = mapped_column(
        Double, server_default="0", comment="제시자 수익"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    author_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작가 유저 아이디"
    )
    author_accept_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="최종 제안 수락 여부",
    )
    offer_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="제안한 유저 아이디"
    )
    offer_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="제안 형태 - 금액대 구분코드 50~100…등등, 금액 직접입력",
    )
    offer_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="제안 금액대 코드 - 50~100, 100~200, …등등",
    )
    offer_price: Mapped[float] = mapped_column(
        Double, nullable=True, comment="제안 금액(제안 금액대, 직접입력 금액)"
    )
    offer_message: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="제안 메시지"
    )
    offer_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="제안 일시"
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


class ProductEvaluation(Base):
    __tablename__ = "tb_product_evaluation"  # 작품 평가 (회차 평가에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    eval_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="평가 코드",
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


class ProductRank(Base):
    __tablename__ = "tb_product_rank"  # 작품 랭킹(유/무료 top 50) (일배치에서 ins)

    # column
    rank_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    current_rank: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="현재 랭킹"
    )
    privious_rank: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="이전 랭킹"
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


class ProductRankArea(Base):
    __tablename__ = "tb_product_rank_area"  # 작품 랭킹(영역별 top 50)

    rank_area_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    area_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        index=True,
        nullable=False,
        comment="랭킹 영역 코드",
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    current_rank: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="현재 랭킹"
    )
    previous_rank: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="이전 랭킹"
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


class ProductTrendIndex(Base):
    __tablename__ = "tb_product_trend_index"  # 작품 지표 (작품 등록에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    reading_rate: Mapped[float] = mapped_column(
        Double, server_default="0", comment="연독률"
    )
    writing_count_per_week: Mapped[float] = mapped_column(
        Double, server_default="0", comment="주평균 연재횟수"
    )
    primary_reader_group: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="주요 독자층"
    )  # {"1": "20대 남", "2": "20대 여"} 혹은 {"1": "40대 남"} 형식의 데이터
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


class ProductKeyword(Base):
    __tablename__ = "tb_mapped_product_keyword"  # 작품 키워드 매핑 (작품 등록에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    keyword_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="키워드 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
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


class ProductUserKeyword(Base):
    __tablename__ = "tb_product_user_keyword"  # 작품 사용자 키워드 (작품 등록에서 ins)

    # column
    keyword_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    keyword_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="키워드명"
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


class ProductCountVariance(Base):
    __tablename__ = "tb_product_count_variance"  # 작품 인디케이터 (일배치에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    count_hit_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="조회수 변동치"
    )
    count_bookmark_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="선작수 변동치"
    )
    count_unbookmark_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="선작해제수 변동치"
    )
    count_recommend_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="추천수 변동치"
    )
    count_cp_hit_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="cp조회수 변동치"
    )
    count_interest_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="누적관심수 변동치"
    )
    count_interest_sustain_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="관심유지수 변동치"
    )
    count_interest_loss_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="관심이탈수 변동치"
    )
    reading_rate_indicator: Mapped[float] = mapped_column(
        Double, server_default="0", comment="연독률 변동치"
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


class MainRuleSlotSnapshot(Base):
    __tablename__ = "tb_main_rule_slot_snapshot"  # 메인 규칙형 구좌 3일 스냅샷

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slot_key: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="구좌 키"
    )
    adult_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        index=True,
        nullable=False,
        server_default="N",
        comment="성인 작품 포함 여부",
    )
    snapshot_start_date: Mapped[date] = mapped_column(
        Date, index=True, nullable=False, comment="스냅샷 시작일"
    )
    snapshot_end_date: Mapped[date] = mapped_column(
        Date, index=True, nullable=False, comment="스냅샷 종료일"
    )
    display_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="노출 순서"
    )
    product_id: Mapped[int | None] = mapped_column(
        Integer, index=True, nullable=True, comment="작품 ID, 후보가 없으면 NULL sentinel"
    )
    created_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductEpisodeCountVariance(Base):
    __tablename__ = (
        "tb_product_episode_count_variance"  # 회차 인디케이터 (일배치에서 ins)
    )

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    episode_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="회차수"
    )
    count_hit_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="조회수 변동치"
    )
    count_recommend_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="추천수 변동치"
    )
    count_comment_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="댓글수 변동치"
    )
    count_evaluation_indicator: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="평가수 변동치"
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


class UserBookmark(Base):
    __tablename__ = (
        "tb_user_bookmark"  # 사용자 작품 선작(북마크) (작품 북마크/북마크해제에서 ins)
    )

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
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


class UserProductUsage(Base):
    __tablename__ = "tb_user_product_usage"  # 사용자가 본 작품 및 회차 (회차 보기, 회차 추천/비추천에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    recommend_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="추천 여부"
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


class UserProductRecent(Base):
    __tablename__ = "tb_user_product_recent"  # 최근 본 작품

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
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


class UserProductCommentRecommend(Base):
    __tablename__ = "tb_user_product_comment_recommend"  # 작품별 유저 공감/비공감 (작품 댓글 공감, 작품 댓글 비공감에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    comment_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="댓글 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    recommend_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="공감 여부"
    )
    not_recommend_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="비공감 여부"
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


class ProductReview(Base):
    __tablename__ = "tb_product_review"  # 작품 리뷰

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="회차 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    review_text: Mapped[str] = mapped_column(
        String(3000), index=True, nullable=False, comment="리뷰 내용"
    )
    open_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="공개 여부"
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


class ProductEpisodeLike(Base):
    __tablename__ = "tb_product_episode_like"  # 회차 좋아요

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
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


class ProductAiMetadata(Base):
    __tablename__ = "tb_product_ai_metadata"  # 작품 AI 메타데이터

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    protagonist_type: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="주인공 유형"
    )
    protagonist_desc: Mapped[str] = mapped_column(
        String(500), nullable=True, comment="주인공 설명"
    )
    protagonist_current_age_band: Mapped[str] = mapped_column(
        String(30), nullable=True, comment="주인공 현재 연령대"
    )
    protagonist_mental_age_band: Mapped[str] = mapped_column(
        String(30), nullable=True, comment="주인공 정신연령대"
    )
    past_life_age_band: Mapped[str] = mapped_column(
        String(30), nullable=True, comment="전생 연령대"
    )
    regression_type: Mapped[str] = mapped_column(
        String(30), nullable=True, comment="회귀/빙의/환생/none"
    )
    heroine_type: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="히로인 유형"
    )
    heroine_weight: Mapped[str] = mapped_column(
        String(50), nullable=True, comment="히로인 비중"
    )
    romance_chemistry_weight: Mapped[str] = mapped_column(
        String(20), nullable=True, comment="연애 케미 비중"
    )
    mood: Mapped[str] = mapped_column(String(200), nullable=True, comment="분위기")
    pacing: Mapped[str] = mapped_column(
        String(50), nullable=True, comment="전개 속도"
    )
    premise: Mapped[str] = mapped_column(String(500), nullable=True, comment="핵심 소재")
    hook: Mapped[str] = mapped_column(String(300), nullable=True, comment="1화 훅")
    episode_summary_text: Mapped[str] = mapped_column(
        Text, nullable=True, comment="작품요약 (1~10화 3문장 요약)"
    )
    protagonist_goal_primary: Mapped[str] = mapped_column(
        String(30), nullable=True, comment="주인공 대목표"
    )
    goal_confidence: Mapped[float] = mapped_column(
        Double, nullable=True, comment="주인공 대목표 confidence"
    )
    overall_confidence: Mapped[float] = mapped_column(
        Double, nullable=True, comment="전체 confidence"
    )
    axis_label_scores: Mapped[str] = mapped_column(
        String(8000), nullable=True, comment="축별 라벨 점수"
    )
    protagonist_material_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="주인공 능력/매력 태그"
    )
    worldview_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="세계관 태그"
    )
    protagonist_type_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="주인공 타입(타) 태그"
    )
    protagonist_job_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="주인공 직업(직) 태그"
    )
    axis_style_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="작풍(작) 태그"
    )
    axis_romance_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="연애/케미(연) 태그"
    )
    themes: Mapped[str] = mapped_column(String(3000), nullable=True, comment="테마 태그")
    similar_famous: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="유사 유명작"
    )
    taste_tags: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="취향 태그"
    )
    raw_analysis: Mapped[str] = mapped_column(
        String(12000), nullable=True, comment="LLM 원본 응답"
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="분석 일시"
    )
    model_version: Mapped[str] = mapped_column(
        String(50), nullable=True, comment="사용 모델 버전"
    )
    analysis_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        server_default="pending",
        comment="분석 상태 (pending/success/failed)",
    )
    analysis_attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="분석 시도 누적 횟수"
    )
    analysis_error_message: Mapped[str] = mapped_column(
        String(1000), nullable=True, comment="분석 실패 사유"
    )
    exclude_from_recommend_yn: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        server_default="N",
        comment="추천 제외 여부",
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductAiOnboarding(Base):
    __tablename__ = "tb_ai_onboarding_product"  # AI 온보딩 작품 노출 관리

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="온보딩 노출 순서"
    )
    use_yn: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        server_default="Y",
        comment="사용 여부",
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductAiOnboardingTag(Base):
    __tablename__ = "tb_ai_onboarding_tag"  # AI 온보딩 태그 노출 관리

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tab_key: Mapped[str] = mapped_column(
        String(20), index=True, nullable=False, comment="탭 키 (hero/worldTone/relation)"
    )
    tag_name: Mapped[str] = mapped_column(
        String(100), nullable=False, comment="태그명"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="탭 내 노출 순서"
    )
    use_yn: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        server_default="Y",
        comment="사용 여부",
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserAiSignalEvent(Base):
    __tablename__ = "tb_user_ai_signal_event"  # AI 추천용 유저 행동 원천 이벤트

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="회차 아이디"
    )
    event_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="이벤트 타입"
    )
    session_id: Mapped[str] = mapped_column(
        String(64), index=True, nullable=True, comment="세션 아이디"
    )
    active_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="활성 열람 시간(초)"
    )
    scroll_depth: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="스크롤 깊이(0~1)"
    )
    progress_ratio: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="진행률(0~1)"
    )
    next_available_yn: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="N", comment="다음화 존재 여부"
    )
    latest_episode_reached_yn: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="N", comment="최신화 도달 여부"
    )
    event_payload: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="추가 이벤트 페이로드"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class UserAiSignalEventFactor(Base):
    __tablename__ = "tb_user_ai_signal_event_factor"  # AI 추천용 유저 행동 factor detail

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(
        BigInteger, index=True, nullable=False, comment="원본 이벤트 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="회차 아이디"
    )
    event_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="원본 이벤트 타입"
    )
    factor_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="취향 축 타입"
    )
    factor_key: Mapped[str] = mapped_column(
        String(120), index=True, nullable=False, comment="취향 축 키"
    )
    signal_score: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="신호 점수"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )


class UserAiSignalEventDaily(Base):
    __tablename__ = "tb_user_ai_signal_event_daily"  # AI 추천용 유저 행동 일단위 집계

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    stat_date: Mapped[date] = mapped_column(
        Date, index=True, nullable=False, comment="집계일"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    event_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="이벤트 타입"
    )
    event_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="이벤트 건수"
    )
    sum_active_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="활성 열람 시간 합계(초)"
    )
    avg_scroll_depth: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="평균 스크롤 깊이"
    )
    avg_progress_ratio: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="평균 진행률"
    )
    latest_episode_reached_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="최신화 도달 건수"
    )
    revisit_24h_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="24시간 내 재방문 건수"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserAiSignalEventWeekly(Base):
    __tablename__ = "tb_user_ai_signal_event_weekly"  # AI 추천용 유저 행동 주단위 집계

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    week_start_date: Mapped[date] = mapped_column(
        Date, index=True, nullable=False, comment="주 시작일(월요일)"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    event_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="이벤트 타입"
    )
    event_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="이벤트 건수"
    )
    sum_active_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="활성 열람 시간 합계(초)"
    )
    avg_scroll_depth: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="평균 스크롤 깊이"
    )
    avg_progress_ratio: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="평균 진행률"
    )
    latest_episode_reached_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="최신화 도달 건수"
    )
    revisit_24h_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="24시간 내 재방문 건수"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductDetailFunnelDaily(Base):
    __tablename__ = "tb_product_detail_funnel_daily"  # 작품 상세 퍼널 일별 mart
    __table_args__ = (
        UniqueConstraint(
            "computed_date",
            "product_id",
            "entry_source_norm",
            name="uk_product_detail_funnel_daily",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    computed_date: Mapped[date] = mapped_column(
        Date, index=True, nullable=False, comment="집계일(퍼널 세션 시작일)"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    entry_source: Mapped[str | None] = mapped_column(
        String(50), nullable=True, comment="상세 진입 source(nullable)"
    )
    entry_source_norm: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="__null__",
        comment="NULL dedupe용 source key",
    )
    detail_view_raw_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="raw 상세 진입 이벤트 수"
    )
    detail_view_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="dedupe된 상세 퍼널 세션 수"
    )
    detail_view_user_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="상세 퍼널 진입 유저 수"
    )
    detail_to_view_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="상세->viewer 전환 세션 수"
    )
    detail_to_view_user_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="상세->viewer 전환 유저 수"
    )
    detail_exit_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="작품 컨텍스트 이탈 세션 수"
    )
    exit_home_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="홈 이동 이탈 세션 수"
    )
    exit_search_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="검색 이동 이탈 세션 수"
    )
    exit_other_product_detail_session_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="다른 작품 상세 이동 이탈 세션 수",
    )
    exit_other_route_session_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="기타 경로 이동 이탈 세션 수"
    )
    episode_exit_event_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="세션 내 회차 exit 이벤트 수"
    )
    avg_episode_exit_progress_ratio: Mapped[float | None] = mapped_column(
        Double, nullable=True, comment="세션 내 회차 exit 평균 진행률"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ProductEpisodeDropoffDaily(Base):
    __tablename__ = "tb_product_episode_dropoff_daily"  # 작품 회차별 읽다 나감 일별 mart
    __table_args__ = (
        UniqueConstraint(
            "computed_date",
            "product_id",
            "episode_id",
            name="uk_product_episode_dropoff_daily",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    computed_date: Mapped[date] = mapped_column(
        Date, index=True, nullable=False, comment="집계일(회차 읽기 시작일)"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="회차 아이디"
    )
    episode_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="회차 번호"
    )
    episode_title: Mapped[str | None] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="회차 제목"
    )
    read_start_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="읽기 시작 수"
    )
    episode_dropoff_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="읽다 나감 수(progress 95% 미만)",
    )
    episode_dropoff_rate: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="읽다 나감 비율"
    )
    avg_dropoff_progress_ratio: Mapped[float | None] = mapped_column(
        Double, nullable=True, comment="평균 이탈 지점(progress 95% 미만)"
    )
    near_complete_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="거의 다 읽음 수(progress 95% 이상)",
    )
    dropoff_0_10_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="0~10% 구간 이탈 수"
    )
    dropoff_10_30_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="10~30% 구간 이탈 수"
    )
    dropoff_30_60_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="30~60% 구간 이탈 수"
    )
    dropoff_60_90_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="60~90% 구간 이탈 수"
    )
    dropoff_90_plus_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        server_default="0",
        comment="90% 이상 이탈 수(95% 미만)",
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserTasteFactorScore(Base):
    __tablename__ = "tb_user_taste_factor_score"  # 유저 취향 축 점수

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    factor_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="축 타입"
    )
    factor_key: Mapped[str] = mapped_column(
        String(120), nullable=False, comment="축 키"
    )
    score: Mapped[float] = mapped_column(
        Double, nullable=False, server_default="0", comment="점수"
    )
    signal_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", comment="반영 신호 수"
    )
    last_event_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="최종 반영 이벤트 시각"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class AiSlotServingLog(Base):
    __tablename__ = "tb_ai_slot_serving_log"  # AI 추천 구좌 노출/성과 로그

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    slot_type: Mapped[str] = mapped_column(
        String(50), index=True, nullable=False, comment="구좌 타입"
    )
    slot_key: Mapped[str] = mapped_column(
        String(100), nullable=True, comment="구좌 키"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    served_at: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    clicked_yn: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="N", comment="클릭 여부"
    )
    continued_3ep_yn: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="N", comment="3화 연독 여부"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class AiSignalRetentionPolicy(Base):
    __tablename__ = "tb_ai_signal_retention_policy"  # AI 시그널 원천로그 보관 정책

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    retention_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="90", comment="원천 이벤트 보관일"
    )
    rollup_before_delete_yn: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="Y", comment="삭제 전 롤업 여부"
    )
    enabled_yn: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="Y", comment="정책 사용 여부"
    )
    last_rollup_date: Mapped[date] = mapped_column(
        Date, nullable=True, comment="마지막 롤업 기준일"
    )
    last_purge_before_date: Mapped[date] = mapped_column(
        Date, nullable=True, comment="마지막 삭제 기준일"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )
