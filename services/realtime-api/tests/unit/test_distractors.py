"""Unit tests for DistractorSelector."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.study.db import init_db
from app.training.db import migrate_db
from app.training.distractors import DistractorSelector


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path) -> Path:
    p = tmp_path / "study.sqlite"
    init_db(p)
    migrate_db(p)
    return p


@pytest.fixture
def selector(db_path) -> DistractorSelector:
    return DistractorSelector(db_path)


def _insert_item(db_path: Path, target: str, native: str, item_type: str = "word",
                 lexical_type: str | None = None) -> int:
    from app.study.db import get_db
    with get_db(db_path) as conn:
        conn.execute(
            "INSERT INTO study_items(item_type, target_text, native_text, lexical_type) "
            "VALUES (?, ?, ?, ?)",
            (item_type, target, native, lexical_type),
        )
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# ---------------------------------------------------------------------------
# Tests: basic distractor selection
# ---------------------------------------------------------------------------

class TestSelectNativeDistractors:
    def test_returns_exactly_n_items(self, db_path, selector):
        ids = []
        for i in range(10):
            ids.append(_insert_item(db_path, f"word{i}", f"слово{i}", "word", "noun"))
        result = selector.select_native_distractors(ids[0], "word", "noun", n=3)
        assert len(result) == 3

    def test_never_includes_item_itself(self, db_path, selector):
        iid = _insert_item(db_path, "ephemeral", "кратковременный", "word", "adjective")
        for i in range(5):
            _insert_item(db_path, f"other{i}", f"другой{i}", "word", "adjective")
        result = selector.select_native_distractors(iid, "word", "adjective", n=3)
        assert "кратковременный" not in result

    def test_result_does_not_contain_duplicates(self, db_path, selector):
        iid = _insert_item(db_path, "unique", "уникальный", "word", "adjective")
        for i in range(10):
            _insert_item(db_path, f"adj{i}", f"прил{i}", "word", "adjective")
        result = selector.select_native_distractors(iid, "word", "adjective", n=3)
        assert len(result) == len(set(result))

    def test_falls_back_to_padding_when_pool_empty(self, db_path, selector):
        # Only one item in DB — no pool for distractors
        iid = _insert_item(db_path, "alone", "одинокий", "word", "adjective")
        result = selector.select_native_distractors(iid, "word", "adjective", n=3)
        assert len(result) == 3
        # At least some fallbacks must be present
        from app.training.distractors import _FALLBACK_DISTRACTORS
        assert any(v in _FALLBACK_DISTRACTORS for v in result)

    def test_partial_pool_padded_to_n(self, db_path, selector):
        iid = _insert_item(db_path, "main", "главный", "word")
        _insert_item(db_path, "other1", "другой1", "word")  # only 1 candidate
        result = selector.select_native_distractors(iid, "word", None, n=3)
        assert len(result) == 3


# ---------------------------------------------------------------------------
# Tests: tier selection
# ---------------------------------------------------------------------------

class TestTierSelection:
    def test_prefers_same_lexical_and_item_type(self, db_path, selector):
        iid = _insert_item(db_path, "run", "бежать", "word", "verb")
        # Tier 1: same lexical + same item_type
        for i in range(5):
            _insert_item(db_path, f"verb_word_{i}", f"глагол_{i}", "word", "verb")
        # Tier 3: same item_type only
        for i in range(5):
            _insert_item(db_path, f"noun_word_{i}", f"сущ_{i}", "word", "noun")

        result = selector.select_native_distractors(iid, "word", "verb", n=3, seed=42)
        # All 3 should come from Tier 1 (verbs matching both criteria)
        assert all(v.startswith("глагол_") for v in result)

    def test_falls_back_to_same_item_type_when_no_lexical_match(self, db_path, selector):
        iid = _insert_item(db_path, "spill", "расплескать", "phrasal_verb", "verb")
        # No other phrasal_verb+verb in DB; but same item_type exists
        for i in range(5):
            _insert_item(db_path, f"pv_{i}", f"фразовый_{i}", "phrasal_verb", "noun")

        result = selector.select_native_distractors(iid, "phrasal_verb", "verb", n=3, seed=0)
        assert len(result) == 3
        assert all(v.startswith("фразовый_") for v in result)

    def test_falls_back_to_anything_when_no_type_match(self, db_path, selector):
        iid = _insert_item(db_path, "spill beans", "раскрыть секрет", "idiom", "idiom")
        # No idioms in DB; add phrases
        for i in range(5):
            _insert_item(db_path, f"phrase_{i}", f"фраза_{i}", "phrase", "noun")

        result = selector.select_native_distractors(iid, "idiom", "idiom", n=3, seed=1)
        assert len(result) == 3

    def test_items_without_native_text_excluded(self, db_path, selector):
        iid = _insert_item(db_path, "main_item", "главное", "word", "noun")
        # Insert items with empty native_text — should be excluded
        from app.study.db import get_db
        with get_db(db_path) as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO study_items(item_type, target_text, native_text, lexical_type) "
                    "VALUES ('word', ?, '', 'noun')",
                    (f"empty_native_{i}",),
                )
        # Add 3 valid candidates
        for i in range(3):
            _insert_item(db_path, f"valid_{i}", f"валидный_{i}", "word", "noun")

        result = selector.select_native_distractors(iid, "word", "noun", n=3)
        assert not any(v == "" for v in result)


# ---------------------------------------------------------------------------
# Tests: target distractors
# ---------------------------------------------------------------------------

class TestSelectTargetDistractors:
    def test_returns_target_texts(self, db_path, selector):
        iid = _insert_item(db_path, "give_up", "сдаться", "phrasal_verb", "verb")
        for i in range(5):
            _insert_item(db_path, f"pv_target_{i}", f"фразовый_{i}", "phrasal_verb", "verb")

        result = selector.select_target_distractors(iid, "phrasal_verb", "verb", n=3, seed=7)
        assert len(result) == 3
        assert all(v.startswith("pv_target_") for v in result)
