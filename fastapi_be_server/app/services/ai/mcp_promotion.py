"""Promotion preparation; integration is disabled until explicit scoped intent.

The host must obtain actor/scopes/approved_plan_id from authenticated first-party
state, never from model-supplied MCP arguments. No tools are registered here.
"""

import asyncio
import json
import time
import uuid
from datetime import date, datetime
from decimal import Decimal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import text
from httpx import AsyncClient

from app.schemas.admin import PostBannerReqBody, PostApplyPaidConversionReqBody
from app.schemas.partner import PutProductReqBody
from app.services.ai import mcp_store as store
from app.services.ai.mcp_config import load as load_config
from app.rdb import likenovel_db_session

KST = ZoneInfo("Asia/Seoul")
CAMPAIGN_SCOPE = "likenovel.mcp.promotion.write"
PAID_APPROVAL_SCOPE = "likenovel.mcp.paid-approval.write"
PAID_CONVERSION_SCOPE = "likenovel.mcp.paid-conversion.write"
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


def prepare_paid_conversion(owner, before, actor, paid_episode_no):
    """Freeze an accepted request and the explicit first paid episode.

    The official service saves settings; the minute batch performs conversion.
    Waiting-for-free is a separate promotion and is not added implicitly.
    """
    if actor.get("role") != "admin":
        raise ValueError("CMS admin authentication is required")
    application, product = before["application"], before["product"]
    if application.get("status_code") != "accepted" or application.get("use_yn") != "Y":
        raise ValueError("Only an active accepted paid application can be applied")
    if application["product_id"] != product["product_id"]:
        raise ValueError("Application and product do not match")
    if product.get("price_type") != "free" or product.get("product_type") != "normal":
        raise ValueError("Paid conversion requires a free normal serial")
    if product.get("paid_episode_no") is not None or product.get("paid_open_date") is not None:
        raise ValueError("Paid conversion settings already exist")
    episode_no = _positive_id(paid_episode_no)
    if episode_no > len(before["episodes"]) + 1:
        raise ValueError("First paid episode must not exceed the next current episode")
    request = PostApplyPaidConversionReqBody(paid_episode_no=episode_no).model_dump()
    request["apply_id"] = _positive_id(application["id"])
    return _save_plan(owner, "paid-conversion", before, request, _positive_id(actor["user_id"]))


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


async def paid_conversion_snapshot(apply_id, db, *, lock=False):
    """Snapshot all fields the transition settings can depend on or preserve."""
    result = await _paid_snapshot(_positive_id(apply_id), db, lock=lock)
    product_state = await campaign_snapshot(result["product"]["product_id"], db, lock=lock)
    result["product"] = product_state["product"]
    result["episodes"] = product_state["episodes"]
    result["campaigns"] = product_state["campaigns"]
    return result


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
                "paid-conversion": PAID_CONVERSION_SCOPE, "banner": BANNER_SCOPE}[kind]
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
        elif kind == "paid-approval":
            from app.services.admin import admin_user_service as service

            current = await _paid_snapshot(plan["request"]["apply_id"], db, lock=True)
            if current != plan["before"]:
                raise ValueError("Paid application or product changed; prepare again")
            store.save(operation_id, owner, "applying", {"kind": kind, "plan_id": plan_id})
            await service.accept_apply_rank_up(plan["request"]["apply_id"], db)
            after = await _paid_snapshot(plan["request"]["apply_id"], db)
            if after["application"]["status_code"] != "accepted" or after["product"] != current["product"]:
                raise ValueError("Approval readback failed or product was unexpectedly changed")
        else:
            from app.services.admin import admin_user_service as service

            current = await paid_conversion_snapshot(plan["request"]["apply_id"], db, lock=True)
            if current != plan["before"]:
                raise ValueError("Paid application, product or episodes changed; prepare again")
            request = PostApplyPaidConversionReqBody.model_validate(plan["request"])
            store.save(operation_id, owner, "applying", {"kind": kind, "plan_id": plan_id})
            await service.apply_paid_conversion_by_admin(
                plan["request"]["apply_id"], request, actor["user_id"], db,
            )
            after = await paid_conversion_snapshot(plan["request"]["apply_id"], db)
            if (after["product"].get("paid_episode_no") != request.paid_episode_no
                    or not after["product"].get("paid_open_date")):
                raise ValueError("Paid conversion settings readback failed")
            allowed_changes = {"paid_episode_no", "paid_open_date", "updated_id", "updated_date"}
            if (any(after["product"].get(key) != value for key, value in current["product"].items()
                    if key not in allowed_changes)
                    or after["application"] != current["application"]
                    or after["episodes"] != current["episodes"]
                    or after["campaigns"] != current["campaigns"]):
                raise ValueError("An unrelated conversion field changed; rolling back")
    # Lost-response failure before this line remains 'applying', blocks retries.
    payload = {"kind": kind, "plan_id": plan_id, "after": after,
               "public_verified": False, "approval_only": kind == "paid-approval"}
    if kind == "paid-conversion":
        payload["transition_pending"] = True
        payload["effective_conversion_verified"] = False
    store.save(operation_id, owner, "completed", payload)
    return store.get(operation_id, owner)


async def _public_json(client, url, *, params=None):
    # Stream bounds memory before JSON decoding; never forward admin credentials.
    async with client.stream("GET", url, params=params, headers={"Cache-Control": "no-cache"}) as response:
        response.raise_for_status()
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > 2 * 1024 * 1024:
                raise ValueError("Public readback exceeds the response size bound")
    return json.loads(body)


async def _public_prices(base, product_id):
    urls = [f"{base}/v1/query/products/{product_id}/detail-shell",
            f"{base}/v1/query/products/{product_id}/episodes"]
    async with asyncio.timeout(60):
        async with AsyncClient(timeout=10, follow_redirects=False) as client:
            product = (await _public_json(client, urls[0]))["data"]
            episodes = {}
            total = None
            for page in range(1, 21):
                payload = (await _public_json(client, urls[1], params={
                    "page": page, "limit": 100, "order_by": "episodeNo",
                    "order_dir": "asc", "_mcp_readback": uuid.uuid4().hex,
                }))["data"]
                count = payload["pagination"]["totalCount"]
                if type(count) is not int or count < 0 or (total is not None and count != total):
                    raise ValueError("Public episode count changed during readback")
                total = count
                rows = payload["episodes"]
                if not isinstance(rows, list) or len(rows) > 100:
                    raise ValueError("Invalid public episode page")
                for row in rows:
                    episode_id = _positive_id(row["episodeId"])
                    if episode_id in episodes or row.get("productId") != product_id:
                        raise ValueError("Duplicate or unrelated public episode")
                    episodes[episode_id] = {
                        "episode_no": row["episodeNo"], "price_type": row["priceType"],
                    }
                if len(episodes) == total:
                    return {"product": product, "episodes": episodes, "complete": True, "urls": urls}
                if not rows:
                    break
            return {"product": product, "episodes": episodes, "complete": False, "urls": urls}


async def verify_public(owner, plan_id):
    """Read-only current DB and anonymous public proof, without changing receipts."""
    receipt = store.get("promotion-apply:" + plan_id, owner)
    plan = store.get("promotion-plan:" + plan_id, owner)
    if not receipt or receipt["status"] != "completed" or not plan:
        raise ValueError("Only a committed owned promotion plan can be verified")
    kind = receipt["kind"]
    proof = {"plan_id": plan_id, "kind": kind, "verified_at": datetime.now(KST).isoformat(),
             "public_verification_required": kind != "paid-approval", "public_verified": False}
    async with likenovel_db_session() as db:
        if kind == "paid-approval":
            current = await _paid_snapshot(plan["request"]["apply_id"], db)
            proof.update({
                "db_verified": current["application"]["status_code"] == "accepted"
                    and current["application"]["use_yn"] == "Y",
                "public_verification_required": False, "public_verified": None,
                "approval_only": True,
            })
            return proof
        if kind == "paid-conversion":
            current = await paid_conversion_snapshot(plan["request"]["apply_id"], db)
            start = plan["request"]["paid_episode_no"]
            expected_paid = [row for row in current["episodes"] if row["episode_no"] >= start]
            effective = (
                current["application"]["status_code"] == "accepted"
                and current["product"].get("paid_episode_no") == start
                and current["product"].get("paid_open_date") == receipt["after"]["product"].get("paid_open_date")
                and current["product"].get("price_type") == "paid"
                and bool(expected_paid)
                and all(row["price_type"] == "paid" for row in expected_paid)
            )
            proof.update({"db_verified": effective, "effective_conversion_verified": effective,
                          "transition_pending": not effective})
        elif kind == "hundred-free":
            current = await campaign_snapshot(plan["before"]["product"]["product_id"], db)
            prices = {row["episode_no"]: row["price_type"] for row in current["episodes"]}
            end_expected = datetime.fromisoformat(plan["request"]["hundred_free_campaign_ends_at"])
            campaigns = current["campaigns"]
            period_active = False
            if len(campaigns) == 1:
                campaign = campaigns[0]
                end_actual = datetime.fromisoformat(campaign["ends_at"])
                period_active = (
                    abs((end_actual - end_expected).total_seconds()) < 1
                    and end_actual > datetime.now(KST).replace(tzinfo=None)
                    and campaign.get("campaign_free_start_no") == 1
                    and campaign.get("campaign_free_end_no") == 100
                    and campaign.get("restore_free_start_no") == 1
                    and campaign.get("restore_free_end_no") == 25
                )
            effective = (current["product"].get("price_type") == "paid"
                         and current["product"].get("paid_episode_no") == 101
                         and all(prices.get(number) == "free" for number in range(1, 101))
                         and (101 not in prices or prices[101] == "paid") and period_active)
            proof.update({"db_verified": effective, "campaign_period_active": period_active,
                          "expected_ends_at": end_expected.isoformat(),
                          "actual_ends_at": campaigns[0].get("ends_at") if len(campaigns) == 1 else None})
        else:
            raise ValueError("No public promotion readback adapter exists for this kind")
    product_id = current["product"]["product_id"]
    base = load_config()["resource"].removesuffix("/mcp")
    try:
        public = await _public_prices(base, product_id)
        expected = {row["episode_id"]: {"episode_no": row["episode_no"], "price_type": row["price_type"]}
                    for row in current["episodes"] if row.get("open_yn") == "Y"}
        product = public["product"]
        verified = (effective and public["complete"] and bool(expected)
                    and product.get("productId") == product_id
                    and product.get("priceType") == current["product"]["price_type"]
                    and product.get("paidEpisodeNo") == current["product"]["paid_episode_no"]
                    and public["episodes"] == expected)
        if kind == "hundred-free":
            visible_numbers = {row["episode_no"] for row in public["episodes"].values()}
            verified = verified and visible_numbers.issuperset(range(1, 101))
        proof.update({"public_verified": verified, "public_pages_complete": public["complete"],
                      "public_episode_count": len(public["episodes"]), "public_urls": public["urls"]})
    except Exception as exc:
        proof.update({"public_verified": False, "public_readback_error": type(exc).__name__})
    return proof
