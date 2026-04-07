import pytest

from app.core.interruption import InterruptionManager


@pytest.mark.asyncio
async def test_interruption_manager_marks_and_clears_turns():
    manager = InterruptionManager()
    turn_id = "turn-123"

    assert await manager.is_cancelled(turn_id) is False
    await manager.mark_cancelled(turn_id)
    assert await manager.is_cancelled(turn_id) is True
    await manager.clear(turn_id)
    assert await manager.is_cancelled(turn_id) is False

