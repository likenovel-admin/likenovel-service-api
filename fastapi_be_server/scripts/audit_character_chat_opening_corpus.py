#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_MIN_SECTION_CHARS = 700
DEFAULT_MAX_HEADER_LEN = 120
DEFAULT_MAX_READ_BYTES = 2_000_000
MIN_READY_EPISODE_CHARS = 1_000
MAX_READY_EPISODE_CHARS = 60_000
MAX_READY_EPISODE_LENGTH_RATIO = 8.0
DENSE_HEADER_COUNT = 80
DENSE_HEADER_PER_100K = 4.0


@dataclass(frozen=True)
class ChapterHeader:
    episode_no: int
    line_no: int
    char_offset: int
    pattern: str
    title: str
    raw: str
    priority: int


@dataclass(frozen=True)
class OpeningEpisode:
    episode_no: int
    title: str
    start_offset: int
    end_offset: int
    header_pattern: str
    text_chars: int


def decode_novel_bytes(raw: bytes) -> tuple[str, str]:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace"), "utf-16-bom"
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace"), "utf-8-sig"
    if raw[:2000].count(b"\x00") > 100:
        return raw.decode("utf-16", errors="replace"), "utf-16-null"

    candidates: list[tuple[int, int, str, str]] = []
    for encoding in ("utf-8", "cp949", "euc-kr"):
        text = raw.decode(encoding, errors="replace")
        replacement_count = text.count("\ufffd")
        korean_count = sum(1 for char in text[:20000] if "가" <= char <= "힣")
        candidates.append((replacement_count, -korean_count, encoding, text))
    _, _, encoding, text = sorted(candidates)[0]
    return text, encoding


def _iter_nonempty_lines_with_offsets(text: str) -> Iterable[tuple[int, int, str, str | None]]:
    offset = 0
    previous_nonempty: str | None = None
    for line_no, raw_line in enumerate(text.splitlines(keepends=True), 1):
        stripped = raw_line.strip()
        if stripped:
            yield line_no, offset, stripped, previous_nonempty
            previous_nonempty = stripped
        offset += len(raw_line)


def _next_nonempty_line(lines: list[tuple[int, int, str, str | None]], index: int) -> str:
    for _, _, stripped, _ in lines[index + 1 : index + 4]:
        if stripped:
            return stripped
    return ""


def _normalize_header_title(value: str) -> str:
    title = re.sub(r"\s+", " ", str(value or "").strip())
    title = re.sub(r"^[.\-–—:：|>\])\s]+", "", title)
    title = re.sub(r"\s*[<\[(]\s*$", "", title)
    return title[:80]


def _append_header(
    headers: list[ChapterHeader],
    *,
    episode_no: int,
    line_no: int,
    char_offset: int,
    pattern: str,
    title: str,
    raw: str,
    priority: int,
) -> None:
    if episode_no <= 0 or episode_no > 3000:
        return
    headers.append(
        ChapterHeader(
            episode_no=episode_no,
            line_no=line_no,
            char_offset=char_offset,
            pattern=pattern,
            title=_normalize_header_title(title),
            raw=raw[:DEFAULT_MAX_HEADER_LEN],
            priority=priority,
        )
    )


def find_chapter_headers(text: str) -> list[ChapterHeader]:
    lines = list(_iter_nonempty_lines_with_offsets(text))
    headers: list[ChapterHeader] = []
    for index, (line_no, char_offset, stripped, previous_nonempty) in enumerate(lines):
        if len(stripped) > DEFAULT_MAX_HEADER_LEN:
            continue

        match = re.fullmatch(r"<\s*(?:프롤로그\s*\+\s*)?(?P<no>\d{1,4})\s*화(?P<title>.*?)>", stripped)
        if match:
            _append_header(
                headers,
                episode_no=int(match.group("no")),
                line_no=line_no,
                char_offset=char_offset,
                pattern="angle_nhwa",
                title=match.group("title"),
                raw=stripped,
                priority=0,
            )
            continue

        match = re.fullmatch(r"제\s*(?P<no>\d{1,4})\s*화[.\s]*(?P<title>.*)", stripped)
        if match:
            _append_header(
                headers,
                episode_no=int(match.group("no")),
                line_no=line_no,
                char_offset=char_offset,
                pattern="je_nhwa",
                title=match.group("title"),
                raw=stripped,
                priority=1,
            )
            continue

        match = re.fullmatch(r"\[?\s*(?P<no>\d{1,4})\s*화[.\s\]]*(?P<title>.*)", stripped)
        if match:
            _append_header(
                headers,
                episode_no=int(match.group("no")),
                line_no=line_no,
                char_offset=char_offset,
                pattern="n_hwa",
                title=match.group("title"),
                raw=stripped,
                priority=2,
            )
            continue

        match = re.fullmatch(r"(?P<title>.+?)\s*[\[(]?\s*(?P<no>\d{1,4})\s*[\])]?\s*화", stripped)
        if match and len(match.group("title").strip()) <= 55:
            prefix = match.group("title").strip()
            if prefix and not re.search(r"(총|완결|목차|권|회차|출판|작품\s*소개)", prefix):
                _append_header(
                    headers,
                    episode_no=int(match.group("no")),
                    line_no=line_no,
                    char_offset=char_offset,
                    pattern="title_nhwa",
                    title=prefix,
                    raw=stripped,
                    priority=3,
                )
                continue

        match = re.fullmatch(r"(?P<no>\d{1,4})", stripped)
        next_line = _next_nonempty_line(lines, index)
        if match and next_line and len(next_line) <= 80:
            if not re.fullmatch(r"\d{1,4}", str(previous_nonempty or "")):
                _append_header(
                    headers,
                    episode_no=int(match.group("no")),
                    line_no=line_no,
                    char_offset=char_offset,
                    pattern="number_line",
                    title=next_line,
                    raw=f"{stripped} {next_line}",
                    priority=4,
                )
                continue

        match = re.fullmatch(r"(?P<no>\d{1,4})[.)]\s+(?P<title>[^.].{0,80})", stripped)
        if match:
            _append_header(
                headers,
                episode_no=int(match.group("no")),
                line_no=line_no,
                char_offset=char_offset,
                pattern="number_dot",
                title=match.group("title"),
                raw=stripped,
                priority=5,
            )
    return _dedupe_nearby_headers(headers)


def _dedupe_nearby_headers(headers: list[ChapterHeader]) -> list[ChapterHeader]:
    selected: list[ChapterHeader] = []
    for header in sorted(headers, key=lambda item: (item.char_offset, item.priority)):
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(selected)
                if existing.episode_no == header.episode_no
                and abs(existing.char_offset - header.char_offset) < 80
            ),
            None,
        )
        if duplicate_index is None:
            selected.append(header)
            continue
        existing = selected[duplicate_index]
        if (header.priority, len(header.raw)) < (existing.priority, len(existing.raw)):
            selected[duplicate_index] = header
    return sorted(selected, key=lambda item: item.char_offset)


def _has_plausible_section_gap(
    headers: list[ChapterHeader],
    *,
    min_section_chars: int,
) -> bool:
    return all(
        right.char_offset - left.char_offset >= min_section_chars
        for left, right in zip(headers, headers[1:])
    )


def _has_intervening_opening_duplicate(
    all_headers: list[ChapterHeader],
    selected: list[ChapterHeader],
) -> bool:
    for left, right in zip(selected, selected[1:]):
        for header in all_headers:
            if header.char_offset <= left.char_offset or header.char_offset >= right.char_offset:
                continue
            if (
                left.episode_no < header.episode_no <= right.episode_no
                and header.pattern != "number_dot"
            ):
                return True
    return False


def select_opening_headers(
    headers: list[ChapterHeader],
    *,
    min_section_chars: int = DEFAULT_MIN_SECTION_CHARS,
) -> list[ChapterHeader]:
    by_episode_all: dict[int, list[ChapterHeader]] = {}
    for header in headers:
        if header.episode_no in {1, 2, 3, 4}:
            by_episode_all.setdefault(header.episode_no, []).append(header)

    by_episode: dict[int, list[ChapterHeader]] = {}
    for episode_no, candidates in by_episode_all.items():
        strong_candidates = [header for header in candidates if header.pattern != "number_dot"]
        selected_candidates = strong_candidates or candidates
        by_episode[episode_no] = sorted(
            selected_candidates,
            key=lambda item: (item.char_offset, item.priority),
        )[:200]

    best: list[ChapterHeader] = []
    best_score: tuple[int, int, int, int] | None = None
    for first in by_episode.get(1, []):
        for second in by_episode.get(2, []):
            if second.char_offset <= first.char_offset:
                continue
            for third in by_episode.get(3, []):
                if third.char_offset <= second.char_offset:
                    continue
                candidate = [first, second, third]
                if not _has_plausible_section_gap(candidate, min_section_chars=min_section_chars):
                    continue
                if _has_intervening_opening_duplicate(headers, candidate):
                    continue
                score = (
                    sum(item.priority for item in candidate),
                    first.char_offset,
                    -(second.char_offset - first.char_offset),
                    -(third.char_offset - second.char_offset),
                )
                if best_score is None or score < best_score:
                    best = candidate
                    best_score = score
    if best:
        return best

    for first in by_episode.get(1, []):
        for second in by_episode.get(2, []):
            if second.char_offset <= first.char_offset:
                continue
            candidate = [first, second]
            if not _has_plausible_section_gap(candidate, min_section_chars=min_section_chars):
                continue
            if _has_intervening_opening_duplicate(headers, candidate):
                continue
            return candidate
    return by_episode.get(1, [])[:1]


def extract_opening_episodes(
    text: str,
    *,
    max_episodes: int = 3,
    min_section_chars: int = DEFAULT_MIN_SECTION_CHARS,
) -> tuple[list[OpeningEpisode], list[ChapterHeader]]:
    headers = find_chapter_headers(text)
    selected = select_opening_headers(headers, min_section_chars=min_section_chars)
    if not selected:
        return [], headers

    next_headers = [header for header in headers if header.char_offset > selected[-1].char_offset]
    boundary_after_last = next_headers[0].char_offset if next_headers else len(text)
    openings: list[OpeningEpisode] = []
    for index, header in enumerate(selected[:max_episodes]):
        next_offset = (
            selected[index + 1].char_offset
            if index + 1 < len(selected)
            else boundary_after_last
        )
        body_start = header.char_offset + len(header.raw)
        text_chars = max(next_offset - body_start, 0)
        openings.append(
            OpeningEpisode(
                episode_no=header.episode_no,
                title=header.title,
                start_offset=header.char_offset,
                end_offset=next_offset,
                header_pattern=header.pattern,
                text_chars=text_chars,
            )
        )
    return openings, headers


def classify_opening_quality(openings: list[OpeningEpisode]) -> str:
    episode_nos = [item.episode_no for item in openings]
    if episode_nos[:3] == [1, 2, 3]:
        return "first3_detected"
    if episode_nos[:2] == [1, 2]:
        return "partial_first3"
    if episode_nos[:1] == [1]:
        return "episode1_only"
    return "no_headers"


def build_split_diagnostics(
    openings: list[OpeningEpisode],
    *,
    quality: str,
    header_count: int,
    analyzed_text_chars: int,
    file_size: int,
    read_bytes: int,
) -> dict[str, object]:
    text_lengths = [item.text_chars for item in openings]
    patterns = [item.header_pattern for item in openings]
    length_outlier_flags: list[str] = []
    for item in openings:
        if item.text_chars < MIN_READY_EPISODE_CHARS:
            length_outlier_flags.append(f"episode_{item.episode_no}_too_short")
        if item.text_chars > MAX_READY_EPISODE_CHARS:
            length_outlier_flags.append(f"episode_{item.episode_no}_too_long")

    positive_lengths = [max(length, 1) for length in text_lengths]
    length_variance_outlier = False
    if len(positive_lengths) >= 3:
        length_ratio = max(positive_lengths) / min(positive_lengths)
        length_variance_outlier = (
            length_ratio > MAX_READY_EPISODE_LENGTH_RATIO
            and max(positive_lengths) > MAX_READY_EPISODE_CHARS / 2
        )
        if length_variance_outlier:
            length_outlier_flags.append("episode_length_variance")

    third_episode_too_short = len(openings) >= 3 and openings[2].text_chars < MIN_READY_EPISODE_CHARS
    number_dot_present = "number_dot" in patterns
    number_dot_only = bool(patterns) and all(pattern == "number_dot" for pattern in patterns)
    header_density_per_100k = round(header_count / max(analyzed_text_chars / 100_000, 1), 2)
    dense_headers = (
        header_count >= DENSE_HEADER_COUNT
        and header_density_per_100k >= DENSE_HEADER_PER_100K
    )
    read_window_truncated = read_bytes > 0 and file_size > read_bytes

    if quality != "first3_detected":
        split_confidence = "fail"
    elif length_outlier_flags:
        split_confidence = "suspect"
    elif number_dot_present:
        split_confidence = "medium"
    else:
        split_confidence = "high"

    if split_confidence == "high":
        llm_labeling_bucket = "main"
    elif split_confidence == "medium":
        llm_labeling_bucket = "review"
    else:
        llm_labeling_bucket = "blocked"

    return {
        "splitConfidence": split_confidence,
        "readyForLLMLabeling": split_confidence in {"high", "medium"},
        "llmLabelingBucket": llm_labeling_bucket,
        "lengthOutlierFlags": length_outlier_flags,
        "thirdEpisodeTooShort": third_episode_too_short,
        "numberDotPresent": number_dot_present,
        "numberDotOnly": number_dot_only,
        "denseHeaders": dense_headers,
        "headerDensityPer100k": header_density_per_100k,
        "readWindowTruncated": read_window_truncated,
        "lengthVarianceOutlier": length_variance_outlier,
    }


def audit_zip(
    zip_path: Path,
    *,
    min_section_chars: int = DEFAULT_MIN_SECTION_CHARS,
    max_read_bytes: int = DEFAULT_MAX_READ_BYTES,
) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    encoding_counts: Counter[str] = Counter()
    quality_counts: Counter[str] = Counter()
    pattern_counts: Counter[str] = Counter()
    confidence_counts: Counter[str] = Counter()
    llm_bucket_counts: Counter[str] = Counter()
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            if info.is_dir() or not info.filename.lower().endswith(".txt"):
                continue
            with archive.open(info) as novel_file:
                raw = novel_file.read(max_read_bytes if max_read_bytes > 0 else -1)
            text, encoding = decode_novel_bytes(raw)
            openings, headers = extract_opening_episodes(
                text,
                min_section_chars=min_section_chars,
            )
            quality = classify_opening_quality(openings)
            diagnostics = build_split_diagnostics(
                openings,
                quality=quality,
                header_count=len(headers),
                analyzed_text_chars=len(text),
                file_size=info.file_size,
                read_bytes=max_read_bytes,
            )
            encoding_counts[encoding] += 1
            quality_counts[quality] += 1
            confidence_counts[str(diagnostics["splitConfidence"])] += 1
            llm_bucket_counts[str(diagnostics["llmLabelingBucket"])] += 1
            for opening in openings:
                pattern_counts[opening.header_pattern] += 1
            rows.append(
                {
                    "fileName": info.filename,
                    "fileSize": info.file_size,
                    "analyzedTextChars": len(text),
                    "encoding": encoding,
                    "openingQuality": quality,
                    **diagnostics,
                    "headerCount": len(headers),
                    "openingEpisodeNos": [item.episode_no for item in openings],
                    "openingHeaderPatterns": [item.header_pattern for item in openings],
                    "openingTextChars": [item.text_chars for item in openings],
                }
            )

    file_count = len(rows)
    return {
        "sourceZip": str(zip_path),
        "fileCount": file_count,
        "minSectionChars": min_section_chars,
        "maxReadBytes": max_read_bytes,
        "encodingCounts": dict(sorted(encoding_counts.items())),
        "qualityCounts": dict(sorted(quality_counts.items())),
        "splitConfidenceCounts": dict(sorted(confidence_counts.items())),
        "llmLabelingBucketCounts": dict(sorted(llm_bucket_counts.items())),
        "patternCounts": dict(sorted(pattern_counts.items())),
        "first3DetectedRatio": round(quality_counts.get("first3_detected", 0) / max(file_count, 1), 4),
        "readyForLLMLabelingRatio": round(
            sum(1 for row in rows if row["readyForLLMLabeling"]) / max(file_count, 1),
            4,
        ),
        "rows": rows,
    }


def build_manifest_lines(payload: dict[str, object]) -> list[str]:
    return [
        json.dumps(
            {
                "sourceZip": payload["sourceZip"],
                "minSectionChars": payload["minSectionChars"],
                "maxReadBytes": payload["maxReadBytes"],
                **row,
            },
            ensure_ascii=False,
        )
        for row in payload["rows"]
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="캐릭터챗 400작품 opening corpus 1~3화 추출 감사")
    parser.add_argument("--zip", required=True, dest="zip_path", help="웹소설 txt zip 경로")
    parser.add_argument("--out", default="", help="감사 JSON 저장 경로")
    parser.add_argument("--manifest-out", default="", help="라벨링 후보용 row-level JSONL 저장 경로")
    parser.add_argument("--min-section-chars", type=int, default=DEFAULT_MIN_SECTION_CHARS)
    parser.add_argument("--max-read-bytes", type=int, default=DEFAULT_MAX_READ_BYTES)
    parser.add_argument("--sample-problems", type=int, default=20, help="stdout에 포함할 실패 샘플 수")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = audit_zip(
        Path(args.zip_path),
        min_section_chars=args.min_section_chars,
        max_read_bytes=args.max_read_bytes,
    )
    output_payload = dict(payload)
    problem_rows = [
        {
            "fileName": row["fileName"],
            "openingQuality": row["openingQuality"],
            "splitConfidence": row["splitConfidence"],
            "llmLabelingBucket": row["llmLabelingBucket"],
            "lengthOutlierFlags": row["lengthOutlierFlags"],
            "headerCount": row["headerCount"],
            "headerDensityPer100k": row["headerDensityPer100k"],
            "openingEpisodeNos": row["openingEpisodeNos"],
            "openingHeaderPatterns": row["openingHeaderPatterns"],
            "openingTextChars": row["openingTextChars"],
        }
        for row in payload["rows"]
        if row["openingQuality"] != "first3_detected" or row["splitConfidence"] != "high"
    ][: max(args.sample_problems, 0)]
    output_payload["problemSamples"] = problem_rows

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        output_payload["out"] = str(out_path)
        output_payload.pop("rows", None)
    if args.manifest_out:
        manifest_path = Path(args.manifest_out)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text("\n".join(build_manifest_lines(payload)) + "\n", encoding="utf-8")
        output_payload["manifestOut"] = str(manifest_path)
    print(json.dumps(output_payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
