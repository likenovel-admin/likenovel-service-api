from pydantic import BaseModel, Field
from typing import Optional


class TicketItemBase(BaseModel):
    pass


"""
request area
"""


class PostTicketItemReqBody(TicketItemBase):
    # 이용권/대여권 등록 요청 시 클라이언트에서 보내는 request body
    ticket_type: str = Field(examples=["type"], description="티켓 타입")
    ticket_name: Optional[str] = Field(examples=["name"], description="티켓 이름")
    price: Optional[int] = Field(default=0, examples=[0], description="티켓 금액")
    settlement_yn: Optional[str] = Field(
        default="N", examples=["N"], description="정산 여부"
    )
    expired_hour: Optional[int] = Field(
        default=0, examples=[0], description="사용 만료시간"
    )
    use_yn: Optional[str] = Field(default="Y", examples=["Y"], description="사용 여부")
    target_products: Optional[list[int]] = Field(
        default=[],
        examples=[[1, 2, 3]],
        description="사용 가능한 작품, 빈배열이면 전체 작품에 사용 가능",
    )


class PutTicketItemReqBody(TicketItemBase):
    # 이용권/대여권 수정 요청 시 클라이언트에서 보내는 request body
    ticket_type: Optional[str] = Field(examples=["type"], description="티켓 타입")
    ticket_name: Optional[str] = Field(examples=["name"], description="티켓 이름")
    price: Optional[int] = Field(default=0, examples=[0], description="티켓 금액")
    settlement_yn: Optional[str] = Field(
        default="N", examples=["N"], description="정산 여부"
    )
    expired_hour: Optional[int] = Field(
        default=0, examples=[0], description="사용 만료시간"
    )
    use_yn: Optional[str] = Field(default="Y", examples=["Y"], description="사용 여부")
    target_products: Optional[list[int]] = Field(
        default=[],
        examples=[[1, 2, 3]],
        description="사용 가능한 작품, 빈배열이면 전체 작품에 사용 가능",
    )


"""
response area
"""
