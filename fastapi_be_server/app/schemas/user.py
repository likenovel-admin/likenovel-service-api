from pydantic import BaseModel, Field, ConfigDict
from pydantic.alias_generators import to_camel
from typing import Optional

from datetime import datetime


class UserBase(BaseModel):
    pass


"""
request area
"""


class PostUserApplyRoleReqBody(UserBase):
    # CP/편집자 신청 요청 시 클라이언트에서 보내는 request body
    apply_type: str = Field(examples=["cp"], description="신청구분(cp, editor)")
    company_name: str = Field(examples=["cp회사"], description="회사명")
    email: str = Field(examples=["test@test.com"], description="연락받을 이메일")
    attachment_file_id_1st: int = Field(examples=[1], description="서류 첨부 파일1 id")
    attachment_file_id_2nd: Optional[int] = Field(
        default=None, examples=[], description="서류 첨부 파일1 id"
    )


class PostUserProfilesReqBody(UserBase):
    # 프로필 추가 요청 시 클라이언트에서 보내는 request body
    user_nickname: str = Field(examples=["제로콜라"], description="닉네임")
    event_badge_yn: str = Field(examples=["Y"], description="선택한 이벤트 뱃지 id")
    interest_badge_yn: str = Field(examples=["N"], description="선택한 관심 뱃지 id")
    default_yn: str = Field(examples=["Y"], description="대표 프로필 설정 여부")
    profile_image_file_id: Optional[int] = Field(
        default=None, examples=[], description="프로필 이미지 파일 id"
    )


class PutUserProfilesProfileIdReqBody(UserBase):
    # 프로필 수정 요청 시 클라이언트에서 보내는 request body
    user_nickname: Optional[str] = Field(
        default=None, examples=["제로콜라"], description="닉네임"
    )
    event_badge_id: Optional[int] = Field(
        default=None, examples=[1], description="선택한 이벤트 뱃지 id"
    )
    interest_badge_id: Optional[int] = Field(
        default=None, examples=[], description="선택한 관심 뱃지 id"
    )
    default_yn: Optional[str] = Field(
        default=None, examples=["Y"], description="대표 프로필 설정 여부"
    )
    profile_image_file_id: Optional[int] = Field(
        default=None, examples=[], description="프로필 이미지 파일 id"
    )


class PostUserNicknameDuplicateCheckReqBody(UserBase):
    # 닉네임 중복 확인 요청 시 클라이언트에서 보내는 request body
    user_nickname: str = Field(examples=["제로콜라"], description="닉네임")


class PostDirectPromotionTicketCountReqBody(UserBase):
    # 닉네임 중복 확인 요청 시 클라이언트에서 보내는 request body
    num_of_ticket_per_person_for_free_for_first: int = Field(
        examples=[1], description="명당 증정 대여권 수 - 첫 방문자 무료 대여권"
    )
    num_of_ticket_per_person_for_reader_of_prev: int = Field(
        examples=[1], description="명당 증정 대여권 수 - 선작 독자 무료 대여권"
    )


class PostAppliedPromotionReqBody(UserBase):
    # 작가의 작품 프로모션 신청 요청 시 클라이언트에서 보내는 request body
    type: str = Field(
        examples=["waiting-for-free"],
        description="프로모션 종류, 기다리면 무료 (waiting-for-free) | 6-9 패스 (6-9-path)",
    )
    start_date: str = Field(examples=["2025-08-01"], description="시작일")
    end_date: str = Field(examples=["2025-08-02"], description="종료일")


class PostNotificationToBookmarkedReqBody(UserBase):
    # 작가의 작품 프로모션 신청 요청 시 클라이언트에서 보내는 request body
    content: str = Field(
        examples=["알림 내용입니다 50자 이내로 입력하세요"], description="알림 내용"
    )


class PutNotificationSettingsReqBody(UserBase):
    # 작가의 작품 프로모션 신청 요청 시 클라이언트에서 보내는 request body
    benefit: Optional[str] = Field(
        default=None, examples=["Y"], description="혜택정보 알림"
    )
    comment: Optional[str] = Field(
        default=None, examples=["Y"], description="댓글 알림"
    )
    system: Optional[str] = Field(
        default=None, examples=["Y"], description="시스템 알림"
    )
    event: Optional[str] = Field(
        default=None, examples=["Y"], description="이벤트 알림"
    )
    marketing: Optional[str] = Field(
        default=None, examples=["Y"], description="마케팅 정보 수신 동의"
    )


"""
response area
"""


# camel 표기법으로 치환(쿼리 결과 가공없이 그대로 대입 시에만 사용)
class UserSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class GetUserProfilesToCamel(UserSchema):
    profile_id: int
    user_profile_image_path: Optional[str]
    user_nickname: str
    user_interest_level_badge_image_path: Optional[str]
    user_event_level_badge_image_path: Optional[str]
    user_role: str
    default_yn: str
    nickname_changeable_count: int


class GetUserCashToCamel(UserSchema):
    category: str
    amount: int
    product_title: Optional[str]
    episode_title: Optional[str]
    created_date: datetime


class GetUserCommentsToCamel(UserSchema):
    comment_id: int
    user_id: int
    user_nickname: str
    user_profile_image_path: Optional[str]
    user_interest_level_badge_image_path: Optional[str]
    user_event_level_badge_image_path: Optional[str]
    content: str
    publish_date: datetime
    recommend_count: int
    not_recommend_count: int
    recommend_yn: str
    not_recommend_yn: str
    user_role: str
    comment_episode: Optional[str]
    review_title: Optional[str] = None
    product_title: str
    comment_type: Optional[str] = "episode"


class GetUserCommentsBlockToCamel(UserSchema):
    comment_id: Optional[int] = None
    review_id: Optional[int] = None
    user_id: int
    user_nickname: str
    user_profile_image_path: Optional[str]
    user_interest_level_badge_image_path: Optional[str]
    user_event_level_badge_image_path: Optional[str]
    publish_date: datetime
    comment_type: Optional[str] = "episode"


class GetUserAlarmsToCamel(UserSchema):
    alarm_id: int
    noti_type: str
    noti_yn: str
    author: bool
    title: str
    content: str
    created_at: datetime


class PurchaseNicknameChangeResponse(UserSchema):
    # 닉네임 변경권 구매 응답
    success: bool = Field(description="구매 성공 여부")
    remaining_cash: int = Field(description="남은 캐시")
    nickname_change_count: int = Field(description="무료 닉네임 변경 가능 횟수")
    paid_change_count: int = Field(description="구매한 닉네임 변경권 횟수")


class PostUserRecentProductReqBody(UserBase):
    # 최근 본 작품 저장 요청 시 클라이언트에서 보내는 request body
    product_id: int = Field(examples=[1], description="작품 ID")
