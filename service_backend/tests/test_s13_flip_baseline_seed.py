"""Plan 13 S0 - Group D (the flip's baseline): AC-13-32, 33, 34. RED before
the coder.

``PullSnapshotRepository.ready_source_refs`` does not exist at all yet
(grepped 2026-09-25 - the repository has no such method), so every test
that reaches it fails on ``AttributeError``. ``EtlService.set_delivery_mode``
today only flips the column and re-arms the schedule (`services/etl_
service.py:2905-2970`) - it never touches ``ac_row_hash`` at all, in either
direction - so the seed-on-flip and clear-on-unflip tests fail on a
row-count mismatch, never a crash.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT, ENTITY_STOCK_BALANCE
from modules.autocount.models import (
    DELIVERY_MODE_PULL,
    DELIVERY_MODE_PUSH,
    PULL_SNAPSHOT_STATUS_READY,
    AcCompany,
    AcPullSnapshot,
    AcPullSnapshotRow,
    SINK_IMPL_SORENTO,
)
from modules.autocount.repositories import PullSnapshotRepository, RowHashRepository
from modules.autocount.services.etl_service import EtlService
from modules.autocount.sinks_sorento import SorentoContractInfo, SorentoSink

from tests.test_s10_s5b_registration import _http_raw

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
    from app.secrets import encrypt_secret

    sorento_conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k"}), is_active=True,
    )
    db.add(sorento_conn)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=connection_id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True, sorento_company_code="SRT",
        sink_impl=SINK_IMPL_SORENTO, sink_connection_id=sorento_conn.id,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _ready_snapshot(
    db, company, entity_type: str, refs, *, expires_in_hours=24, extracted_at=NOW
) -> AcPullSnapshot:
    snapshot = AcPullSnapshot(
        id=str(uuid.uuid4()), tenant_id=DEFAULT_TENANT_ID, company_id=company.id,
        entity_type=entity_type, company_code=company.sorento_company_code,
        status=PULL_SNAPSHOT_STATUS_READY, record_count=len(refs), complete=True,
        extracted_at=extracted_at, expires_at=extracted_at + timedelta(hours=expires_in_hours),
    )
    repo = PullSnapshotRepository(db)
    repo.add(snapshot)
    for i, ref in enumerate(refs):
        repo.insert_row(
            AcPullSnapshotRow(
                tenant_id=DEFAULT_TENANT_ID, snapshot_id=snapshot.id, row_index=i,
                company_id=company.id, source_ref=ref, payload_json={"source_ref": ref, "qty": 1},
            )
        )
    db.commit()
    return snapshot


@pytest.fixture
def rig(session_factory, monkeypatch):
    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=2.5, entities=["products", "stock_balances"]),
    )
    db = session_factory()
    conn = _open_connection(db)
    company = _company(db, conn.id)
    EtlService(db).update_task(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, _http_raw(conn.id)
    )
    yield db, company
    db.close()


# ── ready_source_refs does not exist yet ────────────────────────────────────


def test_ready_source_refs_and_has_ready_are_implemented(session_factory):
    """Review round 2 B2 fix - the S0 red test above was an absence-pin,
    now a positive guard: both repository methods exist (`ready_source_
    refs`, the full union; `has_ready`, the EXISTS-only twin `_push_gate`
    calls on every task-view GET), and agree on an empty union."""
    db = session_factory()
    repo = PullSnapshotRepository(db)
    assert hasattr(repo, "ready_source_refs")
    assert hasattr(repo, "has_ready")
    now = datetime.now(timezone.utc)
    assert repo.ready_source_refs(DEFAULT_TENANT_ID, "nonexistent", "product", now) == {}
    assert repo.has_ready(DEFAULT_TENANT_ID, "nonexistent", "product", now) is False


# ── AC-13-32: baseline seed on pull -> push, union of READY snapshots ──────


def test_flip_seeds_the_union_of_ready_snapshot_refs(rig):
    db, company = rig
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS", "AED_SORENTO:B|MBS"])
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:B|MBS", "AED_SORENTO:C|MBS"])

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert set(hashes) == {"AED_SORENTO:A|MBS", "AED_SORENTO:B|MBS", "AED_SORENTO:C|MBS"}


def test_seed_row_hash_is_the_sentinel_naming_the_snapshot(rig):
    db, company = rig
    snapshot = _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"])

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert hashes["AED_SORENTO:A|MBS"] == f"seed:{snapshot.id}"


def test_a_ref_in_two_snapshots_deterministically_keeps_the_latest_sentinel(rig):
    """Review round 2 B2 fix - ``ready_source_refs`` visits snapshots
    oldest-``extracted_at``-FIRST (never bare DB/dict-iteration order), so
    a ref present in more than one READY snapshot deterministically keeps
    the LATEST one's sentinel, reproducible across runs/backends."""
    db, company = rig
    older = _ready_snapshot(
        db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"],
        extracted_at=NOW - timedelta(hours=2),
    )
    newer = _ready_snapshot(
        db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"], extracted_at=NOW,
    )
    assert older.id != newer.id

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert hashes["AED_SORENTO:A|MBS"] == f"seed:{newer.id}"


def test_has_ready_agrees_with_ready_source_refs_on_a_non_empty_union(rig):
    """Review round 2 B2 fix - `has_ready` (the EXISTS-only read `_push_
    gate` uses on every task-view GET) must never disagree with
    `ready_source_refs` (the full union `_seed_baseline_if_empty` uses)
    about whether a snapshot exists to flip from."""
    db, company = rig
    now = datetime.now(timezone.utc)
    repo = PullSnapshotRepository(db)
    assert repo.has_ready(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, now) is False
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"])
    assert repo.has_ready(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, now) is True


def test_flip_never_seeds_a_task_that_already_holds_hash_rows(rig):
    """A task that already carries hash rows (e.g. a prior push period) is
    never seeded or overwritten - AC-13-32's own guard."""
    db, company = rig
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"])
    RowHashRepository(db).upsert_many(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE,
        {"AED_SORENTO:PRE-EXISTING|MBS": "a" * 64}, seen_at=NOW,
    )
    db.commit()

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert set(hashes) == {"AED_SORENTO:PRE-EXISTING|MBS"}, (
        "a task with existing hash rows must never be seeded from a snapshot"
    )


def test_an_expired_snapshot_is_never_part_of_the_seed_union(rig):
    db, company = rig
    _ready_snapshot(
        db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:STALE|MBS"], expires_in_hours=-1
    )
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:FRESH|MBS"])

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert "AED_SORENTO:STALE|MBS" not in hashes
    assert "AED_SORENTO:FRESH|MBS" in hashes


def test_products_flip_without_any_snapshot_leaves_hashes_empty(session_factory):
    """AC-13-32 - unlike stock (AC-13-31 refuses with no snapshot), products
    have no `no_snapshot` gate at all (D17): the flip succeeds either way,
    and seeds ONLY when a READY snapshot happens to exist."""
    from app.secrets import encrypt_secret
    from modules.autocount.services.company_service import CompanyService

    db = session_factory()
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}), is_active=True,
    )
    db.add(conn)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_X",
        company_name="X", name="X", is_active=True, sorento_company_code="X",
    )
    db.add(company)
    db.flush()
    # ENTITY_PRODUCT is NOT in `SEEDED_ENTITIES` (GRN/supplier/customer
    # only) - `seed_company_defaults` never creates its config; a minimal
    # task config is all `set_delivery_mode` needs (it never validates
    # `source_config` content, only that a config row exists).
    from modules.autocount.models import AcEntityConfig

    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="sql_db",
            source_config={"connectionId": conn.id, "query": "SELECT 1 AS code", "keyColumns": ["code"]},
        )
    )
    db.commit()

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert hashes == {}, "no snapshot exists, so nothing seeds - and the flip itself must not refuse"


def test_products_flip_seeds_from_a_ready_snapshot_when_one_exists(session_factory):
    from app.secrets import encrypt_secret
    from modules.autocount.services.company_service import CompanyService

    db = session_factory()
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="api",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}), is_active=True,
    )
    db.add(conn)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_X",
        company_name="X", name="X", is_active=True, sorento_company_code="X",
    )
    db.add(company)
    db.flush()
    from modules.autocount.models import AcEntityConfig

    db.add(
        AcEntityConfig(
            tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_PRODUCT,
            source_impl="sql_db",
            source_config={"connectionId": conn.id, "query": "SELECT 1 AS code", "keyColumns": ["code"]},
            # plan 13 review round 2 S5 fix (rig correction) - EXPLICIT,
            # never left on the bare column ``server_default`` of
            # ``push``: ``set_delivery_mode`` now early-returns as a no-op
            # when the requested mode already matches the current one, so
            # a config that was never genuinely in `pull` must not
            # masquerade as a real `pull -> push` flip.
            delivery_mode=DELIVERY_MODE_PULL,
        )
    )
    db.commit()
    _ready_snapshot(db, company, ENTITY_PRODUCT, ["AED_X:P1", "AED_X:P2"])

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT, DELIVERY_MODE_PUSH
    )
    hashes = RowHashRepository(db).all_hashes(DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT)
    assert set(hashes) == {"AED_X:P1", "AED_X:P2"}


# ── AC-13-33: first run after seed stages current, deletes absent-seeded ──


def test_first_run_after_seed_stages_a_delete_for_a_seeded_ref_absent_now(rig):
    """A seeded ref absent from the FIRST push run's extract stages a
    delete intent - the seed's whole point (closing the Confirm-to-
    first-walk window)."""
    import httpx

    import modules.autocount.http_source.source as http_source_module
    from app.jobs.service import JobService
    from modules.autocount.http_source.client import HttpApiClient
    from modules.autocount.models import AcStagedRecord, STAGED_OP_DELETE
    from modules.autocount.sync import AUTOCOUNT_SYNC, run_autocount_sync

    db, company = rig
    _ready_snapshot(
        db, company, ENTITY_STOCK_BALANCE,
        ["AED_SORENTO:GONE|MBS", "AED_SORENTO:STAYS|MBS"],
    )
    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )

    def handler(request: httpx.Request) -> httpx.Response:
        # NOTE (plan 13 S2 coder, 2026-09-26) - the `rig` fixture's own
        # `_http_raw` (imported from `test_s10_s5b_registration`) carries
        # the REAL stock preset's `combine` + two lookups (item, itemUOM) -
        # a genuine stock task's shape, not a flat pass-through. The main
        # endpoint's rows must be RAW AutoCount-shaped (`ItemCode`/
        # `Location`/`UOM`/`BalQty`, the combine's OWN input), never the
        # combine's OUTPUT shape (`item_code`/`location_code`/`qty`) the
        # original single-response handler here sent - which the require
        # stage's `uom_rate_unresolved` formula could never satisfy (no
        # `ItemCode`/`UOM`/`ItemBaseUOM` to read), failing every row
        # `EXCLUDED_NONZERO` before this test's own assertion is ever
        # reached. `UOM == ItemBaseUOM` on the row itself needs neither
        # lookup to resolve, so both lookup paths answer an empty page.
        if request.url.path.endswith("/itembatchbalqtybypage"):
            return httpx.Response(
                200,
                json=[
                    {
                        "ItemCode": "STAYS", "Location": "MBS", "UOM": "UNIT",
                        "ItemBaseUOM": "UNIT", "BalQty": 5, "UomRate": 1,
                    }
                ],
            )
        return httpx.Response(200, json=[])

    stub_transport = httpx.Client(transport=httpx.MockTransport(handler))
    orig = http_source_module.HttpApiClient
    http_source_module.HttpApiClient = lambda base_url, **kw: HttpApiClient(  # type: ignore
        base_url, transport=stub_transport
    )
    try:
        job = JobService(db).create(
            type=AUTOCOUNT_SYNC, tenant_id=DEFAULT_TENANT_ID,
            payload={"companyId": company.id, "entityType": ENTITY_STOCK_BALANCE, "mode": "manual"},
        )
        run_autocount_sync(db, job)
    finally:
        http_source_module.HttpApiClient = orig

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
    assert [r.source_ref for r in deletes] == ["AED_SORENTO:GONE|MBS"]


# ── AC-13-34: push -> pull clears hashes ────────────────────────────────────


def test_push_to_pull_clears_the_tasks_row_hashes(rig):
    db, company = rig
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"])
    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    assert RowHashRepository(db).count(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE) == 1

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PULL
    )
    assert RowHashRepository(db).count(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE) == 0


def test_round_trip_pull_push_pull_keeps_mapping_byte_identical(rig):
    """AC-13-34 / AC-10-14 control - only the mode + hashes move; mapping
    rows, `source_config` and `result_columns` stay byte-identical across
    a pull -> push -> pull round trip."""
    db, company = rig
    before = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    _ready_snapshot(db, company, ENTITY_STOCK_BALANCE, ["AED_SORENTO:A|MBS"])

    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PUSH
    )
    EtlService(db).set_delivery_mode(
        DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE, DELIVERY_MODE_PULL
    )
    after = EtlService(db).get_task(DEFAULT_TENANT_ID, company.id, ENTITY_STOCK_BALANCE)
    assert after.source_config == before.source_config
    assert after.result_columns == before.result_columns
