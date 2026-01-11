from pydantic import BaseModel, Field
from typing import Optional


class NoticeBase(BaseModel):
    pass


"""
request area
"""


class PostNoticeReqBody(NoticeBase):
    # 공지사항 등록 요청 시 클라이언트에서 보내는 request body
    subject: Optional[str] = Field(examples=["subject"], description="공지 제목")
    content: Optional[str] = Field(examples=["content"], description="공지 내용")
    primary_yn: Optional[str] = Field(
        default="N", examples=["N"], description="우선순위 여부"
    )
    use_yn: Optional[str] = Field(default="Y", examples=["Y"], description="사용 여부")


class PutNoticeReqBody(NoticeBase):
    # 공지사항 수정 요청 시 클라이언트에서 보내는 request body
    subject: Optional[str] = Field(examples=["subject"], description="공지 제목")
    content: Optional[str] = Field(examples=["content"], description="공지 내용")
    primary_yn: Optional[str] = Field(
        default="N", examples=["N"], description="우선순위 여부"
    )
    use_yn: Optional[str] = Field(default="Y", examples=["Y"], description="사용 여부")


"""
response area
"""
