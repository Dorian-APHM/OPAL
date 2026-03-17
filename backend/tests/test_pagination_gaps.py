"""Tests for pagination on endpoints that were missing coverage:
- saved_queries (limit/offset)
- favorites (limit/offset)
"""
import pytest


# ── Saved Queries Pagination ──

class TestSavedQueriesPagination:

    def _create_queries(self, client, n=5):
        ids = []
        for i in range(n):
            resp = client.post("/api/saved-queries/", json={
                "cdm_name": "test_cdm",
                "name": f"Query {i}",
                "sql": f"SELECT {i}",
            })
            ids.append(resp.json()["id"])
        return ids

    def test_default_returns_all(self, client):
        self._create_queries(client, 3)
        resp = client.get("/api/saved-queries/")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["queries"]) == 3
        assert data["total"] == 3
        assert data["limit"] == 100
        assert data["offset"] == 0

    def test_limit(self, client):
        self._create_queries(client, 5)
        resp = client.get("/api/saved-queries/", params={"limit": 2})
        data = resp.json()
        assert len(data["queries"]) == 2
        assert data["total"] == 5

    def test_offset(self, client):
        self._create_queries(client, 5)
        resp = client.get("/api/saved-queries/", params={"limit": 2, "offset": 3})
        data = resp.json()
        assert len(data["queries"]) == 2
        assert data["total"] == 5
        assert data["offset"] == 3

    def test_offset_beyond_total(self, client):
        self._create_queries(client, 3)
        resp = client.get("/api/saved-queries/", params={"offset": 100})
        data = resp.json()
        assert len(data["queries"]) == 0
        assert data["total"] == 3

    def test_limit_one(self, client):
        self._create_queries(client, 3)
        resp = client.get("/api/saved-queries/", params={"limit": 1})
        data = resp.json()
        assert len(data["queries"]) == 1
        assert data["total"] == 3

    def test_pagination_with_cdm_filter(self, client):
        """Pagination should work together with cdm_name filter."""
        for i in range(4):
            client.post("/api/saved-queries/", json={
                "cdm_name": "cdm_a", "name": f"QA{i}", "sql": f"SELECT {i}",
            })
        client.post("/api/saved-queries/", json={
            "cdm_name": "cdm_b", "name": "QB", "sql": "SELECT 99",
        })

        resp = client.get("/api/saved-queries/", params={"cdm_name": "cdm_a", "limit": 2})
        data = resp.json()
        assert len(data["queries"]) == 2
        assert data["total"] == 4


# ── Favorites Pagination ──

class TestFavoritesPagination:

    def _create_favorites(self, client, n=5):
        ids = []
        for i in range(n):
            resp = client.post("/api/favorites/", json={
                "item_type": "cohort",
                "item_id": str(i),
                "item_label": f"Favorite {i}",
            })
            ids.append(resp.json()["id"])
        return ids

    def test_default_returns_all(self, client):
        self._create_favorites(client, 3)
        resp = client.get("/api/favorites/")
        data = resp.json()
        assert len(data["favorites"]) == 3
        assert data["total"] == 3
        assert data["limit"] == 100
        assert data["offset"] == 0

    def test_limit(self, client):
        self._create_favorites(client, 5)
        resp = client.get("/api/favorites/", params={"limit": 2})
        data = resp.json()
        assert len(data["favorites"]) == 2
        assert data["total"] == 5

    def test_offset(self, client):
        self._create_favorites(client, 5)
        resp = client.get("/api/favorites/", params={"limit": 2, "offset": 3})
        data = resp.json()
        assert len(data["favorites"]) == 2
        assert data["total"] == 5
        assert data["offset"] == 3

    def test_offset_beyond_total(self, client):
        self._create_favorites(client, 3)
        resp = client.get("/api/favorites/", params={"offset": 100})
        data = resp.json()
        assert len(data["favorites"]) == 0
        assert data["total"] == 3

    def test_limit_one(self, client):
        self._create_favorites(client, 3)
        resp = client.get("/api/favorites/", params={"limit": 1})
        data = resp.json()
        assert len(data["favorites"]) == 1
        assert data["total"] == 3

    def test_pagination_with_type_filter(self, client):
        """Pagination should work together with item_type filter."""
        for i in range(4):
            client.post("/api/favorites/", json={
                "item_type": "cohort", "item_id": f"c{i}", "item_label": f"C{i}",
            })
        client.post("/api/favorites/", json={
            "item_type": "concept", "item_id": "x1", "item_label": "X",
        })

        resp = client.get("/api/favorites/", params={"item_type": "cohort", "limit": 2})
        data = resp.json()
        assert len(data["favorites"]) == 2
        assert data["total"] == 4

    def test_response_includes_pagination_metadata(self, client):
        """Response should always include total, limit, offset."""
        resp = client.get("/api/favorites/", params={"limit": 10, "offset": 5})
        data = resp.json()
        assert "total" in data
        assert data["limit"] == 10
        assert data["offset"] == 5
