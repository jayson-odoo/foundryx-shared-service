"""``HttpSourceError`` - the one failure type the open REST source raises.

Every failure - transport, an HTTP status, a non-JSON body, a shape change
mid-walk, or the shared row cap - raises THIS before any hash, watermark or
delete-intent state is touched (AC-08-23). ``page``/``status`` are set when
known so the Runs tab can name exactly where the walk broke; ``message`` is
always operator-safe (never more than a bounded head of a response body).
"""
from __future__ import annotations

from typing import Optional


class HttpSourceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        page: Optional[int] = None,
        status: Optional[int] = None,
        # sprint-5/10 (AC-10-22/64) - which WALK this failure came from:
        # ``"enrich"`` for a lookup endpoint (never the main path). ``None``
        # (every pre-plan-10 raise) reads as the main path, so an unlabelled
        # fault always classifies as a source-page failure, never silently
        # as an enrich one.
        phase: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.page = page
        self.status = status
        self.phase = phase
