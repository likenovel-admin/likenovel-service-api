from pydantic import BaseModel, Field, ConfigDict, field_validator
from pydantic.alias_generators import to_camel
from typing import Optional, List

from datetime import datetime


class ProductsBase(BaseModel):
    pass


"""
request area
"""


class PostProductsReqBody(ProductsBase):
    # 작품 등록 요청 시 클라이언트에서 보내는 request body
    cover_image_file_id: Optional[int] = Field(
        default=None, examples=[1], description="표지 이미지 파일 id"
    )
    ongoing_state: str = Field(
        examples=["ongoing"], description="연재 상태(ongoing, rest, end, stop)"
    )
    title: str = Field(examples=["라이크노벨 작품"], description="제목")
    author_nickname: str = Field(examples=["제로콜라"], description="작가명")
    illustrator_nickname: Optional[str] = Field(
        default=None, examples=[""], description="그림 작가명"
    )
    update_frequency: List[str] = Field(
        examples=[["mon", "tue"]], description="연재 요일"
    )
    publish_regular_yn: str = Field(examples=["Y"], description="정기여부")
    primary_genre: str = Field(examples=["판타지"], description="1차 장르")
    sub_genre: Optional[str] = Field(
        default=None, examples=[""], description="2차 장르"
    )
    keywords: Optional[List[str]] = Field(
        default=None, examples=[[""]], description="기본태그"
    )
    custom_keywords: Optional[List[str]] = Field(
        default=None, examples=[[""]], description="직접입력태그"
    )
    synopsis: str = Field(examples=["작품에 대한 소개입니다."], description="작품소개")
    adult_yn: str = Field(examples=["N"], description="연령등급(전체이용가 n, 성인 y)")
    open_yn: str = Field(examples=["Y"], description="공개설정")
    monopoly_yn: str = Field(examples=["N"], description="독점여부")
    cp_contract_yn: str = Field(examples=["N"], description="계약여부")


class PutProductsProductIdReqBody(ProductsBase):
    # 작품 정보수정 요청 시 클라이언트에서 보내는 request body
    cover_image_file_id: Optional[int] = Field(
        default=None, examples=[1], description="표지 이미지 파일 id"
    )
    ongoing_state: str = Field(
        examples=["ongoing"], description="연재 상태(ongoing, rest, end, stop)"
    )
    title: str = Field(examples=["라이크노벨 작품"], description="제목")
    author_nickname: str = Field(examples=["제로콜라"], description="작가명")
    illustrator_nickname: Optional[str] = Field(
        default=None, examples=[""], description="그림 작가명"
    )
    update_frequency: List[str] = Field(
        examples=[["mon", "tue"]], description="연재 요일"
    )
    publish_regular_yn: str = Field(examples=["Y"], description="정기여부")
    primary_genre: str = Field(examples=["판타지"], description="1차 장르")
    sub_genre: Optional[str] = Field(
        default=None, examples=[""], description="2차 장르"
    )
    keywords: Optional[List[str]] = Field(
        default=None, examples=[[""]], description="기본태그"
    )
    custom_keywords: Optional[List[str]] = Field(
        default=None, examples=[[""]], description="직접입력태그"
    )
    synopsis: str = Field(examples=["작품에 대한 소개입니다."], description="작품소개")
    adult_yn: str = Field(examples=["N"], description="연령등급(전체이용가 n, 성인 y)")
    open_yn: str = Field(examples=["Y"], description="공개설정")
    monopoly_yn: str = Field(examples=["N"], description="독점여부")
    cp_contract_yn: str = Field(examples=["N"], description="계약여부")
    paid_setting_date: Optional[datetime] = Field(
        default=None,
        examples=["2024-12-31T23:59:59"],
        description="유료회차 설정일자-유료전환 승인시에만 입력 가능",
    )
    paid_episode_no: Optional[int] = Field(
        default=None,
        examples=[10],
        description="유료 시작 회차-유료전환 승인시에만 입력 가능",
    )

    @field_validator("paid_setting_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None

        return value


class PostProductsCommentsEpisodesEpisodeIdReqBody(ProductsBase):
    # 작품 댓글 등록 요청 시 클라이언트에서 보내는 request body
    content: str = Field(examples=["가나다라마바사"], description="댓글 내용")


class PutProductsCommentsCommentIdReqBody(ProductsBase):
    # 작품 댓글 수정 요청 시 클라이언트에서 보내는 request body
    content: str = Field(examples=["가나다라마바사"], description="댓글 내용")


class PostProductsCommentsCommentIdReportReqBody(ProductsBase):
    # 작품 댓글 신고 요청 시 클라이언트에서 보내는 request body
    reportType: str = Field(examples=["신고내용1"], description="신고 타입")
    content: str = Field(examples=["가나다라마바사"], description="신고 내용")


class PostProductReportReqBody(ProductsBase):
    # 작품 신고 요청 시 클라이언트에서 보내는 request body
    reportType: str = Field(examples=["신고내용1"], description="신고 타입")
    content: str = Field(examples=["가나다라마바사"], description="신고 내용")


class PostProductsProductIdNoticesReqBody(ProductsBase):
    # 작품 공지 저장/등록 요청 시 클라이언트에서 보내는 request body
    title: str = Field(examples=["라이크노벨 작품 공지"], description="제목")
    content: str = Field(examples=["가나다라마바사"], description="내용")
    open_yn: str = Field(examples=["Y"], description="공지공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약설정"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None

        return value


class PutProductsNoticesProductNoticeIdReqBody(ProductsBase):
    # 작품 공지 수정 요청 시 클라이언트에서 보내는 request body
    title: str = Field(examples=["라이크노벨 작품 공지"], description="제목")
    content: str = Field(examples=["가나다라마바사"], description="내용")
    open_yn: str = Field(examples=["Y"], description="공지공개 여부")
    publish_reserve_yn: str = Field(examples=["N"], description="예약설정 여부")
    publish_reserve_date: Optional[datetime] = Field(
        default=None, examples=["2024-12-31T23:59:59"], description="예약설정"
    )

    @field_validator("publish_reserve_date", mode="before")
    def validate_date(cls, value):
        if value == "Invalid Date" or not value:
            return None

        return value


class PostProductsProductIdContractOfferReqBody(ProductsBase):
    # 계약 제안 요청 시 클라이언트에서 보내는 request body
    advance_payment_range: str = Field(
        examples=["50~100"],
        description="선인세 범위(~50, 50~100, 100~200, 200~300, 300~400, 500~)",
    )
    cp_profit_rate: float = Field(
        examples=[30], description="CP 정산비율(퍼센트, 예: 30 = 30%)"
    )
    author_profit_rate: float = Field(
        examples=[70], description="작가 정산비율(퍼센트, 예: 70 = 70%)"
    )
    message: str = Field(examples=["제안 메시지입니다."], description="제안 메시지")


class PurchaseAllEpisodesWithCashReqBody(ProductsBase):
    # 작품 전체 에피소드 구매 요청 시 클라이언트에서 보내는 request body
    profile_id: int = Field(description="프로필 ID")


class SponsorProductReqBody(ProductsBase):
    # 작품 후원 요청 시 클라이언트에서 보내는 request body
    profile_id: int = Field(description="프로필 ID")
    donation_price: int = Field(description="후원 금액", gt=0)
    message: str = Field(default="", description="전달 메시지")


"""
response area
"""


# camel 표기법으로 치환(쿼리 결과 가공없이 그대로 대입 시에만 사용)
class ProductsSchema(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel, populate_by_name=True, from_attributes=True
    )


class GetProductsProductIdCommentsToCamel(ProductsSchema):
    comment_id: int
    user_id: int
    user_nickname: str
    user_profile_image_path: str
    user_interest_level_badge_image_path: str
    user_event_level_badge_image_path: str
    content: str
    publish_date: datetime
    author_pinned_top_yn: str
    author_recommend_yn: str
    recommend_count: int
    not_recommend_count: int
    recommend_yn: str
    not_recommend_yn: str
    user_role: str
    comment_episode: str
    author_nickname: str
    author_profile_image_path: str


class GetProductsGenresToCamel(ProductsSchema):
    genre_id: int
    genre: str
