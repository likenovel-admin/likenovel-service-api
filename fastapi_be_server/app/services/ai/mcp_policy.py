"""Narrow standing authorization for LikeNovel's scheduled Dot operator."""

from datetime import datetime
from zoneinfo import ZoneInfo

KST = ZoneInfo("Asia/Seoul")
READ_SCOPE = "likenovel.mcp.read"
WRITE_SCOPE = "likenovel.mcp.write"
CLIENT_ID = "likenovel-dot-mcp"
SINGLE_KEYS = (
    "before_paid_top",
    "between_direct_recommend_1",
    "between_direct_recommend_2",
)


def cycle_key(kind: str, now: datetime | None = None) -> str:
    current = (now or datetime.now(KST)).astimezone(KST)
    if kind not in {"direct", "single"}:
        raise ValueError("Unknown operation")
    if (current.hour, current.minute) < (10, 5 if kind == "single" else 0):
        raise ValueError("Scheduled operation is not due yet")
    if kind == "single" and current.weekday() not in {0, 3}:
        raise ValueError("Single slots run on Monday and Thursday only")
    return f"{kind}:{current.date().isoformat()}"


def validate_ids(values: object) -> list[int]:
    if (
        not isinstance(values, list)
        or not 1 <= len(values) <= 200
        or any(type(value) is not int or value <= 0 for value in values)
        or len(set(values)) != len(values)
    ):
        raise ValueError("Product IDs must be unique positive integers (1-200)")
    return values


def validate_direct_updates(updates: list[dict], slots: list[dict], candidates: list[dict]):
    from app.services.ai import direct_curator_service as curator

    allowed = {
        curator.SLOT_PD, curator.SLOT_LOWPOINT, curator.SLOT_FREE_NEW,
        curator.SLOT_PAID_OPENRUN, curator.SLOT_WAIT_FREE,
    }
    by_slot = {slot["slot_id"]: slot for slot in slots if slot["name"] in allowed}
    by_product = {item["product_id"]: item for item in candidates}
    if len(by_slot) != 5 or not isinstance(updates, list) or len(updates) > 5:
        raise ValueError("Expected exactly five authorized direct slots")
    seen = set()
    for update in updates:
        if set(update) != {"slot_id", "product_ids", "reason"}:
            raise ValueError("Only product IDs and a reason may be supplied")
        slot_id = update["slot_id"]
        if type(slot_id) is not int or slot_id not in by_slot or slot_id in seen:
            raise ValueError("Unknown or duplicate slot")
        seen.add(slot_id)
        if not isinstance(update["reason"], str) or not 10 <= len(update["reason"]) <= 1500:
            raise ValueError("A concrete editorial reason is required")
        slot = by_slot[slot_id]
        ids = validate_ids(update["product_ids"])
        for product_id in ids:
            item = by_product.get(product_id)
            if item is None or item.get("exclude_from_recommend_yn") == "Y":
                raise ValueError("Product is missing or excluded from recommendations")
            name = slot["name"]
            if name == curator.SLOT_PAID_OPENRUN and not (
                item["price_type"] == "paid" and item["publish_regular_yn"] == "Y"
                and item["status_code"] == "ongoing"
            ):
                raise ValueError("Paid openrun eligibility failed")
            if name == curator.SLOT_WAIT_FREE and not (
                item["price_type"] == "paid" and item["waiting_for_free_yn"] == "Y"
            ):
                raise ValueError("Waiting-for-free eligibility failed")
            if name == curator.SLOT_FREE_NEW and not (
                item["price_type"] == "free" and item["product_type"] == "normal"
                and item["status_code"] == "ongoing"
            ):
                raise ValueError("Free new eligibility failed")
        if slot["name"] == curator.SLOT_FREE_NEW:
            eligible = [
                item for item in candidates
                if item["price_type"] == "free" and item["product_type"] == "normal"
                and item["status_code"] == "ongoing"
                and item.get("exclude_from_recommend_yn") != "Y"
            ]
            eligible.sort(
                key=lambda item: (item["first_public_episode_date"] or "", item["product_id"]),
                reverse=True,
            )
            if ids != [item["product_id"] for item in eligible[:len(slot["product_ids"])]]:
                raise ValueError("Free new slot must preserve capacity and newest-first order")
