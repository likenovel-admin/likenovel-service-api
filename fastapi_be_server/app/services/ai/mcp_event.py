"""Existing CMS event contracts, frozen plans, and human-approved execution."""

import asyncio
import hashlib
import io
import json
import re
import time
import uuid
import warnings
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from httpx import AsyncClient
from PIL import Image
from sqlalchemy import text

from app.const import settings
from app.schemas.admin import PostEventReqBody, PutEventReqBody
from app.services.admin import admin_event_service as service
from app.services.ai import mcp_banner as banner, mcp_store as store
from app.services.ai.mcp_config import load as load_config

WRITE_EVENT = "likenovel.mcp.event.write"
KST = ZoneInfo("Asia/Seoul")
EVENT_TYPES = {"all", "view-3-times", "add-comment", "add-product", "etc"}
CMS_EVENT_IMAGE_SIZES = [[1080, 347], [1120, 360]]
IMAGE_GUIDE = {"formats": ["JPEG", "PNG", "GIF"], "fields": {
    "thumbnail_image_id": {"role": "event_list_thumbnail",
        "cms_sources": ["cms/app/events/add/page.tsx:379", "cms/app/events/[eventId]/page.tsx:414"],
        "cms_displayed_sizes": CMS_EVENT_IMAGE_SIZES,
        "public_rendering": "service/components/event/EventList.tsx:96 uses aspect-[256/140]"},
    "detail_image_id": {"role": "event_detail_body",
        "cms_sources": ["cms/app/events/add/page.tsx:410", "cms/app/events/[eventId]/page.tsx:450"],
        "cms_displayed_sizes": CMS_EVENT_IMAGE_SIZES,
        "public_rendering": "service/app/product/event/[id]/page.tsx:107 uses width:100%, height:auto"}},
    "home_banner": {"separate_asset": True, "source": "cms/lib/bannerImagePolicy.ts",
                    "specification": "position-specific; not the event thumbnail or body"}}
META_KEYS = {"job_id", "status", "updated_at"}


def _clean(value):
    return json.loads(json.dumps(value, ensure_ascii=False, default=lambda item: item.isoformat()))


def _payload(row):
    return {key: value for key, value in row.items() if key not in META_KEYS}


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode()).hexdigest()


def _id(value):
    if type(value) is not int or value <= 0:
        raise ValueError("A positive integer ID is required")
    return value


def _day(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("CMS dates must use YYYY-MM-DD")
    return date.fromisoformat(value)


def _origin():
    resource = urlsplit(load_config().get("resource", ""))
    if (resource.scheme != "https" or resource.hostname not in ("api.likenovel.net", "api.likenovel.dev")
            or resource.port not in (None, 443) or resource.username or resource.password
            or resource.path != "/mcp" or resource.query or resource.fragment):
        raise ValueError("A verified environment-matched MCP resource is required")
    return "https://" + resource.hostname


def _event_url(event_id):
    return _origin().replace("https://api.", "https://") + "/product/event/" + str(event_id)


def _field_value(key, value):
    if key in ("product_ids", "target_product_ids") and isinstance(value, str):
        return json.loads(value)
    if key in ("start_date", "end_date") and value is not None:
        parsed = datetime.fromisoformat(str(value))
        if parsed.time() == datetime.min.time() and parsed.tzinfo is None:
            return parsed.date().isoformat()
    return value


def _request_from_row(row):
    return {key: _field_value(key, row.get(key)) for key in PostEventReqBody.model_fields}


def _validate_request(data, before=None):
    if not isinstance(data, dict) or set(data) - PostEventReqBody.model_fields.keys():
        raise ValueError("Only existing CMS event fields are accepted")
    if before is not None:
        for key, value in data.items():
            if value is None and before.get(key) is not None:
                raise ValueError("Native CMS update cannot clear a field with null")
        data = {**_request_from_row(before), **data}
    for key in ("thumbnail_image_id", "detail_image_id"):
        _id(data.get(key))
    if data["thumbnail_image_id"] == data["detail_image_id"]:
        raise ValueError("Thumbnail and detail must reference separate assets")
    for key in ("product_ids", "target_product_ids"):
        values = data.get(key)
        if values is None and key == "target_product_ids":
            continue
        if (not isinstance(values, list) or len(values) > 200
                or any(type(value) is not int or value <= 0 for value in values)
                or len(set(values)) != len(values)):
            raise ValueError("Product references must be unique positive integer IDs")
    for key in ("show_yn_thumbnail_img", "show_yn_detail_img", "show_yn_product", "show_yn_information"):
        if data.get(key) not in ("Y", "N"):
            raise ValueError("CMS visibility flags must be Y or N")
    if not isinstance(data.get("type"), str) or data["type"] not in EVENT_TYPES - {"all"}:
        raise ValueError("Unknown CMS event type")
    if _day(data.get("start_date")) > _day(data.get("end_date")):
        raise ValueError("Event start must not follow its end")
    if not isinstance(data.get("title"), str) or not data["title"].strip():
        raise ValueError("An exact event title is required")
    if data.get("show_yn_product") == "Y" and not data.get("product_ids"):
        raise ValueError("Visible product sections require product references")
    for key in ("reward_amount", "reward_max_people"):
        value = data.get(key)
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError("Reward counts must be non-negative integers")
    payload = PostEventReqBody.model_validate(data)
    if payload.reward_type not in (None, "ticket", "cash"):
        raise ValueError("Unknown CMS reward type")
    if payload.type != "etc" and (not payload.target_product_ids or not payload.reward_type
            or not payload.reward_amount or not payload.reward_max_people):
        raise ValueError("Reward events require exact target products and positive reward limits")
    # Native PUT skips None; do not invent null-clearing or DB default semantics.
    return payload.model_dump(exclude_none=True)


async def _event_snapshot(db, event_id, *, lock=False):
    result = await db.execute(text("SELECT * FROM tb_event_v2 WHERE id=:id" +
        (" FOR UPDATE" if lock else "")), {"id": _id(event_id)})
    row = result.mappings().one_or_none()
    return _clean(dict(row)) if row is not None else None


async def events_list(db, event_type="all", page=1, count_per_page=20):
    # Native service interpolates type; never pass an unchecked filter.
    if not isinstance(event_type, str) or event_type not in EVENT_TYPES:
        raise ValueError("Unknown CMS event type")
    if type(page) is not int or page < 1 or type(count_per_page) is not int or not 1 <= count_per_page <= 100:
        raise ValueError("Use positive pages and 1..100 events per page")
    return _clean(await service.events_list(event_type, page, count_per_page, db))


async def event_detail(db, event_id):
    result = _clean(await service.event_detail_by_id(_id(event_id), db))
    return {"event": result, "event_url": _event_url(event_id), "image_guide": IMAGE_GUIDE,
            "home_banner_is_separate": True}


def _paid_at(value):
    parsed = datetime.fromisoformat(str(value))
    return parsed.replace(tzinfo=KST) if parsed.tzinfo is None else parsed.astimezone(KST)


async def paid_open_weeks(db, starts_on, ends_before):
    start, end = _day(starts_on), _day(ends_before)
    if not 0 < (end - start).days <= 93:
        raise ValueError("Use a paid_open_date range of 1..93 days")
    result = await db.execute(text("""SELECT product_id,title,paid_open_date,price_type,open_yn,blind_yn,status_code
        FROM tb_product WHERE open_yn='Y' AND COALESCE(blind_yn,'N')='N' AND paid_open_date >= :start AND paid_open_date < :end
        ORDER BY paid_open_date,product_id"""), {"start":start.isoformat(), "end":end.isoformat()})
    groups = {}
    for raw in result.mappings().all():
        row = dict(raw)
        paid = _paid_at(row["paid_open_date"])
        if row["open_yn"] != "Y" or row.get("blind_yn") not in (None,"N") or not start <= paid.date() < end:
            continue
        week = (paid.date() - timedelta(days=paid.weekday())).isoformat()
        groups.setdefault(week, []).append({**_clean(row), "paid_open_date":paid.isoformat()})
    return {"source_field":"tb_product.paid_open_date", "timezone":"Asia/Seoul",
            "week_rule":"Monday 00:00 inclusive through next Monday 00:00 exclusive",
            "weeks":[{"week_start":week, "products":groups[week]} for week in sorted(groups)]}


async def _references(db, request, *, lock=False):
    ids = sorted(set(request["product_ids"] + (request.get("target_product_ids") or [])))
    products = []
    if ids:
        params = {"p"+str(index):value for index,value in enumerate(ids)}
        result = await db.execute(text("SELECT product_id,title,paid_open_date,price_type,open_yn,blind_yn,status_code "
            "FROM tb_product WHERE product_id IN (" + ",".join(":"+key for key in params) + ")"
            " ORDER BY product_id" + (" FOR UPDATE" if lock else "")), params)
        products = _clean([dict(row) for row in result.mappings().all()])
        if sorted(row["product_id"] for row in products) != ids or any(row["open_yn"] != "Y" or row.get("blind_yn") not in (None,"N") for row in products):
            raise ValueError("A referenced product is missing or inactive")
    image_ids = {"thumbnail": request["thumbnail_image_id"], "detail": request["detail_image_id"]}
    params = {"i"+str(index):value for index,value in enumerate(sorted(image_ids.values()))}
    result = await db.execute(text("""SELECT f.file_group_id,f.group_type,f.use_yn,
        i.file_name,i.file_org_name,i.file_path,i.use_yn AS item_use_yn
        FROM tb_common_file f JOIN tb_common_file_item i ON i.file_group_id=f.file_group_id
        WHERE f.file_group_id IN (""" + ",".join(":"+key for key in params) + ")"
        " ORDER BY f.file_group_id" + (" FOR UPDATE" if lock else "")), params)
    rows = [dict(row) for row in result.mappings().all()]
    if (len(rows) != 2 or sorted(row["file_group_id"] for row in rows) != sorted(image_ids.values())
            or any(row["use_yn"] != "Y" or row["item_use_yn"] != "Y" for row in rows)):
        raise ValueError("Image references must resolve to one active file per asset")
    images = {}
    cdn_host = urlsplit(settings.R2_SC_CDN_URL).hostname
    for label, file_id in image_ids.items():
        row = next(row for row in rows if row["file_group_id"] == file_id)
        parsed = urlsplit(row["file_path"])
        if (not cdn_host or parsed.scheme != "https" or parsed.hostname != cdn_host
                or parsed.username or parsed.password or parsed.port not in (None,443)
                or parsed.query or parsed.fragment):
            raise ValueError("Image must use the configured CMS CDN without credentials or query")
        body = await asyncio.to_thread(banner._download, row["file_path"], {cdn_host})
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(body)) as image:
                    size = image.size
            metadata = banner.validate_image(body, size)
        except Exception:
            raise ValueError("Existing event image pixels could not be verified") from None
        if metadata["format"] not in IMAGE_GUIDE["formats"]:
            raise ValueError("Event image format does not match the CMS guide")
        images[label] = {**_clean(row), **metadata,
                        "matches_cms_guide": list(size) in IMAGE_GUIDE["fields"][label+"_image_id"]["cms_displayed_sizes"]}
    return {"products":products, "images":images}


def _read_plan(owner, plan_id, *, check_expiry=True):
    if not isinstance(plan_id, str) or not re.fullmatch(r"[a-f0-9-]{36}", plan_id):
        raise ValueError("Invalid event plan ID")
    record = store.get("event-plan:"+plan_id, owner)
    if not record or record["status"] != "ready":
        raise ValueError("Event plan not found for this owner")
    plan = _payload(record)
    saved_hash = plan.pop("plan_hash")
    if _digest(plan) != saved_hash:
        raise ValueError("Frozen event plan changed")
    if check_expiry and time.time() >= plan["expires_at"]:
        raise ValueError("Event plan expired; prepare a new plan")
    return {**plan, "plan_hash": saved_hash}


async def prepare(owner, request, db, *, idempotency_key, event_id=None, week_start=None, event_url=None):
    if not isinstance(idempotency_key, str) or not re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", idempotency_key):
        raise ValueError("A stable idempotency key is required")
    if event_id is not None:
        _id(event_id)
    input_hash = _digest({"request":request, "event_id":event_id,
                          "week_start":week_start, "event_url":event_url})
    plan_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "likenovel-event:"+owner+":"+idempotency_key))
    existing = store.get("event-plan:"+plan_id, owner)
    if existing:
        if existing.get("input_hash") != input_hash:
            raise ValueError("This idempotency key already belongs to different input")
        return _read_plan(owner, plan_id)
    before = await _event_snapshot(db,event_id) if event_id is not None else None
    if event_id is not None and before is None:
        raise ValueError("Event not found")
    payload = _validate_request(request,before)
    if before is not None and _matches(before,payload):
        raise ValueError("No event fields change; use the read-only event detail")
    destination = _event_url(event_id if event_id is not None else "{event_id}")
    if event_url is not None and (event_id is None or event_url != destination):
        raise ValueError("Use the exact environment-matched event detail URL")
    references = await _references(db,payload)
    if week_start is not None:
        start = _day(week_start)
        if start.weekday() != 0:
            raise ValueError("Paid-open week must start on Monday in Asia/Seoul")
        selected = [row for row in references["products"] if row["product_id"] in payload["product_ids"]]
        if any(not row["paid_open_date"] or
               not start <= _paid_at(row["paid_open_date"]).date() < start+timedelta(days=7) for row in selected):
            raise ValueError("Displayed works do not all belong to this paid_open_date week")
    now = time.time()
    plan = {"plan_id":plan_id, "kind":"event", "action":"update" if before else "create",
        "event_id":event_id, "request":payload, "before":before, "references":references,
        "week_start":week_start, "event_url":destination, "input_hash":input_hash,
        "created_at":now, "expires_at":now+900, "publishes_home_banner":False,
        "image_guide":IMAGE_GUIDE,
        "period_semantics":"CMS YYYY-MM-DD values are midnight in Asia/Seoul; public BETWEEN includes the end instant",
        "execution_requires_user_approval":True}
    plan["plan_hash"] = _digest(plan)
    if not store.claim("event-plan:"+plan_id,owner,plan):
        existing = store.get("event-plan:"+plan_id,owner)
        if not existing or existing.get("input_hash") != input_hash:
            raise ValueError("Concurrent idempotency conflict")
        return _read_plan(owner,plan_id)
    store.save("event-plan:"+plan_id,owner,"ready",plan)
    return plan


def _matches(row, request):
    if not isinstance(row, dict):
        return False
    try:
        actual = {key: _field_value(key,row.get(key)) for key in request}
        # JSON preserves bool/int/list distinctions that Python equality would collapse.
        return _digest(actual) == _digest(request)
    except (TypeError, ValueError):
        return False


async def apply_plan(owner, plan_id, db, actor, *, approved_plan_id=None, approved_plan_hash=None,
                     scopes=(), writes_enabled=False):
    if (writes_enabled is not True or WRITE_EVENT not in scopes or approved_plan_id != plan_id
            or actor.get("role") != "admin" or type(actor.get("user_id")) is not int or actor["user_id"] <= 0):
        raise PermissionError("Event writes need the exact user-approved plan, admin scope and enabled switch")
    plan = _read_plan(owner,plan_id,check_expiry=False)
    if approved_plan_hash != plan["plan_hash"]:
        raise PermissionError("The user-approved event plan hash changed")
    operation_id = "event-apply:"+plan_id
    receipt = store.get(operation_id,owner)
    if receipt:
        if receipt["status"] == "completed":
            return receipt
        raise ValueError("Event execution requires readback; never reapply an unresolved or failed plan")
    _read_plan(owner,plan_id)
    result = {"kind":"event", "plan_id":plan_id, "plan_hash":plan["plan_hash"],
        "event_id":plan["event_id"], "before":plan["before"], "request":plan["request"],
        "committed":False, "db_verified":False, "public_verified":False, "retry_allowed":False,
        "publishes_home_banner":False, "phase":"validating"}
    if not store.claim(operation_id,owner,result):
        raise ValueError("Another worker claimed this event plan; use readback")
    commit_attempted = False
    try:
        async with db.begin():
            if plan["event_id"] is not None:
                current = await _event_snapshot(db,plan["event_id"],lock=True)
                if current != plan["before"]:
                    raise ValueError("CMS event changed after preparation")
            if await _references(db,plan["request"],lock=True) != plan["references"]:
                raise ValueError("Product or image references changed after preparation")
            result["phase"] = "applying"
            store.save(operation_id,owner,"applying",result)
            if plan["action"] == "create":
                await service.post_event(PostEventReqBody.model_validate(plan["request"]),db)
                inserted = await db.execute(text("SELECT LAST_INSERT_ID()"))
                result["event_id"] = _id(inserted.scalar_one())
            else:
                await service.put_event(PutEventReqBody.model_validate(plan["request"]),plan["event_id"],db)
            result["after"] = await _event_snapshot(db,result["event_id"])
            if not _matches(result["after"],plan["request"]):
                raise ValueError("Native CMS readback differs from the approved request")
            if plan["before"] and any(result["after"].get(key) != value
                    for key,value in plan["before"].items()
                    if key not in plan["request"] and key not in ("updated_id","updated_date")):
                raise ValueError("Native CMS changed a field outside the approved request")
            result.update(phase="committing",event_url=_event_url(result["event_id"]))
            store.save(operation_id,owner,"committing",result)
            commit_attempted = True
        result.update(committed=True,db_verified=True,phase="committed")
        store.save(operation_id,owner,"completed",result)
    except Exception as exc:
        result.update(committed=None if commit_attempted else False, db_verified=False,
            error_type=type(exc).__name__, phase="commit_readback_required" if commit_attempted else result["phase"])
        store.save(operation_id,owner,"uncertain" if commit_attempted else "failed",result)
        # Concurrency/validation failures occur before writes and remain explicit to the caller.
        if isinstance(exc, ValueError) and result["phase"] == "validating":
            raise
    return store.get(operation_id,owner)


async def _public_detail(event_id):
    async with AsyncClient(follow_redirects=False,timeout=20,trust_env=False) as client:
        response = await client.get(_origin()+"/v1/query/events/"+str(_id(event_id)))
        if response.status_code != 200:
            raise ValueError("Public event detail lookup failed")
        return response.json()


def _save_readback(operation_id, owner, previous, status, result):
    # A verifier must never replace state advanced by an applying worker or another verifier.
    with store.connection() as db:
        updated = db.execute(
            "UPDATE receipts SET status=?,payload=?,updated=? "
            "WHERE job_id=? AND owner=? AND status=? AND updated=?",
            (status,json.dumps(result,ensure_ascii=False),time.time(),operation_id,
             owner,previous["status"],previous["updated_at"]))
        db.commit()
        changed = updated.rowcount == 1
    latest = store.get(operation_id,owner)
    if not changed:
        return {**latest,"verification_status":"receipt_changed_during_readback","retry_allowed":False}
    return latest


async def verify_receipt(owner, plan_id, db):
    plan = _read_plan(owner,plan_id,check_expiry=False)
    operation_id = "event-apply:"+plan_id
    receipt = store.get(operation_id,owner)
    if not receipt:
        raise ValueError("Event execution receipt not found")
    if receipt["status"] in ("generating","applying"):
        return {**receipt,"verification_status":"execution_in_progress","retry_allowed":False}
    result = _payload(receipt)
    result.update(db_verified=False,public_verified=False,partial_success=False,retry_allowed=False)
    if receipt["status"] == "failed" or result.get("event_id") is None:
        return {**receipt, **result}
    try:
        actual = await _event_snapshot(db,result["event_id"])
    except Exception as exc:
        result.update(verification_status="db_readback_failed",
                      verification_error_type=type(exc).__name__,
                      partial_success=result.get("committed") is True)
        return _save_readback(operation_id,owner,receipt,receipt["status"],result)
    result["current"] = actual
    result["db_verified"] = _matches(actual,plan["request"])
    status = receipt["status"]
    if (status != "completed" and result["db_verified"] and actual == result.get("after")
            and result["phase"] in ("committing","commit_readback_required")):
        result.update(committed=True,phase="confirmed_by_readback")
        status = "completed"
    if result["db_verified"] and result.get("committed") is True:
        try:
            public = (await _public_detail(result["event_id"]))["data"]
            if not _matches(public,plan["request"]) or any(
                    public.get(label+"_image_path") != asset["file_path"]
                    for label,asset in plan["references"]["images"].items()):
                raise ValueError("Public event data differs from the approved plan")
            # Compare actual CDN bytes as well as image IDs and URLs.
            if await _references(db,plan["request"]) != plan["references"]:
                raise ValueError("Current event references differ from the approved plan")
            result.update(public_verified=True,verification_status="verified")
        except Exception as exc:
            result.update(verification_status="public_readback_failed",verification_error_type=type(exc).__name__)
    else:
        result["verification_status"] = ("commit_not_proven" if result["db_verified"]
                                         else "current_db_differs" if actual else "event_missing")
    result["partial_success"] = result.get("committed") is True and not result["public_verified"]
    return _save_readback(operation_id,owner,receipt,status,result)
