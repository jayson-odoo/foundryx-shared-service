"""Meta Graph error types shared by every Meta-app caller (plan 64 D3).

Moved verbatim from ``modules/omnichannel/adapters/base.py``; that module
re-exports both names so ``except SendError`` / ``except CodeExchangeError``
in omnichannel catches exactly the same classes as before.
"""
from typing import Optional


class CodeExchangeError(Exception):
    """Provider rejected the Embedded Signup code exchange (carries the provider's
    human-readable reason so the wizard can show it instead of a generic failure)."""


class SendError(Exception):
    """Provider rejected an outbound send (carries the provider's reason so the
    composer can surface it - e.g. re-engagement outside the 24h window).

    ``transient`` distinguishes a retryable transport/5xx failure (network blip,
    Meta 5xx → the send task retries with backoff) from a permanent rejection
    (bad number, 4xx, template issue → stamp FAILED, plan 12 review)."""

    def __init__(
        self,
        message: str,
        *,
        transient: bool = False,
        code: Optional[str] = None,
        rate_limited: bool = False,
        retry_after: Optional[int] = None,
    ):
        super().__init__(message)
        self.transient = transient
        # The provider's own error code (e.g. Meta `error.code`) when it gave one.
        self.code = code
        # Meta throttled the call (plan 56 A): the send task retries on its own
        # slower schedule and the sync key routes answer HTTP 429. `retry_after`
        # is Meta's `Retry-After` header in whole seconds when it sent one.
        self.rate_limited = rate_limited
        self.retry_after = retry_after


# Graph ``error.code`` values meaning the token no longer works or lost a
# permission (plan 64 AC-64-29): 190 invalid / expired / revoked token,
# 102 session, 10 and 200 permission denied or removed. One list for every
# Meta caller that classifies token health.
TOKEN_ERROR_CODES = frozenset({10, 102, 190, 200})


def is_token_error(code: Optional[int]) -> bool:
    """True when a Graph error code means: reconnect, the token is gone."""
    return isinstance(code, int) and not isinstance(code, bool) and code in TOKEN_ERROR_CODES


# The token itself is dead (invalid, expired, revoked, the app removed from
# the Page): never a per-object answer. Callers acting on a caller-chosen
# object (one form, one lead) flip a source on these only, because 10 / 200
# can also mean "this one object is not allowed".
TOKEN_DEAD_CODES = frozenset({102, 190})


def is_token_dead(code: Optional[int]) -> bool:
    return isinstance(code, int) and not isinstance(code, bool) and code in TOKEN_DEAD_CODES
