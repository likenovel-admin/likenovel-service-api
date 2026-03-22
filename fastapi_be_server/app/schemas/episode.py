from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class EpisodesBase(BaseModel):
    pass


"""
request area
"""


class PostEpisodesProductsProductIdReqBody(EpisodesBase):
    # 회차 저장/등록 요청 body
    title: str = Field(examples=["라이크노벨 1회차"], description="제목")
    content: str = Field(examples=["가나다라마바사"], description="내용")
    author_comment: Optional[str] = Field(
        default=None, examples=["안녕하세요"], description="작가 코멘트"
    )
    evaluation_open_yn: str = Field(examples=["Y"], description="평가 오픈 여부")
    comment_open_yn: str = Field(examples=["Y"], description="댓글 오픈 여부")
    episode_open_yn: str = Field(examples=["Y"], description="회차 공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약 설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약 공개 일시"
    )
    price_type: Optional[str] = Field(
        default=None, examples=["free"], description="회차 가격 타입(free, paid)"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None
        return value


class PostEpisodesProductsProductIdEpubReqBody(EpisodesBase):
    # 회차 EPUB 개별 업로드 body
    title: str = Field(examples=["라이크노벨 1회차"], description="제목")
    epub_file_id: int = Field(examples=[1], description="EPUB 파일 스토리지 그룹 ID")
    episode_no: Optional[int] = Field(
        default=None,
        examples=[1],
        description="회차 번호(미입력 시 자동 증가값 사용)",
    )
    author_comment: Optional[str] = Field(
        default=None, examples=["안녕하세요"], description="작가 코멘트"
    )
    evaluation_open_yn: str = Field(examples=["Y"], description="평가 오픈 여부")
    comment_open_yn: str = Field(examples=["Y"], description="댓글 오픈 여부")
    episode_open_yn: str = Field(examples=["Y"], description="회차 공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약 설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약 공개 일시"
    )
    price_type: Optional[str] = Field(
        default=None, examples=["free"], description="회차 가격 타입(free, paid)"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None
        return value


class PostEpisodesProductsProductIdEpubBatchReqBody(EpisodesBase):
    # 회차 EPUB 일괄 업로드 body
    episodes: List[PostEpisodesProductsProductIdEpubReqBody] = Field(
        default_factory=list, description="업로드할 회차 목록"
    )


class EpisodeTitleBulkUpdateItem(EpisodesBase):
    no: int = Field(examples=[1], description="회차 번호")
    file_name: str = Field(examples=["1.epub"], description="현재 EPUB 파일명")
    title: str = Field(examples=["1화 새로운 제목"], description="변경할 회차명")


class PostEpisodesProductsProductIdTitlesBulkReqBody(EpisodesBase):
    episodes: List[EpisodeTitleBulkUpdateItem] = Field(
        default_factory=list, description="회차명 일괄 수정 대상 목록"
    )


class PostEpisodesReviewRequestsReqBody(EpisodesBase):
    episode_ids: List[int] = Field(
        default_factory=list, description="심사 신청할 회차 ID 목록"
    )


class PostEpisodesReviewCancelReqBody(EpisodesBase):
    apply_ids: List[int] = Field(
        default_factory=list, description="심사 신청 취소할 apply ID 목록"
    )


class PostEpisodesDeleteReqBody(EpisodesBase):
    episode_ids: List[int] = Field(
        default_factory=list, description="삭제할 회차 ID 목록"
    )


class PostEpisodesSaleStartReqBody(EpisodesBase):
    episode_ids: List[int] = Field(
        default_factory=list, description="판매 시작할 회차 ID 목록"
    )


class PostEpisodesSaleReserveReqBody(EpisodesBase):
    episode_ids: List[int] = Field(
        default_factory=list, description="판매 예약할 회차 ID 목록"
    )
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2026-12-31T23:59:59"], description="판매 예약 일시"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_sale_reserve_date(cls, value):
        if value == "Invalid Date" or not value:
            return None
        return value


class PostEpisodesSaleReserveCancelReqBody(EpisodesBase):
    episode_ids: List[int] = Field(
        default_factory=list, description="판매 예약 취소할 회차 ID 목록"
    )


class PutEpisodesEpisodeIdReqBody(EpisodesBase):
    # 회차 수정 요청 body
    title: str = Field(examples=["라이크노벨 1회차"], description="제목")
    content: str = Field(examples=["가나다라마바사"], description="내용")
    author_comment: Optional[str] = Field(
        default=None, examples=["안녕하세요"], description="작가 코멘트"
    )
    evaluation_open_yn: str = Field(examples=["Y"], description="평가 오픈 여부")
    comment_open_yn: str = Field(examples=["Y"], description="댓글 오픈 여부")
    episode_open_yn: str = Field(examples=["Y"], description="회차 공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약 설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약 공개 일시"
    )
    price_type: Optional[str] = Field(
        default=None, examples=["free"], description="회차 가격 타입(free, paid)"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None
        return value


class PostEpisodesEpisodeIdEvaluationReqBody(EpisodesBase):
    rating: str = Field(
        examples=["highlypositive"],
        description="평가 등급(highlypositive, verypositive, positive, somewhatpositive, neutral, somewhatnegative, negative, verynegative, highlynegative)",
    )


class PurchaseEpisodeWithCashReqBody(EpisodesBase):
    profile_id: int = Field(description="프로필 ID")


"""
response area
"""
