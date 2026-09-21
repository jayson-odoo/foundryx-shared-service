"""``HttpApiSource`` - the open (no-auth) REST API implementation of the
``EntitySource`` seam (sprint-5/08, AC-08-22..27).

Same skeleton as ``SqlDbSource.fetch_changes`` (plan §2.4): walk the whole
population every run (there is no server-side delta filter), de-duplicate on
the task's key fields, hash-diff against ``ac_row_hash`` for reconcile/full
extracts, and filter to "changed since the mark" for incremental - a plain
ISO-string comparison, since AutoCount's ``LastModified`` carries no zone and
sorts correctly as text.

Rules worth restating here (mirrors the SQL source's own docstring):

1. **The page walk trusts the ECHOED ``Page``/``TotalPages``/``PageSize``,
   never the requested ``pageSize``** - the wrapper silently CLAMPS a large
   request (5000 observed -> 200).
2. **Any transport, HTTP-status, shape or row-cap failure raises BEFORE any
   hash/watermark/delete state is touched** (AC-08-23) - the walk loop runs
   to completion (or fails) entirely before the hashing/persistence section
   below it is ever reached.
3. **The connection id is a stored polymorphic id**, re-resolved tenant- AND
   provider-scoped on every run via ``ConnectionRepository.get_for_provider``
   - never a bare get-by-id, and never through ``CompanyService.client_for``
   (which refuses a non-vendor company outright and is task-connection-
   independent, AC-08-13 - a company may read an HTTP task off ANY of the
   tenant's open connections, not just its own).
4. **The watermark cursor reuses the SQL source's own keys**
   (``CURSOR_MARK``/``CURSOR_COLUMN``) so the two source kinds are
   indistinguishable to everything downstream of ``FetchResult.cursor``.
"""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import httpx

from ..client import parse_last_modified
from ..mapping import IdentityError, flat_source_ref
from ..models import RUN_MODE_MANUAL, RUN_MODE_RECONCILE, SOURCE_IMPL_AUTOCOUNT_HTTP
from ..repositories import ConnectionRepository, RowHashRepository
from ..provider import PROVIDER_KEY, is_open_connection
from ..sources import (
    FetchResult,
    LookupVerification,
    SourceContext,
    SourceRecord,
    Watermark,
    register_source,
)
from ..sql_source.hashing import compared_columns_for, row_hash
from ..sql_source.source import CURSOR_COLUMN, CURSOR_MARK, MAX_EXTRACT_ROWS
from .client import (
    MIN_PAGE_SIZE,
    HttpApiClient,
    HttpTransportError,
    connection_sizing,
)
from .combine import apply_combine, combine_output_columns
from .envelope import ENVELOPE_LIST, ENVELOPE_PAGED, EnvelopePage, parse_page
from .errors import HttpSourceError
from .lookups import AliasCollisionError, build_index, effective_result_columns, merge_onto_rows
from .preview import validate_http_path

logger = logging.getLogger("foundryx.autocount")

# AC-10-75 (the db2 524-timeout ops finding, 2026-09-19) - a page that has
# now timed out TWICE at the same page size halves it (floor MIN_PAGE_SIZE,
# imported from ``.client`` since sprint-5/10 confirm-3 S1 - see
# ``connection_sizing``'s own docstring) and restarts the walk from page 1,
# at most MAX_PAGE_HALVINGS times per walk before the existing failure rule
# applies unchanged. A connect error or another 5xx (never a timeout, never
# a 4xx) gets its own, separate ladder - up to
# ``len(TRANSPORT_RETRY_BACKOFFS_SECONDS)`` retries with a longer backoff
# and NO halving.
MAX_PAGE_HALVINGS = 2
MAX_TIMEOUT_ATTEMPTS_PER_PAGE = 2
TIMEOUT_RETRY_BACKOFF_SECONDS = 1.0
TRANSPORT_RETRY_BACKOFFS_SECONDS: Tuple[float, ...] = (1.0, 4.0)
# Cloudflare answers a 524 (a gateway-level timeout) as an ordinary HTTP
# response, not a transport exception - AC-10-75 is explicit this must be
# treated as a TIMEOUT, never as "just another 5xx to give up on".
CLOUDFLARE_TIMEOUT_STATUS = 524

# The 20% / 50-row safety net a reconcile's delete diff must clear before it
# is trusted (mirrors ``sql_source.source``'s own constants exactly - shared
# semantics, not a second policy to drift from the first).
DELETE_GUARD_RATIO = 0.2
DELETE_GUARD_MIN_ABSOLUTE = 50

# sprint-5/11 S6 (AC-11-10, owner ruling R2) - a 429 at concurrency > 1 backs
# off ONCE: sleep the echoed ``Retry-After``, clamped to this range (default
# when absent/unparsable), then restart the REST of the walk serially - a
# SECOND 429 (on the serial restart) fails like any other 4xx, never a
# second back-off.
BACKOFF_RETRY_AFTER_DEFAULT_SECONDS = 5.0
BACKOFF_RETRY_AFTER_MIN_SECONDS = 1.0
BACKOFF_RETRY_AFTER_MAX_SECONDS = 30.0


class _PageTimedOutTwice(Exception):
    """Internal signal only (AC-10-75): ONE page has now timed out on BOTH
    its attempts at the CURRENT page size. Caught by ``_walk_endpoint``,
    which owns the halving budget - ``_fetch_page``/``_walk_path`` know
    nothing about it."""


class _ConcurrentBackoff(Exception):
    """Internal signal only (AC-11-10): a worker in a concurrent batch saw a
    429. Caught by the DRAINING thread (never a worker) - it records ONE
    activity note, sleeps the clamped ``Retry-After``, then restarts the
    rest of the walk serially."""

    def __init__(self, retry_after: Optional[str]) -> None:
        super().__init__("429 Too Many Requests")
        self.retry_after = retry_after


def _clamp_retry_after_seconds(raw: Optional[str]) -> float:
    if raw is not None:
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = None
        else:
            return max(
                BACKOFF_RETRY_AFTER_MIN_SECONDS,
                min(value, BACKOFF_RETRY_AFTER_MAX_SECONDS),
            )
    return BACKOFF_RETRY_AFTER_DEFAULT_SECONDS


class HttpApiTaskNotConfigured(HttpSourceError):
    """The task's ``source_config`` is missing a required field. Raised at
    construction, before any request leaves us."""


class HttpApiSource:
    """One entity, one company, one open REST connection."""

    def __init__(
        self,
        ctx: SourceContext,
        *,
        entity_type: str,
        mode: str = RUN_MODE_MANUAL,
        persist_hashes: bool = True,
        row_limit: int = MAX_EXTRACT_ROWS,
        transport: Any = None,
        # sprint-5/10 review round 1 MUST-FIX 1 (AC-10-26) - a liveness
        # callback fired after EVERY page of EVERY endpoint walked (main
        # path AND every lookup, since both route through ``_walk_path``).
        # ``None`` (every push-path construction) is a no-op - the push
        # path's own heartbeat discipline (``sync._heartbeat``) is untouched.
        #
        # sprint-5/11 S5 (AC-11-40) - widened from a bare no-arg callback to
        # ``(stage, page, totalPages)`` so a caller (``sync.py``'s
        # ``_beat_and_check``, ``preview_job.py``'s own checkpoint) can stamp
        # ``JobService.beat_progress`` with real numbers instead of a bare
        # liveness ping - ``stage`` is ``"source"`` for the main walk,
        # ``"lookup:<alias>"`` for a lookup's own walk (set on ``self`` right
        # before each ``_walk_endpoint`` call, read back here); ``totalPages``
        # is ``None`` for a bare-array endpoint (never guessed).
        heartbeat: Optional[Callable[[str, int, Optional[int]], None]] = None,
        **_extra: Any,
    ) -> None:
        self.entity_type = entity_type
        self.mode = mode
        self.persist_hashes = persist_hashes
        self.row_limit = row_limit
        self._on_page = heartbeat
        # sprint-5/11 S5 - which endpoint ``_walk_path`` is CURRENTLY
        # walking, set by ``_walk``/``_apply_lookups`` immediately before
        # each ``_walk_endpoint`` call, read back by ``_walk_path`` itself
        # when it fires ``self._on_page``.
        self._current_stage = "source"
        self._ctx = ctx
        # sprint-5/10 review round 1 follow-up - per-lookup completeness,
        # populated by ``_apply_lookups`` and read back by ``fetch_changes``
        # onto ``FetchResult.lookup_verification``. Keyed by alias; a lookup
        # that is never walked (an empty ``self.lookups``) leaves this empty.
        self._lookup_verification: Dict[str, LookupVerification] = {}
        # review round 2 (item 2, AC-10-32/A7) - the effective page size the
        # MAIN walk (``_walk``, never a lookup's own walk) settled on, post
        # any AC-10-75 halving. ``None`` until the first successful walk;
        # read back by ``sync._run_pull_snapshot`` onto the snapshot's own
        # ``metadata_json.sourcePageSize``.
        self.source_page_size: Optional[int] = None
        # Set by ``_walk_endpoint`` on EVERY successful walk it completes
        # (main path AND every lookup) - purely internal bookkeeping;
        # ``_walk`` alone promotes it onto the public attribute above,
        # immediately after the MAIN walk and before any lookup ever runs.
        self._last_walked_page_size: Optional[int] = None
        # sprint-5/11 S6 (AC-11-11) - mirrors ``source_page_size``/
        # ``_last_walked_page_size`` exactly: the EFFECTIVE concurrency the
        # MAIN walk actually used (the configured N when it legitimately
        # went concurrent, or 1 for every AC-11-02 fallback/downgrade) -
        # ``None`` until the first successful walk; read back by
        # ``sync._run_pull_snapshot`` onto ``metadata_json.sourceConcurrency``.
        self.source_concurrency: Optional[int] = None
        self._last_walk_concurrency: int = 1

        config = getattr(ctx.entity_config, "source_config", None) or {}
        if not isinstance(config, dict):
            raise HttpApiTaskNotConfigured("This entity has no HTTP task configured.")

        self.path = str(config.get("path") or "").strip()
        if not self.path:
            raise HttpApiTaskNotConfigured("This entity's HTTP task has no path saved yet.")
        self.key_fields = [str(c) for c in (config.get("keyFields") or []) if str(c).strip()]
        if not self.key_fields:
            raise HttpApiTaskNotConfigured(
                "This entity's HTTP task has no key fields, so its rows "
                "cannot be correlated."
            )
        self.watermark_field = str(config.get("watermarkField") or "").strip() or None
        self.distinct_of = [
            str(c) for c in (config.get("distinctOf") or []) if str(c).strip()
        ] or None
        # sprint-5/10 (AC-10-01/02, R9) - operator-authored cross-endpoint
        # joins, already validated at save time; trusted as-is here (the SQL
        # source's own runtime trusts its saved config the same way).
        self.lookups: List[Dict[str, Any]] = [
            dict(item) for item in (config.get("lookups") or []) if isinstance(item, dict)
        ]
        # sprint-5/10 S5a (AC-10-76..81, R11) - the entity-agnostic combine
        # step, already validated at save time; trusted as-is here exactly
        # like ``self.lookups`` above. ``None`` when the task carries none.
        combine_config = config.get("combine")
        self.combine: Optional[Dict[str, Any]] = (
            combine_config if isinstance(combine_config, dict) else None
        )

        self.result_columns = [
            str(c) for c in (getattr(ctx.entity_config, "result_columns", None) or [])
        ]
        # review round 1 blocker 3 / round 1b - AC-10-06: the compared-column
        # baseline is derived through the ONE shared helper
        # (``effective_result_columns``), which unions every configured
        # lookup's own field alias onto the STORED (raw-only as of round
        # 1b) result columns. The stamped `result_columns` reflects
        # whatever the LAST preview happened to include (which may predate
        # the lookup, or predate a preview that ever merged one in at all);
        # without this, an enrich-only value change on a task whose last
        # preview ran without the alias would never register as `updated` -
        # AC-10-06's whole point. An operator's EXPLICIT `comparedFields`
        # still wins (`compared_columns_for` only ever narrows to it).
        #
        # review round 3 (B1) - a combine-carrying task's rows are the
        # COMBINED shape by the time de-dup/hashing sees them (AC-10-80):
        # ``self.result_columns``/``self.lookups`` name PRE-combine raw
        # and lookup columns that simply do not exist on a combined row
        # (a ``groupBy``/``measures[].source`` name is CONSUMED, never
        # projected) - hashing a combined row against that stale set
        # compares columns that are always absent, which silently kills
        # change detection forever (proven live: groupBy ``g``, measure
        # ``v`` -> ``total``; a second run with a different ``v`` reported
        # ``updated_count == 0``). ``combine_output_columns`` is the SAME
        # helper the save-time gate and the preview route use, so the
        # compared set, the Mapping/preview picker and the row hash can
        # never drift against one another for a combine-carrying task.
        effective_columns = (
            combine_output_columns(self.combine)
            if self.combine
            else effective_result_columns(self.result_columns, self.lookups)
        )
        configured_compared = [str(c) for c in (config.get("comparedFields") or [])]
        self.compared_columns = compared_columns_for(
            configured=configured_compared,
            result_columns=effective_columns or configured_compared,
            key_columns=self.key_fields,
        )

        connection_id = str(config.get("connectionId") or "").strip()
        if not connection_id:
            raise HttpApiTaskNotConfigured(
                "This entity's HTTP task has no connection selected."
            )
        conn = ConnectionRepository(ctx.db).get_for_provider(
            ctx.tenant_id, connection_id, PROVIDER_KEY
        )
        # S6 (sprint-5/08 review round 1) - provider-scoped alone is not
        # enough: a task saved against a BASIC-auth ``autocount`` connection
        # (e.g. an operator switched a connection's auth after saving the
        # task) must fail the SAME way a missing connection does, never
        # silently attempt an unauthenticated GET against a vendor endpoint
        # that expects a session.
        if conn is None or not is_open_connection(conn):
            raise HttpApiTaskNotConfigured(
                "The API connection this task reads from was not found."
            )
        conn_config = conn.config_json or {}
        base_url = str(conn_config.get("baseUrl") or "").strip()
        # AC-10-85 - the connection's OWN pageSize/requestTimeoutSeconds
        # (falling back to the module defaults for a legacy row), never the
        # fixed module constants a run used to always start from. Sprint-5/10
        # confirm-3 S1 - ``connection_sizing`` is now shared with the preview
        # path (``http_source.preview.run_http_preview`` via
        # ``services.etl_service.EtlService.preview_http``), so the two
        # never disagree on either knob.
        sizing = connection_sizing(conn_config)
        self._page_size = sizing.page_size
        # sprint-5/11 S6 (AC-11-01) - the connection's own opt-in concurrency
        # ceiling (1..8, default 1 = byte-identical to today); read ONCE here
        # exactly like ``self._page_size``, never re-read mid-walk.
        self._page_concurrency = sizing.max_concurrent_pages
        self._client = HttpApiClient(
            base_url, transport=transport, timeout_seconds=sizing.request_timeout_seconds
        )

    # ── identity ───────────────────────────────────────────────────────────

    def source_ref(self, raw: Dict[str, Any]) -> Optional[str]:
        try:
            return flat_source_ref(
                raw,
                database_name=getattr(self._ctx.company, "database_name", ""),
                key_columns=self.key_fields,
                entity_type=self.entity_type,
            )
        except IdentityError:
            return None

    # ── page walk ──────────────────────────────────────────────────────────

    def _fetch_page(self, path: str, page: int, page_size: int) -> httpx.Response:
        """One page GET with the bounded retry ladder (AC-10-75). A TIMEOUT
        (incl. a Cloudflare 524, answered as an ordinary response - never a
        transport exception) gets exactly one retry after a 1s backoff; a
        SECOND timeout of the SAME page+size raises ``_PageTimedOutTwice``
        so ``_walk_endpoint`` (which owns the halving budget) can decide. A
        connect error or another 5xx gets up to
        ``len(TRANSPORT_RETRY_BACKOFFS_SECONDS)`` retries (1s then 4s) and
        never halves. A 4xx, a non-JSON body or a shape change is never
        retried here - the caller's job, unchanged from before this AC.

        review round 1 nit - the timeout counter and the transport-retry
        counter are SEPARATE: a 5xx followed by ONE timeout must not halve
        (only a SECOND consecutive timeout does), so a page that failed once
        for an unrelated reason is never one timeout away from a halve."""
        timeout_attempts = 0
        transport_attempts = 0
        while True:
            try:
                response = self._client.get(path, {"page": page, "pageSize": page_size})
            except HttpTransportError as exc:
                if exc.is_timeout:
                    timeout_attempts += 1
                    if timeout_attempts >= MAX_TIMEOUT_ATTEMPTS_PER_PAGE:
                        raise _PageTimedOutTwice() from exc
                    time.sleep(TIMEOUT_RETRY_BACKOFF_SECONDS)
                    continue
                transport_attempts += 1
                if transport_attempts > len(TRANSPORT_RETRY_BACKOFFS_SECONDS):
                    raise HttpSourceError(exc.message, code="transport", page=page) from exc
                time.sleep(TRANSPORT_RETRY_BACKOFFS_SECONDS[transport_attempts - 1])
                continue

            if response.status_code == CLOUDFLARE_TIMEOUT_STATUS:
                timeout_attempts += 1
                if timeout_attempts >= MAX_TIMEOUT_ATTEMPTS_PER_PAGE:
                    raise _PageTimedOutTwice()
                time.sleep(TIMEOUT_RETRY_BACKOFF_SECONDS)
                continue
            if response.status_code >= 500:
                transport_attempts += 1
                if transport_attempts > len(TRANSPORT_RETRY_BACKOFFS_SECONDS):
                    raise HttpSourceError(
                        f"AutoCount answered HTTP {response.status_code} on page {page}.",
                        code="http_status",
                        page=page,
                        status=response.status_code,
                    )
                time.sleep(TRANSPORT_RETRY_BACKOFFS_SECONDS[transport_attempts - 1])
                continue
            return response

    def _parse_envelope(self, response: httpx.Response, *, page: int) -> EnvelopePage:
        """Status + JSON + shape parsing for ONE already-fetched page
        response - the SAME three checks (``http_status``/``not_json``/
        ``shape``) every walker (serial, or a concurrent worker) raises for
        the identical fault. No DB access, no session - safe to call from a
        worker thread (AC-11-09)."""
        if not (200 <= response.status_code < 300):
            raise HttpSourceError(
                f"AutoCount answered HTTP {response.status_code} on page {page}.",
                code="http_status",
                page=page,
                status=response.status_code,
            )
        try:
            body = response.json()
        except ValueError as exc:
            raise HttpSourceError(
                f"The response on page {page} was not JSON.",
                code="not_json",
                page=page,
                status=response.status_code,
            ) from exc
        try:
            return parse_page(body)
        except ValueError as exc:
            raise HttpSourceError(
                str(exc), code="shape", page=page, status=response.status_code
            ) from exc

    def _walk_path(
        self, path: str, page_size: int
    ) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
        """AC-11-02/03 - the dispatcher: page 1 is ALWAYS fetched alone,
        serially (unchanged retry/halving budget). At ``max_concurrent_pages
        <= 1`` (the connection's own configured N, the default) this hands
        straight to ``_walk_path_serial`` - byte-identical to today, ZERO
        risk to every existing (N never configured) task. Otherwise page 1's
        own echo decides AC-11-02's five fallback conditions (bare-array
        envelope, no ``TotalPages``, no echoed ``Page``, ``TotalPages < 2``,
        or ``max_concurrent_pages == 1`` itself - the last one is already
        handled by the branch above) BEFORE any page 2 request - ineligible
        falls back to the SAME serial walker (fed page 1's already-fetched
        response, so it is never re-requested); eligible goes concurrent."""
        if self._page_concurrency <= 1:
            self._last_walk_concurrency = 1
            return self._walk_path_serial(path, page_size)

        response1 = self._fetch_page(path, 1, page_size)
        parsed1 = self._parse_envelope(response1, page=1)
        eligible = (
            parsed1.kind == ENVELOPE_PAGED
            and parsed1.total_pages is not None
            and parsed1.total_pages >= 2
            and parsed1.page == 1
        )
        if not eligible:
            self._last_walk_concurrency = 1
            self._client.record_note(
                f"'{path}' configured for concurrency {self._page_concurrency} but "
                f"walked serially (1) - the server's own response did not meet "
                f"AC-11-02's conditions (a paged envelope, TotalPages >= 2, and "
                f"an echoed Page == 1 on the first page).",
                ok=True,
            )
            return self._walk_path_serial(path, page_size, prefetched=(response1, parsed1))
        return self._walk_path_concurrent(path, page_size, response1, parsed1)

    def _walk_path_serial(
        self,
        path: str,
        page_size: int,
        *,
        prefetched: Optional[Tuple[httpx.Response, EnvelopePage]] = None,
    ) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
        """GET every page of ONE endpoint at a FIXED page size, returning
        ``(rows, reported_total, envelope_kind)``. Raises ``HttpSourceError``
        before touching any downstream state, or ``_PageTimedOutTwice`` when
        a page has now timed out on both its attempts (the caller decides
        whether to halve and restart). ``envelope_kind`` is the SAME shape
        every page of this walk answered (paged vs bare array,
        ``ENVELOPE_PAGED``/``ENVELOPE_LIST`` - a later page answering a
        DIFFERENT shape already fails loudly above, so this is unambiguous).

        sprint-5/10 review round 1 MUST-FIX 1 (AC-10-26) - fires the
        constructor's ``heartbeat`` callback after EVERY successfully parsed
        page, main path AND lookup endpoints alike (both route through this
        one walker). A build abandoned mid-walk (the callback raises) stops
        the walk immediately - no further pages are requested.

        sprint-5/11 S6 - THE unchanged serial algorithm (AC-11-02's own
        fallback target, and a 429 back-off's serial restart target).
        ``prefetched`` (``_walk_path``'s own AC-11-02 eligibility check,
        or ``None`` for every other caller) supplies page 1's ALREADY-
        fetched response so it is never requested twice - every downstream
        check for it (scanned/reported_total/heartbeat/row-cap/kind) still
        runs HERE, in the SAME order, so behaviour is byte-identical
        regardless of which caller reached this method."""
        scanned: List[Dict[str, Any]] = []
        established_kind: Optional[str] = None
        reported_total: Optional[int] = None
        # SF-5 (sprint-5/08 review round 2) - a server that ignores the
        # `page` query param and echoes the SAME `Page` forever would
        # otherwise spin until the row-limit guard tripped (`MAX_EXTRACT_
        # ROWS`, 200,000) hammering the endpoint the entire way there.
        previous_reported_page: Optional[int] = None
        page = 1
        while True:
            if page == 1 and prefetched is not None:
                response, parsed = prefetched
            else:
                response = self._fetch_page(path, page, page_size)
                parsed = self._parse_envelope(response, page=page)

            if established_kind is None:
                established_kind = parsed.kind
            elif parsed.kind != established_kind:
                raise HttpSourceError(
                    f"Page {page} answered a '{parsed.kind}' shape but page 1 "
                    f"was '{established_kind}'.",
                    code="shape_change",
                    page=page,
                    status=response.status_code,
                )

            scanned.extend(parsed.rows)
            if parsed.total_count is not None:
                reported_total = parsed.total_count

            # MUST-FIX 1 - beat AFTER this page is durable in ``scanned``
            # (never before it is parsed), so a heartbeat always corresponds
            # to real, already-accounted progress. A raise here (the build
            # was abandoned) stops the walk on THIS page - no further
            # request is made. sprint-5/11 S5 - carries THIS page's own
            # number and the echoed total (``None`` for a bare-array
            # endpoint, which never echoes one) so the caller can stamp real
            # progress, not just a liveness ping.
            if self._on_page is not None:
                self._on_page(self._current_stage, page, parsed.total_pages)

            if len(scanned) > self.row_limit:
                raise HttpSourceError(
                    f"This task's extract exceeded the {self.row_limit} row cap.",
                    code="row_limit",
                    page=page,
                )

            if parsed.kind == ENVELOPE_LIST:
                break
            if not parsed.rows:
                # round 3 nit: an empty page always terminates cleanly, even
                # from a server that clamps the echoed `Page` to the last
                # page (e.g. `{"Page": 1, "Data": []}` after page 1 already
                # answered `{"Page": 1, ...}`) - the page-advance guard below
                # must never fire on the page that is ending the scan.
                break

            # SF-5 - a server that ignores the `page` param and echoes the
            # SAME `Page` back on every request must fail fast (the SECOND
            # request, as soon as the echoed value fails to advance) rather
            # than spin toward the row-limit guard.
            if (
                page > 1
                and parsed.page is not None
                and previous_reported_page is not None
                and parsed.page == previous_reported_page
            ):
                raise HttpSourceError(
                    f"The echoed page did not advance past {parsed.page} after "
                    f"requesting page {page} - this endpoint appears to be "
                    f"ignoring the page parameter.",
                    code="shape",
                    page=page,
                    status=response.status_code,
                )
            previous_reported_page = parsed.page

            total_pages = parsed.total_pages
            current_page = parsed.page if parsed.page is not None else page
            if total_pages is not None and current_page >= total_pages:
                break
            page += 1

        return scanned, reported_total, established_kind

    # ── bounded-concurrency walk (sprint-5/11 S6, AC-11-02..11) ─────────────

    def _fetch_page_concurrent(self, path: str, page: int, page_size: int) -> EnvelopePage:
        """The per-page WORKER body a ``ThreadPoolExecutor`` submits for the
        concurrent path (AC-11-09) - HTTP GET + JSON parse ONLY: this body
        touches no database handle of any kind, and fires no liveness
        callback (that happens from the DRAINING thread instead, once per
        completed page, in requested-page order - see
        ``test_concurrent_worker_never_touches_the_database``'s own static
        check on this exact method). Reuses ``_fetch_page``'s own retry
        ladder unchanged (AC-10-75 preserved exactly) and ``_parse_envelope``
        for the SAME status/JSON/shape codes the serial walk raises for the
        identical fault. Raises ``_ConcurrentBackoff`` on a 429 (AC-11-10,
        handled by the draining thread's own back-off) and a ``shape``
        ``HttpSourceError`` naming the REQUESTED page when the echoed
        ``Page`` is present and wrong (AC-11-06 - replaces the serial SF-5
        non-advancing guard, which has no meaning once pages are requested
        out of order)."""
        response = self._fetch_page(path, page, page_size)
        if response.status_code == 429:
            raise _ConcurrentBackoff(response.headers.get("Retry-After"))
        parsed = self._parse_envelope(response, page=page)
        if parsed.page is not None and parsed.page != page:
            raise HttpSourceError(
                f"Page {page} echoed Page={parsed.page}, requested {page}.",
                code="shape",
                page=page,
                status=response.status_code,
            )
        return parsed

    def _run_concurrent_batch(
        self, path: str, page_size: int, batch_pages: List[int]
    ) -> List[EnvelopePage]:
        """Submits every page in ``batch_pages`` to a ``ThreadPoolExecutor``
        AT ONCE (AC-11-03: at most N in flight, N == this batch's size) and
        drains results in REQUESTED-PAGE order (never completion order,
        AC-11-04) - returns them ascending by page. A halving signal
        (``_PageTimedOutTwice``) or any ``HttpSourceError``/
        ``_ConcurrentBackoff`` cancels the WHOLE in-flight set
        (``executor.shutdown(cancel_futures=True)``) and re-raises the
        FIRST fault observed (AC-11-07/08/10) - never assembled, never a
        second batch submitted."""
        results: Dict[int, EnvelopePage] = {}
        executor = ThreadPoolExecutor(max_workers=len(batch_pages))
        try:
            futures = {
                executor.submit(self._fetch_page_concurrent, path, p, page_size): p
                for p in batch_pages
            }
            first_error: Optional[BaseException] = None
            for future in as_completed(futures):
                try:
                    results[futures[future]] = future.result()
                except BaseException as exc:  # noqa: BLE001 - re-raised verbatim below
                    if first_error is None:
                        first_error = exc
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        if first_error is not None:
            raise first_error
        return [results[p] for p in batch_pages]

    def _walk_path_concurrent(
        self,
        path: str,
        page_size: int,
        response1: httpx.Response,
        parsed1: EnvelopePage,
    ) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
        """AC-11-02/03/04/06/07/10/11 - page 1 (already fetched/parsed by
        ``_walk_path``) seeds ``scanned``; pages 2..``TotalPages`` walk in
        batches of ``self._page_concurrency`` via ``_run_concurrent_batch``,
        assembled strictly ascending by REQUESTED page (never completion
        order). A 429 aborts the batch and restarts the REST of the walk
        serially (AC-11-10) - a full, fresh ``_walk_path_serial`` call, so
        page 1 (and everything else) is re-walked exactly once more; every
        other fault (row cap, an echoed-page mismatch, a halving signal)
        propagates straight to the caller, which is `_walk_endpoint`'s own
        halving catch for `_PageTimedOutTwice`."""
        started = time.monotonic()
        established_kind = parsed1.kind
        scanned: List[Dict[str, Any]] = list(parsed1.rows)
        reported_total = parsed1.total_count
        total_pages = parsed1.total_pages
        n = self._page_concurrency
        self._last_walk_concurrency = n

        if self._on_page is not None:
            self._on_page(self._current_stage, 1, total_pages)
        if len(scanned) > self.row_limit:
            raise HttpSourceError(
                f"This task's extract exceeded the {self.row_limit} row cap.",
                code="row_limit",
                page=1,
            )

        # AC-11-07 - the row-cap PRE-FLIGHT: a wildly large walk must never
        # even submit its first concurrent batch. Projected from page 1's
        # OWN echoed PageSize (never the requested one, AC-08-22's "trust
        # the echo" rule) - falls back to the requested size only when the
        # server never echoes one at all.
        echoed_page_size = parsed1.page_size or page_size
        if total_pages and echoed_page_size and total_pages * echoed_page_size > self.row_limit:
            raise HttpSourceError(
                f"This task's extract would exceed the {self.row_limit} row cap "
                f"({total_pages} pages x {echoed_page_size} rows/page projected).",
                code="row_limit",
                page=1,
            )

        next_page = 2
        while next_page <= total_pages:
            batch_pages = list(range(next_page, min(next_page + n, total_pages + 1)))
            try:
                parsed_pages = self._run_concurrent_batch(path, page_size, batch_pages)
            except _ConcurrentBackoff as backoff:
                self._client.record_note(
                    f"AutoCount answered HTTP 429 while walking '{path}' at "
                    f"concurrency {n} - backing off and restarting serially.",
                    ok=False,
                )
                time.sleep(_clamp_retry_after_seconds(backoff.retry_after))
                return self._walk_path_serial(path, page_size)

            for p, parsed in zip(batch_pages, parsed_pages):
                scanned.extend(parsed.rows)
                if parsed.total_count is not None:
                    reported_total = parsed.total_count
                if self._on_page is not None:
                    self._on_page(self._current_stage, p, parsed.total_pages)
                if len(scanned) > self.row_limit:
                    raise HttpSourceError(
                        f"This task's extract exceeded the {self.row_limit} row cap.",
                        code="row_limit",
                        page=p,
                    )
            next_page += n

        elapsed_ms = int((time.monotonic() - started) * 1000)
        self._client.record_note(
            f"Walked '{path}' with concurrency {n} across {total_pages} pages "
            f"in {elapsed_ms}ms.",
            ok=True,
        )
        return scanned, reported_total, established_kind

    def _walk_endpoint(
        self, path: str
    ) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
        """The full page walk for ONE endpoint - the main path OR a lookup
        (AC-10-02: "the SAME page walker"), with AC-10-75's bounded per-page
        retry and page-size halving. Each endpoint walked gets its OWN
        halving budget - the main path and every lookup share the exact
        mechanics, never a counter one could exhaust for the other.

        MUST-FIX 2 (AC-10-24) - a halving RESTART discards the PARTIAL
        ``scanned``/``reported_total`` of the timed-out attempt entirely
        (``_walk_path`` builds a fresh local ``scanned = []`` on every call);
        only the FINAL, successfully-returned tuple from this method is ever
        used - counts are never accumulated across a restart.

        AC-10-85 - starts at THIS connection's own configured page size
        (``self._page_size``, set once in ``__init__``), never the module
        constant - the main path AND every lookup share the same starting
        size and the same halving budget mechanics, since both route
        through this one method."""
        page_size = self._page_size
        halvings = 0
        while True:
            try:
                result = self._walk_path(path, page_size)
                # review round 2 (item 2) - the page size THIS walk actually
                # succeeded at, main path AND every lookup alike; ``_walk``
                # alone promotes it onto the public ``source_page_size``.
                self._last_walked_page_size = page_size
                return result
            except _PageTimedOutTwice as exc:
                if halvings >= MAX_PAGE_HALVINGS:
                    raise HttpSourceError(
                        f"'{path}' timed out repeatedly even after {halvings} "
                        f"halving(s) of the page size.",
                        code="transport",
                    ) from exc
                page_size = max(page_size // 2, MIN_PAGE_SIZE)
                halvings += 1
                # AC-10-75 - "the restart and the effective page size are
                # recorded in the run's CallRecord activity" (every retry
                # attempt is already its own CallRecord via `_record_call`).
                self._client.record_note(
                    f"'{path}' timed out twice at the previous page size - "
                    f"halving to {page_size} and restarting from page 1.",
                    ok=False,
                )

    def _walk(self) -> Tuple[List[Dict[str, Any]], Optional[int], Optional[str]]:
        # sprint-5/11 S5 - the main path's own stage name; already the
        # constructor default, set explicitly here for symmetry with
        # ``_apply_lookups``' own per-lookup assignment below.
        self._current_stage = "source"
        result = self._walk_endpoint(self.path)
        # review round 2 (item 2, AC-10-32/A7) - captured HERE, immediately
        # after the MAIN walk and before any lookup's own ``_walk_endpoint``
        # call ever runs (``_apply_lookups`` fires later in
        # ``fetch_changes``), so this is always the main path's OWN value,
        # never a lookup's.
        self.source_page_size = self._last_walked_page_size
        # sprint-5/11 S6 (AC-11-11) - the SAME promotion, for the effective
        # concurrency the main walk actually used.
        self.source_concurrency = self._last_walk_concurrency
        return result

    # ── lookups (AC-10-01/02/03, R9) ──────────────────────────────────────

    def _apply_lookups(self, rows: List[Dict[str, Any]]) -> None:
        """Merge every configured lookup onto ``rows`` IN PLACE, in list
        order (multi-hop - a later lookup may join on an earlier one's own
        alias, since it is already written onto the row by then). An
        endpoint failure fails the WHOLE run through the same
        ``HttpSourceError`` path a source page failure does (AC-10-03) - the
        message is re-wrapped so it NAMES the lookup and its endpoint,
        because the underlying walk's own message never mentions either."""
        for i, lookup in enumerate(self.lookups):
            path = str(lookup.get("path") or "")
            alias_name = str(lookup.get("as") or "")
            on = lookup.get("on") or []
            fields = lookup.get("fields") or []
            # review round 1 blocker 1(c) - defence in depth: refuse a
            # lookup path that fails the SAME rule the editor/save gate
            # enforces, so a row saved BEFORE this fix (or edited directly
            # in the DB) is never walked, not even once.
            path_error = validate_http_path(path)
            if path_error:
                raise HttpSourceError(
                    f"Lookup {i} ('{alias_name}')'s path '{path}' is invalid: "
                    f"{path_error} Nothing was staged or pushed.",
                    code="lookup_path",
                )
            try:
                # review round 1 follow-up (coordinator ruling 2026-09-20,
                # AC-10-24 applied to lookups) - the lookup walk's OWN
                # ``reported_total``/``envelope_kind`` are no longer thrown
                # away: a pull snapshot build needs them to know whether
                # THIS lookup's own walk was verified, by the exact same
                # rule the main walk uses. The push path never reads
                # ``FetchResult.lookup_verification``, so this is purely
                # additional bookkeeping - the merge below is unchanged.
                #
                # sprint-5/11 S5 - THIS lookup's own stage name, read back by
                # ``_walk_path``'s heartbeat call for the duration of its walk.
                self._current_stage = f"lookup:{alias_name}"
                lookup_rows, lookup_total, lookup_kind = self._walk_endpoint(path)
            except HttpSourceError as exc:
                raise HttpSourceError(
                    f"The '{alias_name}' lookup endpoint '{path}' failed: {exc.message}",
                    code=exc.code,
                    page=exc.page,
                    status=exc.status,
                    # sprint-5/10 (AC-10-22/64) - a pull snapshot build tells
                    # an enrich-endpoint fault apart from a main-path one
                    # (``ENRICH_FAILED`` vs ``SOURCE_PAGE_FAILED``) by this
                    # phase tag, never by parsing the message.
                    phase="enrich",
                ) from exc
            # review round 1 follow-up - verified by the SAME rule the main
            # walk uses (bare array = verified; paged = the scanned count
            # matching the echoed total), counts from THIS walk only (a
            # halving restart already discarded any earlier, timed-out
            # attempt inside ``_walk_endpoint`` itself). An alias reused
            # across a multi-hop lookup config (not possible today - ``as``
            # is unique per task - kept simple: last write wins) never
            # matters in practice.
            self._lookup_verification[alias_name] = LookupVerification(
                verified=(
                    lookup_kind == ENVELOPE_LIST
                    or (lookup_total is not None and len(lookup_rows) == lookup_total)
                ),
                rows_scanned=len(lookup_rows),
                reported_total=lookup_total,
            )
            index = build_index(lookup_rows, on)
            try:
                misses = merge_onto_rows(rows, index, on, fields)
            except AliasCollisionError as exc:
                # review round 1 blocker 2(ii) - a poisoned alias (one that
                # would overwrite a REAL column or an earlier lookup's own
                # alias) fails the whole run, fail-before-state, rather than
                # silently deliver the overwritten value.
                raise HttpSourceError(
                    f"Lookup {i} ('{alias_name}')'s field alias '{exc.alias}' "
                    f"would overwrite an existing column of the same name - "
                    f"nothing was staged or pushed.",
                    code="alias_collision",
                ) from exc
            if misses:
                # AC-10-03 - a miss is counted, never fatal: ONE warning
                # activity note (never a per-row note) naming the entity,
                # the enrich alias and the miss count.
                field_names = ", ".join(str(f.get("as")) for f in fields) or "its fields"
                self._client.record_note(
                    f"{misses} row(s) had no match for the '{alias_name}' lookup "
                    f"('{path}') for '{self.entity_type}' - {field_names} left "
                    f"unset for them.",
                    ok=False,
                )

    # ── de-dup / distinctOf ───────────────────────────────────────────────

    def _dedupe(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """First-occurrence-wins de-dup on the task's key fields (page drift
        while walking, AC-08-22). A row whose identity cannot be resolved is
        kept as-is - it is not a duplicate of anything, it simply fails
        identity later, exactly like the SQL source's own behaviour."""
        seen: set = set()
        duplicates = 0
        kept: List[Dict[str, Any]] = []
        for row in rows:
            ref = self.source_ref(row)
            if ref is None:
                kept.append(row)
                continue
            if ref in seen:
                duplicates += 1
                continue
            seen.add(ref)
            kept.append(row)
        if duplicates:
            logger.warning(
                "AutoCount HTTP %s: %d duplicate key(s) seen across pages for "
                "company %s - first occurrence kept.",
                self.entity_type,
                duplicates,
                getattr(self._ctx.company, "id", ""),
            )
            # S12 (sprint-5/08 review round 1, AC-08-22) - the SAME fact,
            # also on the run's activity trail (not just the app log an
            # operator cannot see).
            self._client.record_note(
                f"{duplicates} duplicate key(s) seen while walking pages for "
                f"'{self.entity_type}' - first occurrence kept.",
                ok=False,
            )
        return kept

    def _project_distinct(self, rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """``distinctOf`` -> one record per distinct non-blank trimmed value
        across the listed fields, first-seen order (AC-08-22)."""
        seen: set = set()
        values: List[str] = []
        for row in rows:
            for field_name in self.distinct_of or ():
                raw_value = row.get(field_name)
                if raw_value is None:
                    continue
                value = str(raw_value).strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                values.append(value)
        return [{"value": v} for v in values]

    # ── fetch ──────────────────────────────────────────────────────────────

    def fetch_changes(self, since: Watermark) -> FetchResult:
        # review round 2 (item 6) - reset EVERY call: an instance reused
        # across two ``fetch_changes`` calls (this class carries no other
        # such per-call state) must never leak a stale alias from a PRIOR
        # call's lookups into this one's own ``FetchResult``.
        self._lookup_verification = {}
        full_extract = self.mode == RUN_MODE_RECONCILE or not self.watermark_field

        # MUST-FIX 2 (AC-10-24) - ``envelope_kind`` is the MAIN path's own
        # shape only, straight onto ``FetchResult`` below: a pull snapshot
        # build needs it to know whether ``reported_total`` is even a thing
        # this endpoint has (a bare-array endpoint has none, by design -
        # ``complete`` is unconditionally true for it; a PAGED endpoint that
        # omitted/nulled ``TotalCount`` must NOT read as complete just
        # because ``reported_total is None``).
        scanned_rows, reported_total, envelope_kind = self._walk()
        # AC-10-02 - lookups merge onto every source row BEFORE de-dup, the
        # row hash and mapping; ``distinctOf`` short-circuits below into an
        # entirely different `{"value": v}` row shape, so a lookup (which
        # names real columns) never applies to it.
        if not self.distinct_of:
            self._apply_lookups(scanned_rows)
        rows_scanned = len(scanned_rows)

        # sprint-5/10 S5a (AC-10-80) - combine runs AFTER lookups (may
        # reference a merged alias) and BEFORE de-dup/hashing: de-dup,
        # source_ref minting and row_hash all run on the COMBINED rows, so a
        # push task combines exactly as a pull task does. ``None`` for every
        # existing/control call site - byte-identical output.
        combine_metadata: Optional[Dict[str, Any]] = None
        if self.distinct_of:
            working_rows = self._project_distinct(scanned_rows)
        else:
            reduced_rows = scanned_rows
            if self.combine:
                # sprint-5/11 review round 2 (item 3, AC-11-40) - the
                # "combine" stage, fired once before the reduction step, not
                # page-driven (`page`/`total` unknown - `0`/`None`). This ONE
                # call site covers both consumers of ``fetch_changes``
                # (``sync.py``'s pull-snapshot build AND ``EtlService.
                # preview_task``'s full-scope walk) with no extra plumbing -
                # ``None`` (every task with no combine step) leaves this
                # exactly as it was.
                if self._on_page is not None:
                    self._on_page("combine", 0, None)
                combine_result = apply_combine(scanned_rows, self.combine)
                reduced_rows = combine_result.rows
                combine_metadata = combine_result.metadata
            working_rows = self._dedupe(reduced_rows)

        # New mark = max seen ACROSS THE WHOLE WALK (AC-08-25) - the watermark
        # must reflect what was truly out there this pass, independent of
        # which rows the incremental filter below happens to keep.
        max_mark: Optional[str] = None
        if self.watermark_field:
            for row in scanned_rows:
                value = row.get(self.watermark_field)
                if value is None:
                    continue
                value_str = str(value)
                if max_mark is None or value_str > max_mark:
                    max_mark = value_str

        mark: Optional[str] = None
        if isinstance(since.cursor, dict) and since.cursor.get(CURSOR_COLUMN) == self.watermark_field:
            stored = since.cursor.get(CURSOR_MARK)
            mark = str(stored) if stored is not None else None
        if not full_extract and self.watermark_field and mark is not None:
            working_rows = [
                row for row in working_rows
                if row.get(self.watermark_field) is not None
                and str(row.get(self.watermark_field)) > mark
            ]

        records: List[SourceRecord] = []
        max_seen_dt = None
        for row in working_rows:
            stamp = (
                parse_last_modified(row.get(self.watermark_field))
                if self.watermark_field
                else None
            )
            records.append(SourceRecord(raw=row, last_modified=stamp))
            if stamp is not None and (max_seen_dt is None or stamp > max_seen_dt):
                max_seen_dt = stamp

        # ── hashing / reconcile (mirrors SqlDbSource.fetch_changes) ─────────
        window_to = datetime.now(timezone.utc)
        known: Dict[str, str] = {}
        if full_extract:
            known = RowHashRepository(self._ctx.db).all_hashes(
                self._ctx.tenant_id, self._ctx.company.id, self.entity_type
            )
        else:
            refs = [r for r in (self.source_ref(row) for row in working_rows) if r]
            if refs:
                known = RowHashRepository(self._ctx.db).hashes_for(
                    self._ctx.tenant_id, self._ctx.company.id, self.entity_type, refs
                )

        hashes: Dict[str, str] = {}
        current_refs: set = set()
        added = updated = 0
        # B-A (sprint-5/08 review round 2 blocker) - an empty effective
        # compared set (never previewed: `result_columns` is None/empty AND
        # nothing configured) would make `row_hash(row, [])` == sha256("")
        # for EVERY row, silently killing change detection forever
        # (`updated_count` stuck at 0). Fall back to the row's own non-key
        # fields at hash time - never done when `distinctOf` is set, since
        # the projected `{"value": v}` rows have no "own fields" to fall
        # back to and are already correctly keyed on their sole field.
        fall_back_to_row_fields = not self.compared_columns and not self.distinct_of
        for row in working_rows:
            ref = self.source_ref(row)
            if ref is None:
                continue
            current_refs.add(ref)
            compared = self.compared_columns
            if fall_back_to_row_fields:
                compared = sorted(k for k in row.keys() if k not in self.key_fields)
            value_hash = row_hash(row, compared)
            hashes[ref] = value_hash
            if ref not in known:
                added += 1
            elif known[ref] != value_hash:
                updated += 1

        delete_refs: List[str] = []
        if full_extract and known:
            #     !!  A ZERO-ROW FULL EXTRACT IS NEVER A GENUINE TOTAL WIPE.  !!
            # Same fail-safe rule as the SQL source: raised BEFORE any hash
            # write, so nothing is staged or pushed either way.
            if not scanned_rows:
                raise HttpSourceError(
                    f"This run returned 0 rows while {len(known)} previously-"
                    f"known row(s) exist for this entity - nothing was staged "
                    f"or pushed. This looks like a broken connection, not a "
                    f"genuine full deletion.",
                    code="delete_guard",
                )
            delete_refs = sorted(ref for ref in known if ref not in current_refs)
            threshold = max(DELETE_GUARD_RATIO * len(known), DELETE_GUARD_MIN_ABSOLUTE)
            if len(delete_refs) > threshold:
                raise HttpSourceError(
                    f"This run would delete {len(delete_refs)} of {len(known)} "
                    f"previously-known row(s) - over the safety threshold "
                    f"({threshold:.0f}). Nothing was staged or pushed.",
                    code="delete_guard",
                )

        if self.persist_hashes and hashes:
            RowHashRepository(self._ctx.db).upsert_many(
                self._ctx.tenant_id,
                self._ctx.company.id,
                self.entity_type,
                hashes,
                seen_at=window_to,
            )
            self._ctx.db.commit()

        return FetchResult(
            records=records,
            max_last_modified=max_seen_dt,
            window_from=None,
            window_to=window_to,
            reported_total=reported_total,
            rows_scanned=rows_scanned,
            added_count=added,
            updated_count=updated,
            delete_refs=delete_refs,
            current_refs=sorted(current_refs),
            cursor=(
                {CURSOR_COLUMN: self.watermark_field, CURSOR_MARK: max_mark}
                if self.watermark_field and max_mark is not None
                else None
            ),
            envelope_kind=envelope_kind,
            lookup_verification=dict(self._lookup_verification),
            combine_metadata=combine_metadata,
        )

    # ── observability ──────────────────────────────────────────────────────

    def drain_activity(self):
        return self._client.drain_calls()

    def close(self) -> None:
        self._client.close()


def _http_api_factory(ctx: SourceContext, *, entity_type: str, **kwargs: Any) -> HttpApiSource:
    """Factory contract (plan §2.1, AC-22-08): builds its OWN transport from
    the context - never touches the SQL runtime, never signs in to the
    vendor session API. Swallows the vendor/SQL-path-only kwargs
    (``vendor_entity``/``record_cap``/``lookback_days``/``envelope``/
    ``initial_load``/``identifier_key``/``last_modified_path``) that
    ``sync.py``'s ONE factory call site passes to every implementation."""
    mode = kwargs.pop("mode", RUN_MODE_MANUAL)
    for stray in (
        "vendor_entity", "record_cap", "lookback_days", "envelope",
        "initial_load", "identifier_key", "last_modified_path",
    ):
        kwargs.pop(stray, None)
    return HttpApiSource(ctx, entity_type=entity_type, mode=mode, **kwargs)


def register_http_source() -> None:
    """Idempotent (the registry is a keyed dict) - kept as a callable for the
    module install hook (``bootstrap.py``), which imports and calls it
    explicitly. The registration itself now ALSO happens at import time below
    (mirrors ``sql_source.source``'s pattern via ``sync.py``'s module-level
    ``register_sql_db_source()`` call): the Celery worker boots no FastAPI
    lifespan and never runs the install hook, so anything it needs to run a
    task must register on the worker's own import chain, not only on boot."""
    register_source(SOURCE_IMPL_AUTOCOUNT_HTTP, _http_api_factory)


# Register at import time - see the docstring above. Any process that imports
# this module (API install hook via ``register_http_source()``, OR the worker
# via ``sync.py``'s explicit import below) ends up with ``autocount_http``
# resolvable through ``source_factory``.
register_source(SOURCE_IMPL_AUTOCOUNT_HTTP, _http_api_factory)
