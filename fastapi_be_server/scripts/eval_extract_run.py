#!/usr/bin/env python3
"""골든셋 작품을 비파괴(read-only)로 추출해 채점용 JSON을 만든다.

extract_product_dna.py의 analyze_product/normalize_payload를 그대로 재사용하되,
DB에는 한 줄도 쓰지 않는다(save_dna 미호출). 회차 본문은 read-only 세션으로 SELECT만 한다.
출력 JSON은 eval_golden_set.py --results 로 채점한다.

전제 env(셸에서 미리 export):
  AI_DNA_PROVIDER=openrouter
  OPENROUTER_API_KEY=...           (값은 출력하지 않는다)
  AI_DNA_OPENROUTER_MODEL=deepseek/deepseek-v3.2
  BATCH_DB_HOST / BATCH_DB_PORT / BATCH_DB_USER / BATCH_DB_PASSWORD / BATCH_DB_NAME

사용법:
  python3 eval_extract_run.py --output results.json
  python3 eval_extract_run.py --output smoke.json --product-ids 1106
  python3 eval_extract_run.py --output smoke.json --limit 3
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any

MODULE_PATH = Path(__file__).resolve().parent.parent / "dist" / "batch" / "extract_product_dna.py"
GOLDEN_PATH_CANDIDATES = [
    Path(__file__).resolve().parents[4] / "docs" / "ai-codebook" / "golden-set-v1.json",
    Path(__file__).resolve().parents[1] / "dist" / "ai" / "golden-set-v1.json",
]

# dna(컬럼형 키) → 축 그룹 키. save_dna 계약과 동일.
AXIS_FROM_DNA = {
    "세": "worldview_tags",
    "직": "protagonist_job_tags",
    "능": "protagonist_material_tags",
    "연": "axis_romance_tags",
    "작": "axis_style_tags",
    "타": "protagonist_type_tags",
}


def load_module():
    spec = importlib.util.spec_from_file_location("extract_product_dna_batch", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def load_golden(path: str | None) -> dict[str, Any]:
    candidates = [Path(path)] if path else GOLDEN_PATH_CANDIDATES
    for candidate in candidates:
        if candidate and candidate.is_file():
            with candidate.open(encoding="utf-8") as fp:
                return json.load(fp)
    raise SystemExit("golden set 파일을 찾을 수 없습니다. --golden 경로를 지정하세요.")


def dna_to_axis_labels(module, dna: dict[str, Any]) -> dict[str, list[str]]:
    labels = {axis: list(dna.get(column) or []) for axis, column in AXIS_FROM_DNA.items()}
    goal = dna.get("protagonist_goal_primary")
    labels["목"] = [goal] if goal else []
    return labels


def main() -> int:
    parser = argparse.ArgumentParser(description="골든셋 비파괴 추출 러너 (DB write 없음)")
    parser.add_argument("--golden", help="golden-set JSON 경로")
    parser.add_argument("--output", required=True, help="추출 결과 JSON 저장 경로")
    parser.add_argument("--product-ids", help="쉼표구분 product_id만 추출(스모크용)")
    parser.add_argument("--limit", type=int, help="앞에서 N개만 추출(스모크용)")
    parser.add_argument("--sleep", type=float, default=1.0, help="작품 간 대기(초)")
    parser.add_argument(
        "--call-timeout",
        type=float,
        default=180.0,
        help="작품별 wall-clock 상한(초). OpenRouter 적체 시 무한 hang 차단",
    )
    parser.add_argument(
        "--head-episodes",
        type=int,
        default=0,
        help="앞에서 N화만 컨텍스트에 사용(1~2화 집중 실험용). 0이면 배치 기본(전체)",
    )
    parser.add_argument(
        "--deepseek-model",
        help="지정 시 DeepSeek 공식 API로 직접 호출(예: deepseek-v4-pro). "
        "anthropic→deepseek fallback 경로를 타며 OpenRouter를 우회. DEEPSEEK_API_KEY 필요",
    )
    parser.add_argument(
        "--dump-full",
        action="store_true",
        help="결과에 dna 전 컬럼 + parsed를 함께 저장(검증 후 LLM 재호출 없이 DB 백필용)",
    )
    parser.add_argument(
        "--all-products",
        action="store_true",
        help="골든셋 대신 prod 전체 공개작(get_products force)을 대상으로 추출 — DB 백필용",
    )
    args = parser.parse_args()

    module = load_module()
    golden = load_golden(args.golden)
    if args.all_products:
        ids = None  # conn 생성 후 get_products로 결정
    else:
        if args.product_ids:
            # 명시 id는 골든셋 밖(백필 대상)도 그대로 허용
            ids = [int(x) for x in args.product_ids.split(",") if x.strip()]
        else:
            ids = [int(w["product_id"]) for w in golden["works"]]
        if args.limit:
            ids = ids[: args.limit]

    allowed_labels = module.load_allowed_labels()
    if args.deepseek_model:
        # DeepSeek 공식 API 직접 호출 모드(모델 업그레이드 실험용).
        # call_claude를 빈 키로 즉시 raise시켜 call_deepseek(fallback) 경로로 보낸다.
        # 라이브 배치 코드는 무수정, 실험 러너에서 module 전역만 덮어쓴다.
        import os as _os
        if not _os.environ.get("DEEPSEEK_API_KEY"):
            raise SystemExit("DEEPSEEK_API_KEY 환경변수가 필요합니다(--deepseek-model 모드).")
        module.AI_DNA_PROVIDER = "anthropic"
        module.ANTHROPIC_API_KEY = ""
        module.DEEPSEEK_API_KEY = _os.environ["DEEPSEEK_API_KEY"]
        module.AI_DNA_DEEPSEEK_FALLBACK_MODEL = args.deepseek_model
        print(f"[INFO] DeepSeek 직접 호출 모드: model={args.deepseek_model}, base={module.DEEPSEEK_BASE_URL}")
    else:
        module._validate_runtime_config(allowed_labels)  # OPENROUTER_API_KEY 등 누락 시 즉시 실패

    conn = module.db_connect()
    with conn.cursor() as cur:
        cur.execute("SET SESSION TRANSACTION READ ONLY")  # write 방지 가드
    if ids is None:  # --all-products: prod 전체 공개작 id 확보
        all_prods = module.get_products(conn, None, force=True)
        ids = [int(p["product_id"]) for p in all_prods]
        if args.limit:
            ids = ids[: args.limit]
    print(f"[OK] DB 연결(read-only) {module.DB_HOST}:{module.DB_PORT}")
    print(f"[INFO] provider={module.AI_DNA_PROVIDER}, version={module.CURRENT_ANALYSIS_VERSION}")
    print(f"[INFO] 추출 대상: {len(ids)}개 작품 (DB write 없음)")

    results: list[dict[str, Any]] = []
    ok = 0
    fail = 0
    # 데몬 스레드 1개로 analyze_product를 감싸 wall-clock 상한을 건다.
    # OpenRouter가 적체 공급자(friendli) 대기 중 keep-alive를 보내면 httpx read 타임아웃이
    # 계속 리셋되어 단일 호출이 무한 대기할 수 있다. 타임아웃 시 해당 스레드는 누수되지만
    # 메인 루프는 다음 작품으로 진행한다(평가 런이라 허용 가능한 트레이드오프).
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        for i, pid in enumerate(ids, 1):
            products = module.get_products(conn, pid, force=True)
            if not products:
                fail += 1
                results.append({"product_id": pid, "status": "missing", "error": "product not found / not open"})
                print(f"[{i}/{len(ids)}] {pid}: MISSING", flush=True)
                continue

            product = products[0]
            title = product.get("title", "")
            episodes = module.get_episodes(conn, pid)
            if args.head_episodes and args.head_episodes > 0:
                episodes = episodes[: args.head_episodes]
            episode_context, used_count = module._build_episode_context(episodes)
            min_required = module.MIN_REQUIRED_EPISODES
            if args.head_episodes and args.head_episodes > 0:
                min_required = min(min_required, args.head_episodes)
            if used_count < min_required:
                fail += 1
                results.append({"product_id": pid, "status": "insufficient_episodes", "used_episodes": used_count})
                print(f"[{i}/{len(ids)}] {pid} {title}: SKIP (episodes={used_count})", flush=True)
                continue

            started = time.monotonic()
            future = executor.submit(
                module.analyze_product, product, allowed_labels, episode_context, used_count
            )
            try:
                dna, parsed = future.result(timeout=args.call_timeout)
            except FutureTimeoutError:
                fail += 1
                results.append({"product_id": pid, "status": "timeout", "error": f">{args.call_timeout}s"})
                print(f"[{i}/{len(ids)}] {pid} {title}: TIMEOUT (>{args.call_timeout}s)", flush=True)
                continue
            except Exception as exc:  # 한 작품 실패가 전체 런을 멈추지 않게
                fail += 1
                results.append({"product_id": pid, "status": "error", "error": str(exc)[:300]})
                print(f"[{i}/{len(ids)}] {pid} {title}: FAIL {str(exc)[:120]}", flush=True)
                continue

            ok += 1
            record = {
                "product_id": pid,
                "title": title,
                "status": "ok",
                "axis_labels": dna_to_axis_labels(module, dna),
                "unmapped_concepts": list(dna.get("unmapped_concepts") or []),
                "used_episodes": used_count,
            }
            if args.dump_full:
                # 채점 통과 시 LLM 재호출 없이 save_dna로 적재하기 위한 원본 보존
                record["dna"] = dna
                record["parsed"] = parsed
            results.append(record)
            # 장시간 단일 실행(백필 전수) 중 터널 끊김 대비 증분 저장
            with open(args.output, "w", encoding="utf-8") as fp:
                json.dump(results, fp, ensure_ascii=False, indent=1, default=str)
            print(f"[{i}/{len(ids)}] {pid} {title}: OK ({time.monotonic() - started:.0f}s)", flush=True)
            time.sleep(args.sleep)
    finally:
        executor.shutdown(wait=False)
        conn.close()

    with open(args.output, "w", encoding="utf-8") as fp:
        json.dump(results, fp, ensure_ascii=False, indent=1, default=str)
    print(f"\n[DONE] ok={ok}, fail={fail} → {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
