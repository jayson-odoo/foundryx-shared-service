"""``run_poll`` / ``run_sweep`` / ``run_backfill``
(plan sections 3.6/3.7/3.8) - the doc-feed service layer. Repositories do
every query (AC-13-41 precedent: tenant AND company scoped); this module
owns the sequencing, retry and verdict-handling rules.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from cryptography.fernet import InvalidToken

from app.jobs.service import JobService
from app.models.background_job import JOB_FAILED
from app.models.integration_activity import ACTIVITY_ERROR, ACTIVITY_SUCCESS

from ..activity import record_activity, record_client_calls, trace_id_for_job
from ..http_source.book import derive_book
from ..http_source.client import HttpApiClient, connection_sizing
from ..http_source.source import DELETE_GUARD_MIN_ABSOLUTE, DELETE_GUARD_RATIO
from ..models import (
    DOC_FEED_BACKFILL_DONE,
    DOC_FEED_BACKFILL_RUNNING,
    DOC_FEED_BACKFILL_STOPPED,
    DOC_FEED_BACKFILL_STOPPING,
    DOC_FEED_MODE_OFF,
    DOC_FEED_MODE_PUSH,
    RUN_FAILED,
    RUN_SUCCESS,
    SINK_IMPL_SORENTO,
    AcCompany,
    AcDocFeed,
    AcDocFeedBackfill,
    AcDocFeedRun,
)
from ..provider import AUTH_NONE, PROVIDER_KEY, auth_mode
from ..repositories import CompanyRepository, ConnectionRepository
from ..scheduler import active_tenant_service_join
from ..repositories.doc_feed_repository import (
    DocFeedIssueRepository,
    DocFeedLedgerRepository,
    DocFeedRepository,
)
from ..sinks_sorento import (
    DOC_FEED_CONTRACT_VERSION,
    describe_consumer_failure,
    SorentoRateLimited,
    SorentoSink,
    sorento_sink_from_connection,
)
from ..sorento_provider import SORENTO_PROVIDER_KEY
from app.secrets import decrypt_secret

from .clock import myt_date
from .constants import (
    BACKFILL_FROM_DEFAULT,
    RUN_KIND_BACKFILL,
    RUN_KIND_POLL,
    RUN_KIND_SWEEP,
    SWEEP_WINDOW_DAYS,
)
from .records import (
    RawVendorRecord,
    dedupe_latest,
    doc_date,
    doc_key,
    push_order,
    source_ref,
    vendor_modified_at,
)
from .vendor import DocFeedVendor, DocFeedVendorError

MAX_BACKFILL_RATE_LIMIT_WAITS = 10

# N7 - the largest vendor document a issue row will store for re-send.
MAX_STORED_RECORD_BYTES = 64 * 1024

_DELETE_KEY_TRANSLATE = {"not_found": "notFound"}

logger = logging.getLogger("foundryx.autocount")


def _sink_failure_text(exc: BaseException, sink: Any) -> str:
    """SS1 - the operator-facing account of a sink failure, never ``str(exc)``
    (a ``SorentoSinkError`` carries the raw CRM body and the URL):
    ``describe_consumer_failure`` strips URLs, redacts the API key and caps
    the length."""
    return describe_consumer_failure(exc, sink=sink)[0]


def _heartbeat(db, job_id: Optional[str]) -> None:
    """B2 - best-effort liveness stamp, called after every vendor day and
    every committed chunk (poll, sweep, backfill) so a long feed never
    passes ``background_job_orphan_after_minutes`` with no heartbeat. A
    ``None`` ``job_id`` (a direct-call test, or the eager dev seam before a
    job row exists) is a silent no-op; a failure to stamp is logged and
    never fails the run (mirrors ``autocount.sync._heartbeat``)."""
    if not job_id:
        return
    try:
        JobService(db).heartbeat(job_id)
    except Exception:  # noqa: BLE001 - liveness is advisory, the run is not
        logger.warning("doc-feed: heartbeat for job %s failed", job_id, exc_info=True)


def _job_is_dead(db, job_id: Optional[str]) -> bool:
    """B2 - ``True`` when ``job_id`` names a ``background_jobs`` row the
    orphan/undispatched sweep (or some other closer) has already marked
    ``FAILED`` out from under this run - a fence a long-running loop
    (today: backfill) checks per day so a zombie worker that is still
    physically alive stops pushing instead of racing the sweep's own
    bookkeeping to a finish. A ``None`` ``job_id`` is never dead (a
    direct-call test)."""
    if not job_id:
        return False
    return JobService(db).fresh_status(job_id) == JOB_FAILED


class RunRefusal(Exception):
    """A run could not even start - ``code`` is the run row's ``errorCode``."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


@dataclass
class _Resolved:
    company: AcCompany
    vendor_client: HttpApiClient
    vendor: DocFeedVendor
    sink: SorentoSink
    book: str


def _resolve(
    db, feed_row: AcDocFeed, *, vendor_transport=None, sink_transport=None
) -> _Resolved:
    """Plan section 3.6 step 1 - resolve every dependency or refuse loudly.
    Never a bare ``get_by_id`` on a stored connection id (the polymorphic-
    stored-id rule) - every lookup is tenant- AND provider-scoped."""
    tenant_id = feed_row.tenant_id
    company = CompanyRepository(db).get(tenant_id, feed_row.company_id)
    if company is None or not company.is_active:
        raise RunRefusal("COMPANY_INACTIVE", "This company is inactive.")

    conn_repo = ConnectionRepository(db)
    conn = conn_repo.get_for_provider(tenant_id, feed_row.connection_id or "", PROVIDER_KEY)
    if conn is None or auth_mode(conn.config_json or {}) != AUTH_NONE:
        raise RunRefusal(
            "NO_CONNECTION", "This feed's AutoCount connection was not found."
        )
    book = derive_book(str((conn.config_json or {}).get("baseUrl") or ""))
    if not book or book != feed_row.book:
        raise RunRefusal(
            "BOOK_MISMATCH",
            "The connection's book no longer matches this feed's stored book.",
        )

    if (
        company.sink_impl != SINK_IMPL_SORENTO
        or not company.sink_connection_id
        or not (company.sorento_company_code or "").strip()
    ):
        raise RunRefusal(
            "SINK_NOT_READY", "This company has no ready Sorento push target."
        )
    sink_conn = conn_repo.get_for_provider(
        tenant_id, company.sink_connection_id, SORENTO_PROVIDER_KEY
    )
    if sink_conn is None:
        raise RunRefusal(
            "SINK_NOT_READY", "The company's Sorento connection was not found."
        )
    try:
        credentials = (
            decrypt_secret(sink_conn.credentials_json) if sink_conn.credentials_json else {}
        )
    except InvalidToken:
        raise RunRefusal(
            "SINK_NOT_READY",
            "The Sorento connection's stored credentials could not be decrypted.",
        )

    sink = sorento_sink_from_connection(
        sink_conn.config_json or {}, credentials, entity_type=feed_row.feed,
        company_code=company.sorento_company_code, transport=sink_transport, book=book,
    )

    # CONTRACT_GATE - checked again at the START of every run (D4/3.5, S1
    # review round 1): an unreachable or malformed probe now FAILS CLOSED,
    # never advisory - "never guess a contract we cannot see" applies at run
    # time exactly as it does at config time (`CompanyService.
    # doc_feed_gate_error`). Probed through the SAME `sink` (and so the SAME
    # `sink_transport`) the push itself will use - there is no second,
    # un-injectable sink instance for a test's stubbed CRM to accidentally
    # bypass; a test that wants to simulate a genuine low/old contract still
    # reaches this exact call by routing `/api/v1/external/contract`
    # through its own `sink_transport` (or by monkeypatching
    # `SorentoSink.fetch_contract_detail` at the class level, unaffected
    # either way).
    try:
        contract = sink.fetch_contract_detail()
    except Exception:  # noqa: BLE001 - the probe itself, unprovable = refused
        contract = None
    if contract is None:
        raise RunRefusal(
            "CONTRACT_GATE",
            "The consumer's contract could not be confirmed (unreachable or "
            "malformed response).",
        )
    supported = (
        contract.version >= DOC_FEED_CONTRACT_VERSION
        and feed_row.feed in contract.entities
    )
    if not supported:
        raise RunRefusal(
            "CONTRACT_GATE",
            f"The consumer's contract ({contract.version}) does not yet "
            f"support '{feed_row.feed}'.",
        )

    sizing = connection_sizing(conn.config_json or {})
    # B1 (review round 1) - the connection's OWN `baseUrl` already ends in
    # the book (plan 08 D2, e.g. `https://hapi.sorento.cc.cd/api/db1`); the
    # vendor client must be built from the FULL base URL, exactly like
    # `HttpApiSource.__init__` (`http_source/source.py:302-318`) - dropping
    # the path down to scheme+host (the former `_host_root`) sent every GET
    # to the bare host and 404d on every real vendor read.
    vendor_client = HttpApiClient(
        str((conn.config_json or {}).get("baseUrl") or ""),
        transport=vendor_transport, timeout_seconds=sizing.request_timeout_seconds,
    )
    return _Resolved(
        company=company, vendor_client=vendor_client, vendor=DocFeedVendor(vendor_client),
        sink=sink, book=book,
    )


def _new_summary() -> Dict[str, Any]:
    return {
        "created": 0, "updated": 0, "unchanged": 0, "staleIgnored": 0,
        "failed": 0, "retryable": 0, "skippedNoKey": 0, "warnings": {},
    }


def _new_run(
    db, feed_row: AcDocFeed, *, kind: str, dry_run: bool, now: datetime,
    job_id: Optional[str] = None,
) -> AcDocFeedRun:
    run = AcDocFeedRun(
        tenant_id=feed_row.tenant_id, company_id=feed_row.company_id, feed_id=feed_row.id,
        feed=feed_row.feed, kind=kind, dry_run=dry_run, job_id=job_id, started_at=now,
    )
    db.add(run)
    # B3 - COMMIT at creation (was only flushed): the orphan hook matches
    # open runs by `job_id` and a `finished_at IS NULL` row it can close; a
    # worker crash before the run's own first commit must not lose the row
    # entirely (the FE hook then polls a run that never existed).
    db.commit()
    return run


def _finish_failed(db, run: AcDocFeedRun, code: str, message: str) -> AcDocFeedRun:
    # S2 - a failed chunk/day may have left the session's transaction in a
    # PendingRollbackError state (an ON CONFLICT race, or any other DB
    # error raised mid-``on_chunk``) - roll it back FIRST so this run's own
    # failure is always recordable. `run` itself is already durable (B3
    # commits it at creation), so a rollback here only discards the
    # UNCOMMITTED work of the failed attempt, never the run row.
    db.rollback()
    run.outcome = RUN_FAILED
    run.error_code = code
    run.error = message[:4000]
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    db.commit()
    return run


def _finish_success(db, run: AcDocFeedRun, summary: Dict[str, Any]) -> AcDocFeedRun:
    run.outcome = RUN_SUCCESS
    run.summary_json = summary
    run.finished_at = datetime.now(timezone.utc)
    run.duration_ms = int((run.finished_at - run.started_at).total_seconds() * 1000)
    db.commit()
    return run


def _record_vendor_activity(db, vendor_client: HttpApiClient, run: AcDocFeedRun) -> None:
    record_client_calls(
        db, vendor_client, tenant_id=run.tenant_id,
        trace_id=trace_id_for_job(run.id), external_ref=run.company_id,
    )


def _record_push_activity(
    db, feed_row: AcDocFeed, run: AcDocFeedRun, summary: Optional[Dict[str, Any]]
) -> None:
    """AC-14-72 - counters only, never the API key or a record body."""
    clean_summary = {k: v for k, v in (summary or {}).items() if k != "warnings"}
    record_activity(
        db, tenant_id=feed_row.tenant_id,
        operation=f"doc_feed {run.kind} {feed_row.feed}",
        status=ACTIVITY_SUCCESS if run.outcome == RUN_SUCCESS else ACTIVITY_ERROR,
        trace_id=trace_id_for_job(run.id), external_ref=feed_row.company_id,
        request={"dryRun": run.dry_run, "requests": run.requests},
        response={"fetched": run.fetched_count, "summary": clean_summary},
    )


def _record_too_large(raw: Any) -> bool:
    try:
        return len(json.dumps(raw, default=str)) > MAX_STORED_RECORD_BYTES
    except (TypeError, ValueError):
        return True


def _apply_document_verdict(
    db, feed_row: AcDocFeed, book: str, record: RawVendorRecord, result: Any,
    *, dry_run: bool, run_id: str, now: datetime, summary: Dict[str, Any],
    failed_refs: Optional[List[Dict[str, Any]]] = None,
) -> None:
    raw = record.raw
    key = doc_key(raw)
    if key is None:
        return
    doc_no = raw.get("DocNo")
    d_date = doc_date(raw)
    modified_at = vendor_modified_at(raw)
    outcome = result.outcome or ""
    warnings = tuple(result.warnings or ())
    ledger_repo = DocFeedLedgerRepository(db)
    issue_repo = DocFeedIssueRepository(db)
    # N-2 - the (json.dumps) size check runs once per record.
    too_large_record = False if result.delivered else _record_too_large(raw)

    if result.delivered:
        stale = outcome == "unchanged" and "stale_ignored" in warnings
        if stale:
            summary["staleIgnored"] = summary.get("staleIgnored", 0) + 1
            if not dry_run:
                ledger_repo.insert_if_absent(
                    feed_row.tenant_id, feed_row.company_id, feed_row.feed, book, key,
                    doc_no=doc_no, doc_date=d_date, source_modified_at=modified_at,
                    outcome=outcome, now=now,
                )
        else:
            summary[outcome] = summary.get(outcome, 0) + 1
            if not dry_run:
                ledger_repo.upsert_delivered(
                    feed_row.tenant_id, feed_row.company_id, feed_row.feed, book, key,
                    doc_no=doc_no, doc_date=d_date, source_modified_at=modified_at,
                    outcome=outcome, now=now,
                )
        if not dry_run:
            issue_repo.delete(feed_row.tenant_id, feed_row.company_id, feed_row.feed, book, key)
    elif outcome == "failed" or too_large_record:
        # N7 - an over-cap document can never be stored for a D9 re-send, so
        # it is a permanent failure with a named error (never a retryable
        # row whose record is missing).
        summary["failed"] = summary.get("failed", 0) + 1
        # N3 (review round 1) - a permanently-failed document push is
        # surfaced in `summary.failedRefs` (the same shape `run_sweep` already uses), not only the persistent issue row: an
        # operator reading one run's summary should see WHICH DocKeys failed
        # without opening the issues list.
        too_large = too_large_record
        errors_out = dict(result.errors or {})
        if too_large:
            errors_out["record"] = (
                f"Too large to store for re-send (over {MAX_STORED_RECORD_BYTES // 1024} KB)."
            )
        if failed_refs is not None:
            failed_refs.append({"sourceRef": record.source_ref, "errors": errors_out})
        if not dry_run:
            issue_repo.upsert(
                feed_row.tenant_id, feed_row.company_id, feed_row.feed, book, key,
                kind="failed", doc_no=doc_no, doc_date=d_date,
                source_modified_at=modified_at, record_json=None if too_large else raw,
                errors_json=errors_out, warnings_json=list(warnings) or None,
                last_run_id=run_id, now=now,
            )
    else:
        # `retryable`, an unknown word, or no verdict at all - the sink
        # already downgrades every one of those to `retryable` (D9).
        summary["retryable"] = summary.get("retryable", 0) + 1
        if not dry_run:
            issue_repo.upsert(
                feed_row.tenant_id, feed_row.company_id, feed_row.feed, book, key,
                kind="retryable", doc_no=doc_no, doc_date=d_date,
                source_modified_at=modified_at, record_json=raw,
                errors_json=result.errors, warnings_json=list(warnings) or None,
                last_run_id=run_id, now=now,
            )
    for warning in warnings:
        bucket = summary.setdefault("warnings", {})
        bucket[warning] = bucket.get(warning, 0) + 1


# ── poll (D5..D11) ────────────────────────────────────────────────────────────


def run_poll(
    db, feed_row: AcDocFeed, *, dry_run: bool, now: datetime, job_id: Optional[str] = None,
    vendor_transport: Any = None, sink_transport: Any = None,
) -> AcDocFeedRun:
    run = _new_run(db, feed_row, kind=RUN_KIND_POLL, dry_run=dry_run, now=now, job_id=job_id)
    try:
        resolved = _resolve(db, feed_row, vendor_transport=vendor_transport, sink_transport=sink_transport)
    except RunRefusal as exc:
        return _finish_failed(db, run, exc.code, exc.message)

    today = myt_date(now)
    if feed_row.cursor_day is None:
        start = today - timedelta(days=1)
    else:
        start = min(feed_row.cursor_day, today - timedelta(days=1))
    end = today
    capped = (end - start).days > 30
    if capped:
        end = start + timedelta(days=30)

    all_records: List[Dict[str, Any]] = []
    requests_count = 0
    day = start
    try:
        while day <= end:
            all_records.extend(resolved.vendor.day_by_last_modified(feed_row.feed, day))
            requests_count += 1
            _heartbeat(db, job_id)  # B2 - per vendor day
            day += timedelta(days=1)
    except DocFeedVendorError as exc:
        run.requests = requests_count
        _record_vendor_activity(db, resolved.vendor_client, run)
        if vendor_transport is None:
            resolved.vendor_client.close()
        return _finish_failed(db, run, exc.code, str(exc))

    deduped = dedupe_latest(all_records)

    # N3 (review round 1) - `resent` counts the retryable issue rows appended
    # here (D9: the stored record, not a refetch) so a run's own summary
    # says how many of this tick's pushes were a re-send, not a fresh read.
    resent_count = 0
    if not dry_run:
        read_keys = {doc_key(r) for r in deduped if doc_key(r) is not None}
        for issue in DocFeedIssueRepository(db).list_retryable(
            feed_row.tenant_id, feed_row.company_id, feed_row.feed, resolved.book
        ):
            if issue.doc_key not in read_keys and issue.record_json:
                deduped.append(issue.record_json)
                resent_count += 1

    ordered = push_order(deduped)
    summary = _new_summary()
    summary["resent"] = resent_count
    failed_refs: List[Dict[str, Any]] = []
    to_send: List[RawVendorRecord] = []
    for record in ordered:
        key = doc_key(record)
        if key is None:
            summary["skippedNoKey"] += 1
            continue
        ref = source_ref(feed_row.feed, resolved.book, record)
        to_send.append(RawVendorRecord(source_ref=ref, entity_type=feed_row.feed, raw=record))

    chunk_error: Optional[BaseException] = None

    def on_chunk(chunk, results, error):
        nonlocal chunk_error
        if error is not None:
            chunk_error = error
            return
        for record, result in zip(chunk, results):
            _apply_document_verdict(
                db, feed_row, resolved.book, record, result, dry_run=dry_run,
                run_id=run.id, now=now, summary=summary, failed_refs=failed_refs,
            )
        db.commit()
        _heartbeat(db, job_id)  # B2 - per committed chunk

    try:
        resolved.sink.write_batch(to_send, request_id=run.id, dry_run=dry_run, on_chunk=on_chunk)
    except Exception as exc:  # noqa: BLE001 - a raised sink error fails the run
        chunk_error = exc

    summary["failedRefs"] = failed_refs[:20]

    run.requests = requests_count
    run.fetched_count = len(all_records)
    run.day_from = start
    run.day_to = end
    _record_vendor_activity(db, resolved.vendor_client, run)
    if vendor_transport is None:
        resolved.vendor_client.close()

    if chunk_error is not None:
        return _finish_failed(db, run, "SINK_ERROR", _sink_failure_text(chunk_error, resolved.sink))

    if not dry_run:
        feed_row.cursor_day = (end + timedelta(days=1)) if capped else today
        feed_row.last_poll_at = now
        feed_row.last_poll_ok_at = now

    _finish_success(db, run, summary)
    _record_push_activity(db, feed_row, run, summary)
    return run


# ── deletion sweep (D12) ──────────────────────────────────────────────────────


def _parse_deletion_doc_key(ref: str) -> Optional[int]:
    if not ref:
        return None
    tail = str(ref).rsplit(":", 1)[-1]
    try:
        return int(tail)
    except ValueError:
        return None


def run_sweep(
    db, feed_row: AcDocFeed, *, dry_run: bool, now: datetime, job_id: Optional[str] = None,
    vendor_transport: Any = None, sink_transport: Any = None,
) -> AcDocFeedRun:
    run = _new_run(db, feed_row, kind=RUN_KIND_SWEEP, dry_run=dry_run, now=now, job_id=job_id)
    try:
        resolved = _resolve(db, feed_row, vendor_transport=vendor_transport, sink_transport=sink_transport)
    except RunRefusal as exc:
        return _finish_failed(db, run, exc.code, exc.message)

    today = myt_date(now)
    window_from = today - timedelta(days=SWEEP_WINDOW_DAYS - 1)
    seen: set = set()
    requests_count = 0
    day = window_from
    try:
        while day <= today:
            for r in resolved.vendor.day_by_doc_date(feed_row.feed, day):
                key = doc_key(r)
                if key is not None:
                    seen.add(key)
            requests_count += 1
            _heartbeat(db, job_id)  # B2 - per vendor day (45 GETs)
            day += timedelta(days=1)
    except DocFeedVendorError as exc:
        run.requests = requests_count
        run.day_from = window_from
        run.day_to = today
        _record_vendor_activity(db, resolved.vendor_client, run)
        if vendor_transport is None:
            resolved.vendor_client.close()
        return _finish_failed(db, run, exc.code, str(exc))

    ledger_repo = DocFeedLedgerRepository(db)
    window_rows = ledger_repo.window_rows(
        feed_row.tenant_id, feed_row.company_id, feed_row.feed, resolved.book,
        day_from=window_from, day_to=today,
    )
    candidates = [row for row in window_rows if row.doc_key not in seen]
    # N1 - the shared delete-guard constants (`http_source/source.py`), not a
    # locally hardcoded 50 / 0.2.
    threshold = max(DELETE_GUARD_MIN_ABSOLUTE, int(DELETE_GUARD_RATIO * len(window_rows)))

    run.requests = requests_count
    run.day_from = window_from
    run.day_to = today

    if len(candidates) > threshold:
        _record_vendor_activity(db, resolved.vendor_client, run)
        if vendor_transport is None:
            resolved.vendor_client.close()
        return _finish_failed(
            db, run, "DELETE_GUARD",
            f"The sweep would deactivate {len(candidates)} of {len(window_rows)} "
            "ledger rows - over the safety guard, refusing.",
        )

    summary = _new_summary()
    summary["candidates"] = len(candidates)
    failed_refs: List[Dict[str, Any]] = []

    if candidates:
        keys = [row.doc_key for row in candidates]
        try:
            result = resolved.sink.delete_doc_keys(
                keys, doc_date_from=window_from.isoformat(), doc_date_to=today.isoformat(),
                dry_run=dry_run,
            )
        except Exception as exc:  # noqa: BLE001
            _record_vendor_activity(db, resolved.vendor_client, run)
            if vendor_transport is None:
                resolved.vendor_client.close()
            return _finish_failed(db, run, "SINK_ERROR", _sink_failure_text(exc, resolved.sink))

        for key, value in (result.get("summary") or {}).items():
            if isinstance(value, int):
                out_key = _DELETE_KEY_TRANSLATE.get(key, key)
                summary[out_key] = summary.get(out_key, 0) + value

        candidate_keys = {row.doc_key for row in candidates}
        matched: set = set()
        for verdict in result.get("records") or []:
            parsed_key = _parse_deletion_doc_key(str(verdict.get("source_ref") or ""))
            outcome = str(verdict.get("outcome") or "")
            if parsed_key is None or parsed_key not in candidate_keys:
                failed_refs.append(
                    {"sourceRef": verdict.get("source_ref"), "errors": verdict.get("errors")}
                )
                continue
            matched.add(parsed_key)
            if outcome in ("deactivated", "not_found"):
                if not dry_run:
                    ledger_repo.mark_vanished(
                        feed_row.tenant_id, feed_row.company_id, feed_row.feed,
                        resolved.book, parsed_key, now=now,
                    )
            else:
                failed_refs.append(
                    {"sourceRef": verdict.get("source_ref"), "errors": verdict.get("errors")}
                )
        for key in candidate_keys - matched:
            failed_refs.append(
                {"sourceRef": f"{resolved.book}:?:{key}", "errors": {"message": "no verdict"}}
            )
        db.commit()
        _heartbeat(db, job_id)  # B2 - per committed chunk

    summary["failedRefs"] = failed_refs[:20]
    _record_vendor_activity(db, resolved.vendor_client, run)
    if vendor_transport is None:
        resolved.vendor_client.close()

    if not dry_run:
        feed_row.last_sweep_ok_at = now

    _finish_success(db, run, summary)
    _record_push_activity(db, feed_row, run, summary)
    return run


# ── backfill (D13) ────────────────────────────────────────────────────────────


def run_backfill(
    db, backfill_row: AcDocFeedBackfill, *, now: datetime,
    vendor_transport: Any = None, sink_transport: Any = None,
) -> AcDocFeedBackfill:
    job_id = backfill_row.job_id

    if backfill_row.status != DOC_FEED_BACKFILL_RUNNING:
        # B2 - an operator Stop (`stopping`) or the orphan sweep itself
        # (`stopped`, set from a DIFFERENT session before this call ever
        # started) both mean "never touch the loop"; only `stopping` is
        # THIS call's own job to close out to `stopped` - a row already
        # `stopped`/`done` must never be re-promoted.
        if backfill_row.status == DOC_FEED_BACKFILL_STOPPING:
            backfill_row.status = DOC_FEED_BACKFILL_STOPPED
            db.commit()
        return backfill_row

    feed_row = DocFeedRepository(db).get_by_id(backfill_row.tenant_id, backfill_row.feed_id)
    if feed_row is None:
        backfill_row.status = DOC_FEED_BACKFILL_STOPPED
        backfill_row.error = "The feed this backfill belonged to no longer exists."
        backfill_row.error_code = "FEED_GONE"
        db.commit()
        return backfill_row

    dry_run = bool(backfill_row.dry_run)

    try:
        resolved = _resolve(db, feed_row, vendor_transport=vendor_transport, sink_transport=sink_transport)
    except RunRefusal as exc:
        backfill_row.status = DOC_FEED_BACKFILL_STOPPED
        backfill_row.error = exc.message
        backfill_row.error_code = exc.code
        db.commit()
        _new_run_for_backfill(
            db, backfill_row, feed_row, now, outcome=RUN_FAILED, error=exc.message,
            error_code=exc.code, requests=0, fetched_count=0,
        )
        return backfill_row

    aggregate_summary = _new_summary()
    aggregate_summary["candidates"] = 0
    day = backfill_row.next_day
    segment_start = backfill_row.next_day  # N2 - this segment's own first day
    requests_count = 0
    fetched_count = 0
    stop_reason: Optional[Dict[str, str]] = None

    while day <= backfill_row.to_day:
        db.refresh(backfill_row)
        if backfill_row.status != DOC_FEED_BACKFILL_RUNNING:
            break
        # SS3 - re-read the feed / tenant / module on EVERY day: a
        # suspended tenant or deactivated module 403s every route (nobody
        # can press Stop) and an operator can flip the feed off mid-run.
        halt = _backfill_halt_reason(db, feed_row, dry_run=dry_run)
        if halt is not None:
            stop_reason = halt
            break
        # B2 - the fence: a beat sweep may have failed this SAME job (no
        # heartbeat for 15 minutes) from a DIFFERENT session moments ago,
        # before its own `on_job_orphaned` write is visible to this
        # `db.refresh` above (or before it ran at all) - stop pushing
        # regardless of what `backfill_row.status` itself currently reads.
        if _job_is_dead(db, job_id):
            stop_reason = {
                "code": "JOB_ORPHANED",
                "message": "The worker running this backfill is no longer live.",
            }
            break

        try:
            rows = resolved.vendor.day_by_doc_date(feed_row.feed, day)
            requests_count += 1
            fetched_count += len(rows)
            _heartbeat(db, job_id)  # B2 - per vendor day
        except DocFeedVendorError as exc:
            stop_reason = {"code": exc.code, "message": str(exc)}
            break

        deduped = dedupe_latest(rows)
        ordered = push_order(deduped)
        to_send: List[RawVendorRecord] = []
        for record in ordered:
            key = doc_key(record)
            if key is None:
                aggregate_summary["skippedNoKey"] += 1
                continue
            ref = source_ref(feed_row.feed, resolved.book, record)
            to_send.append(RawVendorRecord(source_ref=ref, entity_type=feed_row.feed, raw=record))

        rate_limit_waits = 0
        day_error: Optional[BaseException] = None
        # N3 (review round 1) - `write_batch` calls `on_chunk` (and this
        # commits + counts) for every chunk BEFORE the chunk that finally
        # raises `SorentoRateLimited`; a bare retry of the whole `to_send`
        # list re-verdicted (double-counted) those already-applied chunks
        # in `aggregate_summary` on every wait. `remaining` narrows to only
        # the records this day has NOT yet been credited for.
        remaining = to_send
        # B2 (round 2) - credit by IDENTITY (`source_ref`), never by position:
        # `write_batch` keeps going after a chunk whose retries ran out, so
        # a positional slice dropped the failed chunk and re-sent a credited
        # one. `failed_refs` = refs of chunks that errored and are not (yet)
        # credited; the day ends as an error while any remain.
        credited: set = set()
        day_orphaned = False
        failed_chunk_refs: set = set()
        last_chunk_error: Optional[BaseException] = None
        while True:

            def on_chunk(chunk, results, error):
                nonlocal last_chunk_error
                if error is not None:
                    last_chunk_error = error
                    failed_chunk_refs.update(r.source_ref for r in chunk)
                    return
                for record, result in zip(chunk, results):
                    _apply_document_verdict(
                        db, feed_row, resolved.book, record, result, dry_run=dry_run,
                        run_id=backfill_row.id, now=now, summary=aggregate_summary,
                    )
                db.commit()
                _heartbeat(db, job_id)  # B2 - per committed chunk
                credited.update(r.source_ref for r in chunk)

            try:
                resolved.sink.write_batch(
                    remaining, request_id=f"{backfill_row.id}:{day.isoformat()}",
                    dry_run=dry_run, on_chunk=on_chunk,
                )
            except SorentoRateLimited as exc:
                remaining = [r for r in remaining if r.source_ref not in credited]
                rate_limit_waits += 1
                if rate_limit_waits > MAX_BACKFILL_RATE_LIMIT_WAITS:
                    day_error = exc
                    break
                # RS4 - a wait can last minutes: keep the job's heartbeat
                # fresh and honour the orphan fence before every sleep.
                _heartbeat(db, job_id)
                if _job_is_dead(db, job_id):
                    day_orphaned = True
                    break
                time.sleep(exc.retry_after)
                continue
            except Exception as exc:  # noqa: BLE001
                day_error = exc
                break
            # A chunk that errored is retried only by a later 429 attempt
            # (it stays in `remaining`); on a normal finish any ref that is
            # still uncredited means the day is NOT complete.
            if failed_chunk_refs - credited:
                day_error = last_chunk_error
            break

        if day_orphaned:
            stop_reason = {
                "code": "JOB_ORPHANED",
                "message": "The worker running this backfill is no longer live.",
            }
            break
        if day_error is not None:
            stop_reason = {"code": "SINK_ERROR", "message": _sink_failure_text(day_error, resolved.sink)}
            break

        backfill_row.next_day = day + timedelta(days=1)
        backfill_row.days_done = (backfill_row.days_done or 0) + 1
        backfill_row.summary_json = aggregate_summary
        db.commit()
        day = backfill_row.next_day

    _record_vendor_activity(
        db, resolved.vendor_client,
        _fake_run_for_activity(backfill_row, requests_count),
    )
    if vendor_transport is None:
        resolved.vendor_client.close()

    if stop_reason is not None:
        # S2 - discard any uncommitted work of the day this failed on before
        # even touching `backfill_row` (mirrors `_finish_failed`).
        db.rollback()
        backfill_row.status = DOC_FEED_BACKFILL_STOPPED
        backfill_row.error = stop_reason["message"][:4000]
        backfill_row.error_code = stop_reason["code"]
        db.commit()
        _new_run_for_backfill(
            db, backfill_row, feed_row, now, outcome=RUN_FAILED,
            error=backfill_row.error, error_code=backfill_row.error_code,
            summary=aggregate_summary, requests=requests_count, fetched_count=fetched_count,
            segment_start=segment_start,
        )
        return backfill_row

    db.refresh(backfill_row)
    if backfill_row.status != DOC_FEED_BACKFILL_RUNNING:
        # B2 - never promote an externally-set `stopping`/`stopped` row back
        # to `done`; only THIS call's own `stopping` closes to `stopped`
        # here (a `stopped` row the orphan sweep already wrote stays exactly
        # that).
        if backfill_row.status == DOC_FEED_BACKFILL_STOPPING:
            backfill_row.status = DOC_FEED_BACKFILL_STOPPED
            db.commit()
        _new_run_for_backfill(
            db, backfill_row, feed_row, now, outcome=RUN_SUCCESS,
            summary=aggregate_summary, requests=requests_count, fetched_count=fetched_count,
            segment_start=segment_start,
        )
        return backfill_row

    backfill_row.status = DOC_FEED_BACKFILL_DONE
    backfill_row.finished_at = datetime.now(timezone.utc)
    if not dry_run and backfill_row.from_day <= date.fromisoformat(BACKFILL_FROM_DEFAULT):
        feed_row.full_backfill_done_at = now
    db.commit()
    _new_run_for_backfill(
        db, backfill_row, feed_row, now, outcome=RUN_SUCCESS, summary=aggregate_summary,
        requests=requests_count, fetched_count=fetched_count, segment_start=segment_start,
    )
    return backfill_row


def _backfill_halt_reason(db, feed_row: AcDocFeed, *, dry_run: bool) -> Optional[Dict[str, str]]:
    """SS3 - the per-day guard: ``None`` to carry on, else the named stop
    reason. Re-reads the feed row (mode may have flipped), the company, and
    the SAME tenant-lifecycle + module-active predicate the beat uses."""
    fresh = DocFeedRepository(db).get_by_id(feed_row.tenant_id, feed_row.id)
    if fresh is None:
        return {"code": "FEED_GONE", "message": "The feed this backfill belonged to no longer exists."}
    db.refresh(fresh)
    if fresh.mode == DOC_FEED_MODE_OFF:
        return {"code": "FEED_OFF", "message": "This feed was switched off."}
    if not dry_run and fresh.mode != DOC_FEED_MODE_PUSH:
        return {"code": "FEED_NOT_PUSH", "message": "This feed is no longer in Push mode."}
    active = (
        active_tenant_service_join(db.query(AcDocFeed.id), AcDocFeed.tenant_id)
        .filter(AcDocFeed.id == fresh.id)
        .first()
    )
    if active is None:
        return {
            "code": "TENANT_INACTIVE",
            "message": "This workspace or the AutoCount service is no longer active.",
        }
    return None


def _fake_run_for_activity(backfill_row: AcDocFeedBackfill, requests_count: int):
    """A throwaway holder so ``_record_vendor_activity`` can reuse its own
    ``(tenant_id, id, company_id)`` shape for a backfill segment - never
    persisted."""
    class _Holder:
        tenant_id = backfill_row.tenant_id
        id = backfill_row.id
        company_id = backfill_row.company_id

    return _Holder()


def _new_run_for_backfill(
    db, backfill_row: AcDocFeedBackfill, feed_row: AcDocFeed, now: datetime,
    *, outcome: str, error: Optional[str] = None, error_code: Optional[str] = None,
    summary: Optional[Dict[str, Any]] = None,
    requests: Optional[int] = None, fetched_count: int = 0,
    segment_start: Optional[date] = None,
) -> AcDocFeedRun:
    """AC-14-70 - one run row per backfill SEGMENT (this call). B3/S9 -
    carries this segment's own request/fetch counters and its OWN
    ``day_to`` (the last day actually completed, ``next_day - 1``; ``next_
    day`` itself is one day PAST the last day read - a Done 3-day backfill
    otherwise showed a 4-day range)."""
    # N2 - `day_from` is THIS segment's first day (a resumed segment never
    # claims the days an earlier one did); a segment that completed no day
    # has no `day_to` at all (never a range that ends before it starts).
    day_from = segment_start or backfill_row.from_day
    day_to: Optional[date] = backfill_row.next_day - timedelta(days=1)
    if day_to < day_from:
        day_to = None
    run = AcDocFeedRun(
        tenant_id=backfill_row.tenant_id, company_id=backfill_row.company_id,
        feed_id=backfill_row.feed_id, feed=backfill_row.feed, kind=RUN_KIND_BACKFILL,
        dry_run=backfill_row.dry_run, job_id=backfill_row.job_id,
        day_from=day_from, day_to=day_to,
        requests=requests, fetched_count=fetched_count,
        outcome=outcome, error=error, error_code=error_code,
        summary_json=summary, started_at=now, finished_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.commit()
    _record_push_activity(db, feed_row, run, summary)
    return run
