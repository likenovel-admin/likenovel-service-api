import asyncio
from pathlib import Path

import pytest

from app.exceptions import CustomResponseException
from app.services.product import external_distribution_service as svc

ROOT = Path(__file__).resolve().parents[1]

CANDIDATES = [
    {"product_id": 1217, "title": "차원의문 일곱열매", "author_name": "김봉진", "open_episode_count": 95},
    {"product_id": 1225, "title": "아저씨의 요술램프", "author_name": "김봉진", "open_episode_count": 87},
    {"product_id": 1252, "title": "마지막소원", "author_name": "김봉진", "open_episode_count": 62},
    {"product_id": 1097, "title": "프로스트 온더 프로즌 스틸", "author_name": "inigene", "open_episode_count": 166},
    {"product_id": 1135, "title": "엘프특공대에 구조된 인간이 너무 강함", "author_name": "쇼오크", "open_episode_count": 281},
    {"product_id": 1114, "title": "엘프특공대에 구조된 인간이 너무 강함", "author_name": "쇼오크", "open_episode_count": 281},
    {"product_id": 1133, "title": "몽중인, 꿈속의 암살자", "author_name": "무흔", "open_episode_count": 172},
]


def _obs(external_id, title, author, edition="serial"):
    return {"external_id": external_id, "title": title, "author": author, "edition": edition}


def _matched_by_product(result):
    return {m["product_id"]: m for m in result["matched"]}


def test_normalized_title_difference_matches_exactly_within_same_author():
    result = svc.match_observations(
        [
            _obs("70795886", "차원의 문: 일곱열매", "김봉진"),
            _obs("69422616", "몽중인 - 꿈속의 암살자", "무흔"),
        ],
        CANDIDATES,
    )
    matched = _matched_by_product(result)
    assert matched[1217]["match_method"] == svc.MATCH_EXACT
    assert matched[1217]["external_id"] == "70795886"
    assert matched[1133]["match_method"] == svc.MATCH_EXACT
    assert result["unmatched"] == []


def test_spelling_variant_matches_by_author_and_title_similarity():
    result = svc.match_observations(
        [_obs("62150764", "프로스티 온 더 프로즌 스틸", "inigene")], CANDIDATES
    )
    matched = _matched_by_product(result)
    assert matched[1097]["match_method"] == svc.MATCH_AUTHOR_SIMILAR
    assert matched[1097]["score"] >= svc.TITLE_SIMILARITY_MIN


def test_multi_work_author_maps_each_external_work_to_its_own_product():
    result = svc.match_observations(
        [
            _obs("70795886", "차원의 문: 일곱열매", "김봉진"),
            _obs("70795889", "아저씨의 요술램프", "김봉진"),
        ],
        CANDIDATES,
    )
    matched = _matched_by_product(result)
    assert set(matched) == {1217, 1225}
    assert 1252 not in matched


def test_unknown_author_and_unrelated_title_are_not_matched():
    result = svc.match_observations(
        [
            _obs("1", "차원의 문: 일곱열매", "다른필명"),
            _obs("2", "완전히 다른 작품", "김봉진"),
        ],
        CANDIDATES,
    )
    assert result["matched"] == []
    assert [u["reason"] for u in result["unmatched"]] == ["author_not_found", "title_ambiguous"]


def test_single_volume_edition_is_ignored():
    result = svc.match_observations(
        [_obs("69447495", "차원의 문: 일곱열매", "김봉진", edition="single_volume")],
        CANDIDATES,
    )
    assert result == {"matched": [], "unmatched": []}


def test_duplicate_public_products_pick_one_deterministically():
    result = svc.match_observations(
        [_obs("64439474", "엘프특공대에 구조된 인간이 너무 강함", "쇼오크")], CANDIDATES
    )
    assert [m["product_id"] for m in result["matched"]] == [1114]


def test_platform_thresholds_follow_slot_titles():
    assert svc.PLATFORMS["kakaopage"]["min_open_episodes"] == 50
    assert svc.PLATFORMS["ridi"]["min_open_episodes"] == 100
    with pytest.raises(CustomResponseException):
        svc.require_platform("naver")


def test_visible_query_requires_paid_public_mapping_and_episode_threshold():
    query = svc.build_visible_products_query(user_id=None)
    assert "ped.status = 'active'" in query
    assert "ped.miss_count < :miss_limit" in query
    assert "p.price_type = 'paid'" in query
    assert "p.open_yn = 'Y'" in query
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in query
    assert "COALESCE(episode_stats.open_episode_count, 0) >= :min_open_episodes" in query
    assert "LIMIT :limit_count OFFSET :offset_count" in query


def test_migration_adds_mapping_table_and_slot_source_columns_separately():
    migration = (ROOT / "dist/init/119-create-product-external-distribution.sql").read_text(
        encoding="utf-8"
    )
    assert "CREATE TABLE IF NOT EXISTS tb_product_external_distribution" in migration
    assert "UNIQUE KEY uk_product_external_distribution_product_platform (product_id, platform)" in migration
    # auto_migrate는 1060(Duplicate column)을 문장 단위로 건너뛰므로 컬럼마다 ALTER를 분리한다.
    assert migration.count("ALTER TABLE tb_direct_recommend") == 2


def test_direct_curator_reads_only_manual_slots():
    from app.services.ai import direct_curator_service

    assert "COALESCE(source_type, 'manual') = 'manual'" in str(direct_curator_service.SLOT_QUERY)


def test_direct_recommend_external_slot_requires_platform():
    from app.services.admin import admin_recommend_service as admin_svc

    admin_svc._validate_direct_recommend_source("manual", None)
    admin_svc._validate_direct_recommend_source("external_distribution", "ridi")
    with pytest.raises(CustomResponseException):
        admin_svc._validate_direct_recommend_source("external_distribution", None)
    with pytest.raises(CustomResponseException):
        admin_svc._validate_direct_recommend_source("other", None)


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, candidates, existing):
        self.candidates = candidates
        self.existing = existing
        self.writes = []

    async def execute(self, query, params=None):
        sql = " ".join(str(query).split())
        if "FROM tb_product p" in sql and "price_type = 'paid'" in sql:
            return _Result(self.candidates)
        if sql.startswith("SELECT id, product_id, external_id, match_method"):
            return _Result(self.existing)
        self.writes.append((sql, params))
        return _Result([])


def test_sync_inserts_updates_respects_manual_and_counts_misses():
    existing = [
        # 수동 등록: 다른 작품이 같은 외부 ID로 자동 매칭되어도 덮어쓰지 않는다.
        {"id": 1, "product_id": 1225, "external_id": "70795886", "match_method": "manual"},
        # 자동 매칭됐지만 이번 수집에서 안 보인 작품 → miss_count 증가
        {"id": 2, "product_id": 1133, "external_id": "69422616", "match_method": "exact"},
        # 자동 매칭, 이번에도 보임 → 갱신
        {"id": 3, "product_id": 1097, "external_id": "62150764", "match_method": "author_similar"},
    ]
    db = _FakeSession(CANDIDATES, existing)
    result = asyncio.run(svc.apply_sync(
        platform="kakaopage",
        observations=[
            _obs("70795886", "차원의 문: 일곱열매", "김봉진"),
            _obs("62150764", "프로스티 온 더 프로즌 스틸", "inigene"),
            _obs("70795889", "아저씨의 요술램프", "김봉진"),
        ],
        complete=True,
        admin_user_id=7,
        db=db,
    ))
    data = result["data"]
    assert data["skippedManualCount"] == 1  # 1217이 수동 매핑(1225)의 외부 ID를 가져가지 못함
    assert data["updatedCount"] == 2  # 1097 자동 갱신 + 1225 수동 last_seen 갱신
    assert data["insertedCount"] == 0
    assert data["missedCount"] == 1
    miss_writes = [p for sql, p in db.writes if "miss_count = miss_count + 1" in sql]
    assert miss_writes == [{"product_id": 1133, "platform": "kakaopage", "user_id": 7}]


def test_incomplete_sync_never_counts_misses():
    existing = [{"id": 2, "product_id": 1133, "external_id": "69422616", "match_method": "exact"}]
    db = _FakeSession(CANDIDATES, existing)
    result = asyncio.run(svc.apply_sync(
        platform="ridi", observations=[], complete=False, admin_user_id=None, db=db
    ))
    assert result["data"]["missedCount"] == 0
    assert db.writes == []
