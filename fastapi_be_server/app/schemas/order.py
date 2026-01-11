from pydantic import BaseModel, Field


class OrdersBase(BaseModel):
    pass


"""
request area
"""


class OrderCashReqBody(OrdersBase):
    payment_id: str = Field(examples=["1234567890"], description="결제 아이디")
    tx_id: str = Field(examples=["tx1234567890"], description="결제 트랜잭션 아이디")


"""
response area
"""
