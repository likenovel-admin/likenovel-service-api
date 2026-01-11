from sqlalchemy import Integer, String, TIMESTAMP, text, Double
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

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
    approval_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="유료 승인 여부"
    )
    monopoly_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="독점 여부"
    )
    contract_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="계약 여부"
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
