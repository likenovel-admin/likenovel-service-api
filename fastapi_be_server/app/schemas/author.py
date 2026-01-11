from pydantic import BaseModel, Field


class AuthorBase(BaseModel):
    pass


"""
request area
"""


class SponsorAuthorReqBody(AuthorBase):
    # 작가 후원 요청 시 클라이언트에서 보내는 request body
    profile_id: int = Field(description="프로필 ID")
    donation_price: int = Field(description="후원 금액", gt=0)
    message: str = Field(default="", description="전달 메시지")


"""
response area
"""
