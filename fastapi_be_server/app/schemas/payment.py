from typing import Optional
from pydantic import BaseModel, Field


class PaymentsBase(BaseModel):
    pass


"""
request area
"""


class VirtualAccountReqBody(PaymentsBase):
    storeId: Optional[str] = Field(examples=["1234567890"], description="가맹점 아이디")
    # store_id: Optional[str]                 = Field(examples=["1234567890"], description="가맹점 아이디")
    # store_name: Optional[str]               = Field(examples=["가맹점 이름"], description="가맹점 이름")
    # store_code: Optional[str]               = Field(examples=["1234567890"], description="가맹점 코드")
    # virtual_account_number: Optional[str]   = Field(examples=["1234567890"], description="가상계좌 번호")
    # virtual_account_name: Optional[str]     = Field(examples=["가상계좌 이름"], description="가상계좌 이름")
    # virtual_account_bank: Optional[str]     = Field(examples=["가상계좌 은행"], description="가상계좌 은행")

    pass


"""
response area
"""
