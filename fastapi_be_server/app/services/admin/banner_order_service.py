"""
배너 노출 순서 계산 유틸.

DB 접근 없이 현재 행 목록을 1..N 노출 순서로 재배치하는 순수 함수만 둔다.
"""


def _as_int(value, fallback: int = 0) -> int:
    try:
        if value is None:
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _build_banner_reorder_plan(
    rows: list[dict],
    target_id: int | None = None,
    target_position: int | None = None,
) -> list[tuple[int, int]]:
    ordered = sorted(
        rows,
        key=lambda row: (_as_int(row.get("show_order"), 0), _as_int(row.get("id"), 0)),
    )

    if target_id is not None and not any(row.get("id") == target_id for row in ordered):
        raise ValueError("target_id not found")

    if target_id is not None and target_position is not None:
        if target_position < 1 or target_position > len(ordered):
            raise ValueError("target_position out of range")

        current_index = next(
            (index for index, row in enumerate(ordered) if row.get("id") == target_id),
            None,
        )
        target_row = ordered.pop(current_index)
        ordered.insert(target_position - 1, target_row)

    return [(_as_int(row["id"]), index + 1) for index, row in enumerate(ordered)]
