from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_auto_normal_promotion_helper_uses_existing_rank_up_conditions():
    source = _read(ROOT / "app/services/product/product_service.py")

    assert "async def promote_product_to_normal_if_eligible" in source
    helper = source.split("async def promote_product_to_normal_if_eligible", 1)[1]
    helper = helper.split("\nasync def ", 1)[0]

    assert "p.user_id = :user_id" in helper
    assert "p.price_type = 'free'" in helper
    assert "p.open_yn = 'Y'" in helper
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in helper
    assert "COALESCE(p.product_type, 'free') = 'free'" in helper
    assert "e.use_yn = 'Y'" in helper
    assert "COUNT(*) >= 5" in helper
    assert "COALESCE(SUM(e.episode_text_count), 0) >= 20000" in helper
    assert "e.open_yn = 'Y'" not in helper


def test_auto_normal_promotion_updates_once_and_notifies_author_with_title():
    source = _read(ROOT / "app/services/product/product_service.py")
    helper = source.split("async def promote_product_to_normal_if_eligible", 1)[1]
    helper = helper.split("\nasync def ", 1)[0]

    assert "SET p.product_type = 'normal'" in helper
    assert "p.apply_date = COALESCE(p.apply_date, NOW())" in helper
    assert "if result.rowcount != 1" in helper
    assert "INSERT INTO tb_user_notification_item" in helper
    assert "CONCAT('[', p.title, '] 일반연재로 자동승급되었습니다.')" in helper


def test_auto_normal_promotion_runs_after_plain_episode_writes_only():
    source = _read(ROOT / "app/services/product/episode_service.py")

    assert "product_service.promote_product_to_normal_if_eligible" in source
    assert source.count("promote_product_to_normal_if_eligible") == 2
    assert "post_episodes_products_product_id_epub" in source


def test_auto_normal_promotion_runs_when_existing_product_becomes_public():
    source = _read(ROOT / "app/services/product/product_service.py")
    update_product = source.split("async def put_products_product_id(", 1)[1]
    update_product = update_product.split(
        "\nasync def promote_product_to_normal_if_eligible", 1
    )[0]

    assert (
        'next_open_yn = "N" if requested_blind_yn == "Y" else req_body.open_yn'
        in update_product
    )
    assert 'current_open_yn == "N"' in update_product
    assert 'next_open_yn == "Y"' in update_product
    assert "await promote_product_to_normal_if_eligible(" in update_product


def test_can_apply_normal_state_uses_same_public_not_blind_gate():
    source = _read(ROOT / "app/services/product/product_service.py")

    state_expr = source.split("END as canApplyForNormal", 1)[0]
    state_expr = state_expr.rsplit("CASE WHEN", 1)[1]

    assert "p.price_type = 'free'" in state_expr
    assert "p.open_yn = 'Y'" in state_expr
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in state_expr
    assert "COALESCE(p.product_type, 'free') = 'free'" in state_expr
    assert "COALESCE(ep_count.episode_count, 0) >= 5" in state_expr
    assert "COALESCE(ep_count.episode_text_count, 0) >= 20000" in state_expr


def test_backfill_migration_promotes_existing_eligible_free_products_once():
    migration = _read(
        ROOT / "dist/init/102-backfill-auto-normal-promotion.sql"
    )

    assert "UPDATE tb_product p" in migration
    assert "SET p.product_type = 'normal'" in migration
    assert "p.price_type = 'free'" in migration
    assert "p.open_yn = 'Y'" in migration
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in migration
    assert "COALESCE(p.product_type, 'free') = 'free'" in migration
    assert "e.use_yn = 'Y'" in migration
    assert "COUNT(*) >= 5" in migration
    assert "COALESCE(SUM(e.episode_text_count), 0) >= 20000" in migration
    assert "INSERT INTO tb_user_notification_item" in migration
    assert "일반연재로 자동승급되었습니다" in migration
    assert "e.open_yn = 'Y'" not in migration


def test_backfill_migration_can_recover_after_product_update_before_notification():
    migration = _read(
        ROOT / "dist/init/102-backfill-auto-normal-promotion.sql"
    )

    assert "CREATE TABLE IF NOT EXISTS tb_auto_normal_promotion_backfill_102" in migration
    assert "INSERT IGNORE INTO tb_auto_normal_promotion_backfill_102" in migration
    assert "UPDATE tb_product p" in migration
    assert "INSERT INTO tb_user_notification_item" in migration
    assert "NOT EXISTS" in migration
    assert "DROP TABLE IF EXISTS tb_auto_normal_promotion_backfill_102" in migration
    assert migration.index(
        "CREATE TABLE IF NOT EXISTS tb_auto_normal_promotion_backfill_102"
    ) < migration.index("UPDATE tb_product p")
    assert migration.index("UPDATE tb_product p") < migration.index(
        "INSERT INTO tb_user_notification_item"
    )


def test_author_normal_promotion_button_and_info_are_hidden():
    source = _read(REPO_ROOT / "service/components/common/ProductListCard.tsx")

    assert "const canShowApplyNormalButton = false;" in source
