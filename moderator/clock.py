"""Demo clock: starts at a fixed moment so replays are deterministic; waits are compressed."""

from __future__ import annotations

from datetime import date, datetime, timedelta

DEFAULT_START = datetime(2026, 10, 8, 12, 0)


class Clock:
    def __init__(self, start: datetime | None = None):
        self._start = start or DEFAULT_START
        self._offset = timedelta()

    def now(self) -> datetime:
        return self._start + self._offset

    def today(self) -> date:
        return self.now().date()

    def advance(self, hours: float) -> datetime:
        self._offset += timedelta(hours=hours)
        return self.now()
