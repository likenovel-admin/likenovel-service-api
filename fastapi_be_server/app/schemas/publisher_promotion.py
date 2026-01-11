from pydantic import BaseModel


class PublisherPromotionBase(BaseModel):
    pass


"""
request area
"""


class PostPublisherPromotionReqBody(PublisherPromotionBase):
    # 출판사 프로모션 등록 요청 시 클라이언트에서 보내는 request body
    # TODO 구현
    # cover_image_file_id: Optional[int]   = Field(default=None, examples=[1], description="표지 이미지 파일 id")
    # ongoing_state: str                   = Field(examples=["ongoing"], description="연재 상태(ongoing, rest, end, stop)")
    # title: str                           = Field(examples=["라이크노벨 작품"], description="제목")
    # author_nickname: str                 = Field(examples=["제로콜라"], description="작가명")
    # illustrator_nickname: Optional[str]  = Field(default=None, examples=[""], description="그림 작가명")
    # update_frequency: List[str]          = Field(examples=[["mon", "tue"]], description="연재 요일")
    # publish_regular_yn: str              = Field(examples=["Y"], description="정기여부")
    # primary_genre: str                   = Field(examples=["판타지"], description="1차 장르")
    # sub_genre: Optional[str]             = Field(default=None, examples=[""], description="2차 장르")
    # keywords: Optional[List[str]]        = Field(default=None, examples=[[""]], description="기본태그")
    # custom_keywords: Optional[List[str]] = Field(default=None, examples=[[""]], description="직접입력태그")
    # synopsis: str                        = Field(examples=["작품에 대한 소개입니다."], description="작품소개")
    # adult_yn: str                        = Field(examples=["N"], description="연령등급(전체이용가 n, 성인 y)")
    # open_yn: str                         = Field(examples=["Y"], description="공개설정")
    # monopoly_yn: str                     = Field(examples=["N"], description="독점여부")
    # cp_contract_yn: str                  = Field(examples=["N"], description="계약여부")
    pass


class PutPublisherPromotionReqBody(PublisherPromotionBase):
    # 출판사 프로모션 수정 요청 시 클라이언트에서 보내는 request body
    # TODO 구현
    # cover_image_file_id: Optional[int]   = Field(default=None, examples=[1], description="표지 이미지 파일 id")
    # ongoing_state: str                   = Field(examples=["ongoing"], description="연재 상태(ongoing, rest, end, stop)")
    # title: str                           = Field(examples=["라이크노벨 작품"], description="제목")
    # author_nickname: str                 = Field(examples=["제로콜라"], description="작가명")
    # illustrator_nickname: Optional[str]  = Field(default=None, examples=[""], description="그림 작가명")
    # update_frequency: List[str]          = Field(examples=[["mon", "tue"]], description="연재 요일")
    # publish_regular_yn: str              = Field(examples=["Y"], description="정기여부")
    # primary_genre: str                   = Field(examples=["판타지"], description="1차 장르")
    # sub_genre: Optional[str]             = Field(default=None, examples=[""], description="2차 장르")
    # keywords: Optional[List[str]]        = Field(default=None, examples=[[""]], description="기본태그")
    # custom_keywords: Optional[List[str]] = Field(default=None, examples=[[""]], description="직접입력태그")
    # synopsis: str                        = Field(examples=["작품에 대한 소개입니다."], description="작품소개")
    # adult_yn: str                        = Field(examples=["N"], description="연령등급(전체이용가 n, 성인 y)")
    # open_yn: str                         = Field(examples=["Y"], description="공개설정")
    # monopoly_yn: str                     = Field(examples=["N"], description="독점여부")
    # cp_contract_yn: str                  = Field(examples=["N"], description="계약여부")
    pass


"""
response area
"""
