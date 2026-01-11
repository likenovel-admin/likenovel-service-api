from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.utils.auth import analysis_logger
import app.schemas.storage as storage_schema
import app.services.common.storage_service as storage_service


router = APIRouter(prefix="/storages")


@router.post("/upload-url", tags=["스토리지"], dependencies=[Depends(analysis_logger)])
async def create_presigned_upload_url(
    req_body: storage_schema.UploadReqBody, db: AsyncSession = Depends(get_likenovel_db)
):
    """
    파일 업로드 presigned url 생성
    """

    return await storage_service.get_presigned_upload_url(req_body=req_body, db=db)
