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


class SqlDocumentCapExceeded(SqlSourceError):
    """A document task's per-header ``lineQuery`` fan-out exceeded its safety
    cap - one header's own line count (S5 review SHOULD-FIX 3). Raised from
    ``SqlDbSource._read_lines`` BEFORE any hash write, same fail-safe
    contract as ``SqlDeleteGuardExceeded``: nothing is staged or pushed. The
    sibling per-run "too many changed headers" cap is gone (plan sprint-5/03
    S1, AC-03-01) - paging is the bound now."""


class SqlFilterFormulaError(SqlSourceError):
    """A document task's `filterFormula` failed to evaluate against an actual
    header row AT RUN TIME (F2/B3, sprint-5/02 review round) - a genuine
    runtime fault (a value that doesn't coerce the way the formula expects),
    distinct from a save-time parse failure (caught by
    `validate_source_config`'s own gate, which makes this exceedingly rare).
    Raised from `SqlDbSource._read` BEFORE any hash write, same fail-safe
    contract as `SqlDeleteGuardExceeded`/`SqlDocumentCapExceeded`: nothing is
    staged or pushed - a broken filter must be a visible, named task error,
    never a silent fail-open that keeps every header with no sign anything
    is wrong."""


class SqlProbeFailed(SqlSourceError):
    """A company-onboarding probe (current database / profile name, plan
    sprint-5/01 AC-01-02) could not connect or its statement failed. Carries
    the SANITISED runtime message; the company service maps it to a per-field
    422 on ``connectionId``."""
