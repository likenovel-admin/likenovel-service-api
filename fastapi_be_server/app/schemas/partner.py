from pydantic import BaseModel, Field
from typing import Optional


class AdminBase(BaseModel):
    pass


"""
request area
"""


class PutProductReqBody(AdminBase):
    # 파트너/관리자 작품 수정 request body
    author_nickname: Optional[str] = Field(
        default=None, examples=["작가명"], description="작가명"
    )
    cover_image_file_id: Optional[int] = Field(
        default=None, examples=[123], description="표지 이미지 파일 ID"
    )
    title: Optional[str] = Field(
        default=None, examples=["작품명"], description="작품명"
    )
    synopsis: Optional[str] = Field(
        default=None, examples=["작품 소개"], description="작품 소개"
    )
    ratings_code: Optional[str] = Field(
        default=None, examples=["all"], description="연령등급(all, 15, adult)"
    )
    primary_genre_id: Optional[int] = Field(
        default=None, examples=[1], description="1차 장르"
    )
    sub_genre_id: Optional[int] = Field(
        default=None, examples=[2], description="2차 장르"
    )
    status_code: Optional[str] = Field(
        default=None,
        examples=["ongoing"],
        description="연재 상태코드(ongoing, rest, end, stop)",
    )
    uci: Optional[str] = Field(default=None, examples=["uci"], description="UCI 코드")
    isbn: Optional[str] = Field(default=None, examples=["isbn"], description="ISBN 코드")
    series_regular_price: Optional[int] = Field(
        default=None, examples=[100], description="연재 가격"
    )
    single_regular_price: Optional[int] = Field(
        default=None, examples=[100], description="단행본 소장 가격"
    )
    single_rental_price: Optional[int] = Field(
        default=None, examples=[100], description="단행본 대여 가격"
    )
    cp_company_name: Optional[str] = Field(
        default=None, examples=[""], description="CP명, 미지정이면 빈 문자열"
    )
    monopoly_yn: Optional[str] = Field(
        default=None, examples=["Y"], description="독점 여부"
    )
    open_yn: Optional[str] = Field(
        default=None, examples=["Y"], description="공개 여부"
    )
    blind_yn: Optional[str] = Field(
        default=None, examples=["N"], description="블라인드 여부"
    )
    cp_offered_price: Optional[float] = Field(
        default=None,
        examples=[100],
        description="CP 제안 금액(만원 단위)",
    )
    cp_settlement_rate: Optional[float] = Field(
        default=None,
        examples=[85],
        description="CP 정산율(0~100)",
    )
    free_episode_start_no: Optional[int] = Field(
        default=None, examples=[1], description="무료회차 시작 번호"
    )
    free_episode_end_no: Optional[int] = Field(
        default=None, examples=[20], description="무료회차 종료 번호"
    )


class PutPtnProductSalesReqBody(AdminBase):
    # 파트너 정산 수정 request body
    sum_settlement_price_web: Optional[int] = Field(
        default=None, examples=[40000], description="유상 정산액"
    )
    sum_settlement_comped_ticket_price: Optional[int] = Field(
        default=None, examples=[40000], description="무상 정산액"
    )
    tax_price: Optional[int] = Field(default=None, examples=[40000], description="원천세")
    settlement_rate: Optional[float] = Field(
        default=None, examples=[70], description="정산율"
    )
    fee: Optional[float] = Field(default=None, examples=[30], description="결제 수수료")


"""
response area
"""
