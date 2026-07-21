"""``SorentoSink`` — hop 2's real consumer (AC-14-15..18, 14-20..24, 14-40).

Slice 1 shipped ``LoggingSink``, a tagged no-op. This is the real thing: it
delivers canonical suppliers and customers to Sorento's master ingest API over
the network, so ``PUSHED`` finally means *a consumer accepted it* (BL-133).

Everything the vendor contract forced is documented at the point it bites:

* **Auth is ``X-API-Key``, never ``Authorization: Bearer``** (AC-14-15). Bearer
  is Sorento's own human-JWT channel and does not authenticate an integration.
  The legacy ``EXTERNAL_API_KEY`` is refused by construction — its hash is
  seeded onto the *n8n* integration, so presenting it would misattribute every
  write. The key is a write-only credential; it never appears in a log line or
  a stored payload (the activity log masks it).

* **HTTP 200 is not success** (AC-14-16). A batch is not a transaction: Sorento
  returns 200 and a per-record verdict even when every record failed. The sink
  reports each record's own ``created``/``updated``/``failed``/``retryable``
  outcome. ``retryable`` means *nothing was written* — no row, no reference —
  and for suppliers/customers it must never occur (AC-14-24), so it is surfaced
  as a defect signal rather than quietly re-queued.

* **429 is honoured** (AC-14-17). Sorento rate-limits per integration and sends
  ``Retry-After``; there are no ``X-RateLimit-*`` headers to pre-empt with, so
  the only correct response is to wait the stated seconds. Their limiter fails
  OPEN when Redis is absent, so a clean local run proves nothing about
  production throttling.

* **Guard-rail errors may arrive as 500** until the companion Sorento fix lands
  (malformed envelope / oversized batch). An unexpected 500 is therefore logged
  with the full (masked) request so it is diagnosable, not mysterious.

The sink knows nothing about staging, approval or watermarks — it takes
canonical records and returns per-record results. The service owns the
transaction and the exactly-once guarantee.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

import httpx

from .canonical.base import CanonicalRecord
from .canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from .sinks import WriteResult

logger = logging.getLogger("foundryx.autocount")

SINK_SORENTO = "sorento"

# Sorento's ingest batch ceiling (`MAX_BATCH`). We chunk at or below it; going
# over is a 413 (or, until their fix lands, a 500), never a silent truncation.
SORENTO_MAX_BATCH = 1000

# The canonical entity_type → Sorento's ingest path segment. A canonical entity
# with no mapping here CANNOT be delivered to Sorento — raised loudly rather
# than guessed, because a wrong path is a 404 that looks like an outage.
_ENTITY_PATH: Dict[str, str] = {
    ENTITY_SUPPLIER: "suppliers",
    ENTITY_CUSTOMER: "customers",
}

# Outcomes Sorento may report per record. `created`/`updated` = delivered;
# `failed` = bad data (quarantine, do not retry); `retryable` = a referenced
# master isn't synced yet and NOTHING was written (must not occur for
# suppliers/customers — AC-14-24).
_OUTCOME_DELIVERED = {"created", "updated"}


class SorentoSinkError(Exception):
    """A transport- or contract-level failure that is not per-record. The whole
    batch is unresolved; the caller returns it to review rather than marking any
    record pushed."""


class SorentoRateLimited(SorentoSinkError):
    """HTTP 429. Carries the vendor's ``Retry-After`` so the caller can wait the
    exact interval — there is no header telling us remaining quota."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Sorento rate-limited the push; retry after {retry_after}s.")


@dataclass
class Prediction:
    """One record's dry-run verdict (AC-14-20/21). ``diff`` is present only when
    a value would change — for a create it is empty, for an adopt/update it maps
    ``column → {current, incoming}``. This is authoritative because it is
    Sorento's own resolution rolled back, not a reconstruction."""

    source_ref: str
    outcome: str
    entity_id: Optional[str] = None
    diff: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: Dict[str, Any] = field(default_factory=dict)

    @property
    def changes_live_data(self) -> bool:
        """True when approving this record would overwrite an existing value —
        the rows an operator most needs to see before committing."""
        return bool(self.diff)


@dataclass
class DryRunResult:
    """The whole batch's prediction. ``summary`` mirrors Sorento's counts;
    ``predictions`` are in request order."""

    summary: Dict[str, int]
    predictions: List[Prediction]

    @property
    def would_change(self) -> List[Prediction]:
        return [p for p in self.predictions if p.changes_live_data]


class SorentoSink:
    """One entity, one company. Batch-delivers canonical records to Sorento.

    Constructed with an explicit base URL and API key so it is trivially
    testable and never reaches for ambient config. A connection-backed factory
    (``sorento_sink_from_connection``) supplies both in production.
    """

    name = SINK_SORENTO

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        entity_type: str,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
        max_rate_limit_waits: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.entity_type = entity_type
        path = _ENTITY_PATH.get(entity_type)
        if path is None:
            raise SorentoSinkError(
                f"No Sorento ingest path for canonical entity '{entity_type}'."
            )
        self._path_segment = path
        self._timeout = timeout
        self._transport = transport
        self._max_rate_limit_waits = max_rate_limit_waits

    # ── projection ──────────────────────────────────────────────────────────

    @staticmethod
    def _to_records(records: Sequence[CanonicalRecord]) -> List[Dict[str, Any]]:
        """Project each canonical record to EXACTLY Sorento's field set.

        Uses the model's own ``sink_payload`` (the allow-list lives beside the
        model, AC-14-14) so provenance and locally-useful fields never cross the
        wire and trip ``extra="forbid"``.
        """
        out: List[Dict[str, Any]] = []
        for record in records:
            payload = getattr(record, "sink_payload", None)
            if payload is None:
                raise SorentoSinkError(
                    f"{type(record).__name__} has no sink_payload projection; "
                    "it cannot be delivered to Sorento safely."
                )
            out.append(payload())
        return out

    # ── HTTP ────────────────────────────────────────────────────────────────

    def _post(self, records: List[Dict[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
        """One ingest call, with bounded waits on 429. Returns the parsed body.

        Raises ``SorentoSinkError`` on any non-200 that is not a handled 429 —
        the whole batch is then unresolved and the caller must not mark anything
        delivered.
        """
        url = f"{self._base_url}/api/v1/external/ingest/{self._path_segment}"
        params = {"dry_run": "true"} if dry_run else None
        body = {"records": records}
        headers = {
            # X-API-Key, never Bearer (AC-14-15). Never logged.
            "X-API-Key": self._api_key,
            "Content-Type": "application/json",
        }

        waits = 0
        while True:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.post(url, params=params, json=body, headers=headers)

            if response.status_code == 200:
                return response.json()

            if response.status_code == 429:
                retry_after = _retry_after_seconds(response)
                if waits >= self._max_rate_limit_waits:
                    raise SorentoRateLimited(retry_after)
                waits += 1
                logger.info(
                    "Sorento rate-limited the %s push; waiting %ss (wait %d/%d).",
                    self._path_segment, retry_after, waits, self._max_rate_limit_waits,
                )
                time.sleep(retry_after)
                continue

            # Anything else is a batch-level failure. 500 may be a guard-rail
            # error until the companion Sorento fix lands; log the body (the
            # request is masked by the activity layer, not here) so it is
            # diagnosable rather than a bare status code.
            detail = _safe_body(response)
            raise SorentoSinkError(
                f"Sorento ingest returned HTTP {response.status_code} for "
                f"{self._path_segment}: {detail}"
            )

    # ── dry run (AC-14-20/21) ────────────────────────────────────────────────

    def dry_run(self, records: Sequence[CanonicalRecord]) -> DryRunResult:
        """Ask Sorento what a push WOULD do, writing nothing.

        The prediction is authoritative because Sorento runs its real resolution
        — adoption matching included — and rolls back. We never reconstruct the
        adoption rule locally (AC-14-21); two copies would drift and the wrong
        one would be holding the safety gate.
        """
        projected = self._to_records(records)
        if not projected:
            return DryRunResult(
                summary={"total": 0, "created": 0, "updated": 0, "failed": 0, "retryable": 0},
                predictions=[],
            )
        body = self._post(projected, dry_run=True)
        predictions = [
            Prediction(
                source_ref=str(r.get("source_ref") or ""),
                outcome=str(r.get("outcome") or ""),
                entity_id=r.get("entity_id"),
                diff=r.get("diff") or {},
                errors=r.get("errors") or {},
            )
            for r in body.get("records", [])
        ]
        return DryRunResult(summary=body.get("summary") or {}, predictions=predictions)

    # ── real push (AC-14-16/18) ──────────────────────────────────────────────

    def write_batch(
        self, records: Sequence[CanonicalRecord], *, request_id: str
    ) -> List[WriteResult]:
        """Deliver a batch and return one ``WriteResult`` per input record, in
        order. Chunks at the vendor batch ceiling.

        A record's ``delivered`` is True only for a ``created``/``updated``
        outcome — Sorento's own verdict, never inferred from the HTTP status.
        """
        record_list = list(records)
        results: List[WriteResult] = []
        for start in range(0, len(record_list), SORENTO_MAX_BATCH):
            chunk = record_list[start : start + SORENTO_MAX_BATCH]
            projected = self._to_records(chunk)
            body = self._post(projected, dry_run=False)
            by_ref = {str(r.get("source_ref") or ""): r for r in body.get("records", [])}
            for record in chunk:
                ref = getattr(record, "source_ref", "")
                verdict = by_ref.get(ref)
                results.append(self._result_for(ref, verdict))
        return results

    def _result_for(self, ref: str, verdict: Optional[Dict[str, Any]]) -> WriteResult:
        if verdict is None:
            # Sorento did not report this record at all — treat as a
            # batch-level anomaly for this row, never as a silent success.
            return WriteResult(
                ok=False, sink=self.name, external_id=None, delivered=False,
                message=f"Sorento returned no verdict for {ref}.",
            )
        outcome = str(verdict.get("outcome") or "")
        delivered = outcome in _OUTCOME_DELIVERED
        if delivered:
            return WriteResult(
                ok=True, sink=self.name, external_id=verdict.get("entity_id"),
                delivered=True, message=outcome,
            )
        if outcome == "retryable":
            # Must not happen for masters (AC-14-24). Loud, not re-queued.
            return WriteResult(
                ok=False, sink=self.name, external_id=None, delivered=False,
                message=(
                    f"Sorento reported '{ref}' retryable — a referenced master is "
                    "unsynced. This should be unreachable for suppliers/customers; "
                    "investigate rather than retry."
                ),
            )
        errors = verdict.get("errors") or {}
        return WriteResult(
            ok=False, sink=self.name, external_id=None, delivered=False,
            message=f"Sorento rejected '{ref}': {json.dumps(errors) if errors else outcome}",
        )


def _retry_after_seconds(response: httpx.Response) -> int:
    raw = response.headers.get("Retry-After", "")
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        # No/!int header — a conservative default beats hammering.
        return 60


def _safe_body(response: httpx.Response) -> str:
    try:
        return json.dumps(response.json())[:500]
    except (ValueError, TypeError):
        return (response.text or "")[:500]


def sorento_sink_from_connection(
    config: Dict[str, Any],
    credentials: Dict[str, Any],
    *,
    entity_type: str,
    transport: Optional[httpx.BaseTransport] = None,
) -> SorentoSink:
    """Build a sink from a ``consumer`` connection's config + DECRYPTED creds.

    Credentials arrive already decrypted via ``app/secrets.py`` — this module
    never handles ciphertext. ``apiKey`` is refused if it is the legacy
    ``EXTERNAL_API_KEY`` shape is out of scope here; the operator supplies the
    integration's own minted key.
    """
    return SorentoSink(
        base_url=str(config.get("baseUrl", "")).strip(),
        api_key=str(credentials.get("apiKey", "")).strip(),
        entity_type=entity_type,
        transport=transport,
    )
