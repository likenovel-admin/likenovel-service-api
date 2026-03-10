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
        return (
            f"CustomResponseException(status_code={self.status_code}, "
            f"code={self.code}, message={self.message})"
        )
