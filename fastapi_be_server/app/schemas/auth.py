from pydantic import BaseModel, Field, EmailStr, field_validator
from typing import Optional

import re


class AuthBase(BaseModel):
    pass


"""
request area
"""


class SignupReqBody(AuthBase):
    # 회원가입 요청 시 클라이언트에서 보내는 request body
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")
    password: str = Field(examples=["test1234!"], description="비밀번호")
    birthdate: str = Field(examples=["2000-01-31"], description="생년월일(YYYY-MM-DD)")
    gender: str = Field(examples=["M"], description="성별(M, F)")
    ad_info_agree_yn: str = Field(
        examples=["N"], description="광고성정보 수신동의 여부"
    )
    sns_signup_type: Optional[str] = Field(
        default=None,
        example="",
        description="sns 로그인 연동 경로(naver, google, kakao, apple)",
    )
    sns_link_id: Optional[str] = Field(
        default=None, example="", description="sns 로그인 연동시 발급된 id"
    )
    sns_keep_signin_yn: Optional[str] = Field(
        default=None, example="", description="sns 로그인 연동시 로그인 상태 유지 여부"
    )

    @field_validator("email")
    def validate_email(cls, value):
        if len(value) > 100:
            raise ValueError("이메일은 최대 100자 이하")

        return value

    @field_validator("password")
    def validate_password(cls, value):
        if not (8 <= len(value) <= 20):
            raise ValueError("최소 8자 이상 최대 20자 이하")

        if not re.search(r"[A-Za-z]", value):
            raise ValueError("영문 포함")
        if not re.search(r"\d", value):
            raise ValueError("숫자 포함")
        if not re.search(r"[\W_]", value):
            raise ValueError("특문 포함")

        return value


class EmailDuplicateCheckReqBody(AuthBase):
    # 이메일 중복확인 요청 시 클라이언트에서 보내는 request body
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")

    @field_validator("email")
    def validate_email(cls, value):
        if len(value) > 100:
            raise ValueError("이메일은 최대 100자 이하")

        return value


class SigninReqBody(AuthBase):
    # 로그인 요청 시 클라이언트에서 보내는 request body
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")
    password: str = Field(examples=["test1234!"], description="비밀번호")
    keep_signin_yn: str = Field(examples=["Y"], description="로그인 상태 유지 여부")
    sns_signup_type: Optional[str] = Field(
        default=None,
        example="",
        description="sns 로그인 연동 경로(naver, google, kakao, apple)",
    )
    sns_link_id: Optional[str] = Field(
        default=None, example="", description="sns 로그인 연동시 발급된 id"
    )

    @field_validator("email")
    def validate_email(cls, value):
        if len(value) > 100:
            raise ValueError("이메일은 최대 100자 이하")

        return value

    @field_validator("password")
    def validate_password(cls, value):
        if not (8 <= len(value) <= 20):
            raise ValueError("최소 8자 이상 최대 20자 이하")

        if not re.search(r"[A-Za-z]", value):
            raise ValueError("영문 포함")
        if not re.search(r"\d", value):
            raise ValueError("숫자 포함")
        if not re.search(r"[\W_]", value):
            raise ValueError("특문 포함")

        return value


class IdentityAccountSearchReqBody(AuthBase):
    # 아이디 찾기 요청 시 클라이언트에서 보내는 request body
    user_name: str = Field(examples=["test"], description="실명")
    birthdate: str = Field(
        examples=["2000-01-31"], description="생년월일(YYYYMMDD 또는 YYYY-MM-DD)"
    )
    gender: str = Field(examples=["M"], description="성별")


class IdentityPasswordResetReqBody(AuthBase):
    # 패스워드 재설정 요청 시 클라이언트에서 보내는 request body
    email: Optional[EmailStr] = Field(
        default=None, examples=["test@test.com"], description="이메일"
    )
    password: str = Field(examples=["test1234!"], description="비밀번호")
    user_name: Optional[str] = Field(
        default=None, examples=["test"], description="실명"
    )
    birthdate: Optional[str] = Field(
        default=None,
        examples=["2000-01-31"],
        description="생년월일(YYYYMMDD 또는 YYYY-MM-DD)",
    )
    gender: Optional[str] = Field(default=None, examples=["M"], description="성별")

    @field_validator("email")
    def validate_email(cls, value):
        if value and len(value) > 100:
            raise ValueError("이메일은 최대 100자 이하")

        return value

    @field_validator("password")
    def validate_password(cls, value):
        if value and not (8 <= len(value) <= 20):
            raise ValueError("최소 8자 이상 최대 20자 이하")

        if value and not re.search(r"[A-Za-z]", value):
            raise ValueError("영문 포함")
        if value and not re.search(r"\d", value):
            raise ValueError("숫자 포함")
        if value and not re.search(r"[\W_]", value):
            raise ValueError("특문 포함")

        return value


class PasswordResetSendCodeReqBody(AuthBase):
    # 비밀번호 재설정 인증코드 발송 요청
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")

    @field_validator("email")
    def validate_email(cls, value):
        if len(value) > 100:
            raise ValueError("이메일은 최대 100자 이하")

        return value


class PublicPasswordResetReqBody(AuthBase):
    # 비로그인 상태에서 이메일 인증 링크 기반 비밀번호 재설정 요청
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")
    token: str = Field(examples=["abc123..."], description="인증 토큰")
    password: str = Field(examples=["test1234!"], description="새 비밀번호")

    @field_validator("email")
    def validate_email(cls, value):
        if len(value) > 100:
            raise ValueError("이메일은 최대 100자 이하")

        return value

    @field_validator("password")
    def validate_password(cls, value):
        if not (8 <= len(value) <= 20):
            raise ValueError("최소 8자 이상 최대 20자 이하")

        if not re.search(r"[A-Za-z]", value):
            raise ValueError("영문 포함")
        if not re.search(r"\d", value):
            raise ValueError("숫자 포함")
        if not re.search(r"[\W_]", value):
            raise ValueError("특문 포함")

        return value


class IdentityTokenForPasswordReqBody(AuthBase):
    # 패스워드 재설정 요청 시 클라이언트에서 보내는 request body
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")


class SignoutReqBody(AuthBase):
    # 로그아웃 요청 시 클라이언트에서 보내는 request body
    refresh_token: str = Field(
        examples=[
            "<JWT_EXAMPLE>"
        ],
        description="발급받은 리프레시 토큰",
    )


class TokenReissueReqBody(AuthBase):
    # access 토큰 재발급 요청 시 클라이언트에서 보내는 request body
    access_token: str = Field(
        examples=[
            "<JWT_EXAMPLE>"
        ],
        description="발급받은 액세스 토큰",
    )
    refresh_token: str = Field(
        examples=[
            "<JWT_EXAMPLE>"
        ],
        description="발급받은 리프레시 토큰",
    )


class TokenRelayReqBody(AuthBase):
    # 리다이렉트 페이지 콜백 시 클라이언트에서 보내는 request body
    sns_id: int = Field(examples=[1], description="sns id")
    temp_issued_key: str = Field(examples=["ABCD"], description="발급받은 임시 키")


class TokenPartnerRelayIssueReqBody(AuthBase):
    # Service -> Partner 릴레이 발급 요청
    refresh_token: str = Field(
        examples=[
            "<JWT_EXAMPLE>"
        ],
        description="릴레이 발급용 리프레시 토큰",
    )


class TokenPartnerRelayConsumeReqBody(AuthBase):
    # Service -> Partner 릴레이 소비 요청
    relay_key: str = Field(
        examples=["ABCD"],
        description="발급받은 릴레이 키",
    )


"""
response area
"""
