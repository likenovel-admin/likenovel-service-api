#!/usr/bin/env python3
"""검증된 dump-full JSON을 tb_product_ai_metadata에 적재(백필)한다.

eval_extract_run.py --dump-full 산출물의 dna/parsed를 그대로 save_dna로 적재하므로
LLM 재호출이 없다. 적재 전 대상 product_id의 기존 행 전체를 JSON으로 백업한다.

기본은 dry-run(백업 + 적재 대상 카운트만). 실제 write는 --apply 필요.
model_version은 실행 시점 env로 결정된 CURRENT_ANALYSIS_VERSION이 기록되므로,
v4-pro env(AI_DNA_OPENROUTER_MODEL 등)를 export한 뒤 실행해야 한다.

사용:
  python3 backfill_ai_dna_from_json.py --input /tmp/eval_v4pro_backfill.json            # dry-run
  python3 backfill_ai_dna_from_json.py --input /tmp/eval_v4pro_backfill.json --apply     # 실제 적재
"""

from __future__ import annotations

import argparse
import datetime
import importlib.util
import json
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).resolve().parent.parent / "dist" / "batch" / "extract_product_dna.py"


def load_module():
    spec = importlib.util.spec_from_file_location("extract_product_dna_batch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description="dump-full JSON → tb_product_ai_metadata 백필")
    parser.add_argument("--input", required=True, help="eval_extract_run --dump-full 산출 JSON")
    parser.add_argument("--apply", action="store_true", help="실제 DB write 수행(미지정 시 dry-run)")
    parser.add_argument("--backup-dir", default="/tmp", help="백업 JSON 저장 디렉토리")
    args = parser.parse_args()

    module = load_module()
    records = json.load(open(args.input, encoding="utf-8"))
    ok = [r for r in records if r.get("status") == "ok" and "dna" in r and "parsed" in r]
    ids = [int(r["product_id"]) for r in ok]
    if not ids:
        raise SystemExit("적재 대상(status=ok + dna/parsed)이 없습니다.")

    conn = module.db_connect()
    print(f"[OK] DB 연결 {module.DB_HOST}:{module.DB_PORT}")
    print(f"[INFO] model_version(기록될 값) = {module.CURRENT_ANALYSIS_VERSION}")
    print(f"[INFO] 적재 대상: {len(ids)}개 작품")

    # 1) 백업 — 대상 product_id의 기존 행 전체
    placeholders = ",".join(["%s"] * len(ids))
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM tb_product_ai_metadata WHERE product_id IN ({placeholders})",
            ids,
        )
        backup_rows = cur.fetchall()
    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path(args.backup_dir) / f"metadata_backup_{ts}.json"
    with backup_path.open("w", encoding="utf-8") as fp:
        json.dump(backup_rows, fp, ensure_ascii=False, indent=1, default=str)
    print(f"[백업] 기존 {len(backup_rows)}행 → {backup_path} (롤백용)")

    if not args.apply:
        print(f"[DRY-RUN] 적재 미수행. 실제 적재하려면 --apply 추가.")
        conn.close()
        return 0

    # 2) 적재 — save_dna(upsert) 재사용, LLM 재호출 없음
    n = 0
    fail: list[tuple[int, str]] = []
    for r in ok:
        pid = int(r["product_id"])
        try:
            module.save_dna(conn, pid, r["dna"], r["parsed"], 1)
            n += 1
        except Exception as exc:  # 한 건 실패가 전체를 멈추지 않게
            fail.append((pid, str(exc)[:160]))
            print(f"[FAIL] {pid}: {str(exc)[:160]}")
    conn.close()
    print(f"\n[적재 완료] 성공 {n}/{len(ok)}건, 실패 {len(fail)}건")
    if fail:
        print("실패 목록:", fail)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
