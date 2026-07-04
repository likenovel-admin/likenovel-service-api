#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import zipfile
from pathlib import Path
from typing import Iterable

from audit_character_chat_opening_corpus import (
    DEFAULT_MAX_READ_BYTES,
    DEFAULT_MIN_SECTION_CHARS,
    decode_novel_bytes,
    extract_opening_episodes,
)


DEFAULT_MAX_EPISODE_CHARS = 12_000


def load_manifest_rows(
    manifest_path: Path,
    *,
    buckets: set[str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if str(row.get("llmLabelingBucket") or "") in buckets:
            rows.append(row)
    return rows


def _clip_text(value: str, *, max_chars: int) -> tuple[str, bool]:
    text = value.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return text, False
    return text[:max_chars].rstrip(), True


def dumps_jsonl(row: dict[str, object]) -> str:
    return (
        json.dumps(row, ensure_ascii=False)
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def build_label_input_rows(
    *,
    zip_path: Path,
    manifest_rows: Iterable[dict[str, object]],
    max_items: int,
    max_episode_chars: int,
    min_section_chars: int = DEFAULT_MIN_SECTION_CHARS,
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    rows: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    manifest_list = list(manifest_rows)
    if max_items > 0:
        manifest_list = manifest_list[:max_items]

    with zipfile.ZipFile(zip_path) as archive:
        zip_names = set(archive.namelist())
        for manifest_row in manifest_list:
            file_name = str(manifest_row.get("fileName") or "")
            if file_name not in zip_names:
                skipped.append({"fileName": file_name, "reason": "missing_zip_entry"})
                continue
            with archive.open(file_name) as novel_file:
                raw = novel_file.read(max_read_bytes if max_read_bytes > 0 else -1)
            text, encoding = decode_novel_bytes(raw)
            openings, _headers = extract_opening_episodes(
                text,
                min_section_chars=min_section_chars,
            )
            if [item.episode_no for item in openings[:3]] != [1, 2, 3]:
                skipped.append({"fileName": file_name, "reason": "opening_extraction_mismatch"})
                continue

            episode_payloads: list[dict[str, object]] = []
            for opening in openings[:3]:
                episode_text, truncated = _clip_text(
                    text[opening.start_offset : opening.end_offset],
                    max_chars=max_episode_chars,
                )
                episode_payloads.append(
                    {
                        "episodeNo": opening.episode_no,
                        "title": opening.title,
                        "headerPattern": opening.header_pattern,
                        "textChars": opening.text_chars,
                        "labelText": episode_text,
                        "labelTextTruncated": truncated,
                    }
                )

            rows.append(
                {
                    "fileName": file_name,
                    "encoding": encoding,
                    "sourceZip": str(zip_path),
                    "llmLabelingBucket": manifest_row.get("llmLabelingBucket"),
                    "splitConfidence": manifest_row.get("splitConfidence"),
                    "openingQuality": manifest_row.get("openingQuality"),
                    "openingTextChars": manifest_row.get("openingTextChars"),
                    "episodes": episode_payloads,
                }
            )
    return rows, skipped


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="캐릭터챗 opening label input JSONL 생성")
    parser.add_argument("--zip", required=True, dest="zip_path", help="웹소설 txt zip 경로")
    parser.add_argument("--manifest", required=True, dest="manifest_path", help="audit manifest JSONL 경로")
    parser.add_argument("--out", required=True, help="원문 포함 라벨 입력 JSONL 저장 경로")
    parser.add_argument("--bucket", action="append", default=["main"], help="대상 llmLabelingBucket")
    parser.add_argument("--max-items", type=int, default=0, help="0이면 전체")
    parser.add_argument("--max-episode-chars", type=int, default=DEFAULT_MAX_EPISODE_CHARS)
    parser.add_argument("--min-section-chars", type=int, default=DEFAULT_MIN_SECTION_CHARS)
    parser.add_argument("--max-read-bytes", type=int, default=DEFAULT_MAX_READ_BYTES)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    manifest_rows = load_manifest_rows(Path(args.manifest_path), buckets=set(args.bucket))
    rows, skipped = build_label_input_rows(
        zip_path=Path(args.zip_path),
        manifest_rows=manifest_rows,
        max_items=args.max_items,
        max_episode_chars=args.max_episode_chars,
        min_section_chars=args.min_section_chars,
        max_read_bytes=args.max_read_bytes,
    )
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        "\n".join(dumps_jsonl(row) for row in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "out": str(out_path),
                "manifestRows": len(manifest_rows),
                "writtenRows": len(rows),
                "skippedRows": len(skipped),
                "skipped": skipped[:20],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
