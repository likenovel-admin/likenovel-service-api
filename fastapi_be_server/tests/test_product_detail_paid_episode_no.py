import inspect

from app.services.product.product_service import (
    get_select_fields_and_joins_for_product,
    product_details_group_by_product_id,
)


def test_product_detail_select_exposes_paid_episode_no():
    select_bundle = get_select_fields_and_joins_for_product(user_id=None)

    assert "p.paid_episode_no as paidEpisodeNo" in select_bundle["select_fields"]


def test_product_detail_select_exposes_paid_open_date_when_requested():
    select_bundle = get_select_fields_and_joins_for_product(
        user_id=None, include_paid_open_date=True
    )

    assert "p.paid_open_date as paidOpenDate" in select_bundle["select_fields"]


def test_product_details_group_requests_paid_open_date():
    source = inspect.getsource(product_details_group_by_product_id)

    assert "include_paid_open_date=True" in source


def test_default_product_select_does_not_expose_paid_open_date():
    select_bundle = get_select_fields_and_joins_for_product(user_id=None)

    assert "p.paid_open_date as paidOpenDate" not in select_bundle["select_fields"]
