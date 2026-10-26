"""CMS-owned model settings. Metadata checks never perform inference."""
from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.const import settings
from app.exceptions import CustomResponseException
from app.services.common.ai_model_config import (
    AiModelBinding,
    FEATURE_CATALOG,
    default_model_binding,
    get_feature,
    load_ai_model_snapshot,
)

_MODEL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*\Z")
_METADATA_BASES = {
    "hive": "https://api-cdn.thehive.ai/api/v3",
    "river": "https://api.river.ai/v1",
}
_CAPABILITY_PARAMETERS = {
    "text": set(),
    "json_object": {"response_format"},
    "json_schema": {"response_format", "structured_outputs"},
    "tools": {"tools", "tool_choice"},
}


def _invalid(message: str) -> CustomResponseException:
    return CustomResponseException(status_code=422, code="INVALID_AI_MODEL", message=message)


def _feature(feature_key: str):
    try:
        return get_feature(feature_key)
    except ValueError:
        raise _invalid("알 수 없는 AI 기능입니다.") from None


def _item(binding: AiModelBinding, *, updated_date: Any = None) -> dict[str, Any]:
    feature = _feature(binding.feature_key)
    default = default_model_binding(binding.feature_key)
    return {
        **asdict(binding),
        "title": feature.title,
        "category": feature.category,
        "default_model_id": default.model_id,
        "default_billing_route": default.billing_route,
        "required_capabilities": list(feature.required_capabilities),
        "job_boundary": feature.job_boundary,
        "updated_date": updated_date,
    }


def _provider_accounts(provider: str):
    # Gateway owns credential parsing. Config snapshots never import it.
    from app.services.common.ai_model_gateway import load_provider_accounts
    return load_provider_accounts(provider)


def _provider_summaries() -> list[dict[str, Any]]:
    from app.services.common.ai_model_gateway import AiModelGatewayConfigurationError

    result = [{
        "id": "openrouter", "label": "OpenRouter",
        "account_count": 1 if settings.OPENROUTER_API_KEY else 0,
        "configured": bool(settings.OPENROUTER_API_KEY),
    }]
    for provider, label in (("hive", "Hive"), ("river", "River AI")):
        try:
            count = len(_provider_accounts(provider))
        except AiModelGatewayConfigurationError:
            count = 0
        result.append({"id": provider, "label": label, "account_count": count, "configured": count > 0})
    return result


async def get_admin_ai_models(*, db: Any) -> dict[str, Any]:
    snapshot = await load_ai_model_snapshot(db)
    return {"data": {
        "items": [_item(snapshot[key]) for key in FEATURE_CATALOG],
        "providers": _provider_summaries(),
        "apply_policy": "next_job",
    }}


async def _metadata(client: httpx.AsyncClient, url: str, *, headers: dict[str, str] | None = None) -> dict[str, Any]:
    try:
        response = await client.get(url, headers=headers, follow_redirects=False)
    except httpx.RequestError:
        raise CustomResponseException(status_code=503, code="MODEL_METADATA_UNAVAILABLE", message="모델 지원 정보를 확인할 수 없습니다. 현재 설정은 유지됩니다.") from None
    if response.status_code == 404:
        raise _invalid("해당 서비스에서 모델을 찾을 수 없습니다.")
    if response.status_code != 200:
        raise CustomResponseException(status_code=503, code="MODEL_METADATA_UNAVAILABLE", message="모델 목록 또는 계정 연결을 확인할 수 없습니다. 현재 설정은 유지됩니다.")
    try:
        payload = response.json()
    except ValueError:
        raise CustomResponseException(status_code=503, code="MODEL_METADATA_INVALID", message="모델 지원 정보 응답이 올바르지 않습니다.") from None
    if not isinstance(payload, dict):
        raise CustomResponseException(status_code=503, code="MODEL_METADATA_INVALID", message="모델 지원 정보 응답이 올바르지 않습니다.")
    return payload


async def _validate_choice(*, feature_key: str, model_id: str, billing_route: str, client: httpx.AsyncClient) -> dict[str, Any]:
    feature = _feature(feature_key)
    if not _MODEL_ID.fullmatch(model_id):
        raise _invalid("OpenRouter 형식의 모델 ID를 입력해주세요. 예: deepseek/deepseek-v4.1-flash-1017")
    if model_id.lower().endswith(":free") and (
        feature_key.startswith("websochat.")
        or feature_key in {"storyctx.signals", "storyctx.scenes", "storyctx.protagonist", "storyctx.rp"}
    ):
        raise _invalid("이 기능은 실행 시 무료 모델을 허용하지 않습니다. :free가 없는 모델 ID를 선택해주세요.")
    if feature_key == "ai_reader.decision" and len(model_id) > 100:
        raise CustomResponseException(
            status_code=400, code="AI_READER_MODEL_ID_TOO_LONG",
            message="AI 독자 모델 ID는 작업 기록 저장 한도에 맞게 100자 이하여야 합니다.",
        )
    if billing_route not in {"openrouter", "hive", "river"}:
        raise _invalid("지원하지 않는 결제 경로입니다.")

    needed = set().union(*(_CAPABILITY_PARAMETERS[cap] for cap in feature.required_capabilities))
    url = "https://openrouter.ai/api/v1/models/" + quote(model_id, safe="/") + "/endpoints"
    payload = await _metadata(client, url)
    data = payload.get("data")
    endpoints = data.get("endpoints") if isinstance(data, dict) else None
    if not isinstance(endpoints, list) or not any(
        isinstance(endpoint, dict)
        and isinstance(endpoint.get("supported_parameters"), list)
        and all(isinstance(parameter, str) for parameter in endpoint["supported_parameters"])
        and needed.issubset(set(endpoint["supported_parameters"]))
        for endpoint in endpoints
    ):
        raise _invalid("이 기능에 필요한 JSON 출력 또는 도구 호출을 지원하는 OpenRouter 경로가 없습니다.")

    warnings: list[str] = []
    if billing_route != "openrouter":
        from app.services.common.ai_model_gateway import (
            AiModelGatewayConfigurationError,
            provider_model_id,
            provider_capabilities,
        )
        # Capability evidence belongs to the gateway's exact provider/model
        # mapping. Unknown support must not silently strip required parameters.
        supported = provider_capabilities(billing_route, model_id)
        if not set(feature.required_capabilities).issubset(supported):
            raise _invalid("선택한 서비스·모델의 필수 출력 형식 또는 도구 호출 지원이 검증되지 않았습니다. 다른 경로를 선택해주세요.")
        try:
            native_model = provider_model_id(billing_route, model_id)
            accounts = _provider_accounts(billing_route)
        except (AiModelGatewayConfigurationError, ValueError):
            raise _invalid("선택한 서비스의 계정 또는 해당 모델 연결을 먼저 설정해주세요.") from None
        if not accounts:
            raise _invalid("선택한 서비스에 등록된 계정이 없습니다.")
        # All accounts in a pool must expose the exact mapped model; otherwise
        # exhaustion of an earlier account could route to an incompatible one.
        for account in accounts:
            models = await _metadata(
                client, _METADATA_BASES[billing_route] + "/models",
                headers={"Authorization": "Bearer " + account.api_key},
            )
            entries = models.get("data")
            if not isinstance(entries, list) or not any(
                isinstance(entry, dict) and entry.get("id") == native_model for entry in entries
            ):
                raise _invalid("선택한 서비스의 일부 계정에서 해당 모델을 사용할 수 없습니다.")
        warnings.append("선택한 서비스의 사용 가능한 크레딧이 소진되면 OpenRouter를 사용합니다.")
    return {"data": {
        "valid": True,
        "model_id": model_id,
        "billing_route": billing_route,
        "validation_level": "metadata",
        "warnings": warnings,
    }}


async def validate_admin_ai_model(*, feature_key: str, model_id: str, billing_route: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
    if client is not None:
        return await _validate_choice(feature_key=feature_key, model_id=model_id, billing_route=billing_route, client=client)
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as metadata_client:
        return await _validate_choice(feature_key=feature_key, model_id=model_id, billing_route=billing_route, client=metadata_client)


def _conflict() -> CustomResponseException:
    return CustomResponseException(status_code=409, code="AI_MODEL_REVISION_CONFLICT", message="다른 화면에서 설정이 변경되었습니다. 새로고침 후 다시 적용해주세요.")


async def put_admin_ai_model(*, feature_key: str, model_id: str, billing_route: str, expected_revision: int, admin_user_id: int, db: Any) -> dict[str, Any]:
    _feature(feature_key)
    if type(expected_revision) is not int or expected_revision < 0:
        raise _invalid("설정 revision이 올바르지 않습니다.")
    if not admin_user_id:
        raise CustomResponseException(status_code=403, message="관리자 권한이 필요합니다.")
    await validate_admin_ai_model(feature_key=feature_key, model_id=model_id, billing_route=billing_route)
    revision = expected_revision + 1
    try:
        result = await db.execute(text("SELECT feature_key, model_id, billing_route, revision FROM tb_ai_model_config WHERE feature_key = :feature_key"), {"feature_key": feature_key})
        current = result.mappings().one_or_none()
        previous = AiModelBinding(**dict(current)) if current is not None else default_model_binding(feature_key)
        if previous.revision != expected_revision:
            raise _conflict()
        params = {"feature_key": feature_key, "model_id": model_id, "billing_route": billing_route, "revision": revision, "expected_revision": expected_revision, "admin_user_id": admin_user_id}
        if current is None:
            await db.execute(text("""
                INSERT INTO tb_ai_model_config
                    (feature_key, model_id, billing_route, revision, created_id, updated_id)
                VALUES (:feature_key, :model_id, :billing_route, :revision, :admin_user_id, :admin_user_id)
            """), params)
        else:
            result = await db.execute(text("""
                UPDATE tb_ai_model_config
                SET model_id = :model_id, billing_route = :billing_route,
                    revision = :revision, updated_id = :admin_user_id
                WHERE feature_key = :feature_key AND revision = :expected_revision
            """), params)
            if result.rowcount != 1:
                raise _conflict()
        await db.execute(text("""
            INSERT INTO tb_ai_model_config_history
                (feature_key, revision, model_id, billing_route,
                 previous_model_id, previous_billing_route, changed_by)
            VALUES (:feature_key, :revision, :model_id, :billing_route,
                    :previous_model_id, :previous_billing_route, :admin_user_id)
        """), {**params, "previous_model_id": previous.model_id, "previous_billing_route": previous.billing_route})
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        if getattr(exc.orig, "args", (None,))[0] == 1062:
            raise _conflict() from None
        raise
    except Exception:
        await db.rollback()
        raise
    return {"data": {**_item(AiModelBinding(feature_key, model_id, billing_route, revision)), "apply_policy": "next_job"}}
