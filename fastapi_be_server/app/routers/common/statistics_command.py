from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.rdb import get_likenovel_db
from app.schemas.statistics import PostSitePageDwellReqBody, PostSitePageViewReqBody
from app.utils.auth import chk_cur_user
import app.services.common.statistics_service as statistics_service

router = APIRouter(prefix="/statistics")


@router.post(
    "/page-view",
    tags=["site 통계"],
    responses={200: {"description": "사이트 페이지뷰 raw 이벤트 적재"}},
)
async def post_site_page_view(
    req_body: PostSitePageViewReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    await statistics_service.insert_site_page_view_event(
        db=db,
        kc_user_id=user.get("sub"),
        event_id=req_body.event_id,
        occurred_at=req_body.occurred_at,
        visitor_id=req_body.visitor_id,
        session_id=req_body.session_id,
        route_group=req_body.route_group,
        route_name=req_body.route_name,
        path_template=req_body.path_template,
        path=req_body.path,
        query_hash=req_body.query_hash,
        referrer_path=req_body.referrer_path,
        source=req_body.source,
        taxonomy_version=req_body.taxonomy_version,
        utm_source=req_body.utm_source,
        utm_medium=req_body.utm_medium,
        utm_campaign=req_body.utm_campaign,
        utm_content=req_body.utm_content,
        external_referrer_host=req_body.external_referrer_host,
        external_referrer_group=req_body.external_referrer_group,
    )
    return {"data": {"ok": True}}


@router.post(
    "/page-dwell",
    tags=["site 통계"],
    responses={200: {"description": "사이트 페이지 활성 체류 raw 이벤트 적재"}},
)
async def post_site_page_dwell(
    req_body: PostSitePageDwellReqBody,
    user: Dict[str, Any] = Depends(chk_cur_user),
    db: AsyncSession = Depends(get_likenovel_db),
):
    await statistics_service.insert_site_page_dwell_event(
        db=db,
        kc_user_id=user.get("sub"),
        event_id=req_body.event_id,
        occurred_at=req_body.occurred_at,
        visitor_id=req_body.visitor_id,
        session_id=req_body.session_id,
        route_group=req_body.route_group,
        route_name=req_body.route_name,
        path_template=req_body.path_template,
        active_ms=req_body.active_ms,
        source=req_body.source,
        taxonomy_version=req_body.taxonomy_version,
    )
    return {"data": {"ok": True}}
