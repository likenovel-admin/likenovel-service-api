from pydantic import BaseModel, Field
from typing import Optional, Literal


class ProductReviewBase(BaseModel):
    pass


"""
request area
"""


class PostProductReviewReqBody(ProductReviewBase):
    # 사용자 이용권 등록 요청 시 클라이언트에서 보내는 request body
    product_id: int = Field(examples=[1], description="작품 아이디")
    user_id: int = Field(examples=[1], description="유저 아이디")
    review_title: str = Field(
        examples=["정말 재미있는 작품입니다"], description="리뷰 제목", max_length=200
    )
    review_text: str = Field(examples=["text"], description="리뷰 내용")


class PutProductReviewReqBody(ProductReviewBase):
    # 사용자 이용권 수정 요청 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(examples=[1], description="작품 아이디")
    user_id: Optional[int] = Field(examples=[1], description="유저 아이디")
    review_title: Optional[str] = Field(
        examples=["정말 재미있는 작품입니다"], description="리뷰 제목", max_length=200
    )
    review_text: Optional[str] = Field(examples=["text"], description="리뷰 내용")


class PostProductReviewCommentReqBody(ProductReviewBase):
    # 리뷰 댓글 작성 요청 시 클라이언트에서 보내는 request body
    comment_text: str = Field(examples=["댓글 내용입니다"], description="댓글 내용")


class PutProductReviewCommentReqBody(ProductReviewBase):
    # 리뷰 댓글 수정 요청 시 클라이언트에서 보내는 request body
    comment_text: str = Field(
        examples=["수정된 댓글 내용입니다"], description="댓글 내용"
    )


class PostProductReviewReportReqBody(ProductReviewBase):
    # 리뷰 신고 요청 시 클라이언트에서 보내는 request body
    report_reason: Literal[
        "offensive_discriminatory",  # 불쾌한 표현 및 차별/혐오성 표현
        "religious_political",  # 종교 및 정치 관련 내용
        "illegal_content",  # 범죄/불법정보 포함
        "sexual_content",  # 반사회적인 성적 표현
        "spam_advertisement",  # 스팸홍보/도배
    ] = Field(
        examples=["offensive_discriminatory"],
        description="신고 사유 - offensive_discriminatory: 불쾌한 표현 및 차별/혐오성 표현, religious_political: 종교 및 정치 관련 내용, illegal_content: 범죄/불법정보 포함, sexual_content: 반사회적인 성적 표현, spam_advertisement: 스팸홍보/도배",
    )
    report_detail: Optional[str] = Field(
        None,
        examples=["상세한 신고 내용입니다"],
        description="신고 상세 내용",
        max_length=1000,
    )


class PostProductReviewCommentReportReqBody(ProductReviewBase):
    # 리뷰 댓글 신고 요청 시 클라이언트에서 보내는 request body
    report_reason: Literal[
        "offensive_discriminatory",  # 불쾌한 표현 및 차별/혐오성 표현
        "religious_political",  # 종교 및 정치 관련 내용
        "illegal_content",  # 범죄/불법정보 포함
        "sexual_content",  # 반사회적인 성적 표현
        "spam_advertisement",  # 스팸홍보/도배
    ] = Field(
        examples=["offensive_discriminatory"],
        description="신고 사유 - offensive_discriminatory: 불쾌한 표현 및 차별/혐오성 표현, religious_political: 종교 및 정치 관련 내용, illegal_content: 범죄/불법정보 포함, sexual_content: 반사회적인 성적 표현, spam_advertisement: 스팸홍보/도배",
    )
    report_detail: Optional[str] = Field(
        None,
        examples=["상세한 신고 내용입니다"],
        description="신고 상세 내용",
        max_length=1000,
    )


"""
response area
"""
