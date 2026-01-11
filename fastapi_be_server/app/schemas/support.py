from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from datetime import datetime


class SupportBase(BaseModel):
    pass


"""
request area
"""

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
    question: str
    answer: str
    posting_date: datetime


class GetSupportFaqsFaqIdToCamel(SupportSchema):
    title: str
    posting_date: datetime
    content: str
