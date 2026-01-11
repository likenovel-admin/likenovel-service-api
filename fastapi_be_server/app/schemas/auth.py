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


class IdentityTokenForPasswordReqBody(AuthBase):
    # 패스워드 재설정 요청 시 클라이언트에서 보내는 request body
    email: EmailStr = Field(examples=["test@test.com"], description="이메일")


class SignoutReqBody(AuthBase):
    # 로그아웃 요청 시 클라이언트에서 보내는 request body
    refresh_token: str = Field(
        examples=[
            "eyJhbGciOiJIUzUxMiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI4ZmRiZDhjNS1iOTNkLTRmN2EtYWNmOS0xNjljYzc5YzZiNzgifQ.eyJleHAiOjE3Mjk0MjMzMDUsImlhdCI6MTcyOTQyMTUwNSwianRpIjoiMDQyZWRmMWYtZWJmNS00ODQyLTg4Y2YtOTRmNWIyMzUwNGZlIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6Imh0dHBzOi8vYXV0aC5saWtlbm92ZWwuZGV2L3JlYWxtcy9saWtlbm92ZWwiLCJzdWIiOiI2NWY2MzVmYS00ZGQzLTQxOTYtOGYwMS1iOGIyNzFiMTEzMjgiLCJ0eXAiOiJSZWZyZXNoIiwiYXpwIjoic2VydmljZSIsInNpZCI6IjQ0YTA2OGRkLTIyOGEtNGY2Zi1iMjdkLWVkZGU2ZjY3YzBlOSIsInNjb3BlIjoib3BlbmlkIGVtYWlsIGJhc2ljIHdlYi1vcmlnaW5zIHJvbGVzIGFjciBwcm9maWxlIn0.NOXFilbGjROEXmq5T8_922WCaADl0c68cqsvgrhxIMrJwbV6Qhhhk2X2gszbFOkbLlFyZSpD6GuMuRrkAYarOQ"
        ],
        description="발급받은 리프레시 토큰",
    )


class TokenReissueReqBody(AuthBase):
    # access 토큰 재발급 요청 시 클라이언트에서 보내는 request body
    access_token: str = Field(
        examples=[
            "eyJhbGciOiJSUzI1NiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICJ4VUZDMmdJenVMM0c5X0tFb3o4YkJEcFRUOGM5ME1aUHZCWEdKRzZ4dGdZIn0.eyJleHAiOjE3Mjk0MjI3MDUsImlhdCI6MTcyOTQyMTUwNSwianRpIjoiNjY0MmY5ZWQtYTVjOC00NzhkLWFlZjYtZWNjNmZlMGZmNzRiIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6ImFjY291bnQiLCJzdWIiOiI2NWY2MzVmYS00ZGQzLTQxOTYtOGYwMS1iOGIyNzFiMTEzMjgiLCJ0eXAiOiJCZWFyZXIiLCJhenAiOiJzZXJ2aWNlIiwic2lkIjoiNDRhMDY4ZGQtMjI4YS00ZjZmLWIyN2QtZWRkZTZmNjdjMGU5IiwiYWNyIjoiMSIsImFsbG93ZWQtb3JpZ2lucyI6WyIiXSwicmVzb3VyY2VfYWNjZXNzIjp7ImFjY291bnQiOnsicm9sZXMiOlsibWFuYWdlLWFjY291bnQiLCJtYW5hZ2UtYWNjb3VudC1saW5rcyJdfX0sInNjb3BlIjoib3BlbmlkIGVtYWlsIHByb2ZpbGUiLCJlbWFpbF92ZXJpZmllZCI6ZmFsc2UsInByZWZlcnJlZF91c2VybmFtZSI6InRlc3RAdGVzdC5jb20iLCJlbWFpbCI6InRlc3RAdGVzdC5jb20ifQ.GXdRaDNZaaXhUvtSB_O26KtlHzT5PxzoEdVG_EfPBpkOD7Q191989H9QmimMR3_jfmepVbQKXIiEAa2-RP1MGEC5y4Iw6Lk73q-zSssKfHugvk8DEvAAOR98BK8nqEKC2Sdw9Q3ehrQQqwBfDwL8IpZsD9IXJhQj3Wzm_wvpSWDnTXP5graXgyHb6yMPLpbtknSfPNmaPpfPOoTSdqzclWGy1mReufoE1FOFKa_HJaf-YeV5AXtuJkORUGCdTsHNofgkQ89qrPwexvyB-uKxrz5UrzE6tKLmcR7l1t13bUtJ-_gJkAhzOQVG4fZhsfezFpcXRNuhD9J3K1wyDZdWYQ"
        ],
        description="발급받은 액세스 토큰",
    )
    refresh_token: str = Field(
        examples=[
            "eyJhbGciOiJIUzUxMiIsInR5cCIgOiAiSldUIiwia2lkIiA6ICI4ZmRiZDhjNS1iOTNkLTRmN2EtYWNmOS0xNjljYzc5YzZiNzgifQ.eyJleHAiOjE3Mjk0MjMzMDUsImlhdCI6MTcyOTQyMTUwNSwianRpIjoiMDQyZWRmMWYtZWJmNS00ODQyLTg4Y2YtOTRmNWIyMzUwNGZlIiwiaXNzIjoiaHR0cHM6Ly9hdXRoLmxpa2Vub3ZlbC5kZXYvcmVhbG1zL2xpa2Vub3ZlbCIsImF1ZCI6Imh0dHBzOi8vYXV0aC5saWtlbm92ZWwuZGV2L3JlYWxtcy9saWtlbm92ZWwiLCJzdWIiOiI2NWY2MzVmYS00ZGQzLTQxOTYtOGYwMS1iOGIyNzFiMTEzMjgiLCJ0eXAiOiJSZWZyZXNoIiwiYXpwIjoic2VydmljZSIsInNpZCI6IjQ0YTA2OGRkLTIyOGEtNGY2Zi1iMjdkLWVkZGU2ZjY3YzBlOSIsInNjb3BlIjoib3BlbmlkIGVtYWlsIGJhc2ljIHdlYi1vcmlnaW5zIHJvbGVzIGFjciBwcm9maWxlIn0.NOXFilbGjROEXmq5T8_922WCaADl0c68cqsvgrhxIMrJwbV6Qhhhk2X2gszbFOkbLlFyZSpD6GuMuRrkAYarOQ"
        ],
        description="발급받은 리프레시 토큰",
    )


class TokenRelayReqBody(AuthBase):
    # 리다이렉트 페이지 콜백 시 클라이언트에서 보내는 request body
    sns_id: int = Field(examples=[1], description="sns id")
    temp_issued_key: str = Field(examples=["ABCD"], description="발급받은 임시 키")


"""
response area
"""
