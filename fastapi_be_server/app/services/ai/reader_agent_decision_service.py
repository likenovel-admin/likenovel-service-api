import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from fastapi import status
import httpx

from app.const import settings
from app.exceptions import CustomResponseException


READER_DECISION_PROMPT_VERSION = "ai-reader-decision-v1"
READER_DECISION_MAX_TOKENS = 1200
READER_DECISION_PARSE_MAX_ATTEMPTS = 2
OPENROUTER_MAX_ATTEMPTS = 2
OPENROUTER_ALLOWED_FINISH_REASONS = {"stop"}
logger = logging.getLogger(__name__)


BOOKMARK_ACTIONS = {"none", "add", "remove"}
RECOMMEND_ACTIONS = {"none", "press", "remove"}
EVALUATION_CODES = {
    "highlypositive",
    "verypositive",
    "positive",
    "somewhatpositive",
    "neutral",
    "somewhatnegative",
    "negative",
    "verynegative",
    "highlynegative",
}
EPISODE_SCOPED_ACTIONS = {"read", "recommend", "evaluate", "next_episode"}


class InvalidReaderDecisionError(ValueError):
    pass


@dataclass(frozen=True)
class ReaderLlmDecision:
    continue_reading: bool
    next_episode_count: int
    drop_product: bool
    bookmark_action: str
    recommend_action: str
    should_evaluate: bool
    eval_code: str | None
    taste_delta: dict[str, list[str]]
    reason: str
    bayesian_update: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class ReaderActionContext:
    agent_id: int
    user_id: int
    session_id: str
    product_id: int
    episode_id: int | None


@dataclass(frozen=True)
class ReaderActionIntent:
    action_type: str
    target_value: str
    idempotency_key: str


ReaderLlmCall = Callable[[str, str, int], Awaitable[str]]


def build_reader_decision_prompt(input_snapshot: dict[str, Any]) -> tuple[str, str]:
    snapshot_json = json.dumps(input_snapshot, ensure_ascii=False, sort_keys=True)
    system_prompt = f"""
너는 LikeNovel의 AI 독자 에이전트다.
목표는 작품을 홍보하는 것이 아니라, 주어진 독자 프로필과 작품/회차 정보를 보고 사람 독자처럼 판단하는 것이다.
마음에 들면 다음 회차를 더 보고, 선호작을 추가하고, 추천을 누르고, 평가할 수 있다.
마음에 들지 않으면 중단하거나 이미 한 선호작을 해제할 수 있다.

반드시 JSON 객체만 반환한다. 마크다운, 설명문, 주석은 금지한다.
필수 JSON 필드:
- continue_reading: boolean
- next_episode_count: integer, 0 또는 1
- drop_product: boolean
- bookmark_action: "none" | "add" | "remove"
- recommend_action: "none" | "press" | "remove"
- evaluation: {{"should_evaluate": boolean, "eval_code": "highlypositive" | "verypositive" | "positive" | "somewhatpositive" | "neutral" | "somewhatnegative" | "negative" | "verynegative" | "highlynegative" | null}}
- bayesian_update: {{"continue_next_episode": {{"prior": number, "posterior": number}}, "bookmark": {{"prior": number, "posterior": number}}, "recommend": {{"prior": number, "posterior": number}}, "evaluate": {{"prior": number, "posterior": number}}}}
- taste_delta: {{"positive": string[], "negative": string[]}}
- reason: string

판단 기준:
- 독자의 나이/성별/활동 패턴/초기 취향/DNA 취향 메모리를 우선한다.
- 작품 DNA, 제목, 소개/메타데이터, 1~10화 초반 요약, 이전 행동 상태, 현재 공개 지표를 참고한다.
- engagement_context.action_affordances는 서버가 취향 매칭, 읽은 회차 수, 현재 행동 상태, Bayesian 사후확률을 계산한 행동 판단 보조값이다.
- engagement_context.bayesian_action_model은 현재 N화를 보기 전 N+1화 계속보기/선호작/추천/평가의 사전확률(prior)과 서버 posterior_hint를 담는다.
- 현재 N화를 읽었다고 가정한 작품 훅, 전개감, 취향 적합성을 조건부확률 evidence로 보고 bayesian_update.posterior 사후확률을 갱신한다.
- "루즈하면 멈출 수 있음"은 loose_stop_evidence_weight=0.1의 약한 부정 evidence일 뿐, 직접 중단 명령이 아니다.
- action_affordances.*.suggested=true는 서버가 posterior_hint >= posterior_threshold라고 본 상태다. 거절할 명확한 이유가 없으면 해당 행동을 하는 쪽으로 판단한다.
- action_affordances.*.suggested=false는 금지가 아니다. 작품의 훅, 취향, 읽은 회차, 독자 성향상 자연스러우면 직접 행동해도 된다.
- engagement_score_hint가 threshold 이상인데 "임계치 미달"이라고 이유를 쓰면 안 된다.
- read_episode_count가 action_affordances.evaluate.min_read_episode_count 이상이면 "3회차 미만"이라고 판단하면 안 된다.
- 모든 행동은 과장하지 말고 독자 한 명의 자연스러운 반응으로 결정한다.
- 강하게 마음에 든 독자는 첫 회차나 초반부에도 선호작/추천을 할 수 있다. 평가는 보통 3회차 이상 읽은 뒤 판단한다.
- 추천은 선호작보다 가벼운 긍정 신호다. 몇 화를 읽고 계속 볼 마음이 들면 추천을 누를 수 있다.
- 다음 회차를 볼지 말지만 판단한다. 한 번의 판단에서 next_episode_count는 0 또는 1이어야 한다.
- 다음 회차를 보지 않으면 next_episode_count는 0이어야 한다.
- drop_product가 true면 continue_reading은 false여야 한다.
prompt_version={READER_DECISION_PROMPT_VERSION}
""".strip()
    user_prompt = f"""
작품/회차/독자 스냅샷:
{snapshot_json}

위 스냅샷만 근거로 다음 행동 JSON을 반환해라.
""".strip()
    return system_prompt, user_prompt


async def request_reader_decision(
    input_snapshot: dict[str, Any],
    *,
    llm_call: ReaderLlmCall | None = None,
) -> ReaderLlmDecision:
    system_prompt, user_prompt = build_reader_decision_prompt(input_snapshot)
    caller = llm_call or _default_llm_call
    last_error: InvalidReaderDecisionError | None = None
    for attempt_no in range(1, READER_DECISION_PARSE_MAX_ATTEMPTS + 1):
        raw_response = await caller(system_prompt, user_prompt, READER_DECISION_MAX_TOKENS)
        try:
            return parse_llm_decision(raw_response)
        except InvalidReaderDecisionError as exc:
            last_error = exc
            if attempt_no >= READER_DECISION_PARSE_MAX_ATTEMPTS:
                raise
            logger.warning(
                "ai reader llm decision parse failed; retrying",
                extra={
                    "attempt_no": attempt_no,
                    "max_attempts": READER_DECISION_PARSE_MAX_ATTEMPTS,
                    "error": str(exc),
                },
            )
    if last_error is not None:
        raise last_error
    raise InvalidReaderDecisionError("response is not valid json")


def parse_llm_decision(raw_response: str | dict[str, Any]) -> ReaderLlmDecision:
    payload = _coerce_json_object(raw_response)

    continue_reading = _require_bool(payload, "continue_reading")
    drop_product = _require_bool(payload, "drop_product")
    next_episode_count = _require_int(payload, "next_episode_count", minimum=0, maximum=1)
    bookmark_action = _require_choice(payload, "bookmark_action", BOOKMARK_ACTIONS)
    recommend_action = _require_choice(payload, "recommend_action", RECOMMEND_ACTIONS)

    evaluation = payload.get("evaluation")
    if not isinstance(evaluation, dict):
        raise InvalidReaderDecisionError("evaluation must be an object")
    should_evaluate = _require_bool(evaluation, "should_evaluate")
    eval_code = evaluation.get("eval_code")
    if should_evaluate:
        if not isinstance(eval_code, str) or eval_code not in EVALUATION_CODES:
            raise InvalidReaderDecisionError("evaluation.eval_code is invalid")
    else:
        eval_code = None

    taste_delta = _normalize_taste_delta(payload.get("taste_delta"))
    bayesian_update = _normalize_bayesian_update(payload.get("bayesian_update"))
    reason = payload.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise InvalidReaderDecisionError("reason must be a non-empty string")

    _validate_decision_consistency(
        continue_reading=continue_reading,
        next_episode_count=next_episode_count,
        drop_product=drop_product,
        bookmark_action=bookmark_action,
        recommend_action=recommend_action,
    )

    return ReaderLlmDecision(
        continue_reading=continue_reading,
        next_episode_count=next_episode_count,
        drop_product=drop_product,
        bookmark_action=bookmark_action,
        recommend_action=recommend_action,
        should_evaluate=should_evaluate,
        eval_code=eval_code,
        taste_delta=taste_delta,
        reason=reason.strip()[:1000],
        bayesian_update=bayesian_update,
    )


def build_action_intents(
    decision: ReaderLlmDecision,
    context: ReaderActionContext,
) -> list[ReaderActionIntent]:
    intents: list[tuple[str, str]] = [("read", "")]

    if decision.drop_product:
        intents.append(("drop", "Y"))
    elif decision.continue_reading and decision.next_episode_count > 0:
        intents.append(("next_episode", str(decision.next_episode_count)))

    if decision.bookmark_action == "add":
        intents.append(("bookmark", "Y"))
    elif decision.bookmark_action == "remove":
        intents.append(("bookmark", "N"))

    if decision.recommend_action == "press":
        intents.append(("recommend", "Y"))
    elif decision.recommend_action == "remove":
        intents.append(("recommend", "N"))

    if decision.should_evaluate and decision.eval_code:
        intents.append(("evaluate", decision.eval_code))

    return [
        ReaderActionIntent(
            action_type=action_type,
            target_value=target_value,
            idempotency_key=build_idempotency_key(context, action_type, target_value),
        )
        for action_type, target_value in intents
    ]


def build_idempotency_key(
    context: ReaderActionContext,
    action_type: str,
    target_value: str,
) -> str:
    raw = "|".join(
        [
            "ai-reader",
            str(context.agent_id),
            str(context.user_id),
            context.session_id,
            str(context.product_id),
            str(context.episode_id or 0),
            action_type,
            target_value,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_active_action_scope_key(
    *,
    agent_id: int,
    user_id: int,
    product_id: int,
    episode_id: int | None,
    action_type: str,
    target_value: str | None,
) -> str:
    scoped_episode_id = (
        int(episode_id or 0)
        if action_type in EPISODE_SCOPED_ACTIONS
        else 0
    )
    scoped_target_value = "" if action_type == "evaluate" else (target_value or "")
    raw = "|".join(
        [
            "ai-reader-active",
            str(agent_id),
            str(user_id),
            str(product_id),
            str(scoped_episode_id),
            action_type,
            scoped_target_value,
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _coerce_json_object(raw_response: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(raw_response, dict):
        return raw_response
    if not isinstance(raw_response, str):
        raise InvalidReaderDecisionError("response must be json object or string")

    text = raw_response.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[0].startswith("```") and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1]).strip()

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise InvalidReaderDecisionError("response is not valid json") from exc
    if not isinstance(payload, dict):
        raise InvalidReaderDecisionError("response must be a json object")
    return payload


def _require_bool(payload: dict[str, Any], key: str) -> bool:
    value = payload.get(key)
    if not isinstance(value, bool):
        raise InvalidReaderDecisionError(f"{key} must be boolean")
    return value


def _require_int(
    payload: dict[str, Any],
    key: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise InvalidReaderDecisionError(f"{key} must be integer")
    if value < minimum or value > maximum:
        raise InvalidReaderDecisionError(f"{key} is out of range")
    return value


def _require_choice(payload: dict[str, Any], key: str, choices: set[str]) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or value not in choices:
        raise InvalidReaderDecisionError(f"{key} is invalid")
    return value


def _normalize_taste_delta(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, dict):
        raise InvalidReaderDecisionError("taste_delta must be an object")
    normalized: dict[str, list[str]] = {}
    for key in ("positive", "negative"):
        raw_items = value.get(key, [])
        if not isinstance(raw_items, list):
            raise InvalidReaderDecisionError(f"taste_delta.{key} must be a list")
        items: list[str] = []
        for raw_item in raw_items[:20]:
            if isinstance(raw_item, str) and raw_item.strip():
                items.append(raw_item.strip()[:80])
        normalized[key] = items
    return normalized


def _normalize_bayesian_update(value: Any) -> dict[str, dict[str, float]]:
    if value in (None, ""):
        return {}
    if not isinstance(value, dict):
        raise InvalidReaderDecisionError("bayesian_update must be an object")

    normalized: dict[str, dict[str, float]] = {}
    for action_key in ("continue_next_episode", "bookmark", "recommend", "evaluate"):
        raw_item = value.get(action_key)
        if raw_item in (None, ""):
            continue
        if not isinstance(raw_item, dict):
            raise InvalidReaderDecisionError(f"bayesian_update.{action_key} must be an object")
        normalized[action_key] = {
            "prior": _normalize_probability(
                raw_item.get("prior"),
                f"bayesian_update.{action_key}.prior",
            ),
            "posterior": _normalize_probability(
                raw_item.get("posterior"),
                f"bayesian_update.{action_key}.posterior",
            ),
        }
    return normalized


def _normalize_probability(value: Any, key: str) -> float:
    try:
        probability = float(value)
    except (TypeError, ValueError) as exc:
        raise InvalidReaderDecisionError(f"{key} must be a number") from exc
    if probability < 0.0 or probability > 1.0:
        clamped = max(0.0, min(1.0, probability))
        logger.warning(
            "ai reader llm probability out of range; clamped",
            extra={"key": key, "value": probability, "clamped": clamped},
        )
        probability = clamped
    return round(probability, 3)


def _validate_decision_consistency(
    *,
    continue_reading: bool,
    next_episode_count: int,
    drop_product: bool,
    bookmark_action: str,
    recommend_action: str,
) -> None:
    if drop_product and continue_reading:
        raise InvalidReaderDecisionError("drop_product conflicts with continue_reading")
    if not continue_reading and next_episode_count > 0:
        raise InvalidReaderDecisionError("next_episode_count requires continue_reading")
    if drop_product and bookmark_action == "add":
        raise InvalidReaderDecisionError("drop_product conflicts with bookmark add")
    if drop_product and recommend_action == "press":
        raise InvalidReaderDecisionError("drop_product conflicts with recommend press")


async def _default_llm_call(
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> str:
    return await _call_openrouter_chat_completion(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=max_tokens,
    )


async def _call_openrouter_chat_completion(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> str:
    if not settings.OPENROUTER_API_KEY:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="AI 추천 서비스가 설정되지 않았습니다.",
        )
    if not settings.AI_READER_OPENROUTER_MODEL:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="AI reader 모델이 설정되지 않았습니다.",
        )

    payload: dict[str, Any] = {
        "model": settings.AI_READER_OPENROUTER_MODEL,
        "temperature": settings.AI_READER_OPENROUTER_TEMPERATURE,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    provider_only = _split_csv(settings.AI_READER_OPENROUTER_PROVIDER_ONLY)
    if provider_only:
        payload["provider"] = {
            "only": provider_only,
            "require_parameters": True,
        }

    last_error: Exception | None = None
    for attempt_no in range(1, OPENROUTER_MAX_ATTEMPTS + 1):
        try:
            return await _post_openrouter_chat_completion(payload, max_tokens)
        except (CustomResponseException, httpx.HTTPError) as exc:
            last_error = exc
            if attempt_no >= OPENROUTER_MAX_ATTEMPTS or not _is_retryable_openrouter_error(exc):
                raise
            logger.warning(
                "OpenRouter transient response; retrying reader decision call",
                extra={
                    "attempt_no": attempt_no,
                    "max_attempts": OPENROUTER_MAX_ATTEMPTS,
                    "error": str(exc),
                },
            )
    if last_error:
        raise last_error
    raise CustomResponseException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        message="AI 서비스 호출에 실패했습니다.",
    )


async def _post_openrouter_chat_completion(payload: dict[str, Any], max_tokens: int) -> str:
    async with httpx.AsyncClient(
        timeout=settings.AI_READER_OPENROUTER_TIMEOUT_SECONDS
    ) as client:
        resp = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "LikeNovel AI Reader Agent",
            },
            json=payload,
        )
    if resp.status_code != 200:
        logger.error("OpenRouter API error: %s", _sanitize_openrouter_error(resp))
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 서비스 호출에 실패했습니다.",
        )

    data = resp.json()
    choice = _validate_openrouter_choice(data)
    raw = _extract_openrouter_message_text(choice)
    if not raw:
        finish_reason = choice.get("finish_reason") or "unknown"
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message=f"AI 응답이 비어 있습니다. (finish_reason={finish_reason})",
        )
    return raw


def _is_retryable_openrouter_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPError):
        return True
    if not isinstance(exc, CustomResponseException):
        return False
    if exc.status_code != status.HTTP_502_BAD_GATEWAY:
        return False
    return exc.message in {
        "AI 서비스 호출에 실패했습니다.",
        "AI 응답 형식이 유효하지 않습니다.",
    } or str(exc).startswith("AI 응답이 비어 있습니다.")


def _extract_openrouter_message_text(choice: dict[str, Any]) -> str:
    message = choice.get("message") or {}
    content = message.get("content") or ""
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, dict):
                text = item.get("text") or item.get("content") or ""
                if text:
                    parts.append(str(text))
            elif item:
                parts.append(str(item))
        content = "\n".join(parts)
    return str(content or "").strip()


def _validate_openrouter_choice(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message="AI 응답 형식이 유효하지 않습니다.",
        )
    choice = choices[0] or {}
    finish_reason = choice.get("finish_reason")
    if finish_reason and finish_reason not in OPENROUTER_ALLOWED_FINISH_REASONS:
        raise CustomResponseException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            message=f"AI 응답이 중단되었습니다. (finish_reason={finish_reason})",
        )
    return choice


def _sanitize_openrouter_error(resp: httpx.Response) -> str:
    code = ""
    message = ""
    try:
        payload = resp.json()
    except ValueError:
        payload = None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("type") or "").strip()
            message = str(error.get("message") or "").strip()
        if not code:
            code = str(payload.get("code") or "").strip()
        if not message:
            message = str(payload.get("message") or "").strip()
    details = [f"status={resp.status_code}"]
    if code:
        details.append(f"code={code[:80]}")
    if message:
        details.append(f"message={_compact_log_message(message)}")
    return ", ".join(details)


def _compact_log_message(message: str) -> str:
    return " ".join(str(message or "").split())[:240]


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def reader_llm_model_name() -> str:
    return settings.AI_READER_OPENROUTER_MODEL or "openrouter"
