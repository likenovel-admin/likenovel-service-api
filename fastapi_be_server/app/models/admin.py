from sqlalchemy import Integer, String, TIMESTAMP, text
from sqlalchemy.orm import Mapped, mapped_column

from datetime import datetime

from app.const import settings
from app.rdb import Base


class AlgorithmRecommendUser(Base):
    """
    알고리즘 추천구좌 - 유저 테이블

    이 테이블은 각 사용자의 feature 값을 저장합니다.
    feature_basic~feature_10의 값은 카테고리 번호이며,
    tb_algorithm_recommend_set_topic 테이블의 target 칼럼과 매칭됩니다.

    예시:
    - user_id=123, feature_1=3 인 경우
      -> tb_algorithm_recommend_set_topic 테이블에서 feature='feature_1' AND target=3 인 레코드를 찾아서 추천

    feature 값:
    - feature_basic: 성별과 연령을 합친 값 (예: male_1, female_2)
    - feature_1~feature_5: 데이터 분석에 따라 이용자를 구분하는 카테고리 번호
    - feature_6~feature_10: 추가 분석 카테고리 번호
    - NULL 또는 0: feature가 설정되지 않은 경우 (default 추천만 표시)

    주의사항:
    - feature 값은 tb_algorithm_recommend_set_topic의 id 칼럼이 아닌 target 칼럼과 매칭됩니다!
    - 잘못된 예: if user_features[feature_name] != slot_id  # slot_id는 테이블의 id 칼럼
    - 올바른 예: if user_features[feature_name] != target  # target은 테이블의 target 칼럼
    """

    __tablename__ = "tb_algorithm_recommend_user"  # 알고리즘 추천구좌 - 유저 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="사용자 id")
    feature_basic: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="feature_basic, 성별(male/female) + 연령(1(10대)|2(20대)|3(30대)|4(40대)|5(50대이상))",
    )
    feature_1: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_1"
    )
    feature_2: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_2"
    )
    feature_3: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_3"
    )
    feature_4: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_4"
    )
    feature_5: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_5"
    )
    feature_6: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_6"
    )
    feature_7: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_7"
    )
    feature_8: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_8"
    )
    feature_9: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_9"
    )
    feature_10: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature_10"
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


class AlgorithmRecommendSetTopic(Base):
    """
    알고리즘 추천구좌 - 주제 설정 테이블

    이 테이블은 각 feature별로 추천할 작품 목록을 저장합니다.
    tb_algorithm_recommend_user 테이블의 feature 값과 이 테이블의 target 칼럼을 매칭하여 추천합니다.

    칼럼 설명:
    - feature: 유저 테이블의 feature와 동일한 값 (예: feature_1, feature_2, default_1 등)
              default_*는 feature가 설정되지 않은 유저를 대상으로 함
    - target: 유저 테이블의 feature 값과 매치되는 카테고리 번호
              예: feature='feature_1', target=3 이면
                  -> tb_algorithm_recommend_user에서 feature_1=3인 유저에게 추천
    - title: 각 feature에 대한 타이틀 (화면에 표시)
    - novel_list: 각 feature마다 속한 작품의 id 리스트 (JSON 배열 형태)

    예시 데이터:
    - id=20, feature='feature_1', target=3, title='로맨스 팬을 위한', novel_list=[1,2,3]
      -> feature_1=3인 유저에게 작품 1,2,3을 '로맨스 팬을 위한' 제목으로 추천

    - id=1, feature='default_1', target='default', title='인기 작품', novel_list=[10,11,12]
      -> 모든 유저에게 작품 10,11,12를 '인기 작품' 제목으로 추천

    주의사항:
    - 추천 매칭 로직에서 target 칼럼을 사용해야 하며, id 칼럼을 사용하면 안 됩니다!
    - 잘못된 예: user_features[feature_name] != hit.get("id")
    - 올바른 예: user_features[feature_name] != hit.get("target")
    """

    __tablename__ = (
        "tb_algorithm_recommend_set_topic"  # 알고리즘 추천구좌 - 주제 설정 테이블
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    feature: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="feature"
    )
    target: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="target, 성별(male/female) + 연령(1(10대)|2(20대)|3(30대)|4(40대)|5(50대이상))",
    )
    title: Mapped[str] = mapped_column(String(1000), nullable=False, comment="타이틀")
    novel_list: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="작품 id - json 배열 형태"
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


class AlgorithmRecommendSection(Base):
    __tablename__ = "tb_algorithm_recommend_section"  # 알고리즘 추천구좌 - 추천 섹션

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    position: Mapped[str] = mapped_column(String(1000), nullable=False, comment="위치")
    feature: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="feature, default_1~4|feature_basic|feature_1~10",
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


class AlgorithmRecommendSimilar(Base):
    __tablename__ = "tb_algorithm_recommend_similar"  # 알고리즘 추천구좌 - 추천1 내용비슷, 추천2 장르비슷, 추천3 장바구니

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    type: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="내용비슷(content) | 장르비슷(genre) | 장바구니(cart)",
    )
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="작품 id")
    similar_subject_ids: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="similar_subject_ids - json 배열 형태"
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


class DirectRecommend(Base):
    __tablename__ = "tb_direct_recommend"  # 직접 추천구좌

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="추천구좌명"
    )
    order: Mapped[int] = mapped_column(Integer, nullable=False, comment="노출 순서")
    product_ids: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="노출 작품 - json 배열 형태"
    )
    exposure_start_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="노출 기간 시작일"
    )
    exposure_end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="노출 기간 종료일"
    )
    exposure_start_time_weekday: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="노출 시간 주중 시작 시간"
    )
    exposure_end_time_weekday: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="노출 시간 주중 종료 시간"
    )
    exposure_start_time_weekend: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="노출 시간 주말 시작 시간"
    )
    exposure_end_time_weekend: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="노출 시간 주말 종료 시간"
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


class DirectPromotion(Base):
    __tablename__ = "tb_direct_promotion"  # 직접 프로모션

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="작품 id")
    start_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="시작일"
    )
    type: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="프로모션 종류, 첫방문자 무료 (free-for-first) | 선작 독자 (reader-of-prev)",
    )
    status: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="상태, 진행중 (ing) | 중지 (stop)"
    )
    num_of_ticket_per_person: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="명당 증정 대여권 수"
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


class AppliedPromotion(Base):
    __tablename__ = "tb_applied_promotion"  # 신청 프로모션

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="작품 id")
    type: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="프로모션 종류, 기다리면 무료 (waiting-for-free) | 6-9 패스 (6-9-path)",
    )
    status: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="상태, 진행중 (ing) | 신청 (apply) | 철회 (cancel) | 종료 (end) | 반려 (deny)",
    )
    start_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="시작일"
    )
    end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="종료일"
    )
    num_of_ticket_per_person: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="명당 증정 대여권 수"
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


class ChatRoom(Base):
    __tablename__ = "tb_chat_rooms"  # 1:1 대화방 테이블

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ChatRoomMember(Base):
    __tablename__ = "tb_chat_room_members"  # 대화방 멤버 및 읽음 상태 관리

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="대화방 ID")
    profile_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="프로필 ID"
    )
    last_read_message_id: Mapped[int] = mapped_column(
        Integer, nullable=True, comment="마지막으로 읽은 메시지 ID"
    )
    is_active: Mapped[str] = mapped_column(
        String(1),
        nullable=False,
        server_default="Y",
        comment="활성 여부 (채팅방 나갔는지)",
    )
    left_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=True, comment="채팅방 나간 시간"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ChatMessage(Base):
    __tablename__ = "tb_chat_messages"  # 1:1 대화 메시지

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    room_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="대화방 ID")
    sender_profile_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="발신인 profile_id"
    )
    content: Mapped[str] = mapped_column(
        String(10000), nullable=False, comment="메시지 내용"
    )
    is_deleted: Mapped[str] = mapped_column(
        String(1), nullable=False, server_default="N", comment="삭제 여부"
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class ChatMessageReport(Base):
    __tablename__ = "tb_chat_message_reports"  # 메시지 신고 관리

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="신고된 메시지 ID"
    )
    reporter_profile_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="신고자 profile_id"
    )
    reason: Mapped[str] = mapped_column(
        String(1000), nullable=True, comment="신고 사유"
    )
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        server_default="pending",
        comment="처리 상태 (pending, reviewed, rejected)",
    )
    created_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_date: Mapped[datetime] = mapped_column(
        TIMESTAMP,
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )


class PushMessageTemplates(Base):
    __tablename__ = "tb_push_message_templates"  # 푸시 메시지 템플릿

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    use_yn: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE), server_default="Y", comment="사용 여부"
    )
    name: Mapped[str] = mapped_column(String(1000), nullable=False, comment="템플릿명")
    condition: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="발송 조건"
    )
    landing_page: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="랜딩 페이지"
    )
    image_id: Mapped[int] = mapped_column(Integer, nullable=True, comment="이미지 파일")
    contents: Mapped[str] = mapped_column(String(1000), nullable=True, comment="본문")
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


class EventV2(Base):
    __tablename__ = "tb_event_v2"  # 이벤트 (기존꺼 필요한건지 확인 필요, 기존꺼 필요 없으면 삭제할 예정)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(1000), nullable=False, comment="이벤트명")
    start_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="이벤트 기간 (시작일)"
    )
    end_date: Mapped[datetime] = mapped_column(
        TIMESTAMP, nullable=False, comment="이벤트 기간 (종료일)"
    )
    type: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="이벤트 종류, 3화 감상 (view-3-times) | 댓글 등록 (add-comment) | 작품 등록 (add-product) | 그 외 (etc)",
    )
    target_product_ids: Mapped[str] = mapped_column(
        String(1000),
        nullable=True,
        comment="이벤트 작품 등록, 3화 감상, 댓글 등록인 경우의 대상 작품들의 id - json 배열 형태",
    )
    reward_type: Mapped[str] = mapped_column(
        Integer,
        nullable=True,
        comment="이벤트 보상 (type이 etc인 경우 null) - 보상 종류, 이벤트 대여권 (ticket) | 캐시 (cash)",
    )
    reward_amount: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        comment="이벤트 보상 (type이 etc인 경우 null) - 증정 갯수",
    )
    reward_max_people: Mapped[int] = mapped_column(
        Integer,
        nullable=True,
        comment="이벤트 보상 (type이 etc인 경우 null) - 최대 인원",
    )
    show_yn_thumbnail_img: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="Y",
        comment="노출 여부 - 썸네일 이미지",
    )
    show_yn_detail_img: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="Y",
        comment="노출 여부 - 상세 이미지",
    )
    show_yn_product: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="Y",
        comment="노출 여부 - 작품 구좌",
    )
    show_yn_information: Mapped[str] = mapped_column(
        String(settings.VARCHAR_YN_SIZE),
        server_default="Y",
        comment="노출 여부 - 안내 문구",
    )
    thumbnail_image_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="썸네일 이미지 파일"
    )
    detail_image_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="상세 이미지 파일"
    )
    account_name: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="구좌명"
    )
    product_ids: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="노출 구좌에 노출될 잘품들의 id - json 배열 형태",
    )
    information: Mapped[str] = mapped_column(
        String(1000), nullable=False, comment="안내 문구"
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


class EventV2RewardRecipient(Base):
    __tablename__ = "tb_event_v2_reward_recipient"  # 이벤트 보상 수령인

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="이벤트 id")
    user_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="수령인 id")
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
