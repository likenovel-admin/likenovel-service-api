"""Promotion preparation; integration is disabled until explicit scoped intent.

The host must obtain actor/scopes/approved_plan_id from authenticated first-party
state, never from model-supplied MCP arguments. No tools are registered here.
"""

import json
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import text

from app.schemas.admin import PostBannerReqBody
from app.schemas.partner import PutProductReqBody
from app.services.ai import mcp_store as store

KST = ZoneInfo("Asia/Seoul")
CAMPAIGN_SCOPE = "likenovel.mcp.promotion.write"
PAID_APPROVAL_SCOPE = "likenovel.mcp.paid-approval.write"
BANNER_SCOPE = "likenovel.mcp.banner.write"


def _clean(value):
    def encode(item):
        if isinstance(item, (date, datetime)):
            return item.isoformat()
        if isinstance(item, Decimal):
            return str(item)
        raise TypeError(type(item).__name__)

    return json.loads(json.dumps(value, default=encode, ensure_ascii=False))


def _positive_id(value):
    if type(value) is not int or value <= 0:
        raise ValueError("A positive integer ID is required")
    return value


def _save_plan(owner, kind, before, request, actor_id):
    plan_id = str(uuid.uuid4())
    payload = {
        "kind": kind, "before": _clean(before), "request": _clean(request),
        "actor_id": actor_id, "created_at": time.time(),
    }
    store.save("promotion-plan:" + plan_id, owner, "ready", payload)
    return {"plan_id": plan_id, **payload, "execution_requires_explicit_intent": True}


def prepare_hundred_free(owner, before, actor, ends_at, *, now=None):
    """Prepare from a server-fetched product/episode/campaign snapshot."""
    product = before["product"]
    _positive_id(product["product_id"])
    if actor.get("role") != "CP":
        raise ValueError("An authenticated CP identity is required; admin is not a CP")
    cp_id = _positive_id(actor.get("user_id"))
    if cp_id not in (product.get("user_id"), product.get("author_id"), product.get("cp_user_id")):
        raise ValueError("The product does not belong to this CP")
    if product.get("price_type") != "paid" or product.get("series_regular_price") != 100:
        raise ValueError("100-episode free promotion requires an existing paid serial")
    if not (product.get("uci") or product.get("isbn")):
        raise ValueError("The existing service requires UCI or ISBN")
    primary_genre_id = _positive_id(product.get("primary_genre_id"))
    sub_genre_id = product.get("sub_genre_id")
    if sub_genre_id is not None:
        _positive_id(sub_genre_id)
    if primary_genre_id == sub_genre_id:
        raise ValueError("The existing primary and secondary genres must differ")
    episodes = before["episodes"]
    if not {row["episode_no"] for row in episodes}.issuperset(range(1, 101)):
        raise ValueError("Episodes 1 through 100 must all exist")
    if before["campaigns"]:
        raise ValueError("An active campaign already exists; propose a separate change")
    if not isinstance(ends_at, datetime) or ends_at.utcoffset() is None:
        raise ValueError("Specify an explicit timezone for the campaign end")
    now = now or datetime.now(KST)
    if ends_at <= now:
        raise ValueError("The campaign end must be in the future")
    # The established service requires status_code and compares both genre IDs
    # even for a narrow patch. Include frozen values to preserve those fields.
    # It stores DATETIME in server-local KST; normalize before dropping tzinfo.
    request = {
        "status_code": product["status_code"],
        "primary_genre_id": primary_genre_id,
        "sub_genre_id": sub_genre_id,
        "hundred_free_campaign_enabled": True,
        "hundred_free_campaign_ends_at": ends_at.astimezone(KST).replace(tzinfo=None),
    }
    return _save_plan(owner, "hundred-free", before, request, cp_id)


def prepare_paid_approval(owner, before, actor):
    """Approval alone does not change prices or perform paid conversion."""
    if actor.get("role") != "admin":
        raise ValueError("CMS admin authentication is required")
    application = before["application"]
    if application.get("status_code") != "review" or application.get("use_yn") != "Y":
        raise ValueError("Only an active review request may be approved")
    if application["product_id"] != before["product"]["product_id"]:
        raise ValueError("Application and product do not match")
    if before["product"].get("contract_yn") != "Y" or not before["product"].get("cp_user_id"):
        raise ValueError("A valid CP contract is required")
    request = {"apply_id": _positive_id(application["id"])}
    return _save_plan(owner, "paid-approval", before, request, _positive_id(actor["user_id"]))


def prepare_banner(owner, request, scope_rows, *, allowed_link_hosts):
    """Prepare publication after real image upload; does not generate/upload media."""
    from app.services.admin.admin_event_service import _validate_banner_scope

    payload = PostBannerReqBody.model_validate(request)
    _validate_banner_scope(payload.position, payload.division)
    start, end = date.fromisoformat(payload.show_start_date), date.fromisoformat(payload.show_end_date)
    if start > end:
        raise ValueError("Banner end date precedes start date")
    link = urlsplit(payload.url)
    if (link.scheme != "https" or link.hostname not in allowed_link_hosts
            or link.username or link.password or link.port not in (None, 443)):
        raise ValueError("A verified first-party HTTPS link is required")
    _positive_id(payload.image_id)
    _positive_id(payload.mobile_image_id)
    if payload.show_order is not None and not 1 <= payload.show_order <= len(scope_rows) + 1:
        raise ValueError("Banner position is outside the current scope")
    result = _save_plan(owner, "banner", {"scope_rows": scope_rows}, payload.model_dump(), None)
    result["blockers"] = ["image_generation_provider", "uploaded_image_pixel_verification",
                          "public_banner_readback_adapter"]
    return result


async def campaign_snapshot(product_id, db, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    result = await db.execute(text("SELECT * FROM tb_product WHERE product_id=:id" + suffix),
                              {"id": product_id})
    product = result.mappings().one_or_none()
    if product is None:
        raise ValueError("Product not found")
    result = await db.execute(text("""
        SELECT episode_id, episode_no, price_type, open_yn, updated_date
        FROM tb_product_episode WHERE product_id=:id AND use_yn='Y'
        ORDER BY episode_id
    """ + suffix), {"id": product_id})
    episodes = [dict(row) for row in result.mappings().all()]
    result = await db.execute(text("""
        SELECT * FROM tb_product_free_episode_campaign
        WHERE product_id=:id AND active_yn='Y' ORDER BY id
    """ + suffix), {"id": product_id})
    return _clean({"product": dict(product), "episodes": episodes,
                   "campaigns": [dict(row) for row in result.mappings().all()]})


async def _paid_snapshot(apply_id, db, *, lock=False):
    suffix = " FOR UPDATE" if lock else ""
    result = await db.execute(text("SELECT * FROM tb_product_paid_apply WHERE id=:id" + suffix),
                              {"id": apply_id})
    application = result.mappings().one_or_none()
    if application is None:
        raise ValueError("Application not found")
    result = await db.execute(text("SELECT * FROM tb_product WHERE product_id=:id" + suffix),
                              {"id": application["product_id"]})
    product = result.mappings().one_or_none()
    if product is None:
        raise ValueError("Product not found")
    return _clean({"application": dict(application), "product": dict(product)})


async def apply_plan(owner, plan_id, db, actor, *, approved_plan_id=None,
                     scopes=(), writes_enabled=False, expected_cp_company_name=None):
    """Trusted host adapter. Caller supplies an unused session; this owns commit.

    approved_plan_id is set by the host after a direct instruction or exact plan
    approval. A Dot proposal and the existing slot write scope cannot set it.
    """
    if writes_enabled is not True:
        raise ValueError("Promotion extension writes are disabled")
    if approved_plan_id != plan_id:
        raise ValueError("An exact direct instruction or plan approval is required")
    plan = store.get("promotion-plan:" + plan_id, owner)
    if not plan or time.time() - plan["created_at"] > 1800:
        raise ValueError("Plan missing or expired; prepare again")
    kind = plan["kind"]
    required = {"hundred-free": CAMPAIGN_SCOPE, "paid-approval": PAID_APPROVAL_SCOPE,
                "banner": BANNER_SCOPE}[kind]
    if required not in scopes:
        raise ValueError("A separate extension write scope is required")
    if kind == "banner":
        raise ValueError("Banner apply is blocked until verified media/public readback is connected")
    role = "CP" if kind == "hundred-free" else "admin"
    if actor.get("role") != role or actor.get("user_id") != plan["actor_id"]:
        raise ValueError("Authenticated actor does not match the approved plan")
    operation_id = "promotion-apply:" + plan_id
    receipt = store.get(operation_id, owner)
    if receipt:
        if receipt["status"] == "completed":
            return receipt
        raise ValueError("An unresolved receipt exists; reconcile before retrying")
    # Durable claim prevents two workers from applying the same approved plan.
    if not store.claim(operation_id, owner, {"kind": kind, "plan_id": plan_id}):
        raise ValueError("Another worker already claimed this plan")
    async with db.begin():
        if kind == "hundred-free":
            from app.services.partner import partner_product_service as service

            current = await campaign_snapshot(plan["before"]["product"]["product_id"], db, lock=True)
            if current != plan["before"]:
                raise ValueError("Product, episodes or campaign changed; prepare again")
            company = await service.get_approved_cp_company_name_by_user_id(actor["user_id"], db)
            if not expected_cp_company_name or company != expected_cp_company_name:
                raise ValueError("The authenticated LikeNovel CP company is not verified")
            request = PutProductReqBody.model_validate(plan["request"])
            if request.hundred_free_campaign_ends_at <= datetime.now(KST).replace(tzinfo=None):
                raise ValueError("The campaign end has passed")
            store.save(operation_id, owner, "applying", {"kind": kind, "plan_id": plan_id})
            await service.put_product(request, current["product"]["product_id"], db, user_data=actor)
            after = await campaign_snapshot(current["product"]["product_id"], db)
            if not {row["episode_no"] for row in after["episodes"]
                    if row["price_type"] == "free"}.issuperset(range(1, 101)) or len(after["campaigns"]) != 1:
                raise ValueError("Campaign readback failed")
            campaign = after["campaigns"][0]
            if (campaign.get("campaign_free_start_no") != 1
                    or campaign.get("campaign_free_end_no") != 100
                    or after["product"].get("paid_episode_no") != 101):
                raise ValueError("Campaign range readback failed")
            allowed_changes = {"paid_episode_no", "price_type", "updated_id", "updated_date"}
            if any(after["product"].get(key) != value for key, value in current["product"].items()
                   if key not in allowed_changes):
                raise ValueError("An unrelated product field changed; rolling back")
        else:
            from app.services.admin import admin_user_service as service

            current = await _paid_snapshot(plan["request"]["apply_id"], db, lock=True)
            if current != plan["before"]:
                raise ValueError("Paid application or product changed; prepare again")
            store.save(operation_id, owner, "applying", {"kind": kind, "plan_id": plan_id})
            await service.accept_apply_rank_up(plan["request"]["apply_id"], db)
            after = await _paid_snapshot(plan["request"]["apply_id"], db)
            if after["application"]["status_code"] != "accepted" or after["product"] != current["product"]:
                raise ValueError("Approval readback failed or product was unexpectedly changed")
    # Lost-response failure before this line remains 'applying', blocks retries.
    payload = {"kind": kind, "plan_id": plan_id, "after": after,
               "public_verified": False, "approval_only": kind == "paid-approval"}
    store.save(operation_id, owner, "completed", payload)
    return store.get(operation_id, owner)
