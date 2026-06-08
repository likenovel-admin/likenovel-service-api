from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _function_block(source: str, name: str) -> str:
    block = source.split(f"async def {name}", 1)[1]
    return block.split("\nasync def ", 1)[0]


def test_episode_sale_actor_uses_accepted_cp_profile():
    source = _read(ROOT / "app/services/product/episode_service.py")
    helper = _function_block(source, "_resolve_episode_sale_actor")

    assert "from tb_user_profile_apply upa" in helper
    assert "upa.apply_type = 'cp'" in helper
    assert "upa.approval_code = 'accepted'" in helper
    assert "upa.approval_date IS NOT NULL" in helper
    assert "u.use_yn = 'Y'" in helper


def test_sale_state_mutations_allow_approved_cp_linked_products():
    source = _read(ROOT / "app/services/product/episode_service.py")

    for name in [
        "post_episodes_sale_start",
        "post_episodes_sale_reserve",
        "post_episodes_publish_reserve_bulk",
        "post_episodes_sale_reserve_cancel",
    ]:
        block = _function_block(source, name)

        assert "_resolve_episode_sale_actor" in block
        assert '"is_admin": 1 if actor_flags["is_admin"] else 0' in block
        assert '"is_cp": 1 if actor_flags["is_cp"] else 0' in block
        assert "or p.user_id = :user_id" in block
        assert "or (:is_cp = 1 and p.cp_user_id = :user_id)" in block
        assert "p.author_id = :user_id" not in block
        assert "for update" in block.lower()


def test_sale_start_and_reserve_still_require_accepted_episode_apply_status():
    source = _read(ROOT / "app/services/product/episode_service.py")

    for name in ["post_episodes_sale_start", "post_episodes_sale_reserve"]:
        block = _function_block(source, name)

        assert 'latest_apply_status == "accepted"' in block
        assert 'open_yn != "Y"' in block


def test_sale_reserve_cancel_still_targets_only_closed_reserved_episodes():
    source = _read(ROOT / "app/services/product/episode_service.py")
    block = _function_block(source, "post_episodes_sale_reserve_cancel")

    assert "and e.open_yn = 'N'" in block
    assert "and e.publish_reserve_date IS NOT NULL" in block
    assert "이미 판매중이거나 예약된 회차가 없습니다." in block


def test_non_sale_episode_mutations_keep_existing_owner_only_gate():
    source = _read(ROOT / "app/services/product/episode_service.py")

    for name in [
        "post_episodes_products_product_id_titles_bulk",
        "post_episodes_delete",
    ]:
        block = _function_block(source, name)

        assert "comm_service.get_user_from_kc" in block
        assert "and (:is_admin = 1 or p.user_id = :user_id)" in block
        assert "p.cp_user_id = :user_id" not in block
