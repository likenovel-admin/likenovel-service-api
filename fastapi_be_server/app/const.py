from pydantic_settings import BaseSettings
import os
from enum import Enum

"""
상수 모음
@lru_cache는 캐시 초기화와 관련된 운영 이슈가 발생할 수 있어서 제외함
"""


class Settings(BaseSettings):
    # aware datetime
    KOREA_TIMEZONE: str = "Asia/Seoul"

    # root
    ROOT_PATH: str = os.getenv("ROOT_PATH", "/app")

    # frontend 서버 도메인
    FE_DOMAIN: str = os.getenv("FE_DOMAIN", "")
    FE_WWW_DOMAIN: str = os.getenv("FE_WWW_DOMAIN", "")
    FE_REDIRECT_URL: str = f"{FE_WWW_DOMAIN}/storage-relay"

    # 데이터 분석용 파일 로그
    LOGGER_NAME: str = "analysis"
    LOG_FILE: str = "analysis.log"

    # mysql
    DB_USER_ID: str = os.getenv("DB_USER_ID", "ln-admin")
    DB_USER_PW: str = os.getenv("DB_USER_PW", "")
    DB_IP: str = os.getenv("DB_IP", "")
    DB_PORT: str = os.getenv("DB_PORT", "3306")
    LIKENOVEL_DB_URL: str = f"mysql+aiomysql://{DB_USER_ID}:{DB_USER_PW}@{DB_IP}:{DB_PORT}/likenovel?charset=utf8mb4"
    VARCHAR_COMM_SIZE: int = 300
    VARCHAR_ID_SIZE: int = 30
    VARCHAR_CODE_SIZE: int = 20
    VARCHAR_YN_SIZE: int = 1
    DB_DML_DEFAULT_ID: int = 0
    DB_DML_SYSTEM_ID: int = -1
    DB_DML_PORTONE_ID: int = -99

    # keycloak
    KC_DOMAIN: str = os.getenv("KC_DOMAIN", "http://keycloak:8080")
    KC_ISSUER_BASE_URL: str = os.getenv(
        "KC_ISSUER_BASE_URL", "http://keycloak:8080/realms/likenovel"
    )
    KC_AUDIENCE: str = "account"
    KC_OIDC_BASE_URL: str = f"{KC_DOMAIN}/realms/likenovel/protocol/openid-connect"
    KC_ADMIN_BASE_URL: str = f"{KC_DOMAIN}/admin/realms/likenovel"
    KC_CLIENT_ID: str = os.getenv("KC_CLIENT_ID", "service")
    KC_CLIENT_SECRET: str = os.getenv(
        "KC_CLIENT_SECRET", ""
    )
    KC_CLIENT_KEEP_SIGNIN_ID: str = os.getenv(
        "KC_CLIENT_KEEP_SIGNIN_ID", "service-keep"
    )
    KC_CLIENT_KEEP_SIGNIN_SECRET: str = os.getenv(
        "KC_CLIENT_KEEP_SIGNIN_SECRET", ""
    )
    KC_PUBLIC_KEY: str = """
                                        -----BEGIN PUBLIC KEY-----
                                        MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEA7JveazO05HUs7ofmGjkal1g+hcp17cZgfzBOUocC5ovrx06cpJioroNkxGhbzQ5CKguRb55Gx4ocebKmgP/zwThuDyLUUkknSew4icncIoVcu000PL6jQ4FzhCvEPzMFc6+OhbMkVcHSHPg8J8QxWKbCCbYHbV0GpjOcjLJhvckYJdQOTJ3v/1qNZZMiG4XG/oD6T9mAbrRpS5qc2RHJJukhfi4l4P8s0yBsmHlX8yX3K1hKdNuJLVmO/zM/h4eLNi5gjg3yOPntzUg9xUhTj5y73Cu5tGXq85qgTEJ0OxPHanUhsPqqkhQ/nuth5YSEpVrLHTsrW2ELcBSQqS50ywIDAQAB
                                        -----END PUBLIC KEY-----
                                        """
    KC_PK_ALGORITHMS: list = ["RS256"]

    # naver 로그인 연동
    NAVER_OAUTH2_BASE_URL: str = "https://nid.naver.com/oauth2.0"
    NAVER_API_BASE_URL: str = "https://openapi.naver.com/v1/nid"
    NAVER_CLIENT_ID: str = os.getenv("NAVER_CLIENT_ID", "0XC3m3M1KszmRR7vkIIh")
    NAVER_CLIENT_SECRET: str = os.getenv("NAVER_CLIENT_SECRET", "")
    NAVER_PASSWORD: str = os.getenv("NAVER_PASSWORD", "")

    # google 로그인 연동
    GOOGLE_OAUTH2_BASE_URL: str = "https://oauth2.googleapis.com"
    GOOGLE_API_BASE_URL: str = "https://www.googleapis.com/oauth2/v2"
    GOOGLE_CLIENT_ID: str = os.getenv(
        "GOOGLE_CLIENT_ID",
        "",
    )
    GOOGLE_CLIENT_SECRET: str = os.getenv(
        "GOOGLE_CLIENT_SECRET", ""
    )
    GOOGLE_PASSWORD: str = os.getenv("GOOGLE_PASSWORD", "")
    GOOGLE_SIGNUP_REDIRECT_URL: str = os.getenv(
        "GOOGLE_SIGNUP_REDIRECT_URL",
        "https://api.likenovel.net/v1/command/auth/signup/google/callback",
    )
    GOOGLE_SIGNIN_REDIRECT_URL: str = os.getenv(
        "GOOGLE_SIGNIN_REDIRECT_URL",
        "https://api.likenovel.net/v1/command/auth/signin/google/callback",
    )

    # kakao 로그인 연동
    KAKAO_OAUTH2_BASE_URL: str = "https://kauth.kakao.com/oauth"
    KAKAO_API_BASE_URL: str = "https://kapi.kakao.com/v2/user"
    KAKAO_CLIENT_ID: str = os.getenv(
        "KAKAO_CLIENT_ID", ""
    )
    KAKAO_CLIENT_SECRET: str = os.getenv(
        "KAKAO_CLIENT_SECRET", ""
    )
    KAKAO_PASSWORD: str = os.getenv("KAKAO_PASSWORD", "")
    KAKAO_SIGNUP_REDIRECT_URL: str = os.getenv(
        "KAKAO_SIGNUP_REDIRECT_URL",
        "https://api.likenovel.net/v1/command/auth/signup/kakao/callback",
    )
    KAKAO_SIGNIN_REDIRECT_URL: str = os.getenv(
        "KAKAO_SIGNIN_REDIRECT_URL",
        "https://api.likenovel.net/v1/command/auth/signin/kakao/callback",
    )

    # apple 로그인 연동
    APPLE_ISSUER_BASE_URL: str = "https://appleid.apple.com"
    APPLE_OAUTH2_BASE_URL: str = "https://appleid.apple.com/auth"
    APPLE_KEYS_URL: str = f"{APPLE_OAUTH2_BASE_URL}/keys"
    APPLE_CLIENT_ID: str = os.getenv("APPLE_CLIENT_ID", "prod.likenovel")
    APPLE_CLIENT_SECRET: str = os.getenv(
        "APPLE_CLIENT_SECRET",
        "",
    )
    APPLE_PASSWORD: str = os.getenv("APPLE_PASSWORD", "")
    APPLE_SIGNUP_REDIRECT_URL: str = os.getenv(
        "APPLE_SIGNUP_REDIRECT_URL",
        "https://api.likenovel.net/v1/command/auth/signup/apple/callback",
    )
    APPLE_SIGNIN_REDIRECT_URL: str = os.getenv(
        "APPLE_SIGNIN_REDIRECT_URL",
        "https://api.likenovel.net/v1/command/auth/signin/apple/callback",
    )

    # 정적 컨텐츠 제공 서버 도메인
    R2_SC_DOMAIN: str = (
        "https://a168bba93203dec90f4f7ddda837c772.r2.cloudflarestorage.com"
    )
    R2_SC_CDN_URL: str = "https://cdn.likenovel.net"
    R2_SC_IMAGE_BUCKET: str = "image"
    R2_SC_EPUB_BUCKET: str = "epub"
    R2_SC_ATTACHMENT_BUCKET: str = "attachment"
    R2_CLIENT_ID: str = os.getenv("R2_CLIENT_ID", "")
    R2_CLIENT_SECRET: str = os.getenv(
        "R2_CLIENT_SECRET",
        "",
    )
    R2_REGION: str = "apac"
    R2_COVER_DEFAULT_IMAGE: int = 828
    R2_PROFILE_DEFAULT_IMAGE: int = 825
    R2_INTEREST_BADGE_DEFAULT_IMAGE: int = 826
    R2_EVENT_BADGE_DEFAULT_IMAGE: int = 827

    # meilisearch
    MEILISEARCH_HOST: str = os.getenv("MEILISEARCH_HOST", "http://meilisearch:7700")
    MEILISEARCH_API_KEY: str = os.getenv(
        "MEILISEARCH_API_KEY", ""
    )

    # 페이징 기본 설정값
    PAGINATION_DEFAULT_PAGE_NO: int = 1  # 조회 시작 위치
    PAGINATION_DEFAULT_LIMIT: int = 10  # 한 페이지당 개수
    PAGINATION_PRODUCT_DEFAULT_LIMIT: int = 25  # 작품 목록 조회 시 한 페이지당 개수
    PAGINATION_ORDER_DIRECTION_ASC: str = "asc"
    PAGINATION_ORDER_DIRECTION_DESC: str = "desc"

    # custom status code
    class CustomStatusCode(Enum):
        ALREADY_EXIST_LIKENOVEL_EMAIL: str = "M0000"
        ALREADY_APPLY_STATE: str = "M0001"  # TODO: 관련 모듈 구현 후 수정 및 최종 테스트 완료되면 프론트엔드에도 추가 필
        NICKNAME_CHANGE_COUNT0: str = "M0002"  # TODO: 관련 모듈 구현 후 수정 및 최종 테스트 완료되면 프론트엔드에도 추가 필
        ALREADY_EXIST_NICKNAME: str = "M0003"  # TODO: 관련 모듈 구현 후 수정 및 최종 테스트 완료되면 프론트엔드에도 추가 필
        NOT_EXIST_ACCOUNT: str = "M0004"  # TODO: 관련 모듈 구현 후 수정 및 최종 테스트 완료되면 프론트엔드에도 추가 필
        NOT_EXIST_EMAIL: str = "M0005"  # TODO: 관련 모듈 구현 후 수정 및 최종 테스트 완료되면 프론트엔드에도 추가 필
        EXPIRED_ACCESS_TOKEN: str = "E4010"
        EXPIRED_REFRESH_TOKEN: str = "E4011"
        NEED_IDENTITY: str = "E4012"
        INVALID_EMAIL: str = "E4220"
        INVALID_PASSWORD: str = "E4221"
        INVALID_STATE: str = "E4222"
        INVALID_LOGIN_INFO: str = "E4223"
        INVALID_FILE_NAME: str = "E4224"
        INVALID_PRODUCT_INFO: str = "E4225"
        INVALID_EPISODE_INFO: str = "E4226"
        INVALID_PRODUCT_NOTICE_INFO: str = "E4227"
        INVALID_APPLY_ROLE_INFO: str = "E4228"
        INVALID_PROFILE_INFO: str = "E4229"
        INVALID_NICKNAME_INFO: str = "E4230"

    # nice
    NICE_GRANT_TYPE: str = "client_credentials"
    NICE_CLIENT_ID: str = os.getenv(
        "NICE_CLIENT_ID", ""
    )
    NICE_CLIENT_SECRET: str = os.getenv(
        "NICE_CLIENT_SECRET", ""
    )

    # portone
    PORTONE_SECRET_KEY: str = os.getenv(
        "PORTONE_SECRET_KEY",
        # "3T007h1D97FUo3kAPoyVBYxhXILp7vsEWQcRFsNZG626LhPtyEEcaanQRY8ryZjfX3NP3iRxFd9CIU53", # 테스트
        "",  # 운영: 반드시 환경변수로 주입
    )

    # smtp (이메일 발송)
    SMTP_HOST: str = os.getenv("SMTP_HOST", "smtp-relay.gmail.com")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD: str = os.getenv("SMTP_PASSWORD", "")
    SMTP_FROM_EMAIL: str = os.getenv("SMTP_FROM_EMAIL", "noreply@likenovel.net")
    SMTP_FROM_NAME: str = os.getenv("SMTP_FROM_NAME", "라이크노벨")
    SERVICE_FRONTEND_URL: str = os.getenv("SERVICE_FRONTEND_URL", "https://www.likenovel.net")

    # anthropic (AI 추천)
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    STORY_AGENT_GEMINI_MODEL: str = os.getenv(
        "STORY_AGENT_GEMINI_MODEL",
        os.getenv("GEMINI_MODEL", "gemini-3-flash-preview"),
    )


settings = Settings()


class valueEnum(str, Enum):
    def _generate_next_value_(name, start, counts, last_value=None):
        return last_value or name

    def __str__(self):
        return self.value


class LOGGER_TYPE(valueEnum):
    LOGGER_FILE_NAME_FOR_SERVICE_ERROR = "service_error_log"
    LOGGER_INSTANCE_NAME_FOR_SERVICE_ERROR = "service_error_log"
    LOGGER_FILE_NAME_FOR_SERVICE_DATA = "service_data_log"
    LOGGER_INSTANCE_NAME_FOR_SERVICE_DATA = "service_data_log"


class LOGGER_LOG_TYPE(valueEnum):
    TEST_LOG = "test_log"


# 공통 상수들
class CommonConstants:
    # Yes/No 플래그
    YES = "Y"
    NO = "N"

    # 사용자 역할
    ROLE_ADMIN = "admin"
    ROLE_PARTNER = "CP"
    ROLE_AUTHOR = "author"
    ROLE_NORMAL = "normal"

    # 상태 코드
    STATUS_WAIT = "wait"
    STATUS_SERIALIZING = "serializing"
    STATUS_COMPLETED = "completed"

    # 계약 타입
    CONTRACT_NORMAL = "normal"
    CONTRACT_TYPE = "contract"

    # 검색 대상
    SEARCH_PRODUCT_TITLE = "product-title"
    SEARCH_WRITER_NAME = "writer-name"
    SEARCH_PRODUCT_ID = "product-id"
    SEARCH_AUTHOR_NAME = "author-name"
    SEARCH_EMAIL = "email"
    SEARCH_USER_NAME = "user-name"
    SEARCH_COMPANY_NAME = "company-name"
    SEARCH_CP_NAME = "cp-name"

    # 검색 타입
    SEARCH_TYPE_ADMIN = "admin"
    SEARCH_TYPE_PARTNER = "partner"

    # 신청 타입
    APPLY_TYPE_CP = "cp"

    # 기본 페이징 값
    DEFAULT_PAGE = 1
    DEFAULT_COUNT_PER_PAGE = 10
    MAX_COUNT_PER_PAGE = 100

    # 회사명
    COMPANY_LIKENOVEL = "라이크노벨"

    # 에피소드 구매 가격
    EPISODE_PURCHASE_PRICE = 100

    # 닉네임 변경권 가격
    NICKNAME_CHANGE_TICKET_PRICE = 500


# 에러 메시지 중앙 관리 클래스
class ErrorMessages:
    # 인증/권한 관련
    LOGIN_REQUIRED = "로그인이 필요합니다."
    LOGIN_PLEASE = "로그인 해주세요."
    ADMIN_ACCOUNT_REQUIRED = "관리자 계정이 아닙니다."
    ADMIN_LOGIN_REQUIRED = "관리자 계정으로 로그인 해주세요."
    EXPIRED_ACCESS_TOKEN = "액세스 토큰이 만료되었습니다."
    EXPIRED_REFRESH_TOKEN = "리프레시 토큰이 만료되었습니다."
    INVALID_TOKEN = "유효하지 않은 토큰입니다."
    INVALID_LOGIN_INFO = "올바르지 않은 로그인 정보입니다."
    INVALID_EMAIL_FORMAT = "유효하지 않은 이메일 형식입니다."
    INVALID_PASSWORD_FORMAT = "유효하지 않은 비밀번호 형식입니다."
    INVALID_STATE = "유효하지 않은 상태값입니다."
    SNS_ACCOUNT_PASSWORD_RESET_NOT_ALLOWED = (
        "SNS 계정은 비밀번호 재설정을 할 수 없습니다. 해당 SNS 로그인을 이용해주세요."
    )
    SNS_ACCOUNT_PASSWORD_RESET_NOT_ALLOWED_ADMIN = (
        "SNS 계정은 비밀번호 재설정을 할 수 없습니다."
    )
    INVALID_VERIFICATION_CODE = "인증코드가 일치하지 않거나 만료되었습니다."
    VERIFICATION_CODE_SEND_FAILED = "인증코드 발송에 실패했습니다."
    VERIFICATION_CODE_TOO_MANY_REQUESTS = "잠시 후 다시 시도해주세요."

    # 권한 관련 (Forbidden)
    FORBIDDEN = "권한이 없습니다."
    FORBIDDEN_CONTRACT_OFFER_FOR_ACCEPT = "계약 제안을 수락할 권한이 없습니다."
    FORBIDDEN_CONTRACT_OFFER_FOR_REJECT = "계약 제안을 거절할 권한이 없습니다."
    FORBIDDEN_DIRECT_PROMOTION_FOR_STOP = "직접 프로모션을 중지할 권한이 없습니다."
    FORBIDDEN_DIRECT_PROMOTION_FOR_START = "직접 프로모션을 시작할 권한이 없습니다."
    FORBIDDEN_PRODUCT_FOR_DIRECT_PROMOTION = "직접 프로모션을 설정할 권한이 없습니다."
    FORBIDDEN_PRODUCT_FOR_APPLIED_PROMOTION = "신청 프로모션을 설정할 권한이 없습니다."
    FORBIDDEN_NOT_AUTHOR_OF_PRODUCT = "해당 작품의 작가가 아닙니다."
    FORBIDDEN_NOT_OWNER_OF_PRODUCTBOOK = "대여권 소유자만 사용할 수 있습니다."
    FORBIDDEN_NOT_OWNER_OF_TICKETBOOK = "이용권 소유자만 사용할 수 있습니다."

    # 데이터 유효성 관련
    INVALID_PRODUCT_INFO = "유효하지 않은 작품 정보입니다."
    INVALID_EPISODE_INFO = "유효하지 않은 회차 정보입니다."
    INVALID_TICKET_ITEM = "유효하지 않은 티켓 아이템입니다."
    INVALID_PRODUCT_NOTICE_INFO = "유효하지 않은 작품 공지 정보입니다."
    INVALID_NICKNAME_INFO = "유효하지 않은 닉네임입니다."
    INVALID_PROFILE_INFO = "유효하지 않은 프로필 정보입니다."
    INVALID_APPLY_ROLE_INFO = "유효하지 않은 역할 신청 정보입니다."
    FREE_PRODUCT_CANNOT_CREATE_PAID_EPISODE = (
        "무료 작품은 유료 회차를 생성할 수 없습니다."
    )
    INVALID_TIME_RANGE_WEEKDAY = (
        "주중 노출 시작시간은 노출 종료시간보다 이전이어야 합니다."
    )
    INVALID_TIME_RANGE_WEEKEND = (
        "주말 노출 시작시간은 노출 종료시간보다 이전이어야 합니다."
    )
    INVALID_RECOMMEND_EXPOSE_START_DATE = (
        "노출 시작일은 노출 종료일보다 이전이어야 합니다."
    )
    INVALID_START_DATE_FORMAT = (
        "시작 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식이어야 합니다."
    )
    INVALID_END_DATE_FORMAT = (
        "종료 날짜 형식이 올바르지 않습니다. YYYY-MM-DD 형식이어야 합니다."
    )
    INVALID_DATE_RANGE = "시작 날짜가 종료 날짜보다 늦을 수 없습니다."
    PRIMARY_SECONDARY_GENRE_SAME = (
        "1차 장르와 2차 장르가 동일합니다. 다른 장르를 선택해주세요."
    )
    DETAIL_POSITION_REQUIRED = "세부 위치를 지정해주세요."
    PRODUCT_NOTICE_LENGTH_EXCEEDED = "작품 공지 내용은 20,000자를 초과할 수 없습니다."
    NOTIFICATION_CONTENT_LENGTH_EXCEEDED = "알림 내용은 50자를 초과할 수 없습니다."
    INVALID_REQUEST_DATA = "요청 데이터가 유효하지 않습니다."
    UCI_OR_ISBN_REQUIRED = "UCI와 ISBN 중 최소 1개는 입력해야 합니다."

    # 리소스 중복 관련
    ALREADY_EXIST_EMAIL = "이미 존재하는 이메일입니다."
    ALREADY_EXIST_EMAIL_WITH_DIFFERENT_METHOD = (
        "해당 계정은 다른 방식으로 이미 가입된 계정입니다."
    )
    ALREADY_EXIST_NICKNAME = "이미 존재하는 닉네임입니다."
    ALREADY_EXIST_COMPANY = "이미 등록된 회사명입니다."
    ALREADY_EXIST_KEYWORD = "이미 등록된 keyword_name입니다."
    ALREADY_APPLIED_STATE = "이미 신청된 상태입니다."
    ALREADY_LIKED = "이미 좋아요를 했습니다."
    ALREADY_USING_STATE = "이미 사용중인 상태입니다."
    ALREADY_STOPPED_STATE = "이미 사용 중지인 상태입니다."
    ALREADY_APPROVED = "이미 승인되었습니다."
    ALREADY_REJECTED = "이미 반려되었습니다."
    ALREADY_WITHDRAWN_MEMBER = "이미 탈퇴한 회원입니다."
    ALREADY_ACCEPTED_CONTRACT_OFFER = "이미 수락된 계약 제안입니다."
    ALREADY_REJECTED_CONTRACT_OFFER = "이미 거절된 계약 제안입니다."
    ALREADY_ENDED_APPLIED_PROMOTION = "이미 종료된 신청 프로모션입니다."
    ALREADY_APPROVED_IN_PROGRESS_APPLIED_PROMOTION = (
        "이미 승인되어 진행중인 신청 프로모션입니다."
    )
    ALREADY_REJECTED_APPLIED_PROMOTION = "이미 반려된 신청 프로모션입니다."
    CANNOT_START_ENDED_PROMOTION = "종료된 프로모션은 시작할 수 없습니다."
    CANNOT_STOP_ENDED_PROMOTION = "종료된 프로모션은 중지할 수 없습니다."
    CANNOT_ISSUE_NON_READER_OF_PREV_PROMOTION = (
        "선작 독자 무료 대여권 프로모션만 발급할 수 있습니다."
    )
    CANNOT_ISSUE_NOT_IN_PROGRESS_PROMOTION = "진행중인 프로모션만 발급할 수 있습니다."
    CANNOT_START_READER_OF_PREV_WITHOUT_TICKETS = (
        "선작 독자 무료 대여권 장수를 1 이상 설정한 뒤 적용해주세요."
    )
    ALREADY_ISSUED_THIS_WEEK = (
        "이미 이번 주에 발급했습니다. 다음 주 월요일에 다시 발급할 수 있습니다."
    )
    NO_BOOKMARK_USERS = "해당 작품을 북마크한 유저가 없습니다."
    FORBIDDEN_DIRECT_PROMOTION_FOR_CHECK = (
        "직접 프로모션 상태를 확인할 권한이 없습니다."
    )
    CANNOT_CHECK_NON_READER_OF_PREV_PROMOTION = (
        "선작 독자 무료 대여권 프로모션만 상태 확인이 가능합니다."
    )
    NO_READER_OF_PREV_PROMOTION_IN_PROGRESS = "진행중인 선작 독자 프로모션이 없습니다."
    REQUIRED_APPLIED_PROMOTION_START_DATE = "신청 프로모션 시작일이 필요합니다."
    REQUIRED_APPLIED_PROMOTION_END_DATE = "신청 프로모션 종료일이 필요합니다."
    CANNOT_APPLY_WITHIN_180_DAYS_AFTER_DENY = (
        "반려 후 180일이 경과해야 재신청이 가능합니다."
    )
    CANNOT_APPLY_UNTIL_NEXT_WEEK_AFTER_DENY = "다음주에 다시 신청가능합니다."
    ALREADY_APPLIED_PROMOTION = "이미 신청 중인 프로모션이 있습니다."
    ALREADY_IN_PROGRESS_PROMOTION = "이미 진행 중인 프로모션이 있습니다."
    ALREADY_USED_PRODUCTBOOK = "이미 사용한 대여권입니다."
    ALREADY_USED_TICKETBOOK = "이미 사용한 이용권입니다."
    ALREADY_OWNED_EPISODE = "이미 소장한 에피소드입니다."
    ALREADY_RECEIVED_GIFT = "이미 받은 선물입니다."
    ALREADY_VERIFIED_PHONE = "이미 본인인증된 전화번호입니다."
    EXPIRED_GIFT_VALIDITY = "선물의 유효기간(7일)이 만료되었습니다."
    PRODUCTBOOK_NOT_APPLICABLE_FOR_EPISODE = (
        "해당 에피소드에 사용할 수 없는 대여권입니다."
    )
    OWNED_PRODUCT_CANNOT_USE = "소장한 작품은 사용할 필요가 없습니다."

    # 리소스 미존재 관련 (NOT_FOUND)
    NOT_FOUND = "존재하지 않습니다."
    NOT_FOUND_PRODUCT = "존재하지 않는 작품입니다."
    NOT_FOUND_EPISODE = "존재하지 않는 에피소드입니다."
    DELETED_EPISODE = "삭제된 에피소드입니다."
    NOT_FOUND_MEMBER = "존재하지 않는 회원입니다."
    NOT_REGISTERED_ACCOUNT = "등록되지 않은 계정입니다. 회원가입을 먼저 진행해주세요."
    NOT_FOUND_USER = "존재하지 않는 사용자입니다."
    NOT_FOUND_REVIEW = "존재하지 않는 리뷰입니다."
    NOT_FOUND_COMMENT = "존재하지 않는 댓글입니다."
    NOT_FOUND_NOTICE = "존재하지 않는 공지입니다."
    NOT_FOUND_PRODUCT_NOTICE = "존재하지 않는 작품 공지입니다."
    NOT_FOUND_KEYWORD = "존재하지 않는 키워드입니다."
    NOT_FOUND_PRODUCTBOOK = "존재하지 않는 대여권입니다."
    NOT_FOUND_TICKETBOOK = "존재하지 않는 이용권입니다."
    NOT_FOUND_TICKET_ITEM = "존재하지 않는 티켓 아이템입니다."
    NOT_FOUND_EVENT = "존재하지 않는 이벤트입니다."
    NOT_FOUND_BANNER = "존재하지 않는 배너입니다."
    NOT_FOUND_PROMOTION_SLOT = "존재하지 않는 출판사 프로모션 구좌입니다."
    NOT_FOUND_RECOMMEND_SLOT = "존재하지 않는 직접 추천구좌입니다."
    NOT_FOUND_ALGORITHM_RECOMMEND = "존재하지 않는 알고리즘 추천구좌 - 추천 섹션입니다."
    NOT_FOUND_PUSH_TEMPLATE = "존재하지 않는 푸시 메시지 템플릿입니다."
    NOT_FOUND_CONTRACT_OFFER = "존재하지 않는 계약 제안입니다."
    NOT_FOUND_DIRECT_PROMOTION = "존재하지 않는 직접 프로모션입니다."
    NOT_FOUND_APPLIED_PROMOTION = "존재하지 않는 신청 프로모션입니다."
    NOT_FOUND_QUEST = "존재하지 않는 퀘스트입니다."
    NOT_FOUND_FAQ = "존재하지 않는 FAQ입니다."
    NOT_FOUND_BADGE = "존재하지 않는 뱃지입니다."
    NOT_FOUND_DISCOVERY_STAT = "존재하지 않는 발굴 통계입니다."
    NOT_FOUND_AUTHOR = "존재하지 않는 작가입니다."
    APPLICATION_INFO_NOT_FOUND = "자격 신청 정보를 찾을 수 없습니다."
    PROMOTION_UPGRADE_INFO_NOT_FOUND = "작품 승급 신청 정보를 찾을 수 없습니다."

    # 비즈니스 로직 관련
    NOT_LIKED_YET = "좋아요를 하지 않았습니다."
    NICKNAME_CHANGE_COUNT_EXHAUSTED = "닉네임 변경 횟수를 모두 사용했습니다."
    FREE_NICKNAME_CHANGE_REMAINING = (
        "무료 닉네임 변경 횟수가 남아있습니다. 무료 횟수를 모두 사용한 후 구매해주세요."
    )
    EXCEEDED_WEEKLY_NOTIFICATION_LIMIT = (
        "이번 주 알림 발송 횟수를 초과했습니다. (최대 5회)"
    )
    NO_AVAILABLE_APPLIED_PROMOTION_SLOT = "이번주 신청 프로모션에 남은 자리가 없습니다."
    WITHDRAWN_APPLIED_PROMOTION = "철회한 신청 프로모션입니다."
    APPLIED_PROMOTION_REJECTED = "반려된 신청 프로모션입니다."
    INSUFFICIENT_CASH_BALANCE = "캐시 잔액이 부족합니다."
    FREE_EPISODE_CANNOT_PURCHASE = "무료 에피소드는 구매할 수 없습니다."
    REQUIRED_EPISODE_ID_OR_PRODUCT_ID = (
        "episode_id 또는 product_id 중 하나는 필수입니다."
    )
    INVALID_PRODUCT_ID = "유효한 product_id를 찾을 수 없습니다."

    # 리뷰/댓글 관련
    COMMENT_AUTHOR_ONLY_MODIFY = "댓글 작성자만 수정할 수 있습니다."
    COMMENT_AUTHOR_ONLY_DELETE = "댓글 작성자만 삭제할 수 있습니다."
    ALREADY_REPORTED_REVIEW = "이미 신고한 리뷰입니다."
    CANNOT_REPORT_OWN_REVIEW = "자신의 리뷰는 신고할 수 없습니다."
    NOT_FOUND_REVIEW_COMMENT = "존재하지 않는 리뷰 댓글입니다."
    ALREADY_REPORTED_REVIEW_COMMENT = "이미 신고한 리뷰 댓글입니다."
    CANNOT_REPORT_OWN_REVIEW_COMMENT = "자신의 리뷰 댓글은 신고할 수 없습니다."

    # 파일 관련
    GROUP_TYPE_REQUIRED = "group_type을 입력해주세요."
    INVALID_GROUP_TYPE = "group_type 값이 유효하지 않습니다."
    FILENAME_REQUIRED = "filename을 입력해주세요."

    # 검색 관련
    SEARCH_WORD_MUST_BE_NUMBER = (
        "search_target이 product-id인 경우 search_word는 숫자여야 합니다."
    )

    # 정산 관련
    PAID_AMOUNT_NEGATIVE = "유상 정산액이 0보다 작을 수는 없습니다."
    FREE_AMOUNT_NEGATIVE = "무상 정산액이 0보다 작을 수는 없습니다."
    TAX_AMOUNT_NEGATIVE = "세액이 0보다 작을 수는 없습니다."
    SETTLEMENT_RATE_NEGATIVE = "정산율이 0보다 작을 수는 없습니다."
    PAYMENT_FEE_NEGATIVE = "결제 수수료가 0보다 작을 수는 없습니다."
    SETTLEMENT_DATA_CREATION_FAILED = "정산 데이터 생성에 실패했습니다."
    NO_SPONSORSHIP_TO_SETTLE = "정산할 후원 내역이 없습니다."
    SETTLEMENT_FIELDS_REQUIRED = "매출 정보는 유상 정산액, 무상 정산액, 세액 3가지 값이 필요하고, 매출 관리는 정산율, 결제 수수료, 세액 3가지 값이 필요합니다."
    CP_WRITER_SETTLEMENT_POSITIVE = (
        "cp사-작가 정산시 작가의 정산비는 양수로 입력해주세요."
    )
    CP_WRITER_SETTLEMENT_MAX100 = "cp사-작가 정산시 작가의 정산비는 100 이하로 입력해주세요. 100 - 해당값이 cp사의 정산비가 됩니다."
    CP_PROPOSE_AMOUNT_POSITIVE = "cp사 제안 금액은 양수로 입력해주세요."
    INVALID_CONTRACT_OFFER_PROFIT_RATE = (
        "CP 정산비율과 작가 정산비율의 합은 100이어야 합니다."
    )
    INVALID_CONTRACT_OFFER_PROFIT_RATE_POSITIVE = "정산비율은 0보다 커야 합니다."

    # FAQ 관련
    FAQ_TITLE_REQUIRED = "FAQ 제목을 입력해주세요."
    FAQ_CONTENT_REQUIRED = "FAQ 내용을 입력해주세요."

    # 외부 시스템 연동 관련
    REQUEST_NUMBER_MISMATCH = "요청 번호가 일치하지 않습니다."
    INVALID_OR_EXPIRED_SESSION = "유효하지 않거나 만료된 세션입니다."
    DATA_INTEGRITY_VERIFICATION_FAILED = "데이터 무결성 검증에 실패했습니다."

    # 템플릿 메시지
    NOT_ALLOWED_TYPE = "허용되지 않은 종류입니다. ({})"
    NOT_ALLOWED_REWARD_TYPE = "허용되지 않은 이벤트 보상 종류입니다. ({})"
    NOT_ALLOWED_POSITION = "허용되지 않은 위치입니다. ({})"

    # 채팅 관련
    NOT_FOUND_PROFILE = "상대방 프로필을 찾을 수 없습니다."
    FORBIDDEN_ACCESS_CHAT_ROOM = "해당 대화방에 접근할 수 없습니다."
    NOT_FOUND_CHAT_ROOM = "해당 대화방을 찾을 수 없습니다."
    NOT_FOUND_MESSAGE = "해당 메시지를 찾을 수 없습니다."
    ALREADY_REPORTED_MESSAGE = "이미 신고한 메시지입니다."

    # 시스템 오류 관련
    DB_CONNECTION_ERROR = "데이터베이스 연결에 실패했습니다."
    DB_OPERATION_ERROR = "데이터베이스 작업 중 오류가 발생했습니다."
    INTERNAL_SERVER_ERROR = "서버 내부 오류가 발생했습니다."
    EXTERNAL_API_ERROR = "외부 API 호출 중 오류가 발생했습니다."

    # 중복 요청 관련
    DUPLICATE_PRODUCT_CREATION = "동일한 작품이 이미 등록되었습니다. 잠시 후 다시 시도해주세요."
    DUPLICATE_EPISODE_CREATION = "동일한 회차가 이미 등록되었습니다. 잠시 후 다시 시도해주세요."
    KEYCLOAK_CONNECTION_ERROR = "Keycloak 연결에 실패했습니다."
    KEYCLOAK_OPERATION_ERROR = "Keycloak 작업 중 오류가 발생했습니다."
    STORAGE_SERVICE_ERROR = "스토리지 서비스 오류가 발생했습니다."
    SEARCH_SERVICE_ERROR = "검색 서비스 오류가 발생했습니다."
    PAYMENT_SERVICE_ERROR = "결제 서비스 오류가 발생했습니다."
    QUEST_REWARD_ERROR = "퀘스트 보상 지급 중 오류가 발생했습니다."
    INVALID_PAYMENT_STATUS = "결제 정보가 맞지 않습니다."
    PAYMENT_COMPLETED_BUT_PROCESS_FAILED = "결제는 완료되었으나 처리 중 오류가 발생했습니다."  # "결제는 완료되었으나 처리 중 오류가 발생했습니다. 고객센터로 문의해주세요."
    DB_TRANSACTION_ERROR = "데이터베이스 트랜잭션 오류"
    PAYMENT_PROCESSING_ERROR = "결제 처리 중 오류 발생"

    # Request Validation 관련
    @staticmethod
    def required_field_missing(field_name: str) -> str:
        return f"필수 값이 누락되었습니다: {field_name}"

    @staticmethod
    def invalid_data_type(field_name: str) -> str:
        return f"잘못된 데이터 타입입니다: {field_name}"

    @staticmethod
    def invalid_field_value(field_name: str, error_msg: str) -> str:
        return f"{field_name}: {error_msg}"
