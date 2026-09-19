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
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from ..client import parse_last_modified
from ..mapping import IdentityError, flat_source_ref
from ..models import RUN_MODE_MANUAL, RUN_MODE_RECONCILE, SOURCE_IMPL_AUTOCOUNT_HTTP
from ..repositories import ConnectionRepository, RowHashRepository
from ..provider import PROVIDER_KEY, is_open_connection
from ..sources import FetchResult, SourceContext, SourceRecord, Watermark, register_source
from ..sql_source.hashing import compared_columns_for, row_hash
from ..sql_source.source import CURSOR_COLUMN, CURSOR_MARK, MAX_EXTRACT_ROWS
from .client import HttpApiClient, HttpTransportError
from .envelope import ENVELOPE_LIST, parse_page
from .errors import HttpSourceError
from .lookups import AliasCollisionError, build_index, effective_result_columns, merge_onto_rows
from .preview import validate_http_path

logger = logging.getLogger("foundryx.autocount")

# The page size the walk itself requests - the source's OWN choice, never the
# vendor's cap (AC-08-22 "1000 requested, the echoed PageSize/TotalPages
# trusted").
DEFAULT_PAGE_SIZE = 1000

# AC-10-75 (the db2 524-timeout ops finding, 2026-09-19) - a page that has
# now timed out TWICE at the same page size halves it (floor MIN_PAGE_SIZE)
# and restarts the walk from page 1, at most MAX_PAGE_HALVINGS times per
# walk before the existing failure rule applies unchanged. A connect error
# or another 5xx (never a timeout, never a 4xx) gets its own, separate
# ladder - up to ``len(TRANSPORT_RETRY_BACKOFFS_SECONDS)`` retries with a
# longer backoff and NO halving.
MIN_PAGE_SIZE = 50
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


class _PageTimedOutTwice(Exception):
    """Internal signal only (AC-10-75): ONE page has now timed out on BOTH
    its attempts at the CURRENT page size. Caught by ``_walk_endpoint``,
    which owns the halving budget - ``_fetch_page``/``_walk_path`` know
    nothing about it."""


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
        **_extra: Any,
    ) -> None:
        self.entity_type = entity_type
        self.mode = mode
        self.persist_hashes = persist_hashes
        self.row_limit = row_limit
        self._ctx = ctx

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
        effective_columns = effective_result_columns(self.result_columns, self.lookups)
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
        base_url = str((conn.config_json or {}).get("baseUrl") or "").strip()
        self._client = HttpApiClient(base_url, transport=transport)

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

    def _walk_path(
        self, path: str, page_size: int
    ) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """GET every page of ONE endpoint at a FIXED page size, returning
        ``(rows, reported_total)``. Raises ``HttpSourceError`` before
        touching any downstream state, or ``_PageTimedOutTwice`` when a page
        has now timed out on both its attempts (the caller decides whether
        to halve and restart)."""
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
            response = self._fetch_page(path, page, page_size)

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
                parsed = parse_page(body)
            except ValueError as exc:
                raise HttpSourceError(
                    str(exc), code="shape", page=page, status=response.status_code
                ) from exc

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

        return scanned, reported_total

    def _walk_endpoint(self, path: str) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """The full page walk for ONE endpoint - the main path OR a lookup
        (AC-10-02: "the SAME page walker"), with AC-10-75's bounded per-page
        retry and page-size halving. Each endpoint walked gets its OWN
        halving budget - the main path and every lookup share the exact
        mechanics, never a counter one could exhaust for the other."""
        page_size = DEFAULT_PAGE_SIZE
        halvings = 0
        while True:
            try:
                return self._walk_path(path, page_size)
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

    def _walk(self) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        return self._walk_endpoint(self.path)

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
                lookup_rows, _ = self._walk_endpoint(path)
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
        full_extract = self.mode == RUN_MODE_RECONCILE or not self.watermark_field

        scanned_rows, reported_total = self._walk()
        # AC-10-02 - lookups merge onto every source row BEFORE de-dup, the
        # row hash and mapping; ``distinctOf`` short-circuits below into an
        # entirely different `{"value": v}` row shape, so a lookup (which
        # names real columns) never applies to it.
        if not self.distinct_of:
            self._apply_lookups(scanned_rows)
        rows_scanned = len(scanned_rows)

        if self.distinct_of:
            working_rows = self._project_distinct(scanned_rows)
        else:
            working_rows = self._dedupe(scanned_rows)

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
    register_source(SOURCE_IMPL_AUTOCOUNT_HTTP, _http_api_factory)
