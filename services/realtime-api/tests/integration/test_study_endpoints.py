"""Integration tests for the /api/study REST endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app


@pytest.fixture
def study_app(tmp_path):
    """FastAPI app with mock providers and an isolated temp study DB."""
    return create_app(
        AppSettings(
            llm_provider="mock",
            stt_provider="mock",
            tts_provider="mock",
            study_db_path=str(tmp_path / "test_study.sqlite"),
        )
    )


@pytest.fixture
def client(study_app):
    with TestClient(study_app) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /api/study/items
# ---------------------------------------------------------------------------

class TestAddItems:
    def test_add_single_item(self, client):
        resp = client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "ephemeral", "native_text": "мимолётный"}
        ]})
        assert resp.status_code == 201
        data = resp.json()
        assert data["saved"] == 1
        assert data["skipped"] == 0
        assert len(data["ids"]) == 1

    def test_add_duplicate_skipped(self, client):
        payload = {"items": [{"item_type": "word", "target_text": "dupe"}]}
        client.post("/api/study/items", json=payload)
        resp = client.post("/api/study/items", json=payload)
        assert resp.status_code == 201
        assert resp.json()["skipped"] == 1
        assert resp.json()["saved"] == 0

    def test_add_mixed_batch(self, client):
        resp = client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "alpha"},
            {"item_type": "word", "target_text": "alpha"},  # duplicate in same batch
            {"item_type": "collocation", "target_text": "beta"},
        ]})
        assert resp.status_code == 201
        data = resp.json()
        # "alpha" saves once, second "alpha" is a dup (after the first is committed)
        assert data["saved"] + data["skipped"] == 3

    def test_add_empty_items_list(self, client):
        resp = client.post("/api/study/items", json={"items": []})
        assert resp.status_code == 201
        assert resp.json()["saved"] == 0


# ---------------------------------------------------------------------------
# GET /api/study/items
# ---------------------------------------------------------------------------

class TestListItems:
    def test_list_empty(self, client):
        resp = client.get("/api/study/items")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_returns_added_items(self, client):
        client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "test"}
        ]})
        resp = client.get("/api/study/items")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_list_filter_by_status(self, client):
        client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "new_word"}
        ]})
        resp = client.get("/api/study/items?status=new")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        resp2 = client.get("/api/study/items?status=review")
        assert resp2.json() == []

    def test_list_limit(self, client):
        for i in range(5):
            client.post("/api/study/items", json={"items": [
                {"item_type": "word", "target_text": f"word{i}"}
            ]})
        resp = client.get("/api/study/items?limit=3")
        assert len(resp.json()) == 3


# ---------------------------------------------------------------------------
# GET /api/study/due
# ---------------------------------------------------------------------------

class TestDueItems:
    def test_due_returns_new_items(self, client):
        client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "fresh"}
        ]})
        resp = client.get("/api/study/due")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    def test_due_limit_param(self, client):
        for i in range(5):
            client.post("/api/study/items", json={"items": [
                {"item_type": "word", "target_text": f"w{i}"}
            ]})
        resp = client.get("/api/study/due?limit=2")
        assert len(resp.json()) == 2

    def test_due_empty_when_no_items(self, client):
        resp = client.get("/api/study/due")
        assert resp.json() == []


# ---------------------------------------------------------------------------
# POST /api/study/review/{item_id}
# ---------------------------------------------------------------------------

class TestReview:
    def _add_and_get_id(self, client) -> int:
        resp = client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "review_target"}
        ]})
        return resp.json()["ids"][0]

    def test_review_good_returns_updated_item(self, client):
        item_id = self._add_and_get_id(client)
        resp = client.post(f"/api/study/review/{item_id}", json={"rating": "good"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == item_id
        assert data["repetitions"] == 1

    def test_review_again_resets(self, client):
        item_id = self._add_and_get_id(client)
        # Advance first
        client.post(f"/api/study/review/{item_id}", json={"rating": "good"})
        client.post(f"/api/study/review/{item_id}", json={"rating": "good"})
        # Then fail
        resp = client.post(f"/api/study/review/{item_id}", json={"rating": "again"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["repetitions"] == 0
        assert data["lapses"] == 1

    def test_review_invalid_rating_returns_400(self, client):
        item_id = self._add_and_get_id(client)
        resp = client.post(f"/api/study/review/{item_id}", json={"rating": "unknown"})
        assert resp.status_code == 422  # Pydantic validation rejects the enum

    def test_review_unknown_item_returns_404(self, client):
        resp = client.post("/api/study/review/9999", json={"rating": "good"})
        assert resp.status_code == 404

    def test_review_all_ratings(self, client):
        for rating in ("again", "hard", "good", "easy"):
            resp_add = client.post("/api/study/items", json={"items": [
                {"item_type": "word", "target_text": f"target_{rating}"}
            ]})
            item_id = resp_add.json()["ids"][0]
            resp = client.post(f"/api/study/review/{item_id}", json={"rating": rating})
            assert resp.status_code == 200, f"Rating '{rating}' should succeed"


# ---------------------------------------------------------------------------
# GET /api/study/stats
# ---------------------------------------------------------------------------

class TestUpdateItem:
    def _add(self, client) -> int:
        resp = client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "update_target"}
        ]})
        return resp.json()["ids"][0]

    def test_patch_native_text(self, client):
        item_id = self._add(client)
        resp = client.patch(f"/api/study/items/{item_id}", json={"native_text": "перевод"})
        assert resp.status_code == 200
        assert resp.json()["native_text"] == "перевод"

    def test_patch_status_suspended(self, client):
        item_id = self._add(client)
        resp = client.patch(f"/api/study/items/{item_id}", json={"status": "suspended"})
        assert resp.status_code == 200
        assert resp.json()["status"] == "suspended"

    def test_patch_unknown_item_returns_404(self, client):
        resp = client.patch("/api/study/items/9999", json={"native_text": "x"})
        assert resp.status_code == 404

    def test_patch_invalid_status_returns_422(self, client):
        item_id = self._add(client)
        resp = client.patch(f"/api/study/items/{item_id}", json={"status": "unknown"})
        assert resp.status_code == 422  # Pydantic rejects the Literal at deserialization

    def test_patch_multiple_fields(self, client):
        item_id = self._add(client)
        resp = client.patch(f"/api/study/items/{item_id}", json={
            "native_text": "n",
            "context_note": "c",
            "example_sentence": "e",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["native_text"] == "n"
        assert data["context_note"] == "c"
        assert data["example_sentence"] == "e"


class TestDeleteItem:
    def _add(self, client) -> int:
        resp = client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "delete_target"}
        ]})
        return resp.json()["ids"][0]

    def test_delete_returns_204(self, client):
        item_id = self._add(client)
        resp = client.delete(f"/api/study/items/{item_id}")
        assert resp.status_code == 204

    def test_delete_removes_from_list(self, client):
        item_id = self._add(client)
        client.delete(f"/api/study/items/{item_id}")
        resp = client.get("/api/study/items")
        ids = [it["id"] for it in resp.json()]
        assert item_id not in ids

    def test_delete_unknown_item_returns_404(self, client):
        resp = client.delete("/api/study/items/9999")
        assert resp.status_code == 404

    def test_delete_updates_stats(self, client):
        item_id = self._add(client)
        client.delete(f"/api/study/items/{item_id}")
        stats = client.get("/api/study/stats").json()
        assert stats["total_items"] == 0


class TestStats:
    def test_stats_empty(self, client):
        resp = client.get("/api/study/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_items"] == 0
        assert data["due"] == 0
        assert data["total_reviews"] == 0

    def test_stats_after_adding_items(self, client):
        client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "a"},
            {"item_type": "word", "target_text": "b"},
        ]})
        resp = client.get("/api/study/stats")
        data = resp.json()
        assert data["total_items"] == 2
        assert data["new"] == 2
        assert data["due"] == 2

    def test_stats_after_review(self, client):
        resp_add = client.post("/api/study/items", json={"items": [
            {"item_type": "word", "target_text": "reviewed"}
        ]})
        item_id = resp_add.json()["ids"][0]
        client.post(f"/api/study/review/{item_id}", json={"rating": "easy"})
        resp = client.get("/api/study/stats")
        data = resp.json()
        assert data["total_reviews"] == 1
        # After easy on first rep, status = review
        assert data["review"] == 1
        assert data["new"] == 0
