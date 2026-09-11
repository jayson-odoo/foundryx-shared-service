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

logger = logging.getLogger("foundryx.autocount")

# The page size the walk itself requests - the source's OWN choice, never the
# vendor's cap (AC-08-22 "1000 requested, the echoed PageSize/TotalPages
# trusted").
DEFAULT_PAGE_SIZE = 1000

# The 20% / 50-row safety net a reconcile's delete diff must clear before it
# is trusted (mirrors ``sql_source.source``'s own constants exactly - shared
# semantics, not a second policy to drift from the first).
DELETE_GUARD_RATIO = 0.2
DELETE_GUARD_MIN_ABSOLUTE = 50


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

        self.result_columns = [
            str(c) for c in (getattr(ctx.entity_config, "result_columns", None) or [])
        ]
        configured_compared = [str(c) for c in (config.get("comparedFields") or [])]
        self.compared_columns = compared_columns_for(
            configured=configured_compared,
            result_columns=self.result_columns or configured_compared,
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

    def _walk(self) -> Tuple[List[Dict[str, Any]], Optional[int]]:
        """GET every page, returning ``(rows, reported_total)``. Raises
        ``HttpSourceError`` before touching any downstream state."""
        scanned: List[Dict[str, Any]] = []
        established_kind: Optional[str] = None
        reported_total: Optional[int] = None
        page = 1
        while True:
            try:
                response = self._client.get(
                    self.path, {"page": page, "pageSize": DEFAULT_PAGE_SIZE}
                )
            except HttpTransportError as exc:
                raise HttpSourceError(exc.message, code="transport", page=page) from exc

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
                break
            total_pages = parsed.total_pages
            current_page = parsed.page if parsed.page is not None else page
            if total_pages is not None and current_page >= total_pages:
                break
            page += 1

        return scanned, reported_total

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
        for row in working_rows:
            ref = self.source_ref(row)
            if ref is None:
                continue
            current_refs.add(ref)
            value_hash = row_hash(row, self.compared_columns)
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
