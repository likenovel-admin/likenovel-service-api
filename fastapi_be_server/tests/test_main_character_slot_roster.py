"""메인 캐릭터 구좌 슬롯 로스터 게이트 테스트.

character_inventory_v3 payload에 대한 공개 슬롯 게이트(_build_slot_character_roster)를
fake summary row로 검증한다. DB 불필요(순수 함수).
"""

import json

from app.services.product.main_character_slot_service import (
    _build_slot_character_roster,
)


def _eligible_payload(**overrides):
    payload = {
        "display_name": "란",
        "aliases": ["란이", "Ran"],
        "display_safety": {"status": "pass"},
        "public_slot_eligible": True,
        "work_role": "main_protagonist",
    }
    payload.update(overrides)
    return payload


def _row(scope_key, payload):
    return {
        "scopeKey": scope_key,
        "summaryText": json.dumps(payload, ensure_ascii=False),
    }


def test_slot_roster_includes_when_all_conditions_met():
    rows = [_row("protagonist:first_person", _eligible_payload())]
    out = _build_slot_character_roster(rows)
    assert len(out) == 1
    assert out[0]["scopeKey"] == "protagonist:first_person"
    assert out[0]["displayName"] == "란"
    assert out[0]["aliases"] == ["란이", "Ran"]


def test_slot_roster_excludes_when_public_slot_eligible_false():
    rows = [_row("named:x", _eligible_payload(public_slot_eligible=False))]
    assert _build_slot_character_roster(rows) == []


def test_slot_roster_excludes_when_public_slot_eligible_missing():
    payload = _eligible_payload()
    payload.pop("public_slot_eligible")
    rows = [_row("named:x", payload)]
    assert _build_slot_character_roster(rows) == []


def test_slot_roster_excludes_when_display_safety_not_pass():
    for status in ("fail", "review"):
        rows = [_row("named:x", _eligible_payload(display_safety={"status": status}))]
        assert _build_slot_character_roster(rows) == [], status


def test_slot_roster_excludes_when_not_main_protagonist():
    rows = [_row("named:x", _eligible_payload(work_role="supporting"))]
    assert _build_slot_character_roster(rows) == []


def test_slot_roster_empty_when_no_v3_rows():
    assert _build_slot_character_roster([]) == []


def test_slot_roster_dedupes_same_scope_key():
    rows = [
        _row("protagonist:first_person", _eligible_payload()),
        _row("protagonist:first_person", _eligible_payload()),
    ]
    out = _build_slot_character_roster(rows)
    assert len(out) == 1
