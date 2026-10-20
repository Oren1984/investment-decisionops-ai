"""Single injectable clock so every time-dependent behaviour is testable."""

from datetime import UTC, datetime


class Clock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock(Clock):
    def __init__(self, at: datetime):
        self.at = at

    def now(self) -> datetime:
        return self.at

    def set(self, at: datetime) -> None:
        self.at = at


_clock: Clock = Clock()


def get_clock() -> Clock:
    return _clock


def set_clock(clock: Clock) -> None:
    global _clock
    _clock = clock


def utcnow() -> datetime:
    return _clock.now()
