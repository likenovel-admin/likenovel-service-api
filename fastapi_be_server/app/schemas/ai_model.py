from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AiModelChoice(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    model_id: str = Field(min_length=3, max_length=200)
    billing_route: Literal["openrouter", "hive", "river"]


class ValidateAiModelRequest(AiModelChoice):
    feature_key: str = Field(min_length=1, max_length=64)


class PutAiModelRequest(AiModelChoice):
    expected_revision: int = Field(ge=0, strict=True)
