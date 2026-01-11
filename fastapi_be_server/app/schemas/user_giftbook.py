from pydantic import BaseModel, Field
from typing import Optional


class UserGiftbookBase(BaseModel):
    pass


"""
request area
"""


class PostUserGiftbookReqBody(UserGiftbookBase):
    # 선물함 등록 요청 시 클라이언트에서 보내는 request body
    user_id: int = Field(examples=[1], description="유저 아이디")
    product_id: Optional[int] = Field(
        default=None,
        examples=[1],
        description="대여권 발급 대상 작품 (NULL이면 전체 작품)",
    )
    episode_id: Optional[int] = Field(
        default=None,
        examples=[1],
        description="대여권 발급 대상 에피소드 (NULL이면 해당 작품의 전체 에피소드)",
    )
    ticket_type: str = Field(
        examples=["comped"], description="대여권 타입 (comped, paid 등)"
    )
    own_type: str = Field(examples=["rental"], description="보유 타입 (rental, own)")
    acquisition_type: Optional[str] = Field(
        default=None,
        examples=["event"],
        description="획득 방식 (event, promotion, admin_direct 등)",
    )
    acquisition_id: Optional[int] = Field(
        default=None,
        examples=[1],
        description="획득 방식의 ID (프로모션 ID, 이벤트 ID 등)",
    )
    reason: Optional[str] = Field(
        default="", examples=["이벤트 보상"], description="대여권 지급 사유"
    )
    amount: Optional[int] = Field(default=1, examples=[1], description="대여권 장수")
    promotion_type: Optional[str] = Field(
        default=None,
        examples=["free-for-first"],
        description="프로모션 타입 (free-for-first, reader-of-prev, 6-9-path, waiting-for-free 등)",
    )
    expiration_date: Optional[str] = Field(
        default=None,
        examples=["2025-12-31 23:59:59"],
        description="선물함 만료일 (NULL이면 무기한, 단 첫방문자 무료는 프로모션 종료 시 만료)",
    )
    ticket_expiration_type: Optional[str] = Field(
        default=None,
        examples=["days"],
        description="수령 후 대여권 유효기간 타입 (none: 무기한, days: 일수, hours: 시간, on_receive_days: 수령 시점부터 일수)",
    )
    ticket_expiration_value: Optional[int] = Field(
        default=None,
        examples=[7],
        description="유효기간 값 (days, hours, on_receive_days에 따른 숫자)",
    )


class PutUserGiftbookReqBody(UserGiftbookBase):
    # 선물함 수정 요청 시 클라이언트에서 보내는 request body
    user_id: Optional[int] = Field(
        default=None, examples=[1], description="유저 아이디"
    )
    product_id: Optional[int] = Field(
        default=None, examples=[1], description="대여권 발급 대상 작품"
    )
    episode_id: Optional[int] = Field(
        default=None, examples=[1], description="대여권 발급 대상 에피소드"
    )
    ticket_type: Optional[str] = Field(
        default=None, examples=["comped"], description="대여권 타입"
    )
    own_type: Optional[str] = Field(
        default=None, examples=["rental"], description="보유 타입"
    )
    acquisition_type: Optional[str] = Field(
        default=None, examples=["event"], description="획득 방식"
    )
    acquisition_id: Optional[int] = Field(
        default=None, examples=[1], description="획득 방식의 ID"
    )
    read_yn: Optional[str] = Field(
        default=None, examples=["N"], description="읽음 여부"
    )
    received_yn: Optional[str] = Field(
        default=None, examples=["N"], description="선물받기 여부"
    )
    reason: Optional[str] = Field(
        default=None, examples=["이벤트 보상"], description="대여권 지급 사유"
    )
    amount: Optional[int] = Field(default=None, examples=[1], description="대여권 장수")


"""
response area
"""
