from pydantic import BaseModel, Field
from typing import Optional


class ProductEvaluationBase(BaseModel):
    pass


"""
request area
"""


class PostProductEvaluationReqBody(ProductEvaluationBase):
    # 사용자 이용권 등록 요청 시 클라이언트에서 보내는 request body
    product_id: int = Field(examples=[1], description="작품 아이디")
    episode_id: int = Field(examples=[1], description="회차 아이디")
    user_id: int = Field(examples=[1], description="유저 아이디")
    eval_code: str = Field(examples=["eval_code"], description="평가 코드")
    use_yn: Optional[str] = Field(default="Y", examples=["Y"], description="사용 여부")


class PutProductEvaluationReqBody(ProductEvaluationBase):
    # 사용자 이용권 수정 요청 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(examples=[1], description="작품 아이디")
    episode_id: Optional[int] = Field(examples=[1], description="회차 아이디")
    user_id: Optional[int] = Field(examples=[1], description="유저 아이디")
    eval_code: Optional[str] = Field(examples=["eval_code"], description="평가 코드")
    use_yn: Optional[str] = Field(default="Y", examples=["Y"], description="사용 여부")


"""
response area
"""
