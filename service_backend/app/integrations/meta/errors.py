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
