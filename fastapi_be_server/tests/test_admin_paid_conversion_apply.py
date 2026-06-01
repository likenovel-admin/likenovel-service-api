from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[4]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_block(source: str, name: str) -> str:
    block = source.split(f"async def {name}", 1)[1]
    return block.split("\nasync def ", 1)[0]


def test_admin_paid_conversion_apply_route_exists_and_requires_admin():
    router = _read(ROOT / "app/routers/admin/admin_command.py")

    assert '"/apply-rank-up/{id}/apply-paid"' in router
    assert "PostApplyPaidConversionReqBody" in router
    assert "apply_paid_conversion_by_admin" in router
    assert 'role="admin"' in router


def test_admin_paid_conversion_apply_only_delegates_author_paid_settings():
    service = _read(ROOT / "app/services/admin/admin_user_service.py")
    block = _function_block(service, "apply_paid_conversion_by_admin")

    assert "tb_product_paid_apply" in block
    assert "ppa.status_code = 'accepted'" in block
    assert "p.price_type = 'free'" in block
    assert "p.product_type = 'normal'" in block
    assert "p.paid_open_date = NOW()" in block
    assert "p.paid_episode_no = :paid_episode_no" in block
    assert "row[\"paid_episode_no\"] is not None" in block
    assert "row[\"paid_open_date\"] is not None" in block
    assert "isbn" not in block.lower()
    assert "uci" not in block.lower()


def test_admin_paid_conversion_apply_keeps_author_episode_choice_bounds():
    service = _read(ROOT / "app/services/admin/admin_user_service.py")
    block = _function_block(service, "apply_paid_conversion_by_admin")

    assert "COALESCE(ep.episode_count, 0) AS episode_count" in block
    assert "max_paid_episode_no = int(row[\"episode_count\"] or 0) + 1" in block
    assert "paid_episode_no > max_paid_episode_no" in block
    assert "유료 시작 회차는 현재 회차수의 다음 회차까지만 설정할 수 있습니다." in block


def test_admin_paid_conversion_apply_saves_settings_and_leaves_transition_to_minute_batch():
    service = _read(ROOT / "app/services/admin/admin_user_service.py")
    block = _function_block(service, "apply_paid_conversion_by_admin")
    cron = _read(ROOT / "dist/batch/cron_job.sh")
    batch = _read(ROOT / "dist/batch/episode_state_transition_minute_batch.sql")

    for expected in [
        "p.paid_open_date = NOW()",
        "p.paid_episode_no = :paid_episode_no",
    ]:
        assert expected.lower() in block.lower()

    assert "set e.price_type = 'paid'" not in block.lower()
    assert "set p.price_type = 'paid'" not in block.lower()
    assert "paidEpisodeCount" not in block
    assert "productPromoted" not in block

    assert "* * * * *" in cron
    assert "episode_state_transition_minute_batch.sh" in cron
    for expected in [
        "p.paid_open_date IS NOT NULL",
        "p.paid_open_date <= @batch_now",
        "p.paid_episode_no IS NOT NULL",
        "e.episode_no >= p.paid_episode_no",
        "(e.price_type = 'free' or e.price_type is null)",
        "e.use_yn = 'Y'",
        "e.open_yn = 'Y'",
    ]:
        assert expected.lower() in batch.lower()

    assert "set e.price_type = 'paid'" in batch.lower()
    assert "set p.price_type = 'paid'" in batch.lower()


def test_cms_paid_apply_table_exposes_apply_paid_action_for_accepted_free_rows():
    table = _read(
        REPO_ROOT / "cms/app/products/apply-of-advancement/ApplyRankTable.tsx"
    )

    assert "useApplyPaidConversion" in table
    assert 'row.type === "paid"' in table
    assert 'row.status === "accepted"' in table
    assert 'row.price_type === "free"' in table
    assert "handleApplyPaidConversion" in table
    assert "유료 적용" in table
    assert "row.paid_episode_no == null || row.paid_episode_no <= 0" in table
    assert "maxPaidEpisodeNo" in table
