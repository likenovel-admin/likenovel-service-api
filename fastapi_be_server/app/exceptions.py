from typing import Optional


class CustomResponseException(Exception):
    """커스텀 HTTP 예외"""

    def __init__(
        self,
        status_code: int,
        code: Optional[str] = None,
        message: Optional[str] = None,
    ):
        self.status_code = status_code
        self.code = code
        self.message = message

    def __str__(self) -> str:
        # User-facing 메시지만 반환 (auth callback의 ?error= 노출 등에서 사용)
        # 디버깅용 status_code/code 포함 표현은 __repr__ 로 분리
        return self.message or ""

    def __repr__(self) -> str:
        return (
            f"CustomResponseException(status_code={self.status_code}, "
            f"code={self.code}, message={self.message!r})"
        )
