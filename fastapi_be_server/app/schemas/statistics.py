from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator


class PostSitePageViewReqBody(BaseModel):
    event_id: str = Field(..., alias="eventId", min_length=8, max_length=36)
    occurred_at: datetime = Field(..., alias="occurredAt")
    visitor_id: str = Field(..., alias="visitorId", min_length=1, max_length=80)
    session_id: str = Field(..., alias="sessionId", min_length=1, max_length=80)
    route_group: str = Field(..., alias="routeGroup", min_length=1, max_length=80)
    route_name: str = Field(..., alias="routeName", min_length=1, max_length=120)
    path_template: str = Field(..., alias="pathTemplate", min_length=1, max_length=255)
    path: str = Field(..., min_length=1, max_length=255)
    query_hash: str | None = Field(None, alias="queryHash", max_length=64)
    referrer_path: str | None = Field(None, alias="referrerPath", max_length=255)
    source: str = Field("service-web", max_length=50)
    taxonomy_version: int = Field(1, alias="taxonomyVersion", ge=1, le=20)

    model_config = {"populate_by_name": True}

    @field_validator("query_hash")
    @classmethod
    def validate_query_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if re.fullmatch(r"[0-9a-f]{64}", normalized):
            return normalized
        return None


class PostSitePageDwellReqBody(BaseModel):
    event_id: str = Field(..., alias="eventId", min_length=8, max_length=36)
    occurred_at: datetime = Field(..., alias="occurredAt")
    visitor_id: str = Field(..., alias="visitorId", min_length=1, max_length=80)
    session_id: str = Field(..., alias="sessionId", min_length=1, max_length=80)
    route_group: str = Field(..., alias="routeGroup", min_length=1, max_length=80)
    route_name: str = Field(..., alias="routeName", min_length=1, max_length=120)
    path_template: str = Field(..., alias="pathTemplate", min_length=1, max_length=255)
    active_ms: int = Field(..., alias="activeMs", ge=1000, le=86400000)
    source: str = Field("service-web", max_length=50)
    taxonomy_version: int = Field(1, alias="taxonomyVersion", ge=1, le=20)

    model_config = {"populate_by_name": True}
