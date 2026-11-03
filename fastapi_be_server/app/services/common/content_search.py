"""Content search over eligible catalogue rows; no inference or writes at request time."""

import json
from collections import Counter

from app.services.ai.recommendation_service import (
    AXIS_DISPLAY_LABEL,
    AXIS_KEYS,
    _collect_product_axis_labels,
)


def _search_tags(row: dict) -> dict[str, dict]:
    tags = {}
    keywords = row.get("standard_keywords") or []
    if isinstance(keywords, str):
        keywords = json.loads(keywords)
    for item in keywords:
        if item.get("id") and item.get("label"):
            key = f"keyword:{item['id']}"
            tags[key] = {"id": key, "label": item["label"], "group": "작품 태그"}
    if row.get("analysis_status") != "success" or row.get("exclude_from_recommend_yn") == "Y":
        return tags
    # The recommendation codebook and confidence rules remain authoritative.
    for axis in AXIS_KEYS:
        for label in _collect_product_axis_labels(row, axis):
            key = f"dna:{axis}:{label}"
            tags[key] = {"id": key, "label": label, "group": AXIS_DISPLAY_LABEL[axis]}
    return tags


def search_catalog(rows: list[dict], keyword: str, tags: list[str] | None = None, orderby: str = "relevance") -> dict:
    """AND across query words and opaque tag IDs; literal text, not SQL/regex syntax.

    Facet counts mean additional matches within the current result set. Missing
    DNA never removes a product from title/author/synopsis/standard-tag search.
    """
    query = " ".join((keyword or "").split()).casefold()
    words = list(dict.fromkeys(query.split()))
    selected = set(tags or [])
    matches = []
    facet_counts = Counter()
    facets = {}
    selected_tags = {}
    for row in rows:
        row_tags = _search_tags(row)
        selected_tags.update({key: value for key, value in row_tags.items() if key in selected})
        if not selected.issubset(row_tags):
            continue
        fields = [("작품명", str(row.get("title") or "")), ("작가", str(row.get("author_name") or "")), ("작품 소개", str(row.get("synopsis_text") or ""))]
        reasons = [f"{row_tags[key]['group']}: {row_tags[key]['label']}" for key in sorted(selected)]
        score = 0
        for word in words:
            field_match = next(((name, value) for name, value in fields if word in value.casefold()), None)
            tag_matches = [tag for tag in row_tags.values() if word in tag["label"].casefold()]
            if field_match:
                name, _ = field_match
                reasons.append(f"{name}: {word}")
                score += {"작품명": 30, "작가": 20, "작품 소개": 5}[name]
            elif tag_matches:
                reasons.extend(f"{tag['group']}: {tag['label']}" for tag in tag_matches)
                score += 10
            else:
                break
        else:
            if query and str(row.get("title") or "").casefold() == query:
                score += 100
            matches.append({**row, "searchMatchReasons": list(dict.fromkeys(reasons)), "_search_score": score})
            for key, tag in row_tags.items():
                facet_counts[key] += 1
                facets[key] = tag
    # Stable tie-breakers; update/view are retained for existing callers.
    matches.sort(key=lambda row: row["product_id"])
    matches.sort(key=lambda row: str(row.get("last_episode_date") or ""), reverse=True)
    if orderby == "view":
        matches.sort(key=lambda row: row.get("count_hit") or 0, reverse=True)
    elif orderby == "relevance":
        matches.sort(key=lambda row: row["_search_score"], reverse=True)
    return {
        "matches": matches,
        "totalCount": len(matches),
        "selectedTags": list(selected_tags.values()),
        "facets": [{**facets[key], "count": count} for key, count in sorted(facet_counts.items(), key=lambda item: (-item[1], item[0]))],
    }
