from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class UserProductbookBase(BaseModel):
    pass


"""
request area
"""


class PostUserProductbookReqBody(UserProductbookBase):
    # 사용자 이용권 등록 요청 시 클라이언트에서 보내는 request body
    ticket_type: str = Field(examples=["type"], description="사용자 대여권 타입")
    own_type: str = Field(examples=["own"], description="보유 타입(소장, 대여)")
    user_id: int = Field(examples=[1], description="유저 아이디")
    profile_id: int = Field(examples=[1], description="프로필 아이디")
    product_id: Optional[int] = Field(
        examples=[1], description="작품 아이디, null이면 모든 작품 대상"
    )
    episode_id: Optional[int] = Field(
        examples=[1],
        description="회차 아이디, null이면 product_id의 작품의 전체 에피소드 대상",
    )
    acquisition_type: Optional[str] = Field(
        default=None,
        examples=["applied_promotion"],
        description="획득 방식 - applied_promotion, direct_promotion, event, gift, quest",
    )
    acquisition_id: Optional[int] = Field(
        default=None,
        examples=[1],
        description="획득 방식의 ID (프로모션 ID, 이벤트 ID 등)",
    )
    rental_expired_date: Optional[datetime] = Field(
        examples=["2024-12-31T23:59:59"], description="사용자 대여권 만료일자"
    )
    use_yn: Optional[str] = Field(
        default="N", examples=["N"], description="사용자 대여권 만료일자"
    )


class PutUserProductbookReqBody(UserProductbookBase):
    # 사용자 이용권 수정 요청 시 클라이언트에서 보내는 request body
    ticket_type: Optional[str] = Field(
        examples=["type"], description="사용자 대여권 타입"
    )
    own_type: Optional[str] = Field(
        examples=["own"], description="보유 타입(소장, 대여)"
    )
    user_id: Optional[int] = Field(examples=[1], description="유저 아이디")
    profile_id: Optional[int] = Field(examples=[1], description="프로필 아이디")
    product_id: Optional[int] = Field(examples=[1], description="작품 아이디")
    episode_id: Optional[int] = Field(examples=[1], description="회차 아이디")
    acquisition_type: Optional[str] = Field(
        default=None,
        examples=["applied_promotion"],
        description="획득 방식 - applied_promotion, direct_promotion, event, gift, quest",
    )
    acquisition_id: Optional[int] = Field(
        default=None,
        examples=[1],
        description="획득 방식의 ID (프로모션 ID, 이벤트 ID 등)",
    )
    rental_expired_date: Optional[datetime] = Field(
        examples=["2024-12-31T23:59:59"], description="사용자 대여권 만료일자"
    )
    use_yn: Optional[str] = Field(
        default="N", examples=["N"], description="사용자 대여권 만료일자"
    )


class UseUserProductbookReqBody(UserProductbookBase):
    # 사용자 대여권 사용 요청 시 클라이언트에서 보내는 request body
    episode_id: int = Field(examples=[1], description="사용할 에피소드 ID")


"""
response area
"""
