from pydantic import BaseModel, Field
from typing import List, Optional


class AdminBase(BaseModel):
    pass


"""
request area
"""


class PutUserReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    role_type: Optional[str] = Field(
        default=None, examples=["normal", "admin"], description="권한(normal | admin)"
    )


class PutBadgeReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    promotion_conditions: Optional[int] = Field(
        default=None, examples=[1], description="승급 조건"
    )


class PutProductReviewReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(
        default=None, examples=[1], description="작품 아이디"
    )
    episode_id: Optional[int] = Field(
        default=None, examples=[1], description="회차 아이디"
    )
    user_id: Optional[int] = Field(
        default=None, examples=[1], description="유저 아이디"
    )
    review_text: Optional[str] = Field(
        default=None, examples=["내용"], description="리뷰 내용"
    )
    open_yn: Optional[str] = Field(
        default=None, examples=["Y"], description="공개 여부"
    )


class PutProductCommentReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(
        default=None, examples=[1], description="작품 아이디"
    )
    episode_id: Optional[int] = Field(
        default=None, examples=[1], description="회차 아이디"
    )
    user_id: Optional[int] = Field(
        default=None, examples=[1], description="유저 아이디"
    )
    profile_id: Optional[int] = Field(
        default=None, examples=[1], description="프로필 아이디"
    )
    author_recommend_yn: Optional[str] = Field(
        default=None, examples=["N"], description="작가 추천 여부"
    )
    content: Optional[str] = Field(
        default=None, examples=["내용"], description="댓글 내용"
    )
    use_yn: Optional[str] = Field(default=None, examples=["Y"], description="사용 여부")
    open_yn: Optional[str] = Field(
        default=None, examples=["Y"], description="공개 여부"
    )
    display_top_yn: Optional[str] = Field(
        default=None, examples=["N"], description="코멘트 상단 고정 여부"
    )


class PutProductNoticeReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(
        default=None, examples=[1], description="작품 아이디"
    )
    user_id: Optional[int] = Field(
        default=None, examples=[1], description="유저 아이디"
    )
    subject: Optional[str] = Field(
        default=None, examples=["제목"], description="공지 제목"
    )
    content: Optional[str] = Field(
        default=None, examples=["내용"], description="공지 내용"
    )
    publish_reserve_date: Optional[str] = Field(
        default=None, examples=["2025-07-07 12:00:00"], description="예약 설정"
    )
    open_yn: Optional[str] = Field(
        default=None, examples=["N"], description="작품 공지 공개 여부"
    )
    use_yn: Optional[str] = Field(default=None, examples=["Y"], description="사용 여부")


class PostKeywordReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    keyword_name: str = Field(examples=["키워드"], description="키워드 이름")
    category_id: int = Field(examples=[1], description="카테고리 아이디")


class PutKeywordReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    keyword_name: Optional[str] = Field(
        default=None, examples=["키워드"], description="키워드 이름"
    )
    category_id: Optional[int] = Field(
        default=None, examples=[1], description="카테고리 아이디"
    )


class PostPublisherPromotionReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: int = Field(examples=[1], description="작품 아이디")
    show_order: int = Field(examples=[1], description="노출 순서")


class PutPublisherPromotionReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(
        default=None, examples=[1], description="작품 아이디"
    )
    show_order: Optional[int] = Field(
        default=None, examples=[1], description="노출 순서"
    )


class PutAlgorithmRecommendSectionReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    position: Optional[str] = Field(default=None, examples=["위치"], description="위치")
    feature: Optional[str] = Field(
        default=None, examples=["default_1"], description="feature"
    )


class PostDirectRecommendReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    name: str = Field(examples=["추천구좌"], description="추천구좌명")
    order: int = Field(examples=[1], description="노출 순서")
    product_ids: List[int] = Field(examples=[[1, 2]], description="노출 작품")
    exposure_start_date: str = Field(
        examples=["2025-08-01"], description="노출 기간 시작일"
    )
    exposure_end_date: str = Field(
        examples=["2025-08-02"], description="노출 기간 종료일"
    )
    exposure_start_time_weekday: str = Field(
        examples=["10:00"], description="노출 시간 주중 시작 시간"
    )
    exposure_end_time_weekday: str = Field(
        examples=["18:00"], description="노출 시간 주중 종료 시간"
    )
    exposure_start_time_weekend: str = Field(
        examples=["10:00"], description="노출 시간 주말 시작 시간"
    )
    exposure_end_time_weekend: str = Field(
        examples=["18:00"], description="노출 시간 주말 종료 시간"
    )


class PutDirectRecommendReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    name: Optional[str] = Field(
        default=None, examples=["추천구좌"], description="추천구좌명"
    )
    order: Optional[int] = Field(default=None, examples=[1], description="노출 순서")
    product_ids: Optional[List[int]] = Field(
        default=None, examples=[[1, 2]], description="노출 작품"
    )
    exposure_start_date: Optional[str] = Field(
        default=None, examples=["2025-08-01"], description="노출 기간 시작일"
    )
    exposure_end_date: Optional[str] = Field(
        default=None, examples=["2025-08-02"], description="노출 기간 종료일"
    )
    exposure_start_time_weekday: Optional[str] = Field(
        default=None, examples=["10:00"], description="노출 시간 주중 시작 시간"
    )
    exposure_end_time_weekday: Optional[str] = Field(
        default=None, examples=["18:00"], description="노출 시간 주중 종료 시간"
    )
    exposure_start_time_weekend: Optional[str] = Field(
        default=None, examples=["10:00"], description="노출 시간 주말 시작 시간"
    )
    exposure_end_time_weekend: Optional[str] = Field(
        default=None, examples=["18:00"], description="노출 시간 주말 종료 시간"
    )


class PostAppliedPromotionReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: int = Field(examples=[1], description="작품 id")
    type: str = Field(
        examples=["waiting-for-free"],
        description="프로모션 종류, 기다리면 무료 (waiting-for-free) | 6-9 패스 (6-9-path)",
    )
    # status: str                             = Field(examples=['apply'], description="상태, 진행중 (ing) | 신청 (apply) | 철회 (cancel) | 종료 (end) | 반려 (deny)")
    start_date: str = Field(examples=["2025-08-01"], description="시작일")
    end_date: str = Field(examples=["2025-08-02"], description="종료일")
    # num_of_ticket_per_person: int           = Field(examples=[1], description="명당 증정 대여권 수")


class PostAcceptAppliedPromotionReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    end_date: str = Field(examples=["2025-08-02"], description="종료일")


class PutAppliedPromotionReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    product_id: Optional[int] = Field(default=None, examples=[1], description="작품 id")
    type: Optional[str] = Field(
        default=None,
        examples=["waiting-for-free"],
        description="프로모션 종류, 기다리면 무료 (waiting-for-free) | 6-9 패스 (6-9-path)",
    )
    status: Optional[str] = Field(
        default=None,
        examples=["apply"],
        description="상태, 진행중 (ing) | 신청 (apply) | 철회 (cancel) | 종료 (end) | 반려 (deny)",
    )
    start_date: Optional[str] = Field(
        default=None, examples=["2025-08-01"], description="시작일"
    )
    end_date: Optional[str] = Field(
        default=None, examples=["2025-08-02"], description="종료일"
    )
    num_of_ticket_per_person: Optional[int] = Field(
        default=None, examples=[1], description="명당 증정 대여권 수"
    )


class PutPushMessageTemplatesReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    use_yn: Optional[str] = Field(default=None, examples=["Y"], description="사용 여부")
    name: Optional[str] = Field(
        default=None, examples=["템플릿명"], description="템플릿명"
    )
    condition: Optional[str] = Field(
        default=None, examples=["조건"], description="발송 조건"
    )
    landing_page: Optional[str] = Field(
        default=None, examples=["landing_page"], description="랜딩 페이지"
    )
    image_id: Optional[int] = Field(
        default=None, examples=[1], description="이미지 파일"
    )
    contents: Optional[str] = Field(
        default=None, examples=["메시지 내용"], description="본문"
    )


class SendPushMessageDirectlyReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    noti_type: str = Field(
        default="direct",
        examples=["direct"],
        description="알림 타입 (direct:직접발송, benefit:혜택정보, event:이벤트, system:시스템, marketing:마케팅)",
    )
    title: str = Field(examples=["알림 제목"], description="알림 제목")
    content: str = Field(examples=["푸시 내용"], description="본문")


class PutQuestReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    use_yn: Optional[str] = Field(default=None, examples=["Y"], description="사용 여부")
    title: Optional[str] = Field(
        default=None, examples=["퀘스트명"], description="퀘스트명"
    )
    reward_id: Optional[int] = Field(
        default=None, examples=[1], description="보상 아이디"
    )
    end_date: Optional[str] = Field(
        default=None, examples=["2025-12-31"], description="퀘스트 완료일"
    )
    goal_stage: Optional[int] = Field(
        default=None, examples=[5], description="목표 단계"
    )
    renewal: Optional[dict[str, str]] = Field(
        default=None,
        examples=[
            {
                "MON": "N",
                "TUE": "N",
                "WED": "N",
                "THU": "N",
                "FRI": "N",
                "SAT": "N",
                "SUN": "N",
            }
        ],
        description="갱신 주기",
    )
    step1: Optional[dict[str, str | int]] = Field(
        default=None,
        examples=[{"useYn": "N", "count_process": 0, "count_ticket": 0}],
        description="1단계",
    )
    step2: Optional[dict[str, str | int]] = Field(
        default=None,
        examples=[{"useYn": "N", "count_process": 0, "count_ticket": 0}],
        description="2단계",
    )
    step3: Optional[dict[str, str | int]] = Field(
        default=None,
        examples=[{"useYn": "N", "count_process": 0, "count_ticket": 0}],
        description="3단계",
    )


class PostEventReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    title: str = Field(examples=["이벤트명"], description="이벤트명")
    start_date: str = Field(examples=["2025-08-01"], description="이벤트 기간 (시작일)")
    end_date: str = Field(examples=["2025-08-07"], description="이벤트 기간 (종료일)")
    type: str = Field(
        examples=["etc"],
        description="이벤트 종류, 3화 감상 (view-3-times) | 댓글 등록 (add-comment) | 작품 등록 (add-product) | 그 외 (etc)",
    )
    target_product_ids: Optional[list[int]] = Field(
        default=None,
        examples=[[1, 2]],
        description="이벤트 작품 등록, 3화 감상, 댓글 등록인 경우의 대상 작품들의 id",
    )
    reward_type: Optional[str] = Field(
        default=None,
        examples=["ticket"],
        description="이벤트 보상 (type이 etc인 경우 null) - 보상 종류, 이벤트 대여권 (ticket) | 캐시 (cash)",
    )
    reward_amount: Optional[int] = Field(
        default=None,
        examples=[1],
        description="이벤트 보상 (type이 etc인 경우 null) - 증정 갯수",
    )
    reward_max_people: Optional[int] = Field(
        default=None,
        examples=[10],
        description="이벤트 보상 (type이 etc인 경우 null) - 최대 인원",
    )
    show_yn_thumbnail_img: str = Field(
        examples=["Y"], description="노출 여부 - 썸네일 이미지"
    )
    show_yn_detail_img: str = Field(
        examples=["Y"], description="노출 여부 - 상세 이미지"
    )
    show_yn_product: str = Field(examples=["Y"], description="노출 여부 - 작품 구좌")
    show_yn_information: str = Field(
        examples=["Y"], description="노출 여부 - 안내 문구"
    )
    thumbnail_image_id: int = Field(examples=[1], description="썸네일 이미지 파일")
    detail_image_id: int = Field(examples=[2], description="상세 이미지 파일")
    account_name: str = Field(examples=["구좌명"], description="구좌명")
    product_ids: list[int] = Field(
        examples=[[1, 2]], description="노출 구좌에 노출될 잘품들의 id"
    )
    information: str = Field(examples=["안내 문구"], description="안내 문구")


class PutEventReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    title: Optional[str] = Field(
        default=None, examples=["이벤트명"], description="이벤트명"
    )
    start_date: Optional[str] = Field(
        default=None, examples=["2025-08-01"], description="이벤트 기간 (시작일)"
    )
    end_date: Optional[str] = Field(
        default=None, examples=["2025-08-07"], description="이벤트 기간 (종료일)"
    )
    type: Optional[str] = Field(
        default=None,
        examples=["etc"],
        description="이벤트 종류, 3화 감상 (view-3-times) | 댓글 등록 (add-comment) | 작품 등록 (add-product) | 그 외 (etc)",
    )
    target_product_ids: Optional[list[int]] = Field(
        default=None,
        examples=[[1, 2]],
        description="이벤트 작품 등록, 3화 감상, 댓글 등록인 경우의 대상 작품들의 id",
    )
    reward_type: Optional[str] = Field(
        default=None,
        examples=["ticket"],
        description="이벤트 보상 (type이 etc인 경우 null) - 보상 종류, 이벤트 대여권 (ticket) | 캐시 (cash)",
    )
    reward_amount: Optional[int] = Field(
        default=None,
        examples=[1],
        description="이벤트 보상 (type이 etc인 경우 null) - 증정 갯수",
    )
    reward_max_people: Optional[int] = Field(
        default=None,
        examples=[10],
        description="이벤트 보상 (type이 etc인 경우 null) - 최대 인원",
    )
    show_yn_thumbnail_img: Optional[str] = Field(
        default=None, examples=["Y"], description="노출 여부 - 썸네일 이미지"
    )
    show_yn_detail_img: Optional[str] = Field(
        default=None, examples=["Y"], description="노출 여부 - 상세 이미지"
    )
    show_yn_product: Optional[str] = Field(
        default=None, examples=["Y"], description="노출 여부 - 작품 구좌"
    )
    show_yn_information: Optional[str] = Field(
        default=None, examples=["Y"], description="노출 여부 - 안내 문구"
    )
    thumbnail_image_id: Optional[int] = Field(
        default=None, examples=[1], description="썸네일 이미지 파일"
    )
    detail_image_id: Optional[int] = Field(
        default=None, examples=[2], description="상세 이미지 파일"
    )
    account_name: Optional[str] = Field(
        default=None, examples=["구좌명"], description="구좌명"
    )
    product_ids: Optional[list[int]] = Field(
        default=None, examples=[[1, 2]], description="노출 구좌에 노출될 잘품들의 id"
    )
    information: Optional[str] = Field(
        default=None, examples=["안내 문구"], description="안내 문구"
    )


class PostBannerReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    position: str = Field(
        examples=["main"],
        description="노출 위치, main (메인: 대배너(상단 캐러셀), 띠배너(중간), 고정배너(하단)) | paid (메인>유료: 대배너(상단 캐러셀)) | review (메인>작품리뷰: 대배너(상단 캐러셀)) | promotion (메인>프로모션: 고정배너(상단)) | search (검색/검색결과: 고정배너(상단) | viewer (뷰어: 띠배너))",
    )
    division: Optional[str] = Field(
        default=None,
        examples=["top"],
        description="노출 위치 (position이 main인 경우 세부 위치), top (대배너(상단 캐러셀)) | mid (띠배너(중간)) | bot (고정배너(하단))",
    )
    title: str = Field(examples=["배너"], description="배너명")
    show_start_date: str = Field(
        examples=["2025-08-01"], description="노출 기간 (시작일)"
    )
    show_end_date: str = Field(
        examples=["2025-08-07"], description="노출 기간 (종료일)"
    )
    show_order: Optional[int] = Field(
        default=None, examples=[1], description="노출 순서"
    )
    url: str = Field(examples=["http://likenovel.com/test"], description="링크 url")
    image_id: int = Field(examples=[1], description="이미지 id")
    mobile_image_id: int = Field(examples=[1], description="모바일 이미지 id")


class PutBannerReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    position: Optional[str] = Field(
        default=None,
        examples=["main"],
        description="노출 위치, main (메인: 대배너(상단 캐러셀), 띠배너(중간), 고정배너(하단)) | paid (메인>유료: 대배너(상단 캐러셀)) | review (메인>작품리뷰: 대배너(상단 캐러셀)) | promotion (메인>프로모션: 고정배너(상단)) | search (검색/검색결과: 고정배너(상단))",
    )
    division: Optional[str] = Field(
        default=None,
        examples=["top"],
        description="노출 위치 (position이 main인 경우 세부 위치), top (대배너(상단 캐러셀)) | mid (띠배너(중간)) | bot (고정배너(하단))",
    )
    title: Optional[str] = Field(default=None, examples=["배너"], description="배너명")
    show_start_date: Optional[str] = Field(
        default=None, examples=["2025-08-01"], description="노출 기간 (시작일)"
    )
    show_end_date: Optional[str] = Field(
        default=None, examples=["2025-08-07"], description="노출 기간 (종료일)"
    )
    show_order: Optional[int] = Field(
        default=None, examples=[1], description="노출 순서"
    )
    url: Optional[str] = Field(
        default=None, examples=["http://likenovel.com/test"], description="링크 url"
    )
    image_id: Optional[int] = Field(default=None, examples=[1], description="이미지 id")
    mobile_image_id: Optional[int] = Field(
        default=None, examples=[1], description="모바일 이미지 id"
    )


class PutPopupReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    use_yn: Optional[str] = Field(default=None, examples=["Y"], description="노출 여부")
    url: Optional[str] = Field(
        default=None, examples=["http://likenovel.com/test"], description="링크 url"
    )
    image_id: Optional[int] = Field(default=None, examples=[1], description="이미지 id")


class PostFAQReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    subject: str = Field(examples=["제목"], description="FAQ 제목")
    content: str = Field(examples=["내용"], description="FAQ 내용")


class PutFAQReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    subject: Optional[str] = Field(
        default=None, examples=["제목"], description="FAQ 제목"
    )
    content: Optional[str] = Field(
        default=None, examples=["내용"], description="FAQ 내용"
    )


class PostCommonRateReqBody(AdminBase):
    # 관리자 로그인 시 클라이언트에서 보내는 request body
    default_settlement_rate: float = Field(
        examples=[0.7], description="기본 정산율 - 작가 기준"
    )
    donation_settlement_rate: float = Field(
        examples=[0.7], description="후원 정산율 - 작가 기준"
    )
    payment_fee_rate: float = Field(examples=[0.1], description="결제 수수료")
    tax_amount_rate: float = Field(examples=[0.05], description="세액")


class PostNoticeReqBody(AdminBase):
    # 공지사항 등록 요청 시 클라이언트에서 보내는 request body
    subject: str = Field(examples=["subject"], description="공지 제목")
    content: str = Field(examples=["content"], description="공지 내용")
    primary_yn: Optional[str] = Field(
        default="N", examples=["N"], description="우선순위 여부"
    )
    file_id: Optional[int] = Field(
        default=None, examples=[1], description="첨부 파일 id"
    )


class PutNoticeReqBody(AdminBase):
    # 공지사항 수정 요청 시 클라이언트에서 보내는 request body
    subject: Optional[str] = Field(examples=["subject"], description="공지 제목")
    content: Optional[str] = Field(examples=["content"], description="공지 내용")
    primary_yn: Optional[str] = Field(
        default="N", examples=["N"], description="우선순위 여부"
    )
    file_id: Optional[int] = Field(
        default=None, examples=[1], description="첨부 파일 id"
    )


"""
response area
"""
