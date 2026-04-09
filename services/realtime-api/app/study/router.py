"""FastAPI router for the vocabulary study subsystem."""
from __future__ import annotations

from typing import Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from .service import StudyService

router = APIRouter(prefix="/api/study", tags=["study"])


def _svc(request: Request) -> StudyService:
    return request.app.state.study_service


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------

class StudyItemCreate(BaseModel):
    item_type: Literal["word", "phrase", "sentence"] = "word"
    target_text: str = Field(min_length=1)
    native_text: str = ""
    context_note: str = ""
    example_sentence: str = ""
    source_kind: Literal["manual", "mcp_extract", "mcp_manual"] = "manual"
    source_turn_text: str = ""
    source_response_text: str = ""
    language_target: str = "en"
    language_native: str = "ru"


class AddItemsRequest(BaseModel):
    items: list[StudyItemCreate]


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]


class UpdateItemRequest(BaseModel):
    item_type: Optional[Literal["word", "phrase", "sentence"]] = None
    target_text: Optional[str] = None
    native_text: Optional[str] = None
    context_note: Optional[str] = None
    example_sentence: Optional[str] = None
    status: Optional[Literal["new", "learning", "review", "suspended"]] = None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post("/items", status_code=201)
def add_items(body: AddItemsRequest, request: Request) -> dict[str, Any]:
    """Bulk-insert study items. Duplicate entries are silently skipped."""
    return _svc(request).add_items([item.model_dump() for item in body.items])


@router.get("/items")
def list_items(
    request: Request,
    status: str | None = Query(None, description="Filter by status: new|learning|review|suspended"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Return study items, optionally filtered by status."""
    return _svc(request).get_items(status=status, limit=limit, offset=offset)


@router.get("/due")
def due_items(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
) -> list[dict[str, Any]]:
    """Return items due for review, ordered: new → learning → review."""
    return _svc(request).get_due(limit=limit)


@router.post("/review/{item_id}")
def review(item_id: int, body: ReviewRequest, request: Request) -> dict[str, Any]:
    """Submit a review rating for one item. Returns the updated item."""
    try:
        return _svc(request).review_item(item_id, body.rating)
    except ValueError as exc:
        code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc))


@router.patch("/items/{item_id}")
def update_item(item_id: int, body: UpdateItemRequest, request: Request) -> dict[str, Any]:
    """Update editable fields of a study item. Returns the updated item."""
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    try:
        return _svc(request).update_item(item_id, updates)
    except ValueError as exc:
        code = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=code, detail=str(exc))


@router.delete("/items/{item_id}", status_code=204)
def delete_item(item_id: int, request: Request) -> None:
    """Delete a study item and all its review history."""
    try:
        _svc(request).delete_item(item_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    """Return per-status counts, due count, and total review events."""
    return _svc(request).stats()
