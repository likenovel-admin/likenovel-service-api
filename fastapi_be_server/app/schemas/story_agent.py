from typing import Optional

from pydantic import BaseModel, Field, field_validator


class StoryAgentProductItem(BaseModel):
    productId: int
    title: str
    authorNickname: str | None = None
    coverImagePath: str | None = None
    statusCode: str | None = None
    latestEpisodeNo: int = 0
    contextStatus: str | None = None


class StoryAgentSessionItem(BaseModel):
    sessionId: int
    productId: int
    title: str
    updatedDate: str
    createdDate: str
    productTitle: str | None = None
    productAuthorNickname: str | None = None
    coverImagePath: str | None = None
    latestEpisodeNo: int = 0
    contextStatus: str | None = None
    canSendMessage: bool | None = None
    unavailableMessage: str | None = None


class StoryAgentMessageItem(BaseModel):
    messageId: int
    role: str
    content: str
    createdDate: str
    referencedEpisodeNos: list[int] | None = None
    reasonCards: list["StoryAgentReasonCardItem"] | None = None
    actionCards: list["StoryAgentStarterActionItem"] | None = None
    ctaCards: list["StoryAgentCtaCardItem"] | None = None


class StoryAgentStarterActionItem(BaseModel):
    label: str
    prompt: str


class StoryAgentReasonCardItem(BaseModel):
    title: str
    description: str


class StoryAgentCtaCardItem(BaseModel):
    type: str
    label: str
    productId: int | None = None


class StoryAgentStarterItem(BaseModel):
    productTitle: str
    scopeState: str = "unknown"
    readEpisodeNo: int | None = None
    readEpisodeTitle: str | None = None
    latestEpisodeNo: int = 0
    reasonCards: list[StoryAgentReasonCardItem] = []
    ctaCards: list[StoryAgentCtaCardItem] = []
    actions: list[StoryAgentStarterActionItem] = []


class PostStoryAgentSessionReqBody(BaseModel):
    product_id: int = Field(..., gt=0)
    guest_key: Optional[str] = Field(default=None, max_length=64)
    title: Optional[str] = Field(default=None, max_length=120)
    rp_mode: Optional[str] = Field(default=None, max_length=10)
    active_character: Optional[str] = Field(default=None, max_length=80)
    scene_episode_no: Optional[int] = Field(default=None, gt=0)
    game_mode: Optional[str] = Field(default=None, max_length=30)
    game_gender_scope: Optional[str] = Field(default=None, max_length=10)
    game_category: Optional[str] = Field(default=None, max_length=30)
    game_match_mode: Optional[str] = Field(default=None, max_length=30)
    game_read_episode_to: Optional[int] = Field(default=None, gt=0)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("rp_mode")
    @classmethod
    def normalize_rp_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"free", "scene"}:
            raise ValueError("rp_mode는 free 또는 scene만 허용됩니다.")
        return normalized

    @field_validator("active_character")
    @classmethod
    def normalize_active_character(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("game_mode")
    @classmethod
    def normalize_game_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"ideal_worldcup", "vs_game"}:
            raise ValueError("game_mode는 ideal_worldcup 또는 vs_game만 허용됩니다.")
        return normalized

    @field_validator("game_gender_scope")
    @classmethod
    def normalize_game_gender_scope(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"male", "female", "mixed"}:
            raise ValueError("game_gender_scope는 male, female, mixed만 허용됩니다.")
        return normalized

    @field_validator("game_category")
    @classmethod
    def normalize_game_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {
            "romance",
            "date",
            "narrative",
            "power",
            "intelligence",
            "charm",
            "mental",
            "survival",
            "personality",
        }:
            raise ValueError("game_category가 허용 목록에 없습니다.")
        return normalized

    @field_validator("game_match_mode")
    @classmethod
    def normalize_game_match_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"direct_match", "criteria_match"}:
            raise ValueError("game_match_mode는 direct_match 또는 criteria_match만 허용됩니다.")
        return normalized


class PatchStoryAgentSessionReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title은 비어 있을 수 없습니다.")
        return normalized


class DeleteStoryAgentSessionReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)


class PostStoryAgentMessageReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)
    client_message_id: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=2000)
    rp_mode: Optional[str] = Field(default=None, max_length=10)
    active_character: Optional[str] = Field(default=None, max_length=80)
    scene_episode_no: Optional[int] = Field(default=None, gt=0)
    game_mode: Optional[str] = Field(default=None, max_length=30)
    game_gender_scope: Optional[str] = Field(default=None, max_length=10)
    game_category: Optional[str] = Field(default=None, max_length=30)
    game_match_mode: Optional[str] = Field(default=None, max_length=30)
    game_read_episode_to: Optional[int] = Field(default=None, gt=0)

    @field_validator("client_message_id")
    @classmethod
    def normalize_client_message_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("client_message_id는 비어 있을 수 없습니다.")
        return normalized

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("content는 비어 있을 수 없습니다.")
        return normalized

    @field_validator("rp_mode")
    @classmethod
    def normalize_message_rp_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"free", "scene"}:
            raise ValueError("rp_mode는 free 또는 scene만 허용됩니다.")
        return normalized

    @field_validator("active_character")
    @classmethod
    def normalize_message_active_character(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("game_mode")
    @classmethod
    def normalize_message_game_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"ideal_worldcup", "vs_game"}:
            raise ValueError("game_mode는 ideal_worldcup 또는 vs_game만 허용됩니다.")
        return normalized

    @field_validator("game_gender_scope")
    @classmethod
    def normalize_message_game_gender_scope(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"male", "female", "mixed"}:
            raise ValueError("game_gender_scope는 male, female, mixed만 허용됩니다.")
        return normalized

    @field_validator("game_category")
    @classmethod
    def normalize_message_game_category(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {
            "romance",
            "date",
            "narrative",
            "power",
            "intelligence",
            "charm",
            "mental",
            "survival",
            "personality",
        }:
            raise ValueError("game_category가 허용 목록에 없습니다.")
        return normalized

    @field_validator("game_match_mode")
    @classmethod
    def normalize_message_game_match_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"direct_match", "criteria_match"}:
            raise ValueError("game_match_mode는 direct_match 또는 criteria_match만 허용됩니다.")
        return normalized
