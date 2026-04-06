import asyncio


class InterruptionManager:
    def __init__(self) -> None:
        self._cancelled_turns: set[str] = set()
        self._lock = asyncio.Lock()

    async def mark_cancelled(self, turn_id: str) -> None:
        async with self._lock:
            self._cancelled_turns.add(turn_id)

    async def clear(self, turn_id: str) -> None:
        async with self._lock:
            self._cancelled_turns.discard(turn_id)

    async def is_cancelled(self, turn_id: str) -> bool:
        async with self._lock:
            return turn_id in self._cancelled_turns

