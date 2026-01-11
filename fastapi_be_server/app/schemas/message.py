from pydantic import BaseModel, Field
from typing import Optional, Literal


class MessagesBase(BaseModel):
    pass


"""
request area
"""


class PostChatRoomReqBody(MessagesBase):
    """대화방 생성 요청"""

    target_user_id: int = Field(examples=[123], description="대화 상대 사용자 ID")
    default_message: Optional[str] = Field(
        default=None,
        examples=["계약 제안 드립니다."],
        description="첫 메시지 (선택사항)",
    )


class PostChatMessageReqBody(MessagesBase):
    """메시지 전송 요청"""

    content: str = Field(examples=["안녕하세요!"], description="메시지 내용")


class PostChatMessageReportReqBody(MessagesBase):
    """대화방 신고 요청"""

    report_reason: Literal[
        "threat_extortion",  # 협박/갈취/비합리적 금전적 대가 요구
        "fraud_impersonation",  # 사기/허위 업체/특정 인물 및 업체 사칭
        "spam_off_platform",  # 반복적 메시지 발송/플랫폼 밖에서만 협의요구
        "privacy_copyright",  # 개인 신상정보 침해 및 저작권 침해
        "illegal_content",  # 범죄/불법정보 포함
        "spam_advertisement",  # 스팸홍보/도배
    ] = Field(
        examples=["threat_extortion"],
        description="신고 사유 - threat_extortion: 협박/갈취/비합리적 금전적 대가 요구, fraud_impersonation: 사기/허위 업체/특정 인물 및 업체 사칭, spam_off_platform: 반복적 메시지 발송/플랫폼 밖에서만 협의요구, privacy_copyright: 개인 신상정보 침해 및 저작권 침해, illegal_content: 범죄/불법정보 포함, spam_advertisement: 스팸홍보/도배",
    )
    report_detail: Optional[str] = Field(
        default=None, examples=["상세 신고 내용"], description="신고 상세 내용"
    )


"""
response area
"""
