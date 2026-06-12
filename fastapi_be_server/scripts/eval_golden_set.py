#!/usr/bin/env python3
"""골든셋 기반 7축 라벨 추출 평가 러너.

골든셋(docs/ai-codebook/golden-set-v1.json)의 expected/forbidden/optional 의미론으로
추출 결과를 채점한다. 파이프라인(프롬프트, codebook, guard, 모델)을 바꿀 때마다
이 러너를 돌려 회귀를 측정한다. 샘플 보고 guard를 즉흥 추가하는 루프의 대체물이다.

사용법:
  python3 eval_golden_set.py --results results.json
  python3 eval_golden_set.py --from-db                  # tb_product_ai_metadata 채점 (BATCH_DB_* env)
  python3 eval_golden_set.py --results r.json --json report.json

results.json 포맷(둘 다 허용):
  [{"product_id": 1106, "axis_labels": {"세": [...]}, "unmapped_concepts": [...]}, ...]
  {"1106": {"세": [...]}, ...}

채점 규칙:
  expected          누락 시 recall 실패
  expected_any      그룹 중 1개 이상 포함되면 충족
  forbidden         포함 시 violation — 하드 게이트
  strict_axes       해당 축에서 expected+optional+expected_any 외 라벨 → strict violation
  unmapped_expected 예측 unmapped_concepts와의 부분 일치(소프트 지표, 게이트 아님)

종료 코드: forbidden/strict violation 1건 이상이면 1. --no-gate면 항상 0.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

AXIS_ORDER = ("세", "직", "능", "연", "작", "타", "목")

# tb_product_ai_metadata 컬럼 → 축 매핑 (save_dna와 동일한 계약)
DB_AXIS_COLUMNS = {
    "세": "worldview_tags",
    "직": "protagonist_job_tags",
    "능": "protagonist_material_tags",
    "연": "axis_romance_tags",
    "작": "axis_style_tags",
    "타": "protagonist_type_tags",
}

GOLDEN_PATH_CANDIDATES = [
    Path(os.getenv("GOLDEN_SET_PATH", "")),
    Path(__file__).resolve().parents[4] / "docs" / "ai-codebook" / "golden-set-v1.json",
    Path(__file__).resolve().parents[1] / "dist" / "ai" / "golden-set-v1.json",
]


def load_golden(path: str | None) -> dict[str, Any]:
    candidates = [Path(path)] if path else GOLDEN_PATH_CANDIDATES
    for candidate in candidates:
        if candidate and str(candidate) != "." and candidate.is_file():
            with candidate.open(encoding="utf-8") as fp:
                return json.load(fp)
    raise SystemExit("golden set 파일을 찾을 수 없습니다. --golden 경로를 지정하세요.")


def _normalize_prediction(entry: Any) -> dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError("prediction entry must be dict")
    axis_labels = entry.get("axis_labels")
    if not isinstance(axis_labels, dict):
        # {"세": [...], ...} 형태(축 키 직접 보유)도 허용
        axis_labels = {axis: entry.get(axis, []) for axis in AXIS_ORDER}
    labels = {axis: [str(v) for v in (axis_labels.get(axis) or [])] for axis in AXIS_ORDER}
    unmapped = [str(v) for v in (entry.get("unmapped_concepts") or [])]
    return {"axis_labels": labels, "unmapped_concepts": unmapped}


def _is_scorable(entry: Any) -> bool:
    # status가 명시돼 있고 ok가 아니면(timeout/error/missing 등) 미분석으로 취급해
    # 빈 예측을 recall 실패로 오집계하지 않는다.
    return not (isinstance(entry, dict) and entry.get("status") not in (None, "ok"))


def load_results_file(path: str) -> dict[int, dict[str, Any]]:
    with open(path, encoding="utf-8") as fp:
        raw = json.load(fp)
    results: dict[int, dict[str, Any]] = {}
    if isinstance(raw, list):
        for entry in raw:
            if not _is_scorable(entry):
                continue
            results[int(entry["product_id"])] = _normalize_prediction(entry)
    elif isinstance(raw, dict):
        for pid, entry in raw.items():
            if not _is_scorable(entry):
                continue
            results[int(pid)] = _normalize_prediction(entry)
    else:
        raise SystemExit("results 파일 포맷이 올바르지 않습니다(list 또는 dict).")
    return results


def load_results_db(product_ids: list[int]) -> dict[int, dict[str, Any]]:
    import pymysql  # 선택 의존성: --from-db에서만 필요

    conn = pymysql.connect(
        host=os.getenv("BATCH_DB_HOST", "127.0.0.1"),
        port=int(os.getenv("BATCH_DB_PORT", "13306")),
        user=os.getenv("BATCH_DB_USER", ""),
        password=os.getenv("BATCH_DB_PASSWORD", ""),
        database=os.getenv("BATCH_DB_NAME", "likenovel"),
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
    )
    placeholders = ",".join(["%s"] * len(product_ids))
    columns = ", ".join(DB_AXIS_COLUMNS.values())
    results: dict[int, dict[str, Any]] = {}
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT product_id, {columns}, protagonist_goal_primary, raw_analysis
                FROM tb_product_ai_metadata
                WHERE product_id IN ({placeholders})
                  AND analysis_status = 'success'
                """,
                product_ids,
            )
            for row in cur.fetchall():
                labels: dict[str, list[str]] = {}
                for axis, column in DB_AXIS_COLUMNS.items():
                    value = row.get(column)
                    labels[axis] = json.loads(value) if value else []
                goal = row.get("protagonist_goal_primary")
                labels["목"] = [goal] if goal else []
                unmapped: list[str] = []
                if row.get("raw_analysis"):
                    try:
                        raw_payload = json.loads(row["raw_analysis"])
                        unmapped = [str(v) for v in (raw_payload.get("unmapped_concepts") or [])]
                    except (json.JSONDecodeError, TypeError):
                        pass
                results[int(row["product_id"])] = {
                    "axis_labels": labels,
                    "unmapped_concepts": unmapped,
                }
    finally:
        conn.close()
    return results


def score_work(work: dict[str, Any], prediction: dict[str, Any]) -> dict[str, Any]:
    labels = prediction["axis_labels"]
    predicted_unmapped = prediction["unmapped_concepts"]

    expected_misses: list[str] = []
    expected_total = 0
    expected_found = 0
    for axis, wanted in (work.get("expected") or {}).items():
        for label in wanted:
            expected_total += 1
            if label in labels.get(axis, []):
                expected_found += 1
            else:
                expected_misses.append(f"[{axis}] {label}")

    any_misses: list[str] = []
    for axis, groups in (work.get("expected_any") or {}).items():
        for group in groups:
            expected_total += 1
            if any(label in labels.get(axis, []) for label in group):
                expected_found += 1
            else:
                any_misses.append(f"[{axis}] {'|'.join(group)}")

    forbidden_violations: list[str] = []
    for axis, banned in (work.get("forbidden") or {}).items():
        for label in banned:
            if label in labels.get(axis, []):
                forbidden_violations.append(f"[{axis}] {label}")

    strict_violations: list[str] = []
    for axis in work.get("strict_axes") or []:
        allowed = set((work.get("expected") or {}).get(axis, []))
        allowed.update((work.get("optional") or {}).get(axis, []))
        for group in (work.get("expected_any") or {}).get(axis, []):
            allowed.update(group)
        for label in labels.get(axis, []):
            if label not in allowed:
                strict_violations.append(f"[{axis}] {label}")

    unmapped_hits: list[str] = []
    unmapped_misses: list[str] = []
    # 공백/구두점 차이를 무시하고 부분일치(예: 기대 "재능거래" ↔ 출력 "재능 거래")
    def _squash(text: str) -> str:
        return "".join(ch for ch in text if not ch.isspace())

    squashed_predicted = [_squash(c) for c in predicted_unmapped]
    for concept in work.get("unmapped_expected") or []:
        needle = _squash(concept)
        if any(needle in cand or cand in needle for cand in squashed_predicted):
            unmapped_hits.append(concept)
        else:
            unmapped_misses.append(concept)

    return {
        "product_id": work["product_id"],
        "title": work["title"],
        "expected_total": expected_total,
        "expected_found": expected_found,
        "expected_misses": expected_misses + any_misses,
        "forbidden_violations": forbidden_violations,
        "strict_violations": strict_violations,
        "unmapped_hits": unmapped_hits,
        "unmapped_misses": unmapped_misses,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="골든셋 라벨 추출 평가 러너")
    parser.add_argument("--golden", help="golden-set JSON 경로")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--results", help="추출 결과 JSON 파일")
    source.add_argument("--from-db", action="store_true", help="tb_product_ai_metadata에서 읽기")
    parser.add_argument("--json", dest="json_out", help="리포트 JSON 저장 경로")
    parser.add_argument("--no-gate", action="store_true", help="violation이 있어도 종료 코드 0")
    args = parser.parse_args()

    golden = load_golden(args.golden)
    works = golden["works"]
    golden_ids = [work["product_id"] for work in works]

    if args.from_db:
        predictions = load_results_db(golden_ids)
    else:
        predictions = load_results_file(args.results)

    scored: list[dict[str, Any]] = []
    unanalyzed: list[int] = []
    for work in works:
        prediction = predictions.get(work["product_id"])
        if prediction is None:
            unanalyzed.append(work["product_id"])
            continue
        scored.append(score_work(work, prediction))

    expected_total = sum(item["expected_total"] for item in scored)
    expected_found = sum(item["expected_found"] for item in scored)
    forbidden_count = sum(len(item["forbidden_violations"]) for item in scored)
    strict_count = sum(len(item["strict_violations"]) for item in scored)
    unmapped_expected_total = sum(len(item["unmapped_hits"]) + len(item["unmapped_misses"]) for item in scored)
    unmapped_hit_count = sum(len(item["unmapped_hits"]) for item in scored)
    clean_works = sum(
        1
        for item in scored
        if not item["expected_misses"] and not item["forbidden_violations"] and not item["strict_violations"]
    )

    print(f"골든셋: {golden.get('version')} | 작품 {len(works)}개 (채점 {len(scored)} / 미분석 {len(unanalyzed)})")
    for item in scored:
        problems = []
        if item["expected_misses"]:
            problems.append(f"누락 {', '.join(item['expected_misses'])}")
        if item["forbidden_violations"]:
            problems.append(f"금지 {', '.join(item['forbidden_violations'])}")
        if item["strict_violations"]:
            problems.append(f"strict {', '.join(item['strict_violations'])}")
        if problems:
            print(f"  FAIL {item['product_id']} {item['title']}: {' | '.join(problems)}")
    if unanalyzed:
        print(f"  미분석: {unanalyzed}")

    recall = (expected_found / expected_total) if expected_total else 0.0
    print("--- 요약 ---")
    print(f"expected recall: {expected_found}/{expected_total} ({recall:.1%})")
    print(f"forbidden violations: {forbidden_count} (하드 게이트)")
    print(f"strict violations: {strict_count}")
    print(f"unmapped 검출: {unmapped_hit_count}/{unmapped_expected_total} (소프트 지표)")
    print(f"전 항목 통과 작품: {clean_works}/{len(scored)}")

    if args.json_out:
        report = {
            "golden_version": golden.get("version"),
            "summary": {
                "works_total": len(works),
                "works_scored": len(scored),
                "works_clean": clean_works,
                "unanalyzed": unanalyzed,
                "expected_total": expected_total,
                "expected_found": expected_found,
                "expected_recall": recall,
                "forbidden_violations": forbidden_count,
                "strict_violations": strict_count,
                "unmapped_hits": unmapped_hit_count,
                "unmapped_expected_total": unmapped_expected_total,
            },
            "works": scored,
        }
        with open(args.json_out, "w", encoding="utf-8") as fp:
            json.dump(report, fp, ensure_ascii=False, indent=1)
        print(f"리포트 저장: {args.json_out}")

    if not args.no_gate and (forbidden_count > 0 or strict_count > 0):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
