import json
import unittest
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import refresh_public_character_catalog_snapshot as snapshot_refresh
from app.services.product.public_character_catalog_snapshot_service import (
    _prepare_snapshot_rows,
    publish_public_character_catalog_snapshot,
    read_public_character_catalog_snapshot,
)
from scripts.refresh_public_character_catalog_snapshot import (
    _is_snapshot_lock_acquired,
)


def _catalog_item(*, product_id: int, character_slot_id: int) -> dict:
    return {
        "productId": product_id,
        "characterSlotId": character_slot_id,
        "characterScopeKey": f"character:{character_slot_id}",
        "cardOrder": 99,
        "lastViewedEpisodeNo": None,
        "lastViewedAt": None,
    }


class PublicCharacterCatalogSnapshotReadTest(unittest.IsolatedAsyncioTestCase):
    async def test_read_uses_active_generation_live_gate_rank_and_limit(self):
        result = MagicMock()
        result.mappings.return_value.all.return_value = [
            {"payloadJson": json.dumps(_catalog_item(product_id=1182, character_slot_id=7))}
        ]
        db = AsyncMock()
        db.execute.return_value = result

        items = await read_public_character_catalog_snapshot(
            adult_yn="invalid",
            db=db,
            limit=12,
        )

        query = str(db.execute.await_args.args[0])
        assert "snapshot_generation.active_scope = :adult_yn" in query
        assert "product.open_yn = 'Y'" in query
        assert "COALESCE(product.blind_yn, 'N') = 'N'" in query
        assert "COALESCE(product.ai_content_service_enabled_yn, 'N') = 'Y'" in query
        assert "COUNT(DISTINCT public_episode.episode_id)" in query
        assert "ORDER BY snapshot_item.display_order ASC" in query
        assert "LIMIT :limit" in query
        assert db.execute.await_args.args[1] == {"adult_yn": "N", "limit": 12}
        assert items[0]["productId"] == 1182


class PublicCharacterCatalogSnapshotPublishTest(unittest.IsolatedAsyncioTestCase):
    def test_prepare_requires_both_scopes_and_rejects_user_progress(self):
        with pytest.raises(ValueError, match="empty character catalog scope=Y"):
            _prepare_snapshot_rows(
                catalogs={"N": [_catalog_item(product_id=1, character_slot_id=1)]},
                generation_id="generation-1",
            )

        progressed = _catalog_item(product_id=1, character_slot_id=1)
        progressed["lastViewedEpisodeNo"] = 3
        with pytest.raises(ValueError, match="user progress"):
            _prepare_snapshot_rows(
                catalogs={
                    "N": [progressed],
                    "Y": [_catalog_item(product_id=2, character_slot_id=2)],
                },
                generation_id="generation-1",
            )

    async def test_publish_activates_both_scopes_in_one_commit(self):
        activation_result = MagicMock(rowcount=2)
        db = AsyncMock()
        db.execute.side_effect = [MagicMock(), MagicMock(), MagicMock(), activation_result]
        catalogs = {
            "N": [_catalog_item(product_id=1, character_slot_id=11)],
            "Y": [_catalog_item(product_id=2, character_slot_id=22)],
        }

        published = await publish_public_character_catalog_snapshot(
            catalogs=catalogs,
            db=db,
            generation_id="generation-1",
        )

        generation_rows = db.execute.await_args_list[0].args[1]
        item_rows = db.execute.await_args_list[1].args[1]
        statements = [str(call.args[0]) for call in db.execute.await_args_list]
        assert {row["adult_yn"] for row in generation_rows} == {"N", "Y"}
        assert {row["generation_id"] for row in item_rows} == {"generation-1"}
        assert [row["display_order"] for row in item_rows] == [1, 1]
        assert "SET active_scope = NULL" in statements[2]
        assert "SET active_scope = adult_yn" in statements[3]
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()
        assert published["generationId"] == "generation-1"
        assert published["itemCounts"] == {"N": 1, "Y": 1}

    async def test_failed_activation_rolls_back_and_preserves_previous_generation(self):
        activation_result = MagicMock(rowcount=1)
        db = AsyncMock()
        db.execute.side_effect = [MagicMock(), MagicMock(), MagicMock(), activation_result]

        with pytest.raises(RuntimeError, match="both adult scopes"):
            await publish_public_character_catalog_snapshot(
                catalogs={
                    "N": [_catalog_item(product_id=1, character_slot_id=11)],
                    "Y": [_catalog_item(product_id=2, character_slot_id=22)],
                },
                db=db,
                generation_id="generation-2",
            )

        db.commit.assert_not_awaited()
        db.rollback.assert_awaited_once()


def test_snapshot_lock_distinguishes_busy_from_provider_errors():
    assert _is_snapshot_lock_acquired(0) is False
    assert _is_snapshot_lock_acquired(1) is True
    with pytest.raises(RuntimeError, match="returned NULL"):
        _is_snapshot_lock_acquired(None)
    with pytest.raises(RuntimeError, match="unexpected GET_LOCK"):
        _is_snapshot_lock_acquired(2)


class PublicCharacterCatalogSnapshotScriptLifecycleTest(
    unittest.IsolatedAsyncioTestCase
):
    async def test_main_disposes_engine_after_success(self):
        original_refresh = snapshot_refresh.refresh_public_character_catalog_snapshot
        original_engine = snapshot_refresh.likenovel_db_engine
        refresh = AsyncMock(return_value={"status": "published"})
        engine = MagicMock()
        engine.dispose = AsyncMock()
        snapshot_refresh.refresh_public_character_catalog_snapshot = refresh
        snapshot_refresh.likenovel_db_engine = engine
        try:
            assert await snapshot_refresh.main() == 0
            engine.dispose.assert_awaited_once()
        finally:
            snapshot_refresh.refresh_public_character_catalog_snapshot = original_refresh
            snapshot_refresh.likenovel_db_engine = original_engine

    async def test_main_disposes_engine_after_failure(self):
        original_refresh = snapshot_refresh.refresh_public_character_catalog_snapshot
        original_engine = snapshot_refresh.likenovel_db_engine
        refresh = AsyncMock(side_effect=RuntimeError("refresh failed"))
        engine = MagicMock()
        engine.dispose = AsyncMock()
        snapshot_refresh.refresh_public_character_catalog_snapshot = refresh
        snapshot_refresh.likenovel_db_engine = engine
        try:
            assert await snapshot_refresh.main() == 1
            engine.dispose.assert_awaited_once()
        finally:
            snapshot_refresh.refresh_public_character_catalog_snapshot = original_refresh
            snapshot_refresh.likenovel_db_engine = original_engine
