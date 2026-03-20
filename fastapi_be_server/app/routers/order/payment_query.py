from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_db
from app.services.order import payment_service
from app.utils.auth import login_required

router = APIRouter(prefix="/payments")


@router.get("/virtual-account/pending")
async def get_active_virtual_account_pending(
    user_id: str = Depends(login_required),
    db: AsyncSession = Depends(get_db),
):
    return await payment_service.get_active_virtual_account_pending(
        kc_user_id=user_id, db=db
    )
