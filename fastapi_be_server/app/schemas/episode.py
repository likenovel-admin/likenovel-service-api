from pydantic import BaseModel, Field, field_validator
from typing import Optional

from datetime import datetime


class EpisodesBase(BaseModel):
    pass


"""
request area
"""


class PostEpisodesProductsProductIdReqBody(EpisodesBase):
    # 회차 저장/등록 요청 시 클라이언트에서 보내는 request body
    title: str = Field(examples=["라이크노벨 1회차"], description="제목")
    content: str = Field(examples=["가나다라마바사"], description="내용")
    author_comment: Optional[str] = Field(
        default=None, examples=["안녕하세요"], description="작가의 말"
    )
    evaluation_open_yn: str = Field(examples=["Y"], description="평가 오픈 여부")
    comment_open_yn: str = Field(examples=["Y"], description="댓글 오픈 여부")
    episode_open_yn: str = Field(examples=["Y"], description="회차공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약설정"
    )
    price_type: Optional[str] = Field(
        default=None, examples=[""], description="무료 여부(free, paid)"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None

        return value


class PutEpisodesEpisodeIdReqBody(EpisodesBase):
    # 회차 수정 요청 시 클라이언트에서 보내는 request body
    title: str = Field(examples=["라이크노벨 1회차"], description="제목")
    content: str = Field(examples=["가나다라마바사"], description="내용")
    author_comment: Optional[str] = Field(
        default=None, examples=["안녕하세요"], description="작가의 말"
    )
    evaluation_open_yn: str = Field(examples=["Y"], description="평가 오픈 여부")
    comment_open_yn: str = Field(examples=["Y"], description="댓글 오픈 여부")
    episode_open_yn: str = Field(examples=["Y"], description="회차공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약설정"
    )
    price_type: Optional[str] = Field(
        default=None, examples=[""], description="무료 여부(free, paid)"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None

        return value


class PostEpisodesEpisodeIdEvaluationReqBody(EpisodesBase):
    # 회차 평가 요청 시 클라이언트에서 보내는 request body
    rating: str = Field(
        examples=["highlypositive"],
        description="평가 등급(highlypositive, verypositive, positive, somewhatpositive, neutral, somewhatnegative, negative, verynegative, highlynegative)",
    )


class PurchaseEpisodeWithCashReqBody(EpisodesBase):
    # 회차 구매 요청 시 클라이언트에서 보내는 request body
    profile_id: int = Field(description="프로필 ID")


"""
response area
"""
