from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _function_block(source: str, name: str) -> str:
    block = source.split(f"async def {name}", 1)[1]
    return block.split("\nasync def ", 1)[0]


def test_paid_conversion_waiting_for_free_request_defaults_and_periods():
    schema = _read("app/schemas/admin.py")

    assert "waiting_for_free_enabled: bool" in schema
    assert "default=False" in schema
    assert "waiting_for_free_period_months: Optional[int]" in schema
    assert "value not in {3, 6, 12, 36}" in schema


def test_paid_conversion_creates_waiting_for_free_without_precommit_advisory_lock():
    service = _read("app/services/admin/admin_user_service.py")
    helper = _function_block(service, "_apply_waiting_for_free_by_admin")
    apply_block = _function_block(service, "apply_paid_conversion_by_admin")

    assert "type = 'waiting-for-free'" in helper
    assert "status IN ('apply', 'ing')" in helper
    assert "INTERVAL {WAITING_FOR_FREE_ACTIVATION_DELAY_MINUTES} MINUTE" in helper
    assert "DATE_ADD(CURDATE(), INTERVAL :period_months MONTH)" in helper
    assert "SELECT GET_LOCK" not in helper
    assert "SELECT RELEASE_LOCK" not in helper
    assert "FOR UPDATE" in apply_block
    assert "_apply_waiting_for_free_by_admin" in apply_block
    assert "waitingForFreeDirectSlotManual" in apply_block


def test_initial_waiting_for_free_issue_is_serialized_and_keeps_gift_lineage():
    product_service = _read("app/services/product/product_service.py")
    giftbook_service = _read("app/services/user/user_giftbook_service.py")

    user_lock = "SELECT user_id FROM tb_user WHERE user_id = :user_id FOR UPDATE"
    duplicate_check = "FROM tb_user_giftbook"
    assert user_lock in product_service
    assert product_service.index(user_lock) < product_service.index(
        duplicate_check,
        product_service.index(user_lock),
    )
    assert "LIMIT 1\n                     FOR UPDATE" in product_service
    assert "'gift', :acquisition_id" in giftbook_service
    assert "Failed to auto-receive waiting-for-free giftbook" in giftbook_service


def test_recharge_batch_and_on_demand_path_share_lock_and_support_legacy_gifts():
    batch = _read("dist/batch/summary_hourly_batch.sql")
    productbook_service = _read("app/services/user/user_productbook_service.py")

    for source in (batch, productbook_service):
        assert "lk_summary_hourly_batch" in source
        assert "tb_user_giftbook" in source
        assert "ug.promotion_type = 'waiting-for-free'" in source
        assert "ug.acquisition_type = 'applied_promotion'" in source
        assert "timestampdiff(hour, seed.last_use_date, now()) >= 24" in source
        assert "'waiting-for-free' as ticket_type" in source
        assert "created_date > seed.last_use_date" in source

    assert "SELECT RELEASE_LOCK(@job_lock_name)" in batch
    assert "await conn.commit()" in productbook_service
    assert productbook_service.index("active_wff_query") < productbook_service.index(
        "_issue_due_waiting_for_free_ticket(\n            user_id=user_id"
    )
    assert productbook_service.index("await conn.commit()") < productbook_service.index(
        "SELECT RELEASE_LOCK(:lock_name)"
    )


def test_waiting_for_free_sources_cannot_be_physically_deleted():
    productbook_service = _read("app/services/user/user_productbook_service.py")
    giftbook_router = _read("app/routers/user/user_giftbook_command.py")
    giftbook_service = _read("app/services/user/user_giftbook_service.py")

    productbook_delete = _function_block(productbook_service, "delete_user_productbook")
    giftbook_delete = _function_block(giftbook_service, "delete_user_giftbook")

    assert "upb.user_id = :user_id" in productbook_delete
    assert "waiting-for-free" in productbook_delete
    assert '@router.delete("/{id}"' not in giftbook_router
    assert '"/{id}/receive"' in giftbook_router
    assert "ug.user_id = :user_id" in giftbook_delete
    assert "waiting-for-free" in giftbook_delete


def test_waiting_for_free_activation_uses_datetime_everywhere():
    paths = [
        "app/services/ai/ai_chat_service.py",
        "app/services/ai/recommendation_service.py",
        "app/services/gift/author_service.py",
        "app/services/product/product_service.py",
        "app/services/user/user_giftbook_service.py",
    ]

    for path in paths:
        source = _read(path)
        assert "wff.start_date <= NOW()" in source
        assert "DATE(wff.start_date) <= CURDATE()" not in source


def test_waiting_for_free_use_never_creates_paid_order():
    service = _read("app/services/user/user_productbook_service.py")
    use_block = _function_block(service, "use_user_productbook")

    assert 'if ticket_type == "paid":' in use_block
    assert "'waiting-for-free' as ticket_type" in service
