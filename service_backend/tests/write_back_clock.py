"""Shared fake clock for the write-back deadline tests.

An action's deadline is ``time.monotonic()`` at the start plus
``ACTION_DEADLINE_SECONDS``, checked before every vendor call (``frame.py``).
Tests that shrink the budget to fractions of a second and cross it with a real
``time.sleep`` flake on a slow CI runner: the reads and database work before the
first write can take longer than the whole budget, so the action is refused
before the point the test means to reach. With this clock the action's time only
moves where a test moves it; real time spent elsewhere never counts.
"""

from __future__ import annotations

import time


class FakeClock:
    """Stands in for the ``time`` module of the write-back frame and service: a
    ``monotonic()`` that only moves when a test moves it."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def __getattr__(self, name):
        return getattr(time, name)


def use_fake_clock(monkeypatch) -> FakeClock:
    """Give the action's deadline (set in ``service``, checked in ``frame``) a
    fake clock for the rest of the test and return it."""
    from modules.autocount.write_back import frame as frame_mod
    from modules.autocount.write_back import service as service_mod

    clock = FakeClock()
    monkeypatch.setattr(service_mod, "time", clock)
    monkeypatch.setattr(frame_mod, "time", clock)
    return clock
