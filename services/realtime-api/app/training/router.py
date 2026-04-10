"""FastAPI router for the training module.

All business logic is delegated to TrainingService.
This module is responsible only for HTTP plumbing.
"""
from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request

from app.training.models import (
    AnswerRequest,
    CompleteSessionRequest,
    CreateSessionRequest,
)
from app.training.service import TrainingService

router = APIRouter(prefix="/api/training", tags=["training"])


def _svc(request: Request) -> TrainingService:
    return request.app.state.training_service


# ---------------------------------------------------------------------------
# Sessions
# ---------------------------------------------------------------------------


@router.post("/sessions", status_code=201)
def create_session(body: CreateSessionRequest, request: Request) -> dict[str, Any]:
    """Create a new training session.

    Returns the session object and the first question (or null if no items).
    """
    session, question = _svc(request).create_session(
        mode=body.mode,
        filters=body.filters.model_dump(exclude_none=True),
        target_count=body.target_count,
    )
    return {"session": session, "question": question}


@router.get("/sessions/{session_id}")
def get_session(session_id: int, request: Request) -> dict[str, Any]:
    try:
        session, question, remaining = _svc(request).get_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {
        "session": session,
        "current_question": question,
        "questions_remaining": remaining,
    }


@router.post("/sessions/{session_id}/answer")
def submit_answer(
    session_id: int, body: AnswerRequest, request: Request
) -> dict[str, Any]:
    try:
        return _svc(request).submit_answer(session_id, body.question_id, body.answer_given)
    except ValueError as exc:
        code = 404 if "not found" in str(exc).lower() else 400
        raise HTTPException(status_code=code, detail=str(exc))


@router.post("/sessions/{session_id}/complete")
def complete_session(
    session_id: int, body: CompleteSessionRequest, request: Request
) -> dict[str, Any]:
    try:
        return _svc(request).complete_session(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/sessions/{session_id}/results")
def get_session_results(session_id: int, request: Request) -> dict[str, Any]:
    try:
        return _svc(request).get_session_results(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Progress & statistics
# ---------------------------------------------------------------------------


@router.get("/progress/{item_id}")
def get_item_progress(item_id: int, request: Request) -> dict[str, Any]:
    try:
        return _svc(request).get_item_progress(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/stats/user")
def get_user_stats(request: Request) -> dict[str, Any]:
    return _svc(request).get_user_stats()


@router.get("/stats/session/{session_id}")
def get_session_stats(session_id: int, request: Request) -> dict[str, Any]:
    try:
        return _svc(request).get_session_results(session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ---------------------------------------------------------------------------
# Vocabulary filtering
# ---------------------------------------------------------------------------


@router.get("/items")
def get_items(
    request: Request,
    mode: Optional[str] = Query(default=None),
    lexical_type: Optional[str] = Query(default=None),
    item_type: Optional[str] = Query(default=None),
    topic: Optional[str] = Query(default=None),
    difficulty_min: Optional[int] = Query(default=None, ge=1, le=5),
    difficulty_max: Optional[int] = Query(default=None, ge=1, le=5),
    status: Optional[list[str]] = Query(default=None),
    language_target: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
) -> list[dict[str, Any]]:
    return _svc(request).get_filtered_items(
        mode=mode,
        lexical_type=lexical_type,
        item_type=item_type,
        topic=topic,
        difficulty_min=difficulty_min,
        difficulty_max=difficulty_max,
        status=status,
        language_target=language_target,
        limit=limit,
    )
