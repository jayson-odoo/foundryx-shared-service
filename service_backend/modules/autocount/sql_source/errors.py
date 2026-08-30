"""Error classes for the SQL source - every one carries an OPERATOR-SAFE
``message`` (never a credential, a DSN, or a driver stack).

Three phases, three classes, so the HTTP layer can map them without parsing
strings: the static guard (422 - before the source is touched), connecting
(502 - the source is unreachable or refused us) and executing (400 - the
source rejected the query).
"""
from __future__ import annotations


class SqlSourceError(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SqlGuardError(SqlSourceError):
    """The statement is not a single SELECT (AC-22-03). Raised BEFORE any
    connection is opened."""


class SqlConnectError(SqlSourceError):
    """Could not open a read-only session on the source (AC-22-02)."""


class SqlQueryError(SqlSourceError):
    """The source rejected the statement (sanitised driver message, AC-22-06)."""


class SqlDeleteGuardExceeded(SqlSourceError):
    """A reconcile (or no-watermark) diff found more delete intents than the
    safety threshold allows (AC-22-22) - raised from ``fetch_changes`` itself,
    BEFORE any hash write, so the run fails with nothing staged and nothing
    pushed (fail-safe means the adds/updates in the same extract are held
    too, not just the deletes)."""
