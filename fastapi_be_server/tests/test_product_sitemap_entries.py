import asyncio
import inspect
from datetime import date

from app.routers.product import product_query
from app.services.product import product_service


class _FakeMappings:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return _FakeMappings(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows
        self.query = None

    async def execute(self, query):
        self.query = str(query)
        return _FakeResult(self._rows)


def test_product_sitemap_entries_return_only_indexable_products():
    last_modified = date(2026, 7, 24)
    db = _FakeDb(
        [
            {"productId": 1214, "lastModified": last_modified},
            {"productId": 1215, "lastModified": None},
        ]
    )

    response = asyncio.run(product_service.product_sitemap_entries(db=db))

    assert response == {
        "data": [
            {"productId": 1214, "lastModified": last_modified},
            {"productId": 1215, "lastModified": None},
        ]
    }
    assert "p.product_id AS productId" in db.query
    assert "DATE(p.last_episode_date) AS lastModified" in db.query
    assert "p.open_yn = 'Y'" in db.query
    assert "COALESCE(p.blind_yn, 'N') = 'N'" in db.query
    assert "p.ratings_code = 'all'" in db.query
    assert "ORDER BY p.product_id ASC" in db.query


def test_product_sitemap_route_precedes_dynamic_product_route():
    sitemap_index = next(
        index
        for index, route in enumerate(product_query.router.routes)
        if route.path == "/products/sitemap"
    )
    product_index = next(
        index
        for index, route in enumerate(product_query.router.routes)
        if route.path == "/products/{product_id}"
    )
    sitemap_route = product_query.router.routes[sitemap_index]

    assert sitemap_index < product_index
    assert "user" not in inspect.signature(sitemap_route.endpoint).parameters
