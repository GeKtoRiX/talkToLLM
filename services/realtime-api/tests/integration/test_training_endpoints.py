"""Integration tests for /api/training/* endpoints."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.config import AppSettings
from app.main import create_app
from app.study.db import get_db


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def training_app(tmp_path):
    return create_app(
        AppSettings(
            llm_provider="mock",
            stt_provider="mock",
            tts_provider="mock",
            study_db_path=str(tmp_path / "test_training.sqlite"),
        )
    )


@pytest.fixture
def client(training_app):
    with TestClient(training_app) as c:
        yield c


def _add_item(client, target: str, native: str = "перевод",
              item_type: str = "word") -> dict:
    resp = client.post("/api/study/items", json={
        "items": [{"target_text": target, "native_text": native, "item_type": item_type}]
    })
    assert resp.status_code == 201
    return resp.json()


def _populate_db(client, n: int = 5):
    """Add n items with distractors."""
    for i in range(n):
        _add_item(client, f"word{i}", f"слово{i}")


# ---------------------------------------------------------------------------
# POST /api/training/sessions
# ---------------------------------------------------------------------------

class TestCreateSession:
    def test_empty_db_returns_completed_session(self, client):
        resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 10})
        assert resp.status_code == 201
        data = resp.json()
        assert data["session"]["status"] == "completed"
        assert data["question"] is None

    def test_creates_active_session_with_items(self, client):
        _populate_db(client, 5)
        resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 5})
        assert resp.status_code == 201
        data = resp.json()
        assert data["session"]["status"] == "active"
        assert data["question"] is not None

    def test_question_has_required_fields(self, client):
        _populate_db(client, 5)
        resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 5})
        q = resp.json()["question"]
        for field in ("id", "session_id", "item_id", "exercise_type",
                      "correct_answer", "prompt_text"):
            assert field in q, f"Missing field: {field}"

    def test_mode_new_only(self, client):
        _populate_db(client, 3)
        resp = client.post("/api/training/sessions", json={"mode": "new_only", "target_count": 5})
        assert resp.status_code == 201
        assert resp.json()["session"]["mode"] == "new_only"

    def test_filter_by_item_type(self, client):
        _add_item(client, "give up", "сдаться", "phrasal_verb")
        _add_item(client, "apple", "яблоко", "word")
        resp = client.post("/api/training/sessions", json={
            "mode": "auto",
            "filters": {"item_type": "phrasal_verb"},
            "target_count": 5,
        })
        assert resp.status_code == 201

    def test_invalid_target_count_returns_422(self, client):
        resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 0})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# GET /api/training/sessions/{id}
# ---------------------------------------------------------------------------

class TestGetSession:
    def test_get_existing_session(self, client):
        _populate_db(client, 3)
        create_resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 3})
        sid = create_resp.json()["session"]["id"]

        resp = client.get(f"/api/training/sessions/{sid}")
        assert resp.status_code == 200
        data = resp.json()
        assert "session" in data
        assert "current_question" in data
        assert "questions_remaining" in data

    def test_get_nonexistent_session_returns_404(self, client):
        resp = client.get("/api/training/sessions/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/training/sessions/{id}/answer
# ---------------------------------------------------------------------------

class TestSubmitAnswer:
    def _create_active_session(self, client):
        _populate_db(client, 5)
        resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 5})
        data = resp.json()
        return data["session"], data["question"]

    def test_correct_answer_returns_200(self, client):
        session, q = self._create_active_session(client)
        resp = client.post(f"/api/training/sessions/{session['id']}/answer", json={
            "question_id": q["id"],
            "answer_given": q["correct_answer"],
        })
        assert resp.status_code == 200
        assert resp.json()["is_correct"] is True

    def test_wrong_answer_returns_200_with_is_correct_false(self, client):
        session, q = self._create_active_session(client)
        resp = client.post(f"/api/training/sessions/{session['id']}/answer", json={
            "question_id": q["id"],
            "answer_given": "COMPLETELY_WRONG_XYZ",
        })
        assert resp.status_code == 200
        assert resp.json()["is_correct"] is False

    def test_answer_response_has_required_fields(self, client):
        session, q = self._create_active_session(client)
        resp = client.post(f"/api/training/sessions/{session['id']}/answer", json={
            "question_id": q["id"],
            "answer_given": q["correct_answer"],
        })
        data = resp.json()
        for field in ("is_correct", "error_type", "correct_answer",
                      "session_complete", "newly_mastered"):
            assert field in data

    def test_duplicate_answer_returns_400(self, client):
        session, q = self._create_active_session(client)
        client.post(f"/api/training/sessions/{session['id']}/answer", json={
            "question_id": q["id"],
            "answer_given": q["correct_answer"],
        })
        resp = client.post(f"/api/training/sessions/{session['id']}/answer", json={
            "question_id": q["id"],
            "answer_given": q["correct_answer"],
        })
        assert resp.status_code == 400

    def test_answer_wrong_question_id_returns_400(self, client):
        session, q = self._create_active_session(client)
        resp = client.post(f"/api/training/sessions/{session['id']}/answer", json={
            "question_id": 99999,
            "answer_given": "answer",
        })
        assert resp.status_code in (400, 404)


# ---------------------------------------------------------------------------
# Full session flow
# ---------------------------------------------------------------------------

class TestFullSessionFlow:
    def test_complete_session_flow(self, client):
        """Create session → answer all questions → get results."""
        _populate_db(client, 5)
        # Create
        create_resp = client.post("/api/training/sessions", json={
            "mode": "auto", "target_count": 3
        })
        assert create_resp.status_code == 201
        session = create_resp.json()["session"]
        question = create_resp.json()["question"]
        sid = session["id"]

        # Answer all questions correctly
        answered = 0
        max_iterations = 30  # safety limit against infinite loops
        while question is not None and answered < max_iterations:
            resp = client.post(f"/api/training/sessions/{sid}/answer", json={
                "question_id": question["id"],
                "answer_given": question["correct_answer"],
            })
            assert resp.status_code == 200
            data = resp.json()
            answered += 1
            if data["session_complete"]:
                break
            question = data.get("next_question")

        # Get results
        results_resp = client.get(f"/api/training/sessions/{sid}/results")
        assert results_resp.status_code == 200
        results = results_resp.json()
        assert results["session_id"] == sid
        assert results["correct_count"] >= 1
        assert "by_exercise_type" in results


# ---------------------------------------------------------------------------
# POST /api/training/sessions/{id}/complete
# ---------------------------------------------------------------------------

class TestCompleteSession:
    def test_complete_sets_status(self, client):
        _populate_db(client, 3)
        resp = client.post("/api/training/sessions", json={"mode": "auto", "target_count": 3})
        sid = resp.json()["session"]["id"]

        comp_resp = client.post(f"/api/training/sessions/{sid}/complete", json={})
        assert comp_resp.status_code == 200
        assert "session_id" in comp_resp.json()


# ---------------------------------------------------------------------------
# GET /api/training/stats/user
# ---------------------------------------------------------------------------

class TestUserStats:
    def test_returns_expected_shape(self, client):
        resp = client.get("/api/training/stats/user")
        assert resp.status_code == 200
        data = resp.json()
        for key in ("total_items", "new", "learning", "mastered",
                    "by_lexical_type", "by_item_type", "overall_accuracy_pct"):
            assert key in data

    def test_total_items_reflects_db(self, client):
        _populate_db(client, 3)
        resp = client.get("/api/training/stats/user")
        assert resp.json()["total_items"] >= 3


# ---------------------------------------------------------------------------
# GET /api/training/progress/{item_id}
# ---------------------------------------------------------------------------

class TestItemProgress:
    def test_no_progress_before_session_returns_404(self, client):
        _populate_db(client, 1)
        # Item 1 exists but progress row hasn't been created yet
        resp = client.get("/api/training/progress/1")
        assert resp.status_code == 404

    def test_progress_available_after_session_created(self, client):
        _populate_db(client, 5)
        create_resp = client.post("/api/training/sessions", json={
            "mode": "auto", "target_count": 5
        })
        q = create_resp.json()["question"]
        item_id = q["item_id"]
        resp = client.get(f"/api/training/progress/{item_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["item_id"] == item_id

    def test_nonexistent_item_returns_404(self, client):
        resp = client.get("/api/training/progress/99999")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/training/items
# ---------------------------------------------------------------------------

class TestGetFilteredItems:
    def test_returns_items(self, client):
        _populate_db(client, 3)
        resp = client.get("/api/training/items")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_filter_by_item_type(self, client):
        _add_item(client, "give up", "сдаться", "phrasal_verb")
        _add_item(client, "apple", "яблоко", "word")
        resp = client.get("/api/training/items?item_type=phrasal_verb")
        assert resp.status_code == 200
        data = resp.json()
        assert all(r["item_type"] == "phrasal_verb" for r in data)

    def test_limit_param(self, client):
        _populate_db(client, 10)
        resp = client.get("/api/training/items?limit=3")
        assert resp.status_code == 200
        assert len(resp.json()) <= 3

    def test_invalid_limit_returns_422(self, client):
        resp = client.get("/api/training/items?limit=0")
        assert resp.status_code == 422
