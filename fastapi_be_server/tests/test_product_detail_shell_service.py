import asyncio
import inspect
from unittest.mock import AsyncMock, patch

from fastapi import status

from app.exceptions import CustomResponseException
from app.routers.product import product_query
from app.services.product import product_service


class _FakeMappings:
    def __init__(self, row):
        self._row = row

    def one_or_none(self):
        return self._row


class _FakeResult:
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return _FakeMappings(self._row)


class _FakeDb:
    def __init__(self, row):
        self._row = row
        self.query = None
        self.params = None

    async def execute(self, query, params):
        self.query = str(query)
        self.params = params
        return _FakeResult(self._row)


def test_public_detail_shell_returns_public_product_without_statistics_write():
    db = _FakeDb({"productId": 1140})

    with (
        patch.object(
            product_service,
            "get_select_fields_and_joins_for_home_card_product",
            return_value={"select_fields": "p.product_id as productId", "joins": ""},
        ) as select_bundle,
        patch.object(
            product_service,
            "convert_home_card_product_data",
            return_value={"productId": 1140, "title": "공개 작품"},
        ) as convert,
        patch.object(
            product_service.statistics_service,
            "insert_site_statistics_logs",
            new_callable=AsyncMock,
        ) as insert_statistics,
    ):
        response = asyncio.run(
            product_service.public_product_detail_shell_by_product_id(
                product_id="1140",
                db=db,
            )
        )

    assert response == {"data": {"productId": 1140, "title": "공개 작품"}}
    assert db.params == {"product_id": "1140"}
    assert "p.product_id = :product_id" in db.query
    assert "p.open_yn = 'Y'" in db.query
    select_bundle.assert_called_once_with(user_id=None, rank_area_code=None)
    convert.assert_called_once_with({"productId": 1140})
    insert_statistics.assert_not_awaited()


def test_public_detail_shell_hides_non_public_products():
    db = _FakeDb(None)

    with patch.object(
        product_service,
        "get_select_fields_and_joins_for_home_card_product",
        return_value={"select_fields": "p.product_id as productId", "joins": ""},
    ):
        try:
            asyncio.run(
                product_service.public_product_detail_shell_by_product_id(
                    product_id="1140",
                    db=db,
                )
            )
        except CustomResponseException as exc:
            assert exc.status_code == status.HTTP_404_NOT_FOUND
        else:
            raise AssertionError("a non-public product must not return shell metadata")


def test_public_detail_shell_route_does_not_accept_user_scope():
    route = next(
        route
        for route in product_query.router.routes
        if route.path == "/products/{product_id}/detail-shell"
    )

    assert "user" not in inspect.signature(route.endpoint).parameters
