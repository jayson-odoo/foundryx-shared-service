"""Injectable clock (sprint-4/03 Slice 6) - the ONE source of "now" for
time-dependent rule facts (the day-count facts ``record.<field>.daysSince`` /
``.daysUntil``). Everything else keeps real ``datetime.now`` - stored timestamps
and transition times must never be skewed by a simulation.

Default = real UTC. The admin date-simulation wraps a sweep in
``with clock_override(as_of): …`` so "now" moves for that call only (a
contextvar, reset in ``finally``) - never a persisted/global clock.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import date, datetime, timezone
from typing import Optional, Union

# When set, ``now()`` returns this instead of the wall clock (simulation only).
_now_override: ContextVar[Optional[datetime]] = ContextVar("clock_now_override", default=None)


def now() -> datetime:
    """Aware-UTC current time - the simulated value inside ``clock_override``,
    else the real wall clock."""
    return _now_override.get() or datetime.now(timezone.utc)


def today() -> date:
    """Current calendar date (honors the override) - for date-only comparisons."""
    return now().date()


@contextmanager
def clock_override(as_of: Union[datetime, date]):
    """Run a block with ``now()`` pinned to ``as_of`` (a date is taken at UTC
    midnight). Resets on exit, even on exception."""
    if isinstance(as_of, datetime):
        dt = as_of if as_of.tzinfo else as_of.replace(tzinfo=timezone.utc)
    else:  # date → UTC midnight
        dt = datetime(as_of.year, as_of.month, as_of.day, tzinfo=timezone.utc)
    token = _now_override.set(dt)
    try:
        yield
    finally:
        _now_override.reset(token)
