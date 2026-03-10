import json
import math
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


ALLOWED_AI_SIGNAL_EVENT_TYPES = {
    "episode_view",
    "episode_end",
    "latest_episode_reached",
    "next_episode_click",
}
ALLOWED_AI_FACTOR_TYPES = {
    "protagonist",
    "job",
    "goal",
    "material",
    "worldview",
    "romance",
    "style",
    "theme",
    "mood",
}
MAX_EVENT_PAYLOAD_LENGTH = 3000


# 온보딩

class PostOnboardingReqBody(BaseModel):
    product_ids: list[int] = Field(
        default_factory=list,
        max_length=2,
        description="온보딩에서 선택한 작품 ID 목록 (0~2개)",
    )
    moods: list[str] = Field(
        default_factory=list,
        description="선택한 분위기 태그 목록 (선택사항)",
    )
    hero_tags: list[str] = Field(
        default_factory=list,
        description="주인공 탭에서 선택한 태그 목록 (선택사항)",
    )
    world_tone_tags: list[str] = Field(
        default_factory=list,
        description="세계관/분위기 탭에서 선택한 태그 목록 (선택사항)",
    )
    relation_tags: list[str] = Field(
        default_factory=list,
        description="관계/기타 탭에서 선택한 태그 목록 (선택사항)",
    )
    adult_yn: str = Field(default="N", description="성인 작품 포함 여부 (Y/N)")

    @field_validator("product_ids")
    @classmethod
    def validate_product_ids(cls, values: list[int]) -> list[int]:
        if any(v <= 0 for v in values):
            raise ValueError("product_ids는 양수 정수만 허용됩니다.")
        return values

    @field_validator("moods", "hero_tags", "world_tone_tags", "relation_tags")
    @classmethod
    def normalize_tags(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw in values or []:
            tag = str(raw or "").strip()
            if not tag:
                continue
            if len(tag) > 60:
                tag = tag[:60]
            if tag in seen:
                continue
            normalized.append(tag)
            seen.add(tag)
            if len(normalized) >= 20:
                break
        return normalized

    @field_validator("adult_yn")
    @classmethod
    def validate_adult_yn(cls, value: str) -> str:
        upper = (value or "").upper().strip()
        if upper not in {"Y", "N"}:
            raise ValueError("adult_yn은 Y/N 값만 허용됩니다.")
        return upper

    @model_validator(mode="after")
    def validate_onboarding_inputs(self):
        if (
            not self.product_ids
            and not self.moods
            and not self.hero_tags
            and not self.world_tone_tags
            and not self.relation_tags
        ):
            raise ValueError("작품 또는 태그를 최소 1개 이상 선택해야 합니다.")
        return self


# AI 신호 이벤트 적재

class PostAiSignalEventReqBody(BaseModel):
    product_id: int = Field(..., description="작품 ID")
    episode_id: Optional[int] = Field(default=None, description="회차 ID")
    event_type: str = Field(..., min_length=1, max_length=50, description="이벤트 타입")
    session_id: Optional[str] = Field(default=None, max_length=64, description="세션 ID")
    active_seconds: int = Field(default=0, ge=0, description="활성 열람 시간(초)")
    scroll_depth: float = Field(default=0.0, ge=0.0, le=1.0, description="스크롤 깊이(0~1)")
    progress_ratio: float = Field(default=0.0, ge=0.0, le=1.0, description="진행률(0~1)")
    next_available_yn: str = Field(default="N", description="다음화 존재 여부(Y/N)")
    latest_episode_reached_yn: str = Field(default="N", description="최신화 도달 여부(Y/N)")
    factor_type: Optional[str] = Field(
        default=None, max_length=50, description="취향 축 타입(선택)"
    )
    factor_key: Optional[str] = Field(
        default=None, max_length=120, description="취향 축 키(선택)"
    )
    signal_score: Optional[float] = Field(default=None, description="신호 점수(선택)")
    event_payload: Optional[dict] = Field(default=None, description="추가 이벤트 페이로드(선택)")

    @field_validator("event_type")
    @classmethod
    def normalize_event_type(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("event_type은 비어 있을 수 없습니다.")
        if value not in ALLOWED_AI_SIGNAL_EVENT_TYPES:
            raise ValueError("허용되지 않은 event_type 입니다.")
        return value

    @field_validator("next_available_yn", "latest_episode_reached_yn")
    @classmethod
    def validate_yn(cls, value: str) -> str:
        upper = (value or "").upper().strip()
        if upper not in {"Y", "N"}:
            raise ValueError("Y/N 값만 허용됩니다.")
        return upper

    @field_validator("factor_type")
    @classmethod
    def validate_factor_type(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in ALLOWED_AI_FACTOR_TYPES:
            raise ValueError("허용되지 않은 factor_type 입니다.")
        return normalized

    @field_validator("factor_key")
    @classmethod
    def normalize_factor_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("signal_score")
    @classmethod
    def validate_signal_score(cls, value: Optional[float]) -> Optional[float]:
        if value is None:
            return None
        if not math.isfinite(value):
            raise ValueError("signal_score는 유한한 숫자여야 합니다.")
        if value < -20 or value > 20:
            raise ValueError("signal_score 허용 범위를 벗어났습니다.")
        return float(value)

    @field_validator("event_payload")
    @classmethod
    def validate_event_payload(cls, value: Optional[dict]) -> Optional[dict]:
        if value is None:
            return None
        serialized = json.dumps(value, ensure_ascii=False)
        if len(serialized) > MAX_EVENT_PAYLOAD_LENGTH:
            raise ValueError("event_payload 크기가 허용 범위를 초과했습니다.")
        return value

    @model_validator(mode="after")
    def validate_factor_fields(self):
        has_factor_type = bool(self.factor_type)
        has_factor_key = bool(self.factor_key)
        if has_factor_type != has_factor_key:
            raise ValueError("factor_type과 factor_key는 함께 전달되어야 합니다.")
        if self.signal_score is not None and not (has_factor_type and has_factor_key):
            raise ValueError("signal_score는 factor_type/factor_key와 함께 전달되어야 합니다.")
        return self


# 취향 추천 섹션

class RecommendProduct(BaseModel):
    product_id: int
    title: str
    cover_url: Optional[str] = None
    author_nickname: Optional[str] = None
    episode_count: int = 0
    match_reason: str = ""


class RecommendSection(BaseModel):
    title: str
    dimension: str
    reason: str
    products: list[RecommendProduct] = Field(default_factory=list)


# AI 챗 추천

class PostAiRecommendReqBody(BaseModel):
    query: Optional[str] = Field(
        default=None,
        max_length=200,
        description="자유 입력 질문 (최대 200자, null이면 preset 사용)",
    )
    preset: Optional[str] = Field(
        default=None,
        description="프리셋: stacked-chapters | good-schedule | completed | trending",
    )
    exclude_product_ids: list[int] = Field(
        default_factory=list,
        description="기추천받은 작품 제외 목록",
    )
    adult_yn: str = Field(default="N", description="성인 작품 포함 여부 (Y/N)")

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        value = value.strip()
        return value or None

    @field_validator("preset")
    @classmethod
    def validate_preset(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        preset = value.strip()
        if not preset:
            return None
        allowed = {"stacked-chapters", "good-schedule", "completed", "trending"}
        if preset not in allowed:
            raise ValueError("preset 값이 유효하지 않습니다.")
        return preset

    @field_validator("adult_yn")
    @classmethod
    def validate_adult_yn(cls, value: str) -> str:
        upper = (value or "").upper().strip()
        if upper not in {"Y", "N"}:
            raise ValueError("adult_yn은 Y/N 값만 허용됩니다.")
        return upper


class ChatMessageDTO(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=1000)
    product_id: Optional[int] = None

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized:
            raise ValueError("content는 비어 있을 수 없습니다.")
        return normalized


class BrowsingContext(BaseModel):
    browsed_product_ids: list[int] = Field(default_factory=list)
    trigger: Literal["browsing", "manual"] = "manual"
    page_type: Literal["home", "product", "mypage", "other"] = "other"
    pathname: Optional[str] = Field(default=None, max_length=200)
    current_product_id: Optional[int] = Field(default=None)
    current_episode_id: Optional[int] = Field(default=None)

    @field_validator("browsed_product_ids")
    @classmethod
    def normalize_browsed_product_ids(cls, values: list[int]) -> list[int]:
        normalized: list[int] = []
        seen: set[int] = set()
        for value in values or []:
            try:
                product_id = int(value)
            except (TypeError, ValueError):
                continue
            if product_id <= 0 or product_id in seen:
                continue
            normalized.append(product_id)
            seen.add(product_id)
            if len(normalized) >= 20:
                break
        return normalized

    @field_validator("pathname")
    @classmethod
    def normalize_pathname(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class PostAiChatReqBody(BaseModel):
    messages: list[ChatMessageDTO] = Field(default_factory=list)
    context: BrowsingContext = Field(default_factory=BrowsingContext)
    preset: Optional[str] = Field(
        default=None,
        description="프리셋: stacked-chapters | good-schedule | completed | trending",
    )
    exclude_product_ids: list[int] = Field(default_factory=list)
    adult_yn: str = Field(default="N", description="성인 작품 포함 여부 (Y/N)")

    @field_validator("preset")
    @classmethod
    def validate_chat_preset(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        preset = value.strip()
        if not preset:
            return None
        allowed = {"stacked-chapters", "good-schedule", "completed", "trending"}
        if preset not in allowed:
            raise ValueError("preset 값이 유효하지 않습니다.")
        return preset

    @field_validator("adult_yn")
    @classmethod
    def validate_chat_adult_yn(cls, value: str) -> str:
        upper = (value or "").upper().strip()
        if upper not in {"Y", "N"}:
            raise ValueError("adult_yn은 Y/N 값만 허용됩니다.")
        return upper


class TasteMatch(BaseModel):
    protagonist: float = 0.0
    mood: float = 0.0
    pacing: float = 0.0


class AiRecommendResponse(BaseModel):
    product: RecommendProduct
    reason: str
    taste_match: TasteMatch


# 취향 프로파일

class TasteProfileResponse(BaseModel):
    taste_summary: Optional[str] = None
    taste_tags: list[str] = Field(default_factory=list)
    preferred_protagonist: Optional[dict] = None
    preferred_mood: Optional[dict] = None
    preferred_themes: Optional[dict] = None
    preferred_pacing: Optional[str] = None
    recommendation_sections: list[dict] = Field(default_factory=list)
    has_profile: bool = False
