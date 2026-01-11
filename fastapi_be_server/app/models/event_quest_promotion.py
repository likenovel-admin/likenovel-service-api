from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.const import settings
from app.rdb import Base


class Event(Base):
    __tablename__ = "tb_event"  # 이벤트 마스터

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="상시진행, 기간진행",
    )
    banner_file_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="배너 이미지 파일 아이디"
    )
    subject: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="이벤트 제목"
    )
    content: Mapped[str] = mapped_column(
        String(20000), nullable=True, comment="이벤트 내용"
    )
    begin_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="이벤트 시작일"
    )
    end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="이벤트 종료일"
    )
    close_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="종료 여부"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    link_url: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="링크 url"
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


class EventVoteRound(Base):
    __tablename__ = "tb_event_vote_round"  # 투표 마스터

    # column
    round_product_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    round_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="투표 회차"
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


class Quest(Base):
    __tablename__ = "tb_quest"  # 퀘스트 마스터

    quest_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(200), nullable=True, comment="퀘스트명")
    reward_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="보상 아이디"
    )
    end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="퀘스트 완료일"
    )
    goal_stage: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="목표 단계"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    renewal: Mapped[str] = mapped_column(
        String(1000), nullable=True, comment="갱신 주기 (각 요일별 갱신 여부 Y|N)"
    )
    step1: Mapped[str] = mapped_column(String(1000), nullable=True, comment="1단계")
    step2: Mapped[str] = mapped_column(String(1000), nullable=True, comment="2단계")
    step3: Mapped[str] = mapped_column(String(1000), nullable=True, comment="3단계")
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


class Promotion(Base):
    __tablename__ = "tb_promotion"  # 프로모션 마스터

    # column
    promotion_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    promotion_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="프로모션 구분 - 직접, 신청",
    )
    promotion_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="프로모션 이름"
    )
    from_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="프로모션 시작 일시"
    )
    to_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="프로모션 종료 일시"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    apply_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="신청구분 - 요일, 날짜",
    )
    apply_status: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="신청 상태 - 신청, 승인, 철회",
    )
    available_apply_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="신청 가능 일자"
    )
    interval_apply_days: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="신청 가능 일자에 더해지는 term"
    )
    max_seat_count: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="최대 신청 가능 수"
    )
    item_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="아이템 구분 - 대여권(ticket) 등등",
    )
    item_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="아이템 아이디"
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


class EventVote(Base):
    __tablename__ = "tb_event_vote"  # 투표 상세

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="투표 작품 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    round_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="투표 회차"
    )
    from_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="투표 시작일"
    )
    to_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="투표 종료일"
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


class EventVoteWinner(Base):
    __tablename__ = "tb_event_vote_winner"  # 투표 결과

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="투표 작품 아이디"
    )
    rank_no: Mapped[int] = mapped_column(Integer, server_default="0", comment="순위")
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    round_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="투표 회차"
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


class EventVoteUserReq(Base):
    __tablename__ = "tb_event_vote_user_req"  # 투표 신청

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="투표 작품 아이디"
    )
    round_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="투표 회차"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
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


class EventVoteProductItem(Base):
    __tablename__ = "tb_event_vote_product_item"  # 투표 작품 목록

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="투표 작품 아이디"
    )
    round_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="투표 회차"
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


class EventVoteRoundAnswer(Base):
    __tablename__ = "tb_event_vote_round_answer"

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    round_product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="투표 작품 아이디"
    )
    round_no: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="투표 회차"
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


class QuestUser(Base):
    __tablename__ = "tb_quest_user"  # 퀘스트 진행 유저 목록

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quest_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="퀘스트 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    achieve_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="달성 여부"
    )
    reward_own_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="보상 소유 여부"
    )
    current_stage: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="현재 진행단계"
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


class QuestReward(Base):
    __tablename__ = "tb_quest_reward"  # 퀘스트 보상

    # column
    reward_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    quest_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="퀘스트 아이디"
    )
    item_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="아이템 아이디"
    )
    item_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="보상 아이템 타입",
    )
    item_name: Mapped[str] = mapped_column(
        String(200), nullable=True, comment="보상 아이템 이름"
    )
    goal_stage: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="보상 목표 단계"
    )
    quantity: Mapped[int] = mapped_column(Integer, server_default="0", comment="수량")
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


class CarouselBanner(Base):
    __tablename__ = "tb_carousel_banner"  # 캐러셀 배너

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="노출 위치, main (메인: 대배너(상단 캐러셀), 띠배너(중간), 고정배너(하단)) | paid (메인>유료: 대배너(상단 캐러셀)) | review (메인>작품리뷰: 대배너(상단 캐러셀)) | promotion (메인>프로모션: 고정배너(상단)) | search (검색/검색결과: 고정배너(상단) | viewer (뷰어: 띠배너))",
    )
    division: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="노출 위치 (position이 main인 경우 세부 위치), top (대배너(상단 캐러셀)) | mid (띠배너(중간)) | bot (고정배너(하단))",
    )
    title: Mapped[str] = mapped_column(
        String(1000), index=True, nullable=False, comment="배너명"
    )
    show_start_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, index=True, nullable=False, comment="노출 기간 시작일"
    )
    show_end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, index=True, nullable=False, comment="노출 기간 종료일"
    )
    show_order: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="노출 순서"
    )
    url: Mapped[str] = mapped_column(
        String(1000), index=True, nullable=False, comment="링크 url"
    )
    image_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="이미지 id"
    )
    mobile_image_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="모바일 이미지 id"
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


class PublisherPromotion(Base):
    __tablename__ = "tb_publisher_promotion"  # 출판사 프로모션

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    show_order: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="노출 순서"
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
