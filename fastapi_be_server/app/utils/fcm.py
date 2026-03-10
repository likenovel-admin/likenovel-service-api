"""
FCM(Firebase Cloud Messaging) 유틸

원본(기존 소스)의 의도/사용법을 유지하되, 운영 보안을 위해 아래 2가지만 강제합니다.
- 서비스 계정 JSON 키 파일은 레포(`secrets/*.json`)에 두지 않습니다.
- 실행 환경에서 `FCM_SERVICE_ACCOUNT_JSON_PATH` 환경변수로 경로를 주입합니다.

주의(Defensive):
- firebase_admin 미설치/키 누락 등 상황에서도 서버가 import 단계에서 죽지 않도록
  send 시점에 초기화하고, 호출부가 처리 가능한 dict 형태로 에러를 반환합니다.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_FIREBASE_APP_INITIALIZED = False


class PushNotificationPayload:
    """
    FCM payload
    - token 또는 topic 중 하나만 지정해야 합니다.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        topic: Optional[str] = None,
        title: str = "",
        body: str = "",
        data: Optional[Dict[str, str]] = None,
        image_url: Optional[str] = None,
    ):
        if (token is None and topic is None) or (token and topic):
            raise ValueError("token 또는 topic 중 하나만 지정해야 합니다.")
        self.token = token
        self.topic = topic
        self.title = title
        self.body = body
        self.data = data or {}
        self.image_url = image_url


def _init_firebase_if_needed() -> None:
    """
    firebase_admin 초기화(Defensive)
    - 키 경로/파일/firebase_admin 미존재 시 예외
    """

    global _FIREBASE_APP_INITIALIZED
    if _FIREBASE_APP_INITIALIZED:
        return

    path = os.getenv("FCM_SERVICE_ACCOUNT_JSON_PATH", "").strip()
    if not path:
        raise RuntimeError("FCM_SERVICE_ACCOUNT_JSON_PATH is missing")
    if not os.path.exists(path):
        raise RuntimeError(f"FCM service account json not found: {path}")

    import firebase_admin  # type: ignore
    from firebase_admin import credentials  # type: ignore

    # 앱당 1번만 초기화(원본 로직 유지)
    if not firebase_admin._apps:  # pylint: disable=protected-access
        cred = credentials.Certificate(path)
        firebase_admin.initialize_app(cred)

    _FIREBASE_APP_INITIALIZED = True


def send_push(payload: PushNotificationPayload) -> Dict[str, Any]:
    """
    FCM 푸시 발송

    Returns:
      성공: {"message_id": "..."}
      실패: {"error": {"message": "...", "type": "..."}}

    NOTE:
    - 기존 호출부가 dict 기반으로 성공/실패를 분기하는 코드가 있어 예외 대신 dict로 반환합니다.
    """

    try:
        _init_firebase_if_needed()
        from firebase_admin import messaging  # type: ignore

        notification = messaging.Notification(
            title=payload.title, body=payload.body, image=payload.image_url
        )

        message_kwargs = {"notification": notification, "data": payload.data}
        if payload.token:
            message = messaging.Message(token=payload.token, **message_kwargs)
        else:
            message = messaging.Message(topic=payload.topic, **message_kwargs)

        response = messaging.send(message)
        return {"message_id": response}
    except Exception as e:
        logger.error(f"[FCM] send_push failed: {e}")
        return {"error": {"message": str(e), "type": type(e).__name__}}


def translate_fcm_error(raw_msg: str) -> str:
    """
    원본 번역 테이블(확장 버전)을 유지합니다.
    """

    translations = {
        "Invalid argument": "요청에 잘못된 인자가 포함되어 있습니다.",
        "Request contains an invalid argument": "요청 형식이 잘못되었습니다.",
        "not a valid FCM registration token": "유효하지 않은 디바이스 토큰입니다.",
        "Requested entity was not found": "지정된 토큰 또는 토픽을 찾을 수 없습니다.",
        "SenderId mismatch": "Sender ID가 일치하지 않습니다.",
        "Unregistered": "해당 디바이스 토큰이 더 이상 등록되어 있지 않습니다.",
        "MismatchSenderId": "주어진 Sender ID와 일치하지 않습니다.",
        "Invalid JSON payload received": "JSON 형식이 올바르지 않습니다.",
        "Missing registration token": "디바이스 토큰이 누락되었습니다.",
        "Topic name is invalid": "토픽 이름이 올바르지 않습니다.",
        "Authorization error": "인증 오류가 발생했습니다.",
        "Authentication Error": "인증에 실패했습니다.",
        "The caller does not have permission": "권한이 없습니다.",
        "Quota exceeded": "FCM 일일 한도를 초과했습니다.",
        "Internal error": "FCM 서버 내부 오류입니다. 잠시 후 다시 시도해주세요.",
        "RESOURCE_EXHAUSTED": "리소스 사용량 제한을 초과했습니다.",
        "UNAUTHENTICATED": "인증되지 않았습니다.",
        "PERMISSION_DENIED": "권한이 거부되었습니다.",
        "INVALID_ARGUMENT": "유효하지 않은 요청입니다.",
        "NOT_FOUND": "대상을 찾을 수 없습니다.",
        "UNAVAILABLE": "FCM 서버가 일시적으로 사용 불가 상태입니다.",
        "DEADLINE_EXCEEDED": "요청 시간이 초과되었습니다.",
    }

    for key, message in translations.items():
        if key.lower() in (raw_msg or "").lower():
            return message

    return "푸시 알림 전송 중 알 수 없는 오류가 발생했습니다."

