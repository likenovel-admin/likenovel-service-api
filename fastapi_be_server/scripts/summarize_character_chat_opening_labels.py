#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from run_character_chat_opening_labeler import derive_effective_readiness, validate_label_payload


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def classify_result_failure_reason(row: dict[str, Any]) -> str:
    status = str(row.get("status") or "missing").strip() or "missing"
    error_text = str(row.get("error") or row.get("parseError") or "")
    lower_error = error_text.lower()
    if status == "missing":
        return "missing"
    if status == "parse_error":
        return "parse_error"
    if "402 payment required" in lower_error:
        return "api_payment_required"
    if "call exceeded" in lower_error or "timed out" in lower_error or "timeout" in lower_error:
        return "timeout"
    if "expecting " in lower_error or "json" in lower_error:
        return "parse_error"
    return status


def merge_label_rows(
    *,
    input_rows: list[dict[str, Any]],
    result_rows: list[dict[str, Any]],
    limit: int = 0,
) -> list[dict[str, Any]]:
    latest_by_file: dict[str, dict[str, Any]] = {}
    for row in result_rows:
        file_name = str(row.get("fileName") or "").strip()
        if file_name:
            latest_by_file[file_name] = row

    selected: list[dict[str, Any]] = []
    source_rows = input_rows[:limit] if limit > 0 else input_rows
    for index, input_row in enumerate(source_rows):
        file_name = str(input_row.get("fileName") or "").strip()
        result = dict(latest_by_file.get(file_name) or {})
        if not result:
            result = {"fileName": file_name, "status": "missing"}
        result["inputIndex"] = index
        result["inputBucket"] = input_row.get("llmLabelingBucket")
        result["inputSplitConfidence"] = input_row.get("splitConfidence")
        if result.get("status") == "ok":
            schema_pass, schema_issues = validate_label_payload(result.get("label") or {})
            effective_status, effective_reasons = derive_effective_readiness(
                result.get("label") or {},
                schema_pass=schema_pass,
                schema_issues=schema_issues,
            )
            result["schemaPassCurrent"] = schema_pass
            result["schemaIssuesCurrent"] = schema_issues
            result["effectiveStatus"] = effective_status
            result["effectiveBlockReasons"] = effective_reasons
        else:
            result["schemaPassCurrent"] = False
            result["schemaIssuesCurrent"] = []
            result["effectiveStatus"] = "not_ready"
            result["effectiveBlockReasons"] = [classify_result_failure_reason(result)]
        selected.append(result)
    return selected


def summarize_rows(rows: list[dict[str, Any]]) -> dict[str, object]:
    status_counts: Counter[str] = Counter(str(row.get("status") or "missing") for row in rows)
    schema_counts: Counter[str] = Counter(
        "pass" if row.get("schemaPassCurrent") is True else "fail"
        for row in rows
        if row.get("status") == "ok"
    )
    readiness_counts: Counter[str] = Counter()
    effective_status_counts: Counter[str] = Counter(str(row.get("effectiveStatus") or "missing") for row in rows)
    user_role_counts: Counter[str] = Counter()
    hook_type_counts: Counter[str] = Counter()
    identity_mode_counts: Counter[str] = Counter()
    target_role_counts: Counter[str] = Counter()
    target_name_evidence_counts: Counter[str] = Counter()
    voice_evidence_counts: Counter[str] = Counter()
    scene_anchor_evidence_counts: Counter[str] = Counter()
    next_beats_count_buckets: Counter[str] = Counter()
    schema_issue_counts: Counter[str] = Counter()
    gate_failure_counts: Counter[str] = Counter()
    status_failure_counts: Counter[str] = Counter()
    target_counts: Counter[str] = Counter()
    for row in rows:
        if row.get("status") != "ok":
            status_failure_counts[classify_result_failure_reason(row)] += 1
        if row.get("effectiveStatus") != "ready":
            gate_reasons = [str(issue) for issue in _as_list(row.get("schemaIssuesCurrent"))]
            if not gate_reasons and row.get("status") != "ok":
                gate_reasons = [classify_result_failure_reason(row)]
            if not gate_reasons:
                gate_reasons = [f"model_{row.get('effectiveStatus') or 'not_ready'}"]
            gate_failure_counts.update(gate_reasons)
        if row.get("status") != "ok":
            continue
        label = _as_dict(row.get("label"))
        readiness = _as_dict(label.get("readiness"))
        work_opening = _as_dict(label.get("work_opening"))
        chat_target = _as_dict(label.get("chat_target"))
        identity_resolution = _as_dict(label.get("identity_resolution"))
        user_role = _as_dict(label.get("user_role"))
        evidence_quality = _as_dict(label.get("evidence_quality"))
        progression = _as_dict(label.get("progression"))
        readiness_counts[str(readiness.get("status") or "missing")] += 1
        user_role_counts[str(user_role.get("role_type") or "missing")] += 1
        hook_type_counts[str(work_opening.get("opening_hook_type") or "missing")] += 1
        identity_mode_counts[str(identity_resolution.get("identity_mode") or "missing")] += 1
        target_role_counts[str(chat_target.get("role") or "missing")] += 1
        target_name_evidence_counts[str(evidence_quality.get("target_name_evidence") or "missing")] += 1
        voice_evidence_counts[str(evidence_quality.get("voice_evidence") or "missing")] += 1
        scene_anchor_evidence_counts[str(evidence_quality.get("scene_anchor_evidence") or "missing")] += 1
        next_beats_len = len(_as_list(progression.get("next_beats")))
        next_beats_count_buckets[str(min(next_beats_len, 4)) if next_beats_len < 4 else "4+"] += 1
        schema_issue_counts.update(str(issue) for issue in _as_list(row.get("schemaIssuesCurrent")))
        target = str(chat_target.get("display_name") or "").strip()
        if target:
            target_counts[target] += 1

    usable_count = sum(1 for row in rows if row.get("status") == "ok" and row.get("effectiveStatus") == "ready")
    return {
        "rowCount": len(rows),
        "statusCounts": dict(sorted(status_counts.items())),
        "schemaPassCurrentCounts": dict(sorted(schema_counts.items())),
        "readinessCounts": dict(sorted(readiness_counts.items())),
        "effectiveStatusCounts": dict(sorted(effective_status_counts.items())),
        "userRoleCounts": dict(sorted(user_role_counts.items())),
        "openingHookTypeCounts": dict(sorted(hook_type_counts.items())),
        "identityModeCounts": dict(sorted(identity_mode_counts.items())),
        "targetRoleCounts": dict(sorted(target_role_counts.items())),
        "targetNameEvidenceCounts": dict(sorted(target_name_evidence_counts.items())),
        "voiceEvidenceCounts": dict(sorted(voice_evidence_counts.items())),
        "sceneAnchorEvidenceCounts": dict(sorted(scene_anchor_evidence_counts.items())),
        "nextBeatsCountBuckets": dict(sorted(next_beats_count_buckets.items())),
        "schemaIssueCounts": dict(sorted(schema_issue_counts.items())),
        "gateFailureReasonCounts": dict(sorted(gate_failure_counts.items())),
        "statusFailureReasonCounts": dict(sorted(status_failure_counts.items())),
        "duplicateTargetCounts": {
            key: count for key, count in sorted(target_counts.items()) if count > 1
        },
        "readyAndSchemaPassCount": sum(
            1
            for row in rows
            if row.get("status") == "ok"
            and row.get("schemaPassCurrent") is True
            and ((row.get("label") or {}).get("readiness") or {}).get("status") == "ready"
        ),
        "usableCount": usable_count,
        "usableRate": round(usable_count / len(rows), 4) if rows else 0,
        "notUsableCount": sum(
            1
            for row in rows
            if row.get("status") != "ok" or row.get("effectiveStatus") != "ready"
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="캐릭터챗 opening label 결과 병합/검증")
    parser.add_argument("--input", required=True, help="라벨 입력 JSONL")
    parser.add_argument("--results", action="append", required=True, help="라벨 결과 JSONL. 여러 번 지정 가능")
    parser.add_argument("--out", default="", help="현재 선택된 row JSONL 저장 경로")
    parser.add_argument("--summary-out", default="", help="summary JSON 저장 경로")
    parser.add_argument("--limit", type=int, default=0)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_rows = load_jsonl(Path(args.input))
    result_rows: list[dict[str, Any]] = []
    for path_value in args.results:
        result_rows.extend(load_jsonl(Path(path_value)))
    selected = merge_label_rows(input_rows=input_rows, result_rows=result_rows, limit=args.limit)
    summary = summarize_rows(selected)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            "\n".join(json.dumps(row, ensure_ascii=False) for row in selected) + ("\n" if selected else ""),
            encoding="utf-8",
        )
        summary["out"] = str(out_path)
    if args.summary_out:
        summary_path = Path(args.summary_out)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
        summary["summaryOut"] = str(summary_path)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
