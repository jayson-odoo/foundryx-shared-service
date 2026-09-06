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
import re
import logging
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

import httpx

from .canonical.base import CanonicalRecord
from .canonical.documents import (
    CanonicalDocument,
    ENTITY_PURCHASE_ORDER,
    ENTITY_SALES_ORDER,
    ENTITY_SHIPPING_ORDER,
)
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

# Sorento's ingest batch ceiling (`MAX_BATCH`) - their PER-REQUEST limit and
# the HARD ceiling here: the batch size a sink actually posts is
# `settings.autocount_sink_batch_size` (default 200 since the 2026-09-06 prod
# 504 - a 1,000-record purchase_order batch with per-record supplier
# back-create outran Sorento nginx's 60s proxy timeout), clamped to this
# constant. Going over it is a 413 (or, until their fix lands, a 500), never a
# silent truncation. Defined in `app.config` (its validator needs it, core
# must not import from modules) and re-exported here under its historic name.
from app.config import SORENTO_MAX_BATCH  # noqa: E402 - re-export, see above

# The CONNECT phase stays short regardless of `settings.
# autocount_sink_timeout_seconds` (round 5) - a dead/unreachable endpoint
# should fail fast, never wait for the same generous budget a slow-but-alive
# Sorento needs to finish INGESTING a large document batch (read/write/pool).
SINK_CONNECT_TIMEOUT_SECONDS = 10.0

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
    # sprint-5/02 S3 (addendum section 3) - a LINE-SET entity on Sorento's
    # side (`spo_allocations`, no header table) but a normal ingest path.
    ENTITY_SHIPPING_ORDER: "shipping_orders",
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
_DEPENDENT_ENTITIES = {
    ENTITY_PRODUCT, ENTITY_SALES_ORDER, ENTITY_PURCHASE_ORDER, ENTITY_SHIPPING_ORDER,
}


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


def sorento_supported_entities_label() -> str:
    """A human, comma-joined phrase naming every entity ``_ENTITY_PATH``
    currently maps (S6 merge-gate review NIT 7).

    Generated FROM the map itself - never a hand-maintained sentence - so a
    future entity join (another document, another master) can never leave
    the operator-facing "not previewable" reason stale again the way "it
    currently accepts suppliers and customers only" did the moment documents
    joined the map (plan 22 S5)."""
    names = [entity_type.replace("_", " ") for entity_type in _ENTITY_PATH]
    if len(names) <= 1:
        return names[0] if names else ""
    return ", ".join(names[:-1]) + f" and {names[-1]}"


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


def contract_major(version: Any, *, default: Optional[int] = None) -> Optional[int]:
    """The MAJOR of a Sorento contract version as the ``/contract`` endpoint
    or the connection config states it: ``2`` / ``2.0`` / ``"2"`` / ``"2.1"``
    all mean major 2. ``None`` / blank / anything that is not a version
    yields ``default`` (``None`` unless the caller says what an absent
    version means - ``fetch_contract`` says 1, the provider's ``test()``
    resolves an absent config key to 1 before calling). Shared by the sink
    (advisory mismatch warning) and the provider (Test verdict) so the two
    can never parse the same answer differently.
    """
    if isinstance(version, bool) or version is None:
        return default
    if isinstance(version, (int, float)):
        return int(version)
    head = str(version).strip().split(".", 1)[0]
    return int(head) if head.isdigit() else default


class SorentoSinkError(Exception):
    """A transport- or contract-level failure that is not per-record. The whole
    batch is unresolved; the caller returns it to review rather than marking any
    record pushed.

    ``status_code`` / ``body`` (both optional, ``None`` when the failure was
    not an HTTP answer) carry what the consumer actually said, so a caller
    that must SHOW the failure (``EtlService.preview_task`` -> 502) can quote
    it instead of a fixed sentence - prod 2026-09-06: an operator saw "the
    dry run failed" twice (a 504 and an unknown SO failure) with no way to
    tell what Sorento had answered. ``str(exc)`` is unchanged for every
    existing caller; ``body`` is the SAME bounded, key-free snippet the
    message already embeds (``_safe_body``), never the request, never the
    URL beyond its path.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: Optional[int] = None,
        body: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.body = body


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


class SinkUnknownEntity(SorentoSinkError):
    """A 404 ``UNKNOWN_ENTITY`` (addendum section 5) - Sorento has not yet
    shipped an endpoint for this entity/path (e.g. ``shipping_orders``'
    ``/deletions`` before their build lands). Distinct from every other
    non-200 (a genuine outage/misconfiguration): the caller retries later
    rather than treating it as a defect."""

    def __init__(self, message: str) -> None:
        super().__init__(message, status_code=404)


class SorentoRateLimited(SorentoSinkError):
    """HTTP 429. Carries the vendor's ``Retry-After`` so the caller can wait the
    exact interval - there is no header telling us remaining quota."""

    def __init__(self, retry_after: int) -> None:
        self.retry_after = retry_after
        super().__init__(
            f"Sorento rate-limited the push; retry after {retry_after}s.",
            status_code=429,
        )


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
        # AC-02-14 - the connection's OWN `sorentoContractVersion` setting
        # (default 1, pre-addendum). This is the AUTHORITATIVE gate on every
        # push (`sink_payload(contract_version=)`) - Sorento's own advertised
        # `/contract` version (`fetch_contract`) is ADVISORY ONLY and never
        # auto-flips it.
        contract_version: int = 1,
        # Records per ingest POST. Clamped to `SORENTO_MAX_BATCH` (their
        # per-request limit); the factory passes
        # `settings.autocount_sink_batch_size` (default 200). Every chunk
        # loop below (`dry_run`, `read`, `delete_batch`, `write_batch`) uses
        # it, so one setting governs every request shape.
        batch_size: int = SORENTO_MAX_BATCH,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.contract_version = contract_version
        self.batch_size = max(1, min(int(batch_size), SORENTO_MAX_BATCH))
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
        #     !!  CONNECT STAYS SHORT; READ/WRITE/POOL FOLLOW THE CALLER'S
        #         `timeout` (round 5).  !!
        # A dead/unreachable endpoint should fail fast (``SINK_CONNECT_
        # TIMEOUT_SECONDS``, never the same generous budget); a slow-but-
        # ALIVE Sorento genuinely ingesting a large document batch (lines
        # included) needs the full `timeout` on the phases that actually
        # wait for it. ``sorento_sink_from_connection`` passes ``settings.
        # autocount_sink_timeout_seconds`` here - never the OLD hard-coded
        # 30.0, which recorded a push FAILURE while Sorento was still
        # processing a genuinely large batch.
        self._timeout = httpx.Timeout(float(timeout), connect=SINK_CONNECT_TIMEOUT_SECONDS)
        self._transport = transport
        self._max_rate_limit_waits = max_rate_limit_waits

    # ── operator-facing text ────────────────────────────────────────────────

    _REDACT_MIN_KEY_LEN = 8

    def redact(self, text: str) -> str:
        """``text`` with this sink's API key replaced by ``[redacted]``.

        For anything that is about to be SHOWN or LOGGED (the preview's 502
        detail, the approve gate's message): the sink's own error strings
        never embed the key, but a consumer body could echo it back, so it is
        scrubbed defensively. Keys shorter than 8 characters are not replaced
        (a 1-3 character "key" would blank out ordinary words); such a key
        is a misconfiguration the connection Test already refuses.
        """
        key = self._api_key or ""
        if len(key) < self._REDACT_MIN_KEY_LEN:
            return text
        return text.replace(key, "[redacted]")

    # ── projection ──────────────────────────────────────────────────────────

    def _to_records(self, records: Sequence[CanonicalRecord]) -> List[Dict[str, Any]]:
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
            # Documents accept `contract_version` (AC-02-14); a master's
            # `sink_payload()` takes no arguments at all - dispatch on the
            # record's OWN TYPE (S6, code review) rather than a bare
            # `except TypeError` around the documents call: a real bug
            # inside a document's `sink_payload()` implementation also
            # raises `TypeError` and would silently be swallowed into the
            # WRONG fallback branch (a bare call a document's signature does
            # not even accept), masking the actual error as a v1 downgrade.
            if isinstance(record, CanonicalDocument):
                out.append(payload(contract_version=self.contract_version))
            else:
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

            if response.status_code == 404:
                unknown = _unknown_entity_error(response)
                if unknown is not None:
                    raise unknown

            # Anything else is a batch-level failure. 500 may be a guard-rail
            # error until the companion Sorento fix lands; log the body (the
            # request is masked by the activity layer, not here) so it is
            # diagnosable rather than a bare status code.
            detail = _safe_body(response)
            raise SorentoSinkError(
                f"Sorento returned HTTP {response.status_code} for "
                f"{path}: {detail}",
                status_code=response.status_code,
                body=detail,
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
        for start in range(0, len(projected), self.batch_size):
            body = self._post(projected[start : start + self.batch_size], dry_run=True)
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
        for start in range(0, len(refs), self.batch_size):
            body = self._call(
                f"read/{self._path_segment}",
                {"source_refs": refs[start : start + self.batch_size]},
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

        A 404 ``UNKNOWN_ENTITY`` (addendum section 5 - e.g. ``shipping_orders``
        before Sorento's own build for it lands) is caught PER CHUNK and every
        ref in that chunk reported ``retryable`` instead of raising - the
        caller's staged delete intent stays STAGED and re-offers on the next
        run, exactly like a dependency-order carry-over, rather than the whole
        run failing on an endpoint that genuinely does not exist yet.
        """
        refs = [str(r) for r in source_refs if str(r or "").strip()]
        summary: Dict[str, int] = {
            "total": 0, "deleted": 0, "deactivated": 0, "not_found": 0,
            "failed": 0, "retryable": 0,
        }
        results: List[Dict[str, Any]] = []
        for start in range(0, len(refs), self.batch_size):
            chunk = refs[start : start + self.batch_size]
            try:
                body = self._call(
                    f"ingest/{self._path_segment}/deletions",
                    {"source_refs": chunk},
                    dry_run=dry_run,
                )
            except SinkUnknownEntity:
                summary["total"] += len(chunk)
                summary["retryable"] += len(chunk)
                results.extend(
                    {"source_ref": ref, "outcome": "retryable"} for ref in chunk
                )
                continue
            for key, value in (body.get("summary") or {}).items():
                if isinstance(value, int):
                    summary[key] = summary.get(key, 0) + value
            results.extend(body.get("records") or [])
        return {"dry_run": dry_run, "summary": summary, "records": results}

    # ── contract (addendum section 11/12, AC-02-14) ──────────────────────────

    def fetch_contract(self) -> Optional[int]:
        """``GET /api/v1/external/contract`` -> the version Sorento advertises,
        or ``None`` on ANY failure (network, non-200, malformed body).

        ADVISORY ONLY - never gates a push, never raised as a task-level
        error. The caller compares it to ``self.contract_version`` (the
        connection's own authoritative setting) and surfaces a mismatch as a
        non-blocking preview warning only.
        """
        url = f"{self._base_url}/api/v1/external/contract"
        headers = {"X-API-Key": self._api_key}
        try:
            with httpx.Client(timeout=self._timeout, transport=self._transport) as client:
                response = client.get(url, headers=headers)
            if response.status_code != 200:
                return None
            body = response.json()
            if not isinstance(body, dict):
                return None
            # ``{"version": 2}`` (contract 2) or ``{"version": "2.1"}`` (2.1,
            # a STRING - a point release of the same major); majors only. A
            # contract endpoint that answers but names no version is a
            # contract-1 Sorento.
            return contract_major(body.get("version"), default=1)
        except Exception:  # noqa: BLE001 - advisory only, must never propagate
            return None

    # ── real push (AC-14-16/18) ──────────────────────────────────────────────

    def write_batch(
        self, records: Sequence[CanonicalRecord], *, request_id: str
    ) -> List[WriteResult]:
        """Deliver a batch and return one ``WriteResult`` per input record, in
        order. Chunks at the vendor batch ceiling.

        A record's ``delivered`` is True only for a ``created``/``updated``
        outcome - Sorento's own verdict, never inferred from the HTTP status.

        ``settings.autocount_sink_concurrency`` (S5b, performance round;
        read at CALL time, never cached) lets up to N chunk POSTs run WITH
        REAL OVERLAP instead of one at a time. The ALL-OR-NOTHING contract
        is unchanged at every concurrency level, concurrency 1 included:
        this method returns verdicts ONLY once every chunk has succeeded,
        in submission order - one chunk failing (a transport error, a
        5xx, a rate-limit exhaustion) propagates the SAME exception a
        purely sequential loop always raised, and the caller
        (``SyncService._auto_push_upserts``) already treats that as "apply
        nothing, every row stays STAGED, the next run re-offers
        everything" - concurrency only changes how many POSTs are in
        flight, never what a failure means.
        """
        record_list = list(records)
        chunks = [
            record_list[start : start + self.batch_size]
            for start in range(0, len(record_list), self.batch_size)
        ]
        if not chunks:
            return []

        from app.config import settings as _settings

        concurrency = int(getattr(_settings, "autocount_sink_concurrency", 1) or 1)
        concurrency = max(1, min(concurrency, len(chunks)))

        if concurrency == 1:
            #     !!  BYTE-IDENTICAL TO BEFORE S5b - ONE POST AT A TIME, THE
            #         SAME ORDER.  !!
            bodies = [
                self._post(self._to_records(chunk), dry_run=False) for chunk in chunks
            ]
        else:
            with ThreadPoolExecutor(max_workers=concurrency) as executor:
                futures = [
                    executor.submit(self._post, self._to_records(chunk), dry_run=False)
                    for chunk in chunks
                ]
                bodies = []
                try:
                    for future in futures:
                        bodies.append(future.result())
                except BaseException:
                    # A chunk failed - never submit/await anything further
                    # than the context manager already will: cancel every
                    # NOT-YET-STARTED future (a genuine no-op call to
                    # Sorento avoided), let anything already running finish
                    # in the background (the ``with`` block's own exit
                    # waits for it), and propagate exactly like the
                    # sequential path always did - no verdict from this
                    # method reaches the caller either way.
                    for pending in futures:
                        pending.cancel()
                    raise

        results: List[WriteResult] = []
        for chunk, body in zip(chunks, bodies):
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


def _unknown_entity_error(response: httpx.Response) -> Optional[SinkUnknownEntity]:
    """A 404 that is Sorento's ``UNKNOWN_ENTITY`` code (addendum section 5) ->
    the typed error, else ``None`` (an ordinary 404 falls through to the
    generic batch-level error)."""
    try:
        body = response.json()
    except (ValueError, TypeError):
        return None
    if not isinstance(body, dict):
        return None
    if str(body.get("code") or "") != "UNKNOWN_ENTITY":
        return None
    return SinkUnknownEntity(str(body.get("message") or "Unknown entity."))


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


_CONSUMER_SNIPPET_MAX = 300
_URL_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://\S+")


_HTTP_STATUS_RE = re.compile(r"\bHTTP (\d{3})\b")


def describe_consumer_failure(
    exc: BaseException, *, sink: Optional[Any] = None
) -> Tuple[str, Optional[int], str]:
    """The operator-facing account of a failed dry run / push:
    ``(line, status_code, detail)``.

    Shared by ``EtlService.preview_task`` (activation preview -> 502) and
    ``SyncService``'s approve-gate dry run (-> 502) so the two never word
    the same failure differently (prod 2026-09-06: a fixed generic sentence
    left the operator unable to tell a 504 from an unknown SO failure).

    Built from STATUS + captured BODY, never from an error string that might
    embed a header or URL:

    * a TRANSPORT error (``httpx.HTTPError`` - the sink does not wrap these,
      so the caller catches them beside ``SorentoSinkError``) ->
      ``Consumer unreachable: <Class>: <text>``, status ``None``;
    * a ``SorentoSinkError`` carrying ``status_code`` (any non-200 answer,
      a 429, an ``UNKNOWN_ENTITY`` 404) -> ``Consumer said: HTTP <n>
      <captured body>``;
    * a ``SorentoSinkError`` WITHOUT the attribute but whose text names an
      ``HTTP <n>`` (an older sink, a test double) -> ``Consumer said: HTTP
      <n>`` and nothing else - the text is not trusted onto the surface;
    * a ``SorentoSinkError`` with no HTTP answer at all (an unroutable
      entity, a record without a projection - the sink's own key-free
      strings) -> ``Consumer error: <text>``.

    ``detail`` is whitespace-collapsed, capped at exactly
    ``_CONSUMER_SNIPPET_MAX`` characters (after ``_safe_body``'s own 500),
    scrubbed through the sink's public ``redact`` when it has one (never a
    private attribute), and any ``scheme://...`` token is replaced - the
    sink's own strings carry only the request PATH and this keeps a consumer
    body from re-introducing a URL.
    """
    if isinstance(exc, httpx.HTTPError):
        status: Optional[int] = None
        raw = f"{type(exc).__name__}: {exc}"
        prefix = "Consumer unreachable: "
    else:
        status = getattr(exc, "status_code", None)
        body = getattr(exc, "body", None)
        if status is not None:
            raw = body or ""
            prefix = f"Consumer said: HTTP {status} "
        else:
            match = _HTTP_STATUS_RE.search(str(exc))
            if match:
                status = int(match.group(1))
                raw = ""
                prefix = f"Consumer said: HTTP {status} "
            else:
                raw = str(exc)
                prefix = "Consumer error: "
    detail = " ".join(str(raw).split())
    redact = getattr(sink, "redact", None)
    if callable(redact):
        detail = redact(detail)
    detail = _URL_RE.sub("[url]", detail)[:_CONSUMER_SNIPPET_MAX]
    return f"{prefix}{detail}".rstrip(), status, detail


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
    from app.config import settings  # read at CALL time (round 5), never cached

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
        # The LIVE setting (round 5), never the class default - an operator
        # whose Sorento endpoint needs a longer (or shorter) budget retunes
        # it without a code change.
        timeout=settings.autocount_sink_timeout_seconds,
        # Records per ingest POST, read at CALL time like ``timeout`` (default
        # 200 since the 2026-09-06 prod 504; ceiling ``SORENTO_MAX_BATCH``).
        batch_size=settings.autocount_sink_batch_size,
        transport=transport,
        # AC-02-14 - the connection's own authoritative gate. The integrations
        # form stores the select's value as the STRING "1" / "2"; ``int`` on
        # ``contract_major`` resolves "2" (and a hand-set "2.0") to 2; a
        # value that is not a version at all ("abc" - the config PATCH merges
        # verbatim, nothing validates it against the select's options) falls
        # back to 1 instead of raising ValueError inside ``sink_for_company``.
        # Default 1 (pre-addendum) so an existing connection with no such key
        # configured behaves exactly as it always has - there is deliberately
        # NO backfill of this key: an existing tenant opts into contract 2 by
        # picking it on the connection's edit form (Settings > Integrations >
        # Sorento), where the provider's Test then checks the choice against
        # the contract Sorento advertises.
        contract_version=contract_major(config.get("sorentoContractVersion"), default=1) or 1,
    )
