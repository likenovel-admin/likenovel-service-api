from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class SupportBase(BaseModel):
    pass


"""
request area
"""


class PostSupportQnaReqBody(SupportBase):
    model_config = ConfigDict(str_strip_whitespace=True)

    category: Literal[
        "서비스문의",
        "결제문의",
        "정산문의",
        "바라는점",
        "회원상태문의",
        "버그리포팅",
        "제휴문의",
        "작품신고",
        "악성유저신고",
        "게시물신고",
    ]
    subject: str = Field(min_length=1, max_length=300)
    content: str = Field(min_length=1, max_length=20000)
    email: str = Field(
        min_length=3,
        max_length=100,
        pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$",
    )

"""
response area
"""


# camel 표기법으로 치환(쿼리 결과 가공없이 그대로 대입 시에만 사용)
class SupportSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class GetSupportFaqsToCamel(SupportSchema):
    id: int
    type: str
    type_name: str | None = None
    question: str
    answer: str
    posting_date: datetime


class GetSupportFaqCategoryToCamel(SupportSchema):
    code: str
    name: str
    sort_order: int


class GetSupportFaqsFaqIdToCamel(SupportSchema):
    title: str
    posting_date: datetime
    content: str
