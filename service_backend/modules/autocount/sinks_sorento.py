"""``SorentoSink`` - hop 2's real consumer (AC-14-15..18, 14-20..24, 14-40).

Slice 1 shipped ``LoggingSink``, a tagged no-op. This is the real thing: it
delivers canonical suppliers and customers to Sorento's master ingest API over
the network, so ``PUSHED`` finally means *a consumer accepted it* (BL-133).

Everything the vendor contract forced is documented at the point it bites:

* **Auth is ``X-API-Key``, never ``Authorization: Bearer``** (AC-14-15). Bearer
  is Sorento's own human-JWT channel and does not authenticate an integration.
  The legacy ``EXTERNAL_API_KEY`` is refused by construction - its hash is
  seeded onto the *n8n* integration, so presenting it would misattribute every
  write. The key is a write-only credential; it never appears in a log line or
  a stored payload (the activity log masks it).

* **HTTP 200 is not success** (AC-14-16). A batch is not a transaction: Sorento
  returns 200 and a per-record verdict even when every record failed. The sink
  reports each record's own ``created``/``updated``/``failed``/``retryable``
  outcome. ``retryable`` means *nothing was written* - no row, no reference -
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

The sink knows nothing about staging, approval or watermarks - it takes
canonical records and returns per-record results. The service owns the
transaction and the exactly-once guarantee.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import httpx

from .canonical.base import CanonicalRecord
from .canonical.documents import ENTITY_PURCHASE_ORDER, ENTITY_SALES_ORDER
from .canonical.masters import (
    ENTITY_CUSTOMER,
    ENTITY_PRODUCT,
    ENTITY_PRODUCT_CATEGORY,
    ENTITY_SALES_AGENT,
    ENTITY_SUPPLIER,
    ENTITY_UNIT_OF_MEASURE,
    ENTITY_WAREHOUSE,
)
from .sinks import WriteResult

logger = logging.getLogger("foundryx.autocount")

SINK_SORENTO = "sorento"

# Sorento's ingest batch ceiling (`MAX_BATCH`). We chunk at or below it; going
# over is a 413 (or, until their fix lands, a 500), never a silent truncation.
SORENTO_MAX_BATCH = 1000

# The canonical entity_type → Sorento's ingest path segment (Appendix A6/A8 -
# ``product_categories | units_of_measure | warehouses | suppliers | customers
# | products | sales_agents``). A canonical entity with no mapping here CANNOT
# be delivered to Sorento - raised loudly rather than guessed, because a wrong
# path is a 404 that looks like an outage.
_ENTITY_PATH: Dict[str, str] = {
    ENTITY_SUPPLIER: "suppliers",
    ENTITY_CUSTOMER: "customers",
    ENTITY_PRODUCT_CATEGORY: "product_categories",
    ENTITY_UNIT_OF_MEASURE: "units_of_measure",
    ENTITY_WAREHOUSE: "warehouses",
    ENTITY_PRODUCT: "products",
    ENTITY_SALES_AGENT: "sales_agents",
    # Plan 22 S5 (AC-22-24, Appendix A6/A8) - documents land end to end.
    ENTITY_SALES_ORDER: "sales_orders",
    ENTITY_PURCHASE_ORDER: "purchase_orders",
}

# Outcomes Sorento may report per record. `created`/`updated` = delivered;
# `failed` = bad data (quarantine, do not retry); `retryable` = a referenced
# master isn't synced yet and NOTHING was written.
_OUTCOME_DELIVERED = {"created", "updated"}

# Entities whose ``retryable`` is EXPECTED, not a defect (AC-22-23, extended
# S5/AC-22-24): a product's ``category_code``/``uom_code`` may legitimately
# not have synced yet, and a document ALWAYS carries at least one master
# reference (``customer_ref``/``product_ref``/…) that may not have synced yet
# either (Appendix A6 item 3 - "unknown ref = whole record retryable"), so
# both resolve automatically once the dependency lands. Every OTHER master
# here carries no such reference, so for them ``retryable`` stays the
# AC-14-24 "must be unreachable" defect signal.
_DEPENDENT_ENTITIES = {ENTITY_PRODUCT, ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER}


def sorento_supports_entity(entity_type: str) -> bool:
    """Whether Sorento's ingest API accepts this canonical entity yet.

    Sorento ingests masters (suppliers, customers, product categories, units
    of measure, warehouses, products, sales agents - plan 22 S4) and the two
    documents sales/purchase orders (plan 22 S5, Appendix A6/A8). GRN has no
    ingest endpoint on the consumer yet, so it stays absent from
    ``_ENTITY_PATH`` - a company set to push to Sorento falls back to the
    logging sink for it (stages + logs, delivering nothing) rather than
    erroring on a missing path - *deliverability*, an expected not-yet-built
    state, not a misconfiguration.
    """
    return entity_type in _ENTITY_PATH


# ── company anchor (plan 22 Appendix A6/A7) ───────────────────────────────────
#
#     !!  AN ANCHOR FAILURE IS A TASK-LEVEL FAULT, NEVER A PER-RECORD ONE.  !!
#
# Sorento resolves the target company from the top-level ``companyCode`` on
# EVERY ingest/read/deletion call. When that resolution fails it answers 422
# with a FLAT body - ``{"message": ..., "detail": null, "code": ...}`` - before
# it looks at a single record. The records are fine; the company wiring is not.
# Reporting it against the first record would send an operator to fix data that
# is not broken, so it is surfaced on the TASK (``last_run_error_code``).
COMPANY_ANCHOR_REQUIRED = "COMPANY_ANCHOR_REQUIRED"
UNKNOWN_COMPANY = "UNKNOWN_COMPANY"
COMPANY_BINDING_INVALID = "COMPANY_BINDING_INVALID"
COMPANY_ANCHOR_AMBIGUOUS = "COMPANY_ANCHOR_AMBIGUOUS"
ANCHOR_ERROR_CODES = frozenset(
    {
        COMPANY_ANCHOR_REQUIRED,
        UNKNOWN_COMPANY,
        COMPANY_BINDING_INVALID,
        COMPANY_ANCHOR_AMBIGUOUS,
    }
)


class SorentoSinkError(Exception):
    """A transport- or contract-level failure that is not per-record. The whole
    batch is unresolved; the caller returns it to review rather than marking any
    record pushed."""


class SinkAnchorError(SorentoSinkError):
    """Sorento could not resolve the company anchor (Appendix A6/A7).

    A subclass of ``SorentoSinkError`` on purpose: every existing caller already
    treats it as "the whole batch is unresolved, nothing was written", which is
    exactly right. What the subclass ADDS is the ``code``, so the task can show
    WHICH wiring is wrong instead of a generic delivery failure.
    """

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.sorento_message = message
        super().__init__(f"{code}: {message}")


class SorentoRateLimited(SorentoSinkError):
    """HTTP 429. Carries the vendor's ``Retry-After`` so the caller can wait the
    exact interval - there is no header telling us remaining quota."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(f"Sorento rate-limited the push; retry after {retry_after}s.")


@dataclass
class Prediction:
    """One record's dry-run verdict (AC-14-20/21). ``diff`` is present only when
    a value would change - for a create it is empty, for an adopt/update it maps
    ``column → {current, incoming}``. This is authoritative because it is
    Sorento's own resolution rolled back, not a reconstruction."""

    source_ref: str
    outcome: str
    entity_id: Optional[str] = None
    diff: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    errors: Dict[str, Any] = field(default_factory=dict)

    @property
    def changes_live_data(self) -> bool:
        """True when approving this record would overwrite an existing value -
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
        company_code: Optional[str] = None,
        timeout: float = 30.0,
        transport: Optional[httpx.BaseTransport] = None,
        max_rate_limit_waits: int = 2,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        # The Sorento company this sink delivers INTO (Appendix A6). Sent as the
        # top-level ``companyCode`` on every call; a blank one is deliberately
        # still SENT (as absent) so Sorento answers the authoritative
        # ``COMPANY_ANCHOR_REQUIRED`` rather than us guessing its rules locally.
        self.company_code = (company_code or "").strip() or None
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

    def _body(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Every call body carries the company anchor FIRST (Appendix A6).

        One helper for ingest, read-back and deletions alike - three call sites
        that must never drift on the one field Sorento resolves before it looks
        at anything else.
        """
        body: Dict[str, Any] = {}
        if self.company_code:
            body["companyCode"] = self.company_code
        body.update(payload)
        return body

    def _call(
        self, path: str, payload: Dict[str, Any], *, dry_run: bool
    ) -> Dict[str, Any]:
        """One POST to ``/api/v1/external/{path}``, with bounded waits on 429.

        Raises ``SinkAnchorError`` on an anchor 422 (a TASK-level fault, see the
        codes above) and ``SorentoSinkError`` on any other non-200 that is not a
        handled 429 - the whole batch is then unresolved and the caller must not
        mark anything delivered.
        """
        url = f"{self._base_url}/api/v1/external/{path}"
        params = {"dry_run": "true"} if dry_run else None
        body = self._body(payload)
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

            if response.status_code == 422:
                anchor = _anchor_error(response)
                if anchor is not None:
                    raise anchor

            # Anything else is a batch-level failure. 500 may be a guard-rail
            # error until the companion Sorento fix lands; log the body (the
            # request is masked by the activity layer, not here) so it is
            # diagnosable rather than a bare status code.
            detail = _safe_body(response)
            raise SorentoSinkError(
                f"Sorento returned HTTP {response.status_code} for "
                f"{path}: {detail}"
            )

    def _post(self, records: List[Dict[str, Any]], *, dry_run: bool) -> Dict[str, Any]:
        """One ingest call. Kept as the ingest-shaped wrapper over ``_call`` so
        every existing caller (and its tests) is unchanged."""
        return self._call(
            f"ingest/{self._path_segment}", {"records": records}, dry_run=dry_run
        )

    # ── dry run (AC-14-20/21) ────────────────────────────────────────────────

    def dry_run(self, records: Sequence[CanonicalRecord]) -> DryRunResult:
        """Ask Sorento what a push WOULD do, writing nothing.

        The prediction is authoritative because Sorento runs its real resolution
        - adoption matching included - and rolls back. We never reconstruct the
        adoption rule locally (AC-14-21); two copies would drift and the wrong
        one would be holding the safety gate.
        """
        projected = self._to_records(records)
        summary: Dict[str, int] = {
            "total": 0, "created": 0, "updated": 0, "failed": 0, "retryable": 0
        }
        predictions: List[Prediction] = []
        # CHUNKED at the vendor ceiling exactly like ``write_batch``. A dry run
        # of an INITIAL LOAD (the activation gate, AC-22-18) is routinely larger
        # than one batch, and an over-size body is a 413 - which would make the
        # gate un-passable on precisely the companies that most need it.
        for start in range(0, len(projected), SORENTO_MAX_BATCH):
            body = self._post(projected[start : start + SORENTO_MAX_BATCH], dry_run=True)
            for key, value in (body.get("summary") or {}).items():
                if isinstance(value, int):
                    summary[key] = summary.get(key, 0) + value
            predictions.extend(
                Prediction(
                    source_ref=str(r.get("source_ref") or ""),
                    outcome=str(r.get("outcome") or ""),
                    entity_id=r.get("entity_id"),
                    diff=r.get("diff") or {},
                    errors=r.get("errors") or {},
                )
                for r in body.get("records", [])
            )
        return DryRunResult(summary=summary, predictions=predictions)

    # ── read-back (Appendix A7 §3/§4, A8) ────────────────────────────────────

    def read_back(self, source_refs: Sequence[str]) -> Dict[str, Any]:
        """``POST /api/v1/external/read/{entity}`` → ``{records, not_found}``.

        Two contract details are handled HERE so no caller re-learns them:

        * **Numbers arrive as JSON numbers** (Sorento runs Decimals through
          FastAPI's encoder). They are parsed via ``str()`` into ``Decimal`` -
          never through a float, which silently rounds a 4-dp quantity.
        * The envelope is ``{"records": [...], "not_found": [...]}`` and a ref
          under the wrong company lists as ``not_found``, not as an error.
        """
        refs = [str(r) for r in source_refs if str(r or "").strip()]
        records: List[Dict[str, Any]] = []
        not_found: List[str] = []
        for start in range(0, len(refs), SORENTO_MAX_BATCH):
            body = self._call(
                f"read/{self._path_segment}",
                {"source_refs": refs[start : start + SORENTO_MAX_BATCH]},
                dry_run=False,
            )
            records.extend(_decimalize(r) for r in (body.get("records") or []))
            not_found.extend(str(r) for r in (body.get("not_found") or []))
        return {"records": records, "not_found": not_found}

    # ── deletions (Appendix A4/A6, consumed by S3's delete intents) ──────────

    def delete_batch(
        self, source_refs: Sequence[str], *, dry_run: bool = False
    ) -> Dict[str, Any]:
        """``POST /api/v1/external/ingest/{entity}/deletions``.

        Per-ref verdict ``deleted | deactivated | not_found | failed`` - Sorento
        tries a hard DELETE and falls back to deactivating when dependents exist
        (it probes the FK graph first, so a customer with orders is never
        orphaned). Returns the merged ``{summary, records}``.
        """
        refs = [str(r) for r in source_refs if str(r or "").strip()]
        summary: Dict[str, int] = {
            "total": 0, "deleted": 0, "deactivated": 0, "not_found": 0, "failed": 0
        }
        results: List[Dict[str, Any]] = []
        for start in range(0, len(refs), SORENTO_MAX_BATCH):
            body = self._call(
                f"ingest/{self._path_segment}/deletions",
                {"source_refs": refs[start : start + SORENTO_MAX_BATCH]},
                dry_run=dry_run,
            )
            for key, value in (body.get("summary") or {}).items():
                if isinstance(value, int):
                    summary[key] = summary.get(key, 0) + value
            results.extend(body.get("records") or [])
        return {"dry_run": dry_run, "summary": summary, "records": results}

    # ── real push (AC-14-16/18) ──────────────────────────────────────────────

    def write_batch(
        self, records: Sequence[CanonicalRecord], *, request_id: str
    ) -> List[WriteResult]:
        """Deliver a batch and return one ``WriteResult`` per input record, in
        order. Chunks at the vendor batch ceiling.

        A record's ``delivered`` is True only for a ``created``/``updated``
        outcome - Sorento's own verdict, never inferred from the HTTP status.
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
            # Sorento did not report this record at all - treat as a
            # batch-level anomaly for this row, never as a silent success.
            return WriteResult(
                ok=False, sink=self.name, external_id=None, delivered=False,
                # No verdict at all is a batch-level ANOMALY, not a data
                # rejection - re-offering it next run is the safe reading.
                outcome="retryable",
                message=f"Sorento returned no verdict for {ref}.",
            )
        outcome = str(verdict.get("outcome") or "")
        delivered = outcome in _OUTCOME_DELIVERED
        if delivered:
            return WriteResult(
                ok=True, sink=self.name, external_id=verdict.get("entity_id"),
                delivered=True, message=outcome, outcome=outcome,
            )
        if outcome == "retryable":
            if self.entity_type in _DEPENDENT_ENTITIES:
                # EXPECTED for a product whose category/UOM has not synced yet
                # (AC-22-23), or for a document referencing a master (customer/
                # supplier/product/warehouse/sales agent) that has not synced
                # yet (AC-22-24, Appendix A6 item 3) - stays STAGED and
                # re-offers on the next run, never quarantined
                # (``SyncService._auto_push_upserts``).
                dependency = (
                    "its category or unit of measure"
                    if self.entity_type == ENTITY_PRODUCT
                    else "a referenced master (customer/supplier/product/warehouse/agent)"
                )
                return WriteResult(
                    ok=False, sink=self.name, external_id=None, delivered=False,
                    outcome=outcome,
                    message=(
                        f"Sorento reported '{ref}' retryable - {dependency} has "
                        "not synced yet. It resolves automatically once that "
                        "dependency lands."
                    ),
                )
            # Must not happen for masters with no dependency reference
            # (AC-14-24). Loud, not re-queued.
            return WriteResult(
                ok=False, sink=self.name, external_id=None, delivered=False,
                outcome=outcome,
                message=(
                    f"Sorento reported '{ref}' retryable - a referenced master is "
                    "unsynced. This should be unreachable for this entity; "
                    "investigate rather than retry."
                ),
            )
        if outcome == "failed":
            errors = verdict.get("errors") or {}
            return WriteResult(
                ok=False, sink=self.name, external_id=None, delivered=False,
                outcome="failed",
                message=f"Sorento rejected '{ref}': {json.dumps(errors) if errors else outcome}",
            )
        #     !!  QUARANTINE ONLY ON THE EXPLICIT "failed" WORD.  !!
        # A BLANK outcome or a word outside our known vocabulary (S2 review
        # SHOULD-FIX 9 - a future Sorento outcome we haven't shipped support
        # for yet, or a malformed record) reads the SAME safe way as no
        # verdict at all: retryable. Defaulting an unrecognised word to
        # "failed" would permanently quarantine a record over our own
        # ignorance of the vocabulary, not proof the DATA was rejected.
        return WriteResult(
            ok=False, sink=self.name, external_id=None, delivered=False,
            outcome="retryable",
            message=(
                f"Sorento returned an unrecognised outcome "
                f"'{outcome or '(blank)'}' for '{ref}'."
            ),
        )


def _anchor_error(response: httpx.Response) -> Optional[SinkAnchorError]:
    """A 422 that is a COMPANY-ANCHOR failure → the typed error, else None.

    The body is FLAT (Appendix A6 - ``{"message", "detail": null, "code"}``),
    deliberately NOT FastAPI's usual ``{"detail": ...}`` wrapper, so it is read
    at the top level. Anything else with a 422 falls through to the generic
    batch-level error - never mislabelled as an anchor problem.
    """
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    code = str(body.get("code") or "")
    if code not in ANCHOR_ERROR_CODES:
        return None
    return SinkAnchorError(
        code, str(body.get("message") or "Sorento could not resolve the company.")
    )


def _decimalize(value: Any) -> Any:
    """JSON numbers → ``Decimal`` via ``str()``, recursively.

    Through ``str()`` and never ``Decimal(float)``: a 4-dp quantity round-tripped
    through binary floating point comes back as 12.340000000000000497379915032,
    and the diff layer then reports a change that does not exist. Booleans are
    left alone (``isinstance(True, int)`` is True).
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, float) or isinstance(value, int):
        return Decimal(str(value))
    if isinstance(value, list):
        return [_decimalize(v) for v in value]
    if isinstance(value, dict):
        return {k: _decimalize(v) for k, v in value.items()}
    return value


def _retry_after_seconds(response: httpx.Response) -> int:
    raw = response.headers.get("Retry-After", "")
    try:
        return max(1, int(float(raw)))
    except (TypeError, ValueError):
        # No/!int header - a conservative default beats hammering.
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
    company_code: Optional[str] = None,
    transport: Optional[httpx.BaseTransport] = None,
) -> SorentoSink:
    """Build a sink from a ``consumer`` connection's config + DECRYPTED creds.

    Credentials arrive already decrypted via ``app/secrets.py`` - this module
    never handles ciphertext. ``apiKey`` is refused if it is the legacy
    ``EXTERNAL_API_KEY`` shape is out of scope here; the operator supplies the
    integration's own minted key.
    """
    return SorentoSink(
        base_url=str(config.get("baseUrl", "")).strip(),
        api_key=str(credentials.get("apiKey", "")).strip(),
        entity_type=entity_type,
        # From ``ac_company.sorento_company_code`` - the per-COMPANY anchor
        # (Appendix A6). Deliberately not read off the connection: one Sorento
        # connection legitimately serves several AutoCount companies, so binding
        # the code to the connection would anchor them all to one Sorento
        # company and silently cross-post their masters.
        company_code=company_code,
        transport=transport,
    )
