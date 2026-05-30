EXCLUDED_PRIMARY_GENRE_NAMES = {"로맨스"}


def _normalize_genre_name(genre_name: str | None) -> str:
    return (genre_name or "").strip()


def is_excluded_primary_genre_name(genre_name: str | None) -> bool:
    return _normalize_genre_name(genre_name) in EXCLUDED_PRIMARY_GENRE_NAMES


def can_use_as_primary_genre(genre_name: str | None) -> bool:
    normalized = _normalize_genre_name(genre_name)
    return bool(normalized) and normalized not in EXCLUDED_PRIMARY_GENRE_NAMES
