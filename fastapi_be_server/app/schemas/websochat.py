from typing import Optional

from pydantic import BaseModel, Field, field_validator


class WebsochatProductItem(BaseModel):
    productId: int
    title: str
    authorNickname: str | None = None
    coverImagePath: str | None = None
    statusCode: str | None = None
    latestEpisodeNo: int = 0
    publishedLatestEpisodeNo: int = 0
    syncedLatestEpisodeNo: int = 0
    contextStatus: str | None = None


class WebsochatSessionItem(BaseModel):
    sessionId: int
    productId: int
    title: str
    updatedDate: str
    createdDate: str
    productTitle: str | None = None
    productAuthorNickname: str | None = None
    coverImagePath: str | None = None
    readEpisodeNo: int | None = None
    readEpisodeTitle: str | None = None
    latestEpisodeNo: int = 0
    publishedLatestEpisodeNo: int = 0
    syncedLatestEpisodeNo: int = 0
    contextStatus: str | None = None
    canSendMessage: bool | None = None
    unavailableMessage: str | None = None
    pendingQaActionKey: str | None = None


class WebsochatMessageItem(BaseModel):
    messageId: int
    role: str
    content: str
    createdDate: str
    clientMessageId: str | None = None
    referencedEpisodeNos: list[int] | None = None
    reasonCards: list["WebsochatReasonCardItem"] | None = None
    actionCards: list["WebsochatStarterActionItem"] | None = None
    ctaCards: list["WebsochatCtaCardItem"] | None = None


class WebsochatStarterActionItem(BaseModel):
    label: str
    prompt: str
    modeKey: str | None = None
    qaActionKey: str | None = None
    cashCost: int | None = None


class WebsochatReasonCardItem(BaseModel):
    title: str
    description: str


class WebsochatCtaCardItem(BaseModel):
    type: str
    label: str
    productId: int | None = None


class WebsochatStarterItem(BaseModel):
    productTitle: str
    scopeState: str = "unknown"
    readEpisodeNo: int | None = None
    readEpisodeTitle: str | None = None
    latestEpisodeNo: int = 0
    publishedLatestEpisodeNo: int = 0
    syncedLatestEpisodeNo: int = 0
    reasonCards: list[WebsochatReasonCardItem] = []
    ctaCards: list[WebsochatCtaCardItem] = []
    actions: list[WebsochatStarterActionItem] = []


class PostWebsochatSessionReqBody(BaseModel):
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
    account_read_episode_to: Optional[int] = Field(default=None, gt=0)

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


class PatchWebsochatSessionReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)
    title: str = Field(..., min_length=1, max_length=120)

    @field_validator("title")
    @classmethod
    def normalize_title(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("title은 비어 있을 수 없습니다.")
        return normalized


class PatchWebsochatSessionReadScopeReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)
    read_episode_to: int = Field(..., gt=0)


class PatchWebsochatSessionModeReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)
    mode_key: str = Field(..., min_length=1, max_length=30)
    rp_mode: Optional[str] = Field(default=None, max_length=10)
    force_entry_guide: bool = False

    @field_validator("mode_key")
    @classmethod
    def normalize_mode_key(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {"qa", "rp", "ideal_worldcup"}:
            raise ValueError("mode_key는 qa, rp, ideal_worldcup만 허용됩니다.")
        return normalized

    @field_validator("rp_mode")
    @classmethod
    def normalize_patch_rp_mode(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"free", "scene"}:
            raise ValueError("rp_mode는 free 또는 scene만 허용됩니다.")
        return normalized


class DeleteWebsochatSessionReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)


class PostWebsochatMessageReqBody(BaseModel):
    guest_key: Optional[str] = Field(default=None, max_length=64)
    client_message_id: str = Field(..., min_length=1, max_length=64)
    content: str = Field(..., min_length=1, max_length=2000)
    starter_mode_key: Optional[str] = Field(default=None, max_length=30)
    qa_action_key: Optional[str] = Field(default=None, max_length=30)
    rp_mode: Optional[str] = Field(default=None, max_length=10)
    active_character: Optional[str] = Field(default=None, max_length=80)
    scene_episode_no: Optional[int] = Field(default=None, gt=0)
    game_mode: Optional[str] = Field(default=None, max_length=30)
    game_gender_scope: Optional[str] = Field(default=None, max_length=10)
    game_category: Optional[str] = Field(default=None, max_length=30)
    game_match_mode: Optional[str] = Field(default=None, max_length=30)
    game_read_episode_to: Optional[int] = Field(default=None, gt=0)
    account_read_episode_to: Optional[int] = Field(default=None, gt=0)

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

    @field_validator("starter_mode_key")
    @classmethod
    def normalize_starter_mode_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"qa", "rp", "ideal_worldcup"}:
            raise ValueError("starter_mode_key는 qa, rp, ideal_worldcup만 허용됩니다.")
        return normalized

    @field_validator("qa_action_key")
    @classmethod
    def normalize_qa_action_key(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized not in {"predict", "next_episode_write"}:
            raise ValueError("qa_action_key는 predict 또는 next_episode_write만 허용됩니다.")
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
