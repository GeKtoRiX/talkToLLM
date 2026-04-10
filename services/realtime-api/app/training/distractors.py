"""Distractor selector for multiple-choice and context-choice exercises.

Selects semantically plausible wrong-answer options from the vocabulary DB.
Uses a four-tier priority system to pick the most confusable distractors.
"""
from __future__ import annotations

import random
from pathlib import Path

from app.study.db import get_db

# Fallback strings used when the vocabulary pool is too small.
_FALLBACK_DISTRACTORS = ["—", "not applicable", "none of these"]


class DistractorSelector:
    """Select n native-language distractors for a given study item.

    The selector queries the DB live (lightweight — only 4 columns) rather
    than receiving the full item list as a parameter, which keeps the call
    site simple.
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def select_native_distractors(
        self,
        item_id: int,
        item_type: str,
        lexical_type: str | None,
        n: int = 3,
        *,
        seed: int | None = None,
    ) -> list[str]:
        """Return n native_text strings suitable as wrong-answer options.

        Tier selection (first tier with enough candidates wins):
          1. Same lexical_type AND same item_type
          2. Same lexical_type only
          3. Same item_type only
          4. Anything (excluding the item itself and items with empty native_text)

        If the total pool has fewer than n items, pads with fallback strings.
        """
        candidates = self._load_candidates(item_id)
        selected = self._pick_from_tiers(
            candidates, item_type, lexical_type, n, seed=seed
        )
        return selected

    def select_target_distractors(
        self,
        item_id: int,
        item_type: str,
        lexical_type: str | None,
        n: int = 3,
        *,
        seed: int | None = None,
    ) -> list[str]:
        """Return n target_text strings (for context-choice prompts)."""
        candidates = self._load_candidates(item_id, field="target_text")
        selected = self._pick_from_tiers(
            candidates, item_type, lexical_type, n, seed=seed
        )
        return selected

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_candidates(
        self, item_id: int, field: str = "native_text"
    ) -> list[dict]:
        """Load all eligible candidates from the DB."""
        with get_db(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT id, item_type, lexical_type, {field} AS value
                FROM   study_items
                WHERE  id != ?
                  AND  {field} != ''
                  AND  status != 'suspended'
                """,
                (item_id,),
            ).fetchall()
        return [dict(r) for r in rows]

    def _pick_from_tiers(
        self,
        candidates: list[dict],
        item_type: str,
        lexical_type: str | None,
        n: int,
        *,
        seed: int | None,
    ) -> list[str]:
        rng = random.Random(seed)

        def _tier(lt_match: bool, it_match: bool) -> list[dict]:
            return [
                c for c in candidates
                if (not lt_match or c["lexical_type"] == lexical_type)
                and (not it_match or c["item_type"] == item_type)
            ]

        # Tier 1 → 4 (pick first non-empty tier with ≥ n items; fall back if needed)
        pool: list[dict] = []
        for lt, it in ((True, True), (True, False), (False, True), (False, False)):
            tier = _tier(lt, it)
            if len(tier) >= n:
                pool = tier
                break
        if not pool:
            # Use whatever we have, even if fewer than n
            pool = candidates

        selected = rng.sample(pool, min(n, len(pool)))
        values = [c["value"] for c in selected]

        # Pad with fallbacks if the vocabulary is sparse
        if len(values) < n:
            needed = n - len(values)
            values.extend(_FALLBACK_DISTRACTORS[:needed])

        return values
