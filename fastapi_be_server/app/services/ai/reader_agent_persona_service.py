import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


KOREAN_AXIS_ORDER = ("세", "직", "능", "연", "작", "타", "목")
AGE_GROUP_WEIGHTS = (
    ("10s", 0.08),
    ("20s", 0.23),
    ("30s", 0.36),
    ("40s", 0.29),
    ("50s", 0.04),
)
AXIS_CODEBOOK_KEY = {
    "type": "타",
    "job": "직",
    "goal": "목",
    "material": "능",
    "worldview": "세",
    "romance": "연",
    "style": "작",
}


@dataclass(frozen=True)
class ReaderAgentSeed:
    agent_key: str
    age_group: str
    gender: str
    persona_json: str
    taste_memory_json: str
    activity_pattern_json: str


def generate_reader_agent_seed(
    index: int,
    *,
    age_group: str | None = None,
    gender: str | None = None,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
) -> ReaderAgentSeed:
    if index < 0:
        raise ValueError("index must be non-negative")
    rng = random.Random(f"likenovel-ai-reader:{index}")
    age_group = age_group or _weighted_pick(rng, list(AGE_GROUP_WEIGHTS))
    gender = gender or _weighted_pick(rng, [("M", 0.52), ("F", 0.45), ("X", 0.03)])
    initial_axis_bias = build_initial_axis_bias(rng)
    persona = {
        "initial_axis_bias": initial_axis_bias,
        "patience": round(rng.uniform(0.25, 0.85), 3),
        "rating_severity": round(rng.uniform(0.2, 0.8), 3),
        "bookmark_threshold": round(rng.uniform(0.55, 0.85), 3),
        "recommend_threshold": round(rng.uniform(0.52, 0.82), 3),
        "drop_threshold": round(rng.uniform(0.18, 0.45), 3),
        "loose_stop_weight": 0.1,
        "novelty_seeking": round(rng.uniform(0.15, 0.75), 3),
        "session_burst_size": _session_burst_size(age_group, rng),
    }
    taste_memory = {
        "source": "initial_persona",
        "positive_axes": initial_axis_bias,
        "negative_axes": {axis: {} for axis in KOREAN_AXIS_ORDER},
    }
    activity_pattern = build_activity_pattern(
        age_group=age_group,
        gender=gender,
        seed=index,
        active_hours=active_hours,
        daily_session_target=daily_session_target,
    )
    return ReaderAgentSeed(
        agent_key=f"ai-reader-{index:04d}",
        age_group=age_group,
        gender=gender,
        persona_json=_json_dumps(persona),
        taste_memory_json=_json_dumps(taste_memory),
        activity_pattern_json=_json_dumps(activity_pattern),
    )


def generate_reader_agent_seeds(
    *,
    count: int,
    index_offset: int = 0,
    age_group_ratios: dict[str, int] | None = None,
    gender_ratios: dict[str, int] | None = None,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
) -> list[ReaderAgentSeed]:
    if count < 0:
        raise ValueError("count must be non-negative")
    age_groups = _expand_ratio_values(
        age_group_ratios or _ratio_map_from_weights(AGE_GROUP_WEIGHTS),
        count=count,
        order=[item[0] for item in AGE_GROUP_WEIGHTS],
    )
    genders = _expand_ratio_values(
        gender_ratios or {"M": 52, "F": 45, "X": 3},
        count=count,
        order=["M", "F", "X"],
    )
    return [
        generate_reader_agent_seed(
            index_offset + index,
            age_group=age_groups[index],
            gender=genders[index],
            active_hours=active_hours,
            daily_session_target=daily_session_target,
        )
        for index in range(count)
    ]


def build_initial_axis_bias(rng: random.Random) -> dict[str, dict[str, float]]:
    allowed = _load_allowed_labels_by_axis()
    bias: dict[str, dict[str, float]] = {axis: {} for axis in KOREAN_AXIS_ORDER}
    for english_axis, labels in allowed.items():
        korean_axis = AXIS_CODEBOOK_KEY.get(english_axis)
        if not korean_axis:
            continue
        sorted_labels = sorted(labels)
        if not sorted_labels:
            continue
        sample_size = min(len(sorted_labels), rng.randint(2, 4))
        for label in rng.sample(sorted_labels, sample_size):
            bias[korean_axis][label] = round(rng.uniform(0.35, 0.95), 3)
    return bias


def _load_allowed_labels_by_axis() -> dict[str, set[str]]:
    path = (
        Path(__file__).resolve().parents[3]
        / "dist"
        / "ai"
        / "allowed-labels-by-axis.json"
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    allowed: dict[str, set[str]] = {}
    for english_axis, korean_axis in AXIS_CODEBOOK_KEY.items():
        labels = payload.get(korean_axis, [])
        if isinstance(labels, list):
            allowed[english_axis] = {
                str(label).strip()
                for label in labels
                if str(label).strip()
            }
        else:
            allowed[english_axis] = set()
    return allowed


def build_activity_pattern(
    *,
    age_group: str,
    gender: str,
    seed: int,
    active_hours: list[int] | None = None,
    daily_session_target: int | None = None,
) -> dict[str, Any]:
    rng = random.Random(f"likenovel-ai-reader-activity:{age_group}:{gender}:{seed}")
    base_hours_by_age = {
        "10s": [16, 17, 18, 19, 20, 21, 22, 23],
        "20s": [8, 12, 18, 19, 20, 21, 22, 23, 0],
        "30s": [7, 8, 12, 20, 21, 22],
        "40s": [6, 7, 8, 12, 20, 21],
        "50s": [5, 6, 7, 12, 20, 21],
    }
    base_hours = list(base_hours_by_age.get(age_group, base_hours_by_age["30s"]))
    if gender == "X":
        extra_candidates = [hour for hour in range(24) if hour not in base_hours]
        if extra_candidates:
            base_hours.append(rng.choice(extra_candidates))
    elif gender == "F" and 23 not in base_hours and rng.random() < 0.35:
        base_hours.append(23)
    elif gender == "M" and 6 not in base_hours and rng.random() < 0.25:
        base_hours.append(6)

    if active_hours is None:
        normalized_active_hours = sorted(set(base_hours))
    else:
        normalized_active_hours = sorted(set(int(hour) for hour in active_hours))
    sleep_hours = [hour for hour in range(24) if hour not in normalized_active_hours]
    return {
        "active_hours": normalized_active_hours,
        "sleep_hours": sleep_hours,
        "weekday_weight": round(rng.uniform(0.75, 1.05), 3),
        "weekend_weight": round(rng.uniform(0.85, 1.35), 3),
        "daily_session_target": daily_session_target or rng.randint(1, 5),
    }


def _weighted_pick(rng: random.Random, items: list[tuple[str, float]]) -> str:
    total = sum(weight for _, weight in items)
    cursor = rng.random() * total
    acc = 0.0
    for value, weight in items:
        acc += weight
        if cursor <= acc:
            return value
    return items[-1][0]


def _ratio_map_from_weights(items: tuple[tuple[str, float], ...]) -> dict[str, int]:
    return {key: int(round(weight * 100)) for key, weight in items}


def _expand_ratio_values(
    ratios: dict[str, int],
    *,
    count: int,
    order: list[str],
) -> list[str]:
    if count == 0:
        return []
    base_counts: dict[str, int] = {}
    remainders: list[tuple[float, int, str]] = []
    for order_index, key in enumerate(order):
        ratio = max(0, int(ratios.get(key, 0)))
        raw_count = count * ratio / 100
        base_count = int(raw_count)
        base_counts[key] = base_count
        remainders.append((raw_count - base_count, -order_index, key))

    remaining_count = count - sum(base_counts.values())
    for _fraction, _order_index, key in sorted(remainders, reverse=True)[:remaining_count]:
        base_counts[key] += 1

    values: list[str] = []
    for key in order:
        values.extend([key] * base_counts.get(key, 0))
    return values[:count]


def _session_burst_size(age_group: str, rng: random.Random) -> list[int]:
    if age_group == "10s":
        return [1, rng.randint(2, 5)]
    if age_group == "20s":
        return [1, rng.randint(3, 7)]
    if age_group == "30s":
        return [1, rng.randint(2, 5)]
    return [1, rng.randint(1, 4)]


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
