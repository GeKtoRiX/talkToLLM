"""FastAPI router for the vocabulary study subsystem."""
from __future__ import annotations

from typing import Any, List, Literal, Optional

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
    item_type: Literal["word", "phrase", "phrasal_verb", "idiom", "collocation"] = "word"
    target_text: str = Field(min_length=1)
    native_text: str = ""
    context_note: str = ""
    example_sentence: str = ""
    source_kind: Literal["manual", "mcp_extract", "mcp_manual"] = "manual"
    source_turn_text: str = ""
    source_response_text: str = ""
    language_target: str = "en"
    language_native: str = "ru"
    # vocabulary metadata (optional)
    lexical_type: Optional[str] = None
    alternative_translations: List[str] = []
    topic: str = ""
    difficulty_level: Optional[int] = Field(default=None, ge=1, le=5)
    tags: List[str] = []
    example_sentence_native: str = ""


class AddItemsRequest(BaseModel):
    items: list[StudyItemCreate]


class ReviewRequest(BaseModel):
    rating: Literal["again", "hard", "good", "easy"]


class UpdateItemRequest(BaseModel):
    item_type: Optional[Literal["word", "phrase", "phrasal_verb", "idiom", "collocation"]] = None
    target_text: Optional[str] = None
    native_text: Optional[str] = None
    context_note: Optional[str] = None
    example_sentence: Optional[str] = None
    status: Optional[Literal[
        "new", "learning", "review", "mastered", "difficult", "suspended"
    ]] = None
    # vocabulary metadata
    lexical_type: Optional[str] = None
    alternative_translations: Optional[List[str]] = None
    topic: Optional[str] = None
    difficulty_level: Optional[int] = Field(default=None, ge=1, le=5)
    tags: Optional[List[str]] = None
    example_sentence_native: Optional[str] = None


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
    status: str | None = Query(None),
    lexical_type: str | None = Query(None),
    item_type: str | None = Query(None),
    topic: str | None = Query(None),
    difficulty_min: Optional[int] = Query(None, ge=1, le=5),
    difficulty_max: Optional[int] = Query(None, ge=1, le=5),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> list[dict[str, Any]]:
    """Return study items with optional filters."""
    return _svc(request).get_items(
        status=status,
        lexical_type=lexical_type,
        item_type=item_type,
        topic=topic,
        difficulty_min=difficulty_min,
        difficulty_max=difficulty_max,
        limit=limit,
        offset=offset,
    )


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
