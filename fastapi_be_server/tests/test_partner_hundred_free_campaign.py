from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_block(source: str, name: str) -> str:
    block = source.split(f"async def {name}", 1)[1]
    return block.split("\nasync def ", 1)[0]


def test_partner_product_schema_accepts_hundred_free_campaign_fields():
    schema = _read(ROOT / "app/schemas/partner.py")

    assert "hundred_free_campaign_enabled" in schema
    assert "hundred_free_campaign_ends_at" in schema


def test_partner_product_detail_returns_active_hundred_free_campaign_state():
    service = _read(ROOT / "app/services/partner/partner_product_service.py")
    block = _function_block(service, "product_detail")

    assert "tb_product_free_episode_campaign" in block
    assert "hundred_free_campaign_active_yn" in block
    assert "hundred_free_campaign_ends_at" in block


def test_partner_product_update_applies_campaign_range_and_restore_policy():
    service = _read(ROOT / "app/services/partner/partner_product_service.py")
    block = _function_block(service, "put_product")

    assert "hundred_free_campaign_enabled" in block
    assert "hundred_free_campaign_ends_at" in block
    assert "campaign_free_start_no" in block
    assert "campaign_free_end_no" in block
    assert "restore_free_start_no" in block
    assert "restore_free_end_no" in block
    assert "free_episode_start_no = 1" in block
    assert "free_episode_end_no = 100" in block
    assert "restore_free_start_no = 1" in block
    assert "restore_free_end_no = 25" in block
    assert "active_yn = 'N'" in block


def test_hundred_free_campaign_migration_and_batch_restore_exist():
    migration = _read(ROOT / "dist/init/105-create-product-free-episode-campaign.sql")
    batch = _read(ROOT / "dist/batch/free_episode_campaign_expire_batch.sql")
    cron = _read(ROOT / "dist/batch/cron_job.sh")
    cron_dev = _read(ROOT / "dist/batch/cron_job.dev.sh")

    assert "CREATE TABLE IF NOT EXISTS tb_product_free_episode_campaign" in migration
    assert "idx_product_free_episode_campaign_active_ends" in migration
    assert "tb_product_free_episode_campaign" in batch
    assert "restore_free_start_no" in batch
    assert "restore_free_end_no" in batch
    assert "SET e.price_type = CASE" in batch
    assert "c.active_yn = 'N'" in batch
    assert "free_episode_campaign_expire_batch.sh" in cron
    assert "free_episode_campaign_expire_batch.sh" in cron_dev


def test_partner_upload_ui_sends_hundred_free_campaign_payload():
    page_path = REPO_ROOT / "partner/app/products/upload/page.tsx"
    dto_path = REPO_ROOT / "partner/api/product/dto.ts"
    product_type_path = REPO_ROOT / "partner/types/product.ts"
    if not page_path.exists():
        pytest.skip("root partner files are unavailable in standalone backend checkout")

    page = _read(page_path)
    dto = _read(dto_path)
    product_type = _read(product_type_path)

    assert "이번주만 백화무료 지정" in page
    assert "hundredFreeCampaignEnabled" in page
    assert "hundredFreeCampaignEndsAt" in page
    assert "hundred_free_campaign_enabled" in page
    assert "hundred_free_campaign_ends_at" in page
    assert 'setField("freeEpisodeStartNo", "1")' in page
    assert 'setField("freeEpisodeEndNo", "100")' in page
    assert 'setField("freeEpisodeEndNo", "25")' in page

    assert "hundred_free_campaign_enabled" in dto
    assert "hundred_free_campaign_ends_at" in dto
    assert "hundred_free_campaign_active_yn" in product_type
    assert "hundred_free_campaign_ends_at" in product_type
