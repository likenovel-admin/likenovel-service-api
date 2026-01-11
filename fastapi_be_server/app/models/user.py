from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.const import settings
from app.rdb import Base


class User(Base):
    __tablename__ = "tb_user"  # 유저 마스터

    # column
    user_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kc_user_id: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, comment="키클록 user_entity pk"
    )
    email: Mapped[str] = mapped_column(
        String(100),
        nullable=True,
        comment="이메일(sns 로그인 연동은 서비스 제공자에 등록된 값 그대로 활용)",
    )
    gender: Mapped[str] = mapped_column(String(1), nullable=True, comment="성별")
    birthdate: Mapped[str] = mapped_column(
        String(10), nullable=True, comment="생년월일"
    )
    user_name: Mapped[str] = mapped_column(String(100), nullable=True, comment="실명")
    mobile_no: Mapped[str] = mapped_column(
        String(100), nullable=True, comment="휴대폰번호"
    )
    identity_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="본인인증 여부"
    )
    agree_terms_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="Y",
        comment="이용약관 동의 여부",
    )
    agree_privacy_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="Y",
        comment="개인정보 동의 여부",
    )
    agree_age_limit_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="만14세이상 여부"
    )
    stay_signed_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="로그인유지 여부"
    )
    latest_signed_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="최근 로그인한 일자"
    )
    latest_signed_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="최근 로그인 타입(자체, 네이버, 구글, 카카오, 애플)",
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    role_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        server_default="normal",
        index=True,
        nullable=False,
        comment="권한 - 일반, 관리자",
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


class UserNotification(Base):
    __tablename__ = "tb_user_notification"  # 유저 알림 수신 동의

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    noti_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="알림 동의 여부 - 혜택정보, 댓글, 시스템, 이벤트",
    )
    noti_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="알림 여부"
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


class UserNotificationItem(Base):
    __tablename__ = "tb_user_notification_item"  # 유저 알림

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    noti_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="알림 타입",
    )
    read_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="읽음 여부"
    )
    title: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="제목"
    )
    content: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="내용"
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


class UserSocial(Base):
    __tablename__ = "tb_user_social"  # 로그인 연동 정보 (회원가입에서 ins)

    # column
    sns_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    integrated_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="통합 유저 아이디"
    )
    sns_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="회원가입 경로 - 라이크노벨 자체, 네이버, 구글, 카카오, 애플",
    )
    sns_link_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        index=True,
        nullable=False,
        comment="sns 로그인 연동 고유 발급 아이디",
    )
    default_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="N",
        comment="최초 본인인증 여부",
    )
    temp_issued_key: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        index=True,
        nullable=True,
        comment="정보 리턴용 임시 키",
    )
    access_token: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="액세스 토큰"
    )
    access_expire_in: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="액세스 토큰 만료 시간"
    )
    refresh_token: Mapped[str] = mapped_column(
        String(3000), nullable=True, comment="리프레시 토큰"
    )
    refresh_expire_in: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="리프레시 토큰 만료 시간"
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


class UserProfileApply(Base):
    __tablename__ = "tb_user_profile_apply"  # 프로필 자격 신청 (CP/편집자 신청에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    apply_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="권한 타입",
    )
    company_name: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="회사이름"
    )
    email: Mapped[str] = mapped_column(
        String(100), nullable=True, comment="연락받을 이메일"
    )
    attach_file_id_1st: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="첨부파일1 아이디"
    )
    attach_file_id_2nd: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="첨부파일2 아이디"
    )
    approval_code: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="승인 코드",
    )
    approval_message: Mapped[str] = mapped_column(
        String(500), nullable=True, comment="승인 메시지"
    )
    approval_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="승인한 아이디"
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


class UserProfile(Base):
    __tablename__ = "tb_user_profile"  # 프로필 정보 (회원가입, 프로필 추가에서 ins)

    # column
    profile_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    nickname: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        unique=True,
        nullable=False,
        comment="닉네임",
    )
    default_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="프로필 선택 여부"
    )
    role_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="권한 - 독자, 작가, CP, 편집자, 엔터사",
    )
    profile_image_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="프로필 이미지 파일"
    )
    nickname_change_max_count: Mapped[int] = mapped_column(
        Integer, server_default="3", comment="닉네임 최대 변경 가능 횟수"
    )
    nickname_change_count: Mapped[int] = mapped_column(
        Integer, server_default="3", comment="닉네임 변경 가능 횟수"
    )
    paid_change_count: Mapped[int] = mapped_column(
        Integer, server_default="0", comment="구매한 닉네임 변경권 횟수"
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


class UserBadge(Base):
    __tablename__ = "tb_user_badge"  # 뱃지 정보(관심, 이벤트) (회원가입에서 ins)

    # column
    badge_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    profile_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="프로필 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    badge_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="뱃지 유형 - 이벤트, 뱃지",
    )
    badge_level: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="레벨 수치"
    )
    badge_image_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="뱃지 이미지 파일"
    )
    display_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="뱃지 선택 여부"
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


class UserBlock(Base):
    __tablename__ = "tb_user_block"  # 차단 목록 (작품 댓글 차단/차단해제에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
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
    off_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="차단한 유저 아이디"
    )
    off_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="차단 여부"
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


class UserReport(Base):
    __tablename__ = "tb_user_report"  # 신고 목록 (작품 댓글 신고에서 ins)

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="회차 아이디"
    )
    comment_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="댓글 아이디"
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    reported_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="신고된 유저 아이디"
    )
    report_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="신고 타입",
    )
    content: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="신고 내용"
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


class UserAlarm(Base):
    __tablename__ = "tb_user_alarm"  # 유저 알림 목록

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    title: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="제목"
    )
    content: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE), nullable=True, comment="내용"
    )
    read_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="읽음 여부"
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


class UserCashbook(Base):
    __tablename__ = "tb_user_cashbook"  # 사용자 캐시 잔액

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    balance: Mapped[int] = mapped_column(Integer, server_default="0", comment="잔액")
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


class UserCashbookTransaction(Base):
    __tablename__ = "tb_user_cashbook_transaction"  # 사용자 캐시 히스토리

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    from_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="송신한 유저 아이디"
    )
    to_user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="수신한 유저 아이디"
    )
    amount: Mapped[int] = mapped_column(Integer, server_default="0", comment="수량")
    sponsor_type: Mapped[str] = mapped_column(
        String(20),
        nullable=True,
        comment="후원 타입 (author: 작가 후원, product: 작품 후원)",
    )
    product_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="후원 대상 작품 ID (작품 후원인 경우)"
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


class UserGiftbook(Base):
    __tablename__ = "tb_user_giftbook"  # 사용자 선물함

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer,
        index=True,
        nullable=True,
        comment="대여권 발급 대상 작품 (NULL이면 전체 작품)",
    )
    episode_id: Mapped[int] = mapped_column(
        Integer,
        index=True,
        nullable=True,
        comment="대여권 발급 대상 에피소드 (NULL이면 해당 작품의 전체 에피소드)",
    )
    ticket_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="대여권 타입",
    )
    own_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        nullable=False,
        comment="보유 타입 (rental, own)",
    )
    read_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="읽음 여부"
    )
    received_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="N", comment="선물받기 여부"
    )
    received_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="선물받기한 날짜"
    )
    reason: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        server_default="",
        comment="대여권 지급 사유",
    )
    amount: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="대여권 장수"
    )
    acquisition_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="획득 방식 (event, promotion, admin_direct 등)",
    )
    acquisition_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="획득 방식의 ID (프로모션 ID, 이벤트 ID 등)"
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


class UserGiftTransaction(Base):
    __tablename__ = "tb_user_gift_transaction"  # 사용자 선물함 히스토리

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="타입 - received(받은 내역), used(사용 내역)",
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    giftbook_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="선물함 아이디"
    )
    ticket_item_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="대여권 아이디"
    )
    amount: Mapped[int] = mapped_column(
        Integer, server_default="1", comment="대여권 장수"
    )
    reason: Mapped[str] = mapped_column(
        String(settings.VARCHAR_COMM_SIZE),
        server_default="",
        comment="거래 사유",
    )
    created_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserTicketbook(Base):
    __tablename__ = "tb_user_ticketbook"  # 사용자 이용권

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ticket_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="대여권타입",
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="작품 아이디"
    )
    use_expired_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="대여권 만료일자"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    created_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserTicketTransaction(Base):
    __tablename__ = "tb_user_ticket_transaction"  # 사용자 이용권 히스토리

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserProductbook(Base):
    __tablename__ = "tb_user_productbook"  # 사용자 대여권

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    own_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="보유 타입(소장, 대여)",
    )
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    profile_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="프로필 아이디"
    )
    product_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="작품 아이디"
    )
    episode_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="회차 아이디"
    )
    ticket_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=False,
        comment="티켓 타입",
    )
    acquisition_type: Mapped[str] = mapped_column(
        String(settings.VARCHAR_CODE_SIZE),
        index=True,
        nullable=True,
        comment="획득 방식 - applied_promotion(신청 프로모션), direct_promotion(직접 프로모션), event(이벤트), gift(선물), quest(퀘스트)",
    )
    acquisition_id: Mapped[int] = mapped_column(
        Integer,
        index=True,
        nullable=True,
        comment="획득 방식의 ID (프로모션 ID, 이벤트 ID 등)",
    )
    rental_expired_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="대여권 만료일자"
    )
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    use_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="사용한 날짜"
    )
    created_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserProductTransaction(Base):
    __tablename__ = "tb_user_product_transaction"  # 사용자 대여권 히스토리

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 생성한 id"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_id: Mapped[str] = mapped_column(
        String(settings.VARCHAR_ID_SIZE), nullable=True, comment="row를 갱신한 id"
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class UserSuggest(Base):
    __tablename__ = "tb_user_suggest"  # 사용자별 추천

    # column
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, index=True, nullable=False, comment="유저 아이디"
    )
    feature: Mapped[int] = mapped_column(
        Integer, index=True, nullable=True, comment="feature"
    )
    target: Mapped[str] = mapped_column(
        String(100),
        index=True,
        nullable=True,
        comment="타겟(성별+연령 형식 ex - male20)",
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
