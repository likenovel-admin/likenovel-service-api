"""Versioned model choices, pinned once at a caller's job boundary.

The context contains no credentials. Never mutate app.const.settings to switch
models: concurrent requests must retain their own immutable choices.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from types import MappingProxyType
from typing import Any, Iterator, Mapping

from sqlalchemy import text

from app.const import FLASH_1017_MODEL, settings

MODEL_SUBMISSION_UNKNOWN_PREFIX = "provider_submission_unknown:"
# Explicit migration of the two deployed V4 Pro spellings. Stored CMS overrides
# are not rewritten, so a subsequent deliberate choice keeps its exact model.
LEGACY_V4_PRO_MODELS = frozenset({"deepseek/deepseek-v4-pro", "deepseek/deepseek-v4-pro-0813"})
BILLING_ROUTES = frozenset({"openrouter", "hive", "river", "anthropic", "gemini"})


@dataclass(frozen=True)
class AiModelBinding:
    feature_key: str
    model_id: str
    billing_route: str
    revision: int

    def __post_init__(self) -> None:
        if not self.feature_key or not self.model_id or len(self.model_id) > 200:
            raise ValueError("invalid model binding")
        if self.billing_route not in BILLING_ROUTES:
            raise ValueError("invalid billing route")
        if type(self.revision) is not int or self.revision < 0:
            raise ValueError("invalid model revision")


@dataclass(frozen=True)
class AiModelFeature:
    title: str
    category: str
    env_name: str
    default_model: str
    default_route: str
    required_capabilities: tuple[str, ...]
    job_boundary: str


FEATURE_CATALOG: Mapping[str, AiModelFeature] = MappingProxyType({
    "websochat.speed": AiModelFeature("웹소챗 빠름 답변", "실시간 채팅", "WEBSOCHAT_OPENROUTER_MODEL", "google/gemini-3.1-flash-lite", "openrouter", ("text",), "다음 채팅 턴"),
    "websochat.balance": AiModelFeature("웹소챗 균형 답변", "실시간 채팅", "WEBSOCHAT_OPENROUTER_MODEL", "google/gemini-3.1-flash-lite", "openrouter", ("text",), "다음 채팅 턴"),
    "websochat.deep": AiModelFeature("웹소챗 딥 답변", "실시간 채팅", "WEBSOCHAT_OPENROUTER_MODEL", "google/gemini-3.1-flash-lite", "openrouter", ("text",), "다음 채팅 턴"),
    "websochat.structured": AiModelFeature("웹소챗 분기·기억·회상 판단", "실시간 채팅", "WEBSOCHAT_OPENROUTER_MODEL", "google/gemini-3.1-flash-lite", "openrouter", ("json_object",), "다음 채팅 턴"),
    "ai_chat.tools": AiModelFeature("AI 사서 도구 판단", "AI 사서·추천", "", FLASH_1017_MODEL, "openrouter", ("tools",), "다음 사서 대화"),
    "ai_chat.answer": AiModelFeature("AI 사서 답변", "AI 사서·추천", "", FLASH_1017_MODEL, "hive", ("text",), "다음 사서 대화"),
    "recommendation": AiModelFeature("추천·추천 이유", "AI 사서·추천", "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001", "anthropic", ("json_object",), "다음 추천 작업"),
    "recommendation.answer": AiModelFeature("추천 이유 문장", "AI 사서·추천", "ANTHROPIC_MODEL", "claude-haiku-4-5-20251001", "anthropic", ("text",), "다음 추천 작업"),
    "ai_reader.decision": AiModelFeature("AI 독자 판단·댓글", "AI 독자", "", FLASH_1017_MODEL, "hive", ("json_object",), "다음 독자 판단 작업"),
    "dna.analysis": AiModelFeature("작품 DNA 분석", "작품 분석", "AI_DNA_OPENROUTER_MODEL", FLASH_1017_MODEL, "openrouter", ("json_schema",), "다음 작품 분석"),
    "storyctx.summary": AiModelFeature("회차 요약", "작품 컨텍스트", "STORY_AGENT_SUMMARY_MODEL", "deepseek/deepseek-v3.2", "openrouter", ("text",), "다음 작품 수집 작업"),
    "storyctx.signals": AiModelFeature("인물 신호 추출", "작품 컨텍스트", "STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL", FLASH_1017_MODEL, "openrouter", ("json_schema",), "다음 작품 수집 작업"),
    "storyctx.protagonist": AiModelFeature("작품 주인공 판정", "작품 컨텍스트", "STORY_AGENT_CHARACTER_SIGNALS_OPENROUTER_MODEL", FLASH_1017_MODEL, "openrouter", ("json_schema",), "다음 작품 수집 작업"),
    "storyctx.scenes": AiModelFeature("장면 추출", "작품 컨텍스트", "STORY_AGENT_SCENE_EXTRACTION_OPENROUTER_MODEL", FLASH_1017_MODEL, "openrouter", ("json_object",), "다음 작품 수집 작업"),
    "storyctx.rp": AiModelFeature("캐릭터 RP 계획·프로필·대사", "작품 컨텍스트", "STORY_AGENT_RP_OPENROUTER_MODEL", "google/gemma-4-31b-it", "openrouter", ("json_schema",), "다음 작품 수집 작업"),
    "mcp.single_copy": AiModelFeature("단일구좌 소개 문구", "운영 도구", "MCP_SINGLE_COPY_MODEL", "google/gemini-3.8-flash", "openrouter", ("json_object",), "다음 문구 생성 작업"),
    "provider_health.deepseek": AiModelFeature("DeepSeek 연결 확인", "운영 도구", "AI_PROVIDER_HEALTH_OPENROUTER_DEEPSEEK_MODEL", FLASH_1017_MODEL, "openrouter", ("text",), "다음 연결 확인"),
    "character.opening_label": AiModelFeature("캐릭터 오프닝 라벨", "운영 도구", "CHARACTER_CHAT_OPENING_LABEL_MODEL", "deepseek/deepseek-v3.2", "openrouter", ("json_object",), "다음 라벨링 작업"),
})

ModelSnapshot = Mapping[str, AiModelBinding]
_current_snapshot: ContextVar[ModelSnapshot | None] = ContextVar("ai_model_snapshot", default=None)
_CONFIG_SELECT = "SELECT feature_key, model_id, billing_route, revision FROM tb_ai_model_config"


def get_feature(feature_key: str) -> AiModelFeature:
    try:
        return FEATURE_CATALOG[feature_key]
    except KeyError:
        raise ValueError("unknown AI model feature") from None


def default_model_binding(feature_key: str) -> AiModelBinding:
    feature = get_feature(feature_key)
    # Preserve the existing explicit native signal consumer until its
    # STORY_AGENT_RP_REASONING_MODEL path is retired. Saved CMS rows override
    # this revision-zero default in _snapshot_from_rows.
    if feature_key == "storyctx.signals":
        native_model = os.getenv("STORY_AGENT_RP_REASONING_MODEL", "").strip()
        if native_model.startswith("anthropic."):
            native_model = native_model.split(".", 1)[1].strip()
        native_key = os.getenv("ANTHROPIC_API_KEY", settings.ANTHROPIC_API_KEY)
        if native_model and native_key:
            return AiModelBinding(feature_key, native_model, "anthropic", 0)
    # Empty env_name marks the explicitly requested CMS initial migration.
    # Legacy native-provider environment values must not undo that choice.
    model = str(os.getenv(feature.env_name, getattr(settings, feature.env_name, feature.default_model)) or feature.default_model).strip() if feature.env_name else feature.default_model
    if model in LEGACY_V4_PRO_MODELS:
        model = FLASH_1017_MODEL
    return AiModelBinding(feature_key, model, feature.default_route, 0)


def _snapshot_from_rows(rows: list[Mapping[str, Any]]) -> ModelSnapshot:
    bindings = {key: default_model_binding(key) for key in FEATURE_CATALOG}
    for row in rows:
        key = str(row["feature_key"])
        get_feature(key)
        bindings[key] = AiModelBinding(key, str(row["model_id"]), str(row["billing_route"]), int(row["revision"]))
    return MappingProxyType(bindings)


async def load_ai_model_snapshot(db: Any) -> ModelSnapshot:
    """One read freezes all settings for a job; missing migration is an error."""
    result = await db.execute(text(_CONFIG_SELECT))
    return _snapshot_from_rows(list(result.mappings().all()))


def load_ai_model_snapshot_sync(conn: Any) -> ModelSnapshot:
    with conn.cursor() as cursor:
        cursor.execute(_CONFIG_SELECT)
        rows = cursor.fetchall()
    return _snapshot_from_rows(list(rows))


def serialize_model_snapshot(snapshot: ModelSnapshot) -> dict[str, dict[str, Any]]:
    return {key: asdict(binding) for key, binding in snapshot.items()}


def deserialize_model_snapshot(value: Mapping[str, Mapping[str, Any]]) -> ModelSnapshot:
    bindings: dict[str, AiModelBinding] = {}
    for key, item in value.items():
        get_feature(key)
        if item.get("feature_key") != key:
            raise ValueError("model snapshot feature mismatch")
        bindings[key] = AiModelBinding(**dict(item))
    if set(bindings) != set(FEATURE_CATALOG):
        raise ValueError("incomplete model snapshot")
    return MappingProxyType(bindings)


@contextmanager
def use_ai_model_snapshot(snapshot: ModelSnapshot) -> Iterator[ModelSnapshot]:
    # Copy the mapping so mutating the caller's dict cannot alter an active job.
    frozen = MappingProxyType(dict(snapshot))
    token = _current_snapshot.set(frozen)
    try:
        yield frozen
    finally:
        _current_snapshot.reset(token)


def has_ai_model_snapshot() -> bool:
    return _current_snapshot.get() is not None


def get_model_binding(feature_key: str, *, default_model: str | None = None, default_route: str = "openrouter") -> AiModelBinding:
    get_feature(feature_key)
    snapshot = _current_snapshot.get()
    if snapshot is not None:
        if feature_key not in snapshot:
            raise ValueError("feature missing from pinned model snapshot")
        return snapshot[feature_key]
    if default_model:
        model = FLASH_1017_MODEL if default_model in LEGACY_V4_PRO_MODELS else default_model
        return AiModelBinding(feature_key, model, default_route, 0)
    return default_model_binding(feature_key)
