import hmac

from fastapi import APIRouter, Depends, Header, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.const import settings
from app.exceptions import CustomResponseException
from app.rdb import get_likenovel_db
from app.services.ai import direct_curator_service
from app.utils.auth import analysis_logger


router = APIRouter(prefix="/ai/direct-curator")


def require_curator_key(
    supplied_key: str | None = Header(
        default=None,
        alias="X-LikeNovel-Direct-Curator-Key",
    ),
) -> None:
    expected_key = settings.DIRECT_CURATOR_SNAPSHOT_TOKEN
    if not expected_key:
        raise CustomResponseException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            message="Direct curator snapshot is unavailable",
        )
    if not supplied_key or not hmac.compare_digest(supplied_key, expected_key):
        raise CustomResponseException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            message="Unauthorized",
        )


@router.get(
    "/snapshot",
    tags=["AI 추천"],
    responses={200: {"description": "직접추천 구좌 큐레이션 읽기 전용 스냅샷"}},
    dependencies=[Depends(analysis_logger)],
)
async def get_direct_curator_snapshot(
    response: Response,
    db: AsyncSession = Depends(get_likenovel_db),
    _authorized: None = Depends(require_curator_key),
):
    response.headers["Cache-Control"] = "no-store"
    snapshot = await direct_curator_service.build_scheduled_snapshot(db)
    return {"data": snapshot}
