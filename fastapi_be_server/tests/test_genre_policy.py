from app.services.common.genre_policy import (
    can_use_as_primary_genre,
    is_excluded_primary_genre_name,
)


def test_romance_is_excluded_only_from_primary_genre():
    assert is_excluded_primary_genre_name("로맨스")
    assert not can_use_as_primary_genre("로맨스")
    assert can_use_as_primary_genre("현대판타지")


def test_primary_genre_exclusion_normalizes_whitespace():
    assert is_excluded_primary_genre_name(" 로맨스 ")


if __name__ == "__main__":
    test_romance_is_excluded_only_from_primary_genre()
    test_primary_genre_exclusion_normalizes_whitespace()
