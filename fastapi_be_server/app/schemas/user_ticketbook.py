from datetime import datetime
from pydantic import BaseModel, Field
from typing import Optional


class UserTicketbookBase(BaseModel):
    pass


"""
request area
"""


class PostUserTicketbookReqBody(UserTicketbookBase):
    # 사용자 이용권 등록 요청 시 클라이언트에서 보내는 request body
    ticket_type: str = Field(examples=["type"], description="사용자 이용권 타입")
    user_id: int = Field(examples=[1], description="유저 아이디")
    product_id: int = Field(examples=[1], description="작품 아이디")
    use_expired_date: Optional[datetime] = Field(
        examples=["2024-12-31T23:59:59"], description="사용자 이용권 만료일자"
    )
    use_yn: Optional[str] = Field(
        default="N", examples=["N"], description="사용자 이용권 만료일자"
    )


class PutUserTicketbookReqBody(UserTicketbookBase):
    # 사용자 이용권 수정 요청 시 클라이언트에서 보내는 request body
    ticket_type: Optional[str] = Field(
        examples=["type"], description="사용자 이용권 타입"
    )
    user_id: Optional[int] = Field(examples=[1], description="유저 아이디")
    product_id: Optional[int] = Field(examples=[1], description="작품 아이디")
    use_expired_date: Optional[datetime] = Field(
        examples=["2024-12-31T23:59:59"], description="사용자 이용권 만료일자"
    )
    use_yn: Optional[str] = Field(
        default="N", examples=["N"], description="사용자 이용권 만료일자"
    )


"""
response area
"""
