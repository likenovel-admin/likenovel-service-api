from datetime import datetime
import re

from pydantic import BaseModel, Field, field_validator


def _normalize_marketing_token(value: str | None, max_length: int) -> str | None:
    if value is None:
        return None
    compacted = re.sub(r"[\x00-\x1f\x7f]", "", value).strip().lower()
    if not compacted:
        return None
    normalized = re.sub(r"[^a-z0-9_-]+", "_", compacted).strip("_")
    if not normalized:
        return None
    return normalized[:max_length]


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
    utm_source: str | None = Field(None, alias="utmSource")
    utm_medium: str | None = Field(None, alias="utmMedium")
    utm_campaign: str | None = Field(None, alias="utmCampaign")
    utm_content: str | None = Field(None, alias="utmContent")
    external_referrer_host: str | None = Field(
        None, alias="externalReferrerHost"
    )
    external_referrer_group: str | None = Field(
        None, alias="externalReferrerGroup"
    )
    product_id: int | None = Field(None, alias="productId", ge=1)
    entry_source: str | None = Field(None, alias="entrySource")
    entry_source_group: str | None = Field(None, alias="entrySourceGroup")
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

    @field_validator(
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_content",
        "external_referrer_group",
        "entry_source",
        "entry_source_group",
    )
    @classmethod
    def validate_marketing_token(cls, value: str | None) -> str | None:
        return _normalize_marketing_token(value, 120)

    @field_validator("external_referrer_host")
    @classmethod
    def validate_external_referrer_host(cls, value: str | None) -> str | None:
        if value is None:
            return None
        host = value.strip().lower()
        if not host:
            return None
        return host[:255]


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
