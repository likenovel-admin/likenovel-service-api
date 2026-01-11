from pydantic import BaseModel, Field
from typing import Optional


class AdminBase(BaseModel):
    pass


"""
request area
"""


class PutProductReqBody(AdminBase):
    # 관리자 수정 요청 시 클라이언트에서 보내는 request body
    title: Optional[str] = Field(
        default=None, examples=["작품명"], description="작품명"
    )
    ratings_code: Optional[str] = Field(
        default=None, examples=["all"], description="연령등급(전체-all, 성인-adult)"
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
        description="연재 상태코드(연재중-ongoing, 휴재중-rest, 완결-end, 연재중지-stop)",
    )
    uci: Optional[str] = Field(default=None, examples=["uci"], description="uci 코드")
    isbn: Optional[str] = Field(
        default=None, examples=["isbn"], description="isbn 코드"
    )
    series_regular_price: Optional[int] = Field(
        default=None, examples=[100], description="연재 가격"
    )
    single_regular_price: Optional[int] = Field(
        default=None, examples=[100], description="단행본 가격"
    )
    cp_company_name: Optional[str] = Field(
        default=None, examples=[""], description="cp사명, 설정 안하는 경우 빈 문자열"
    )
    monopoly_yn: Optional[str] = Field(
        default=None, examples=["Y"], description="독점 여부"
    )
    open_yn: Optional[str] = Field(
        default=None,
        examples=["Y"],
        description="공개 여부, 작품 블라인드 체크시 N, 체크 해제시 Y",
    )
    cp_offered_price: Optional[float] = Field(
        default=None,
        examples=[100],
        description="cp사 제안 금액, 만원 단위, 100입력시 100만원, cp_id값이 있는 경우 필수",
    )
    cp_settlement_rate: Optional[float] = Field(
        default=None,
        examples=[85],
        description="cp사-작가 정산시 작가의 정산비, 전체 100을 기준으로 작성해주세요, cp_id값이 있는 경우 필수",
    )


class PutPtnProductSalesReqBody(AdminBase):
    # 관리자 수정 요청 시 클라이언트에서 보내는 request body
    sum_settlement_price_web: Optional[int] = Field(
        default=None, examples=[40000], description="유상 정산액"
    )
    sum_settlement_comped_ticket_price: Optional[int] = Field(
        default=None, examples=[40000], description="무상 정산액"
    )
    tax_price: Optional[int] = Field(default=None, examples=[40000], description="세액")
    settlement_rate: Optional[float] = Field(
        default=None, examples=[70], description="정산율"
    )
    fee: Optional[float] = Field(default=None, examples=[30], description="결제 수수료")


"""
response area
"""
