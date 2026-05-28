from app.services.product.product_service import get_select_fields_and_joins_for_product


def test_product_detail_select_exposes_paid_episode_no():
    select_bundle = get_select_fields_and_joins_for_product(user_id=None)

    assert "p.paid_episode_no as paidEpisodeNo" in select_bundle["select_fields"]
