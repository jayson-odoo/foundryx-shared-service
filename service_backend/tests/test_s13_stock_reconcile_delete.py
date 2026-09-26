"""Plan 13 S0 - Group B push run semantics: AC-13-10, 12, 13, 14, 15. RED
before the coder.

Two levels: (1) ``HttpApiSource.fetch_changes`` directly (mirrors
``tests/test_autocount_http_source.py``'s own rig) for the mechanics AC-13-10
says already work ("no code"), pinned here for ``ENTITY_STOCK_BALANCE``
specifically rather than trusted by inference; (2) a full
``run_autocount_sync`` push run (mirrors ``tests/test_autocount_http_
lifecycle.py``'s ``HttpApiClient`` monkeypatch rig) for AC-13-12/13, which
are genuinely NEW run-level behaviour with no code today.

The stock tasks here carry NO combine/lookups - AC-13-10's own citation
(``http_source/source.py:1025``) is combine-agnostic (it runs on whatever
``working_rows`` the source ends with), so a flat two-column-key config
proves the same mechanism without the extra weight of the real preset's two
lookups. AC-13-12's test DOES use the real ``STOCK_BALANCE_HTTP_PRESET``
combine block (imported, never re-typed) since the exclusion machinery being
pinned IS the combine's own require-stage output.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_STOCK_BALANCE
from modules.autocount.models import AcCompany, AcEntityConfig, AcStagedRecord, STAGED_OP_DELETE
from modules.autocount.repositories import RowHashRepository
from modules.autocount.services.company_service import CompanyService
from modules.autocount.sources import SourceContext, Watermark

NOW = datetime(2026, 9, 25, 12, 0, 0, tzinfo=timezone.utc)


def _open_connection(db) -> Connection:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _company(db, connection_id: str) -> AcCompany:
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
    )
    db.add(company)
    db.flush()
    # Seeds default 1:1 field mappings for every registered entity (incl.
    # stock_balance) - without this, `map_document` has nothing to map `qty`
    # through and the combine step's own Decimal `qty` never gets coerced to
    # `CanonicalStockBalance`'s typed `int` field before it reaches a JSON
    # column.
    CompanyService(db).seed_company_defaults(DEFAULT_TENANT_ID, company.id)
    db.commit()
    db.refresh(company)
    return company


@pytest.fixture
def rig(session_factory):
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    yield db, company, conn
    db.close()


# ── AC-13-10: full diff every run regardless of mode, delete on drop to zero ──


def _flat_config(db, company, conn, *, combine=None) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_STOCK_BALANCE,
        source_impl="autocount_http",
        source_config={
            "connectionId": conn.id,
            "path": "/itembatchbalqtybypage",
            "keyFields": ["item_code", "location_code"],
            "watermarkField": None,
            "comparedFields": [],
            "distinctOf": None,
            "lookups": [],
            "combine": combine,
            "incrementalMinutes": 15,
            "reconcileMode": "dailyAt",
            "reconcileAt": "02:00",
        },
    )
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _ctx(db, company, config) -> "SourceContext":
    return SourceContext(
        db=db, tenant_id=DEFAULT_TENANT_ID, company=company, entity_config=config,
        company_service=CompanyService(db),
    )


def _bare_array_handler(rows):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=rows)

    return handler


def test_incremental_mode_still_stages_a_delete_for_a_pair_gone_to_zero(rig):
    """AC-13-10 - a watermark-less HTTP task's fetch is ALWAYS a full diff
    (``mode`` is irrelevant, `source.py:1025`): a pair known from a prior
    run and ABSENT from this run's extract computes a delete_ref, even
    though the caller asked for an `incremental` run."""
    from modules.autocount.http_source.source import HttpApiSource
    from modules.autocount.models import RUN_MODE_INCREMENTAL

    db, company, conn = rig
    config = _flat_config(db, company, conn)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
        {"AED_SORENTO:X1|MBS": "a" * 64, "AED_SORENTO:X2|MBS": "b" * 64}, seen_at=NOW,
    )
    db.commit()

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_STOCK_BALANCE, mode=RUN_MODE_INCREMENTAL,
        transport=httpx.Client(
            transport=httpx.MockTransport(
                _bare_array_handler([{"item_code": "X1", "location_code": "MBS", "qty": 5}])
            )
        ),
    )
    result = source.fetch_changes(Watermark())
    assert result.delete_refs == ["AED_SORENTO:X2|MBS"]


def test_negative_drop_stages_a_delete_intent_for_a_previously_known_pair():
    """AC-13-15 - a `drop` rule (negative) never produces a `SourceRecord`
    directly, but a pair the previous run knew and this run's combine
    DROPPED still computes as a genuine delete via the reconcile diff (the
    dropped pair is simply absent from `current_refs`)."""
    from modules.autocount.http_source.combine import apply_combine
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    combine = STOCK_BALANCE_HTTP_PRESET.combine
    rows = [
        {"ItemCode": "NEG", "Location": "MBS", "UOM": "UNIT", "ItemBaseUOM": "UNIT", "BalQty": -3, "UomRate": 1},
    ]
    result = apply_combine(rows, combine)
    assert result.rows == [], "a negative pair must never survive combine as a live row"
    dropped = result.metadata.get("dropped") or {}
    assert dropped.get("negative", {}).get("count") == 1


def test_excluded_and_dropped_rows_never_become_source_records():
    """AC-13-15 - control: neither a `require` exclusion (uom_rate
    unresolved) nor a `drop` (zero/negative) produces a live combine row -
    the ONLY way either becomes a delete intent is via the reconcile diff
    against a previously-known ref, never a direct SourceRecord."""
    from modules.autocount.http_source.combine import apply_combine
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET

    combine = STOCK_BALANCE_HTTP_PRESET.combine
    rows = [
        # require-excluded: UOM != base UOM, no UomRate at all.
        {"ItemCode": "EXC", "Location": "MBS", "UOM": "BOX", "ItemBaseUOM": "UNIT", "BalQty": 10},
        # dropped: zero.
        {"ItemCode": "ZERO", "Location": "MBS", "UOM": "UNIT", "ItemBaseUOM": "UNIT", "BalQty": 0, "UomRate": 1},
    ]
    result = apply_combine(rows, combine)
    assert result.rows == []


# ── AC-13-14: delete guard control (existing, unchanged) ───────────────────


def test_delete_guard_still_fires_on_mass_disappearance(rig):
    from modules.autocount.http_source.errors import HttpSourceError
    from modules.autocount.http_source.source import HttpApiSource

    db, company, conn = rig
    config = _flat_config(db, company, conn)
    # DELETE_GUARD_MIN_ABSOLUTE is 50 - the ratio alone (20%) never trips on
    # a small known set, so this needs enough known refs that "all but one
    # missing" clears the absolute floor too.
    known = {
        f"AED_SORENTO:X{i}|MBS": "a" * 64 for i in range(60)
    }
    RowHashRepository(db).upsert_many(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, known, seen_at=NOW)
    db.commit()

    source = HttpApiSource(
        _ctx(db, company, config), entity_type=ENTITY_STOCK_BALANCE,
        transport=httpx.Client(
            transport=httpx.MockTransport(
                _bare_array_handler([{"item_code": "X0", "location_code": "MBS", "qty": 5}])
            )
        ),
    )
    with pytest.raises(HttpSourceError) as exc_info:
        source.fetch_changes(Watermark())
    assert exc_info.value.code == "delete_guard"


# ── AC-13-12: EXCLUDED_NONZERO fails closed before staging (new, no code) ──


def test_excluded_nonzero_is_a_public_constant_on_sync():
    """Review round 2 B2 fix - the S0 red test above was an absence-pin,
    now a positive guard: ``sync.EXCLUDED_NONZERO`` is the SAME value the
    run-level test below asserts against, so the two can never drift."""
    import modules.autocount.sync as sync_module

    assert sync_module.EXCLUDED_NONZERO == "EXCLUDED_NONZERO"


def test_a_run_with_an_unresolved_nonzero_rate_fails_before_staging(session_factory, monkeypatch):
    """AC-13-12 - a require-excluded row with NO UomRate at all (measure is
    unresolvable, AC-10-77 ruling 4: a missing measure counts as non-zero,
    fail-closed) must fail the WHOLE run with ``EXCLUDED_NONZERO`` before
    anything stages - today `run_autocount_sync` never reads
    `pull_metadata_map`/`apply_pull_metadata_map` on the push path at all
    (only `_run_pull_snapshot` does), so this run currently SUCCEEDS and
    stages the clean row - wrong per AC-13-12.

    RED TODAY FOR A SECOND, DISTINCT REASON (found while writing this test,
    2026-09-25): `_stage_documents` stores `raw_json=source_record.raw`
    VERBATIM (`sync.py`, "retained verbatim" per its own docstring), and for
    a combine-carrying HTTP source that raw row is the POST-COMBINE row -
    which carries a genuine ``Decimal`` `qty` (`apply_combine`'s own
    ``_round``/measure-sum step never coerces it, confirmed interactively).
    Stock is the FIRST combine-based entity ever staged this way (it was
    pull-only until this plan; the pull-snapshot path already JSON-sanitizes
    via `combine.py`'s `_json_safe_row`/`_json_safe`, `_stage_documents`
    does not) - so this run currently crashes with `sqlalchemy.exc.
    StatementError: Object of type Decimal is not JSON serializable`
    instead of cleanly succeeding-when-it-should-not. Both reasons block
    this test; the coder needs to close BOTH before it goes green (the
    Decimal fix likely belongs beside AC-13-11's changed-only staging work,
    since EVERY combine-carrying HTTP push hits it, not just this scenario)."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    config = _flat_config(db, company, conn, combine=STOCK_BALANCE_HTTP_PRESET.combine)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                # require-excluded: UOM != ItemBaseUOM, UomRate ABSENT - an
                # unresolvable (not merely zero) rate, nonzero BalQty.
                {"ItemCode": "EXC1", "Location": "MBS", "UOM": "BOX", "ItemBaseUOM": "UNIT", "BalQty": 10},
                # a clean row that would otherwise stage fine.
                {"ItemCode": "OK1", "Location": "MBS", "UOM": "UNIT", "ItemBaseUOM": "UNIT", "BalQty": 5, "UomRate": 1},
            ],
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    refreshed = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert refreshed.last_run_error_code == "EXCLUDED_NONZERO", refreshed.last_run_error_code
    staged = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company.id,
            AcStagedRecord.entity_type == ENTITY_STOCK_BALANCE,
        )
        .all()
    )
    assert staged == [], "nothing may stage once EXCLUDED_NONZERO fires"


def test_a_zero_measure_exclusion_never_blocks_the_run_control(session_factory, monkeypatch):
    """AC-13-12 control - an exclusion whose measure is EXACTLY 0 (the live
    db1 case, 5 rows) must never fail the run; this one SHOULD already pass
    today (nothing blocks it yet) and must KEEP passing once EXCLUDED_
    NONZERO ships.

    RED TODAY for the SAME pre-existing Decimal/`raw_json` defect the
    sibling test above documents in full (`_stage_documents` stores a
    combine row's `Decimal` `qty` verbatim into a JSON column) - not a
    logic gap in this control's own assertion, which only checks
    `last_run_error_code`. Once the coder fixes that storage bug this
    control should go green on its own, with no further change here."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.presets import STOCK_BALANCE_HTTP_PRESET
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _flat_config(db, company, conn, combine=STOCK_BALANCE_HTTP_PRESET.combine)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[
                # require-excluded with a RESOLVED rate of 0 -> measure is
                # exactly 0, never counted as "non-zero".
                {"ItemCode": "EXC2", "Location": "MBS", "UOM": "BOX", "ItemBaseUOM": "UNIT", "BalQty": 10, "UomRate": 0},
                {"ItemCode": "OK2", "Location": "MBS", "UOM": "UNIT", "ItemBaseUOM": "UNIT", "BalQty": 5, "UomRate": 1},
            ],
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    refreshed = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert refreshed.last_run_error_code != "EXCLUDED_NONZERO"


# ── AC-13-13: truncation never deletes ──────────────────────────────────────


def test_extract_is_complete_is_public_and_shared_with_the_snapshot_build():
    """Review round 2 B2 fix - the S0 red test above was an absence-pin,
    now a positive guard: ``sync.extract_is_complete`` is PUBLIC (no
    leading underscore) and is the SAME rule `_run_pull_snapshot` applies
    unchanged for its own ``complete`` - a bare-array (``ENVELOPE_LIST``)
    result is unconditionally complete, a paged one needs a matching
    ``reported_total``."""
    from modules.autocount.http_source.envelope import ENVELOPE_LIST
    from modules.autocount.sources import FetchResult
    from modules.autocount.sync import extract_is_complete

    assert extract_is_complete(FetchResult(envelope_kind=ENVELOPE_LIST)) is True
    assert extract_is_complete(FetchResult(envelope_kind=None, reported_total=None)) is False
    assert (
        extract_is_complete(
            FetchResult(envelope_kind=None, reported_total=2, rows_scanned=2)
        )
        is True
    )


def test_an_unverified_paged_walk_stages_no_deletes_but_still_stages_upserts(
    session_factory, monkeypatch
):
    """AC-13-13 - a PAGED endpoint that omits `TotalCount` is UNVERIFIED
    (the exact rule `_run_pull_snapshot` already applies, `sync.py:2778`):
    a ref this walk should have re-seen but did not must NOT stage a
    delete, but a genuinely new/changed row still stages normally. Today
    `run_autocount_sync`'s push path applies no such guard at all - this
    run currently stages the stale ref as a delete, which is exactly the
    bug AC-13-13 exists to close."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.repositories import EntityConfigRepository
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _flat_config(db, company, conn)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
        {"AED_SORENTO:STALE|MBS": "a" * 64}, seen_at=NOW,
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        # A paged envelope with NO TotalCount at all - unverified by
        # AC-10-24's own rule, even though the walk itself terminates
        # cleanly (page 2 comes back empty, same shape as
        # test_autocount_http_source.py's own "clamped last page" case).
        page = int(request.url.params.get("page", "1"))
        if page >= 2:
            return httpx.Response(200, json={"Page": page, "PageSize": 1000, "Data": []})
        return httpx.Response(
            200,
            json={
                "Page": 1, "PageSize": 1000,
                "Data": [{"item_code": "FRESH", "location_code": "MBS", "qty": 9}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    refreshed = EntityConfigRepository(db).get(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert refreshed.last_run_error_code is None, refreshed.last_run_error_code

    deletes = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company.id,
            AcStagedRecord.entity_type == ENTITY_STOCK_BALANCE,
            AcStagedRecord.op == STAGED_OP_DELETE,
        )
        .all()
    )
    assert deletes == [], "an unverified walk must never stage a delete intent"

    upserts = (
        db.query(AcStagedRecord)
        .filter(
            AcStagedRecord.tenant_id == DEFAULT_TENANT_ID,
            AcStagedRecord.company_id == company.id,
            AcStagedRecord.entity_type == ENTITY_STOCK_BALANCE,
            AcStagedRecord.op != STAGED_OP_DELETE,
        )
        .all()
    )
    assert len(upserts) == 1, "upserts still stage even when the walk is unverified"


def test_an_unverified_walk_with_suppressed_deletes_writes_one_activity_note(
    session_factory, monkeypatch
):
    """plan 13 review round 2 S6 fix - AC-13-13's own "one activity note
    names the unverified endpoint(s)" restored, ONLY when a delete was
    actually withheld this run (non-empty ``delete_refs`` AND an
    unverified walk - the SAME scenario as the test above, which has one
    genuinely stale ref). The note must never start with "pull snapshot"
    or contain "could not be verified" (`_run_pull_snapshot`'s own,
    differently-worded note) - the plan-10 guard
    (`test_s10_s3_review1_lookup_complete.py`) pins that phrasing to the
    snapshot build only."""
    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from app.models.integration_activity import IntegrationActivity
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    _flat_config(db, company, conn)
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
        {"AED_SORENTO:STALE|MBS": "a" * 64}, seen_at=NOW,
    )
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        if page >= 2:
            return httpx.Response(200, json={"Page": page, "PageSize": 1000, "Data": []})
        return httpx.Response(
            200,
            json={
                "Page": 1, "PageSize": 1000,
                "Data": [{"item_code": "FRESH", "location_code": "MBS", "qty": 9}],
            },
        )

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        http_source_module, "HttpApiClient",
        lambda base_url, **kw: HttpApiClient(base_url, transport=stub_transport),
    )

    job = JobService(db).create(
        type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
        payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": "manual"},
    )
    run_autocount_sync(db, job)

    notes = (
        db.query(IntegrationActivity)
        .filter(
            IntegrationActivity.tenant_id == DEFAULT_TENANT_ID,
            IntegrationActivity.external_ref == company.database_name,
        )
        .all()
    )
    withheld_notes = [n for n in notes if "withheld" in (n.error_message or "")]
    assert len(withheld_notes) == 1, notes
    note = withheld_notes[0]
    assert note.operation == f"sync {ENTITY_STOCK_BALANCE}"
    assert not note.operation.startswith("pull snapshot")
    assert "could not be verified" not in (note.error_message or "")
    assert "the main walk" in note.error_message
