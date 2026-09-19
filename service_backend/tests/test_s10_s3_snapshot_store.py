"""Sprint-5/10 S3 - Group C, snapshot store: AC-10-18, 19, 23, 25.

RED before the coder: NONE of ``AcPullSnapshot``, ``AcPullSnapshotRow``,
``modules.autocount.services.pull_service`` exist on this branch yet - every
import below fails at collection with a plain ``ImportError``/``ModuleNotFoundError``,
which is exactly what a "missing feature" RED looks like (never a bare
``assert False``).

ASSUMED NAMES the coder must conform to (chosen from plan §2.4 + files list +
AC-10-18/19/23/25 - none of these are pinned anywhere else on this branch):

* ``modules.autocount.models``:
  - ``PULL_SNAPSHOT_STATUS_BUILDING = "building"``,
    ``PULL_SNAPSHOT_STATUS_READY = "ready"``,
    ``PULL_SNAPSHOT_STATUS_FAILED = "failed"``,
    ``PULL_SNAPSHOT_STATUSES = (BUILDING, READY, FAILED)``.
  - ``AcPullSnapshot`` (table ``ac_pull_snapshot``): ``id, tenant_id,
    company_id, entity_type, company_code, status, job_id, record_count,
    complete, content_hash, metadata_json, error, error_code, requested_via,
    requested_by, created_at, extracted_at, expires_at`` (AC-10-18 verbatim).
  - ``AcPullSnapshotRow`` (table ``ac_pull_snapshot_row``): composite PK
    ``(tenant_id, snapshot_id, row_index)`` plus ``company_id, source_ref,
    payload_json``.
* ``modules.autocount.services.pull_service``:
  - ``SnapshotService(db)`` - the ONE write gate (AC-10-19 names this class
    verbatim): ``create_building(tenant_id, company_id, entity_type, *,
    company_code, requested_via, requested_by=None) -> AcPullSnapshot``;
    ``insert_row(tenant_id, snapshot, row_index, *, company_id, source_ref,
    payload) -> None``; ``stamp_ready(tenant_id, snapshot, *, record_count,
    complete, content_hash, metadata, extracted_at, expires_at) ->
    AcPullSnapshot``; ``stamp_failed(tenant_id, snapshot, *, error,
    error_code) -> AcPullSnapshot``. ``insert_row``/``stamp_ready``/
    ``stamp_failed`` all raise ``SnapshotNotBuildingError`` (exported from the
    same module) against any snapshot whose ``status != building``.
  - ``compute_content_hash(rows: list[dict]) -> str`` - a PURE function over
    an ordered list of the exact stored ``payload_json`` dicts (AC-10-23's
    formula), so the hash can be pinned independently of the build job that
    will call it in S3's own build-job tests (a different file).
  - ``prune_pull_snapshots(db, *, now=None) -> dict`` - the beat body
    (AC-10-25): deletes every snapshot whose ``expires_at <= now`` (plus its
    rows) and, independently, keeps only the newest 3 ``ready`` snapshots per
    (tenant, company, entity).
* ``modules.autocount.repositories.autocount_repository.PullSnapshotRepository``
  - exposes creation/read/insert-row/terminal-stamp only; there is NO
  update-row or delete-ROW method (whole-snapshot deletion, for pruning, is
  fine and expected) - pinned here structurally via the composite PK (a
  second insert at the same ``row_index`` is a PK violation, never a silent
  overwrite) rather than by asserting the ABSENCE of an arbitrarily-named
  method, which would be a vacuous check.

Kill-test notes are per section below.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from modules.autocount.canonical.masters import ENTITY_PRODUCT
from modules.autocount.models import AcCompany

NOW = datetime(2026, 9, 20, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, *, sorento_company_code="SRT") -> AcCompany:
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name="db1 REST",
        config_json={"baseUrl": "https://hapi.sorento.cc.cd/api/db1", "auth": "none"},
        credentials_json=None, is_active=True,
    )
    db.add(conn)
    db.commit()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=conn.id, database_name="AED_SORENTO",
        company_name="Sorento", name="Sorento", is_active=True,
        sorento_company_code=sorento_company_code,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


# ── AC-10-18: table shape ────────────────────────────────────────────────────


def test_ac_pull_snapshot_and_row_tables_carry_the_documented_columns(db):
    from modules.autocount.models import AcPullSnapshot, AcPullSnapshotRow

    snapshot_cols = {c.name for c in AcPullSnapshot.__table__.columns}
    assert snapshot_cols == {
        "id", "tenant_id", "company_id", "entity_type", "company_code",
        "status", "job_id", "record_count", "complete", "content_hash",
        "metadata_json", "error", "error_code", "requested_via",
        "requested_by", "created_at", "extracted_at", "expires_at",
    }
    row_cols = {c.name for c in AcPullSnapshotRow.__table__.columns}
    assert row_cols == {
        "tenant_id", "snapshot_id", "row_index", "company_id", "source_ref",
        "payload_json",
    }
    pk_cols = {c.name for c in AcPullSnapshotRow.__table__.primary_key.columns}
    assert pk_cols == {"tenant_id", "snapshot_id", "row_index"}


# ── AC-10-19: immutability once ready - structural, not a convention ────────


def test_a_second_insert_at_the_same_row_index_is_a_pk_violation(db):
    """The composite PK IS the "no update-row method" guarantee (AC-10-19):
    there is no legal way to overwrite row 0 of a snapshot short of deleting
    it and re-inserting, which is a different operation entirely."""
    from modules.autocount.services.pull_service import SnapshotService

    company = _company(db)
    service = SnapshotService(db)
    snapshot = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    service.insert_row(
        DEFAULT_TENANT_ID, snapshot, 0,
        company_id=company.id, source_ref="AED_SORENTO:A1", payload={"code": "A1"},
    )
    with pytest.raises(IntegrityError):
        service.insert_row(
            DEFAULT_TENANT_ID, snapshot, 0,
            company_id=company.id, source_ref="AED_SORENTO:A1-OVERWRITE",
            payload={"code": "A1-OVERWRITE"},
        )


def test_insert_row_against_a_ready_snapshot_raises_and_writes_nothing(db):
    from modules.autocount.models import AcPullSnapshotRow
    from modules.autocount.services.pull_service import (
        SnapshotNotBuildingError,
        SnapshotService,
    )

    company = _company(db)
    service = SnapshotService(db)
    snapshot = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    service.insert_row(
        DEFAULT_TENANT_ID, snapshot, 0,
        company_id=company.id, source_ref="AED_SORENTO:A1", payload={"code": "A1"},
    )
    service.stamp_ready(
        DEFAULT_TENANT_ID, snapshot, record_count=1, complete=True,
        content_hash="x" * 64, metadata={}, extracted_at=NOW, expires_at=NOW + timedelta(hours=24),
    )

    with pytest.raises(SnapshotNotBuildingError):
        service.insert_row(
            DEFAULT_TENANT_ID, snapshot, 1,
            company_id=company.id, source_ref="AED_SORENTO:A2", payload={"code": "A2"},
        )
    # CONTROL: still exactly the one row written before ready - proves the
    # raise above genuinely wrote nothing rather than raising AFTER a write.
    assert (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == snapshot.id)
        .count()
        == 1
    )


def test_stamp_ready_against_an_already_ready_snapshot_raises(db):
    from modules.autocount.services.pull_service import (
        SnapshotNotBuildingError,
        SnapshotService,
    )

    company = _company(db)
    service = SnapshotService(db)
    snapshot = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    service.stamp_ready(
        DEFAULT_TENANT_ID, snapshot, record_count=0, complete=True,
        content_hash="x" * 64, metadata={}, extracted_at=NOW, expires_at=NOW + timedelta(hours=24),
    )
    with pytest.raises(SnapshotNotBuildingError):
        service.stamp_ready(
            DEFAULT_TENANT_ID, snapshot, record_count=0, complete=True,
            content_hash="y" * 64, metadata={}, extracted_at=NOW, expires_at=NOW + timedelta(hours=24),
        )


def test_a_building_snapshot_may_be_written_to_and_stamped_control(db):
    """CONTROL for the two raise-tests above: a genuinely BUILDING snapshot
    accepts a row insert and a terminal stamp without raising - proves the
    guard is status-conditional, not a blanket refusal that would make the
    raise-tests vacuously true."""
    from modules.autocount.services.pull_service import SnapshotService

    company = _company(db)
    service = SnapshotService(db)
    snapshot = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    service.insert_row(
        DEFAULT_TENANT_ID, snapshot, 0,
        company_id=company.id, source_ref="AED_SORENTO:A1", payload={"code": "A1"},
    )
    ready = service.stamp_ready(
        DEFAULT_TENANT_ID, snapshot, record_count=1, complete=True,
        content_hash="x" * 64, metadata={}, extracted_at=NOW, expires_at=NOW + timedelta(hours=24),
    )
    assert ready.status == "ready"


# ── AC-10-23: content_hash formula, fixed fixture ────────────────────────────


def test_compute_content_hash_matches_the_documented_sha256_formula():
    from modules.autocount.services.pull_service import compute_content_hash

    rows = [
        {"source_ref": "AED_SORENTO:A1", "code": "A1", "list_price": "0.0"},
        {"source_ref": "AED_SORENTO:A2", "code": "A2", "list_price": "12.50"},
    ]
    expected = hashlib.sha256(
        "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows
        ).encode("utf-8")
    ).hexdigest()
    assert compute_content_hash(rows) == expected


def test_compute_content_hash_changes_when_any_row_changes():
    from modules.autocount.services.pull_service import compute_content_hash

    rows = [{"source_ref": "AED_SORENTO:A1", "code": "A1", "list_price": "0.0"}]
    changed = [{"source_ref": "AED_SORENTO:A1", "code": "A1", "list_price": "0.1"}]
    assert compute_content_hash(rows) != compute_content_hash(changed)


def test_compute_content_hash_is_stable_for_identical_content():
    from modules.autocount.services.pull_service import compute_content_hash

    rows = [{"source_ref": "AED_SORENTO:A1", "code": "A1"}]
    assert compute_content_hash(rows) == compute_content_hash(list(rows))


# ── AC-10-25: TTL + retention prune ──────────────────────────────────────────


def test_prune_removes_an_expired_snapshot_and_its_rows(db):
    from modules.autocount.models import AcPullSnapshot, AcPullSnapshotRow
    from modules.autocount.services.pull_service import (
        SnapshotService,
        prune_pull_snapshots,
    )

    company = _company(db)
    service = SnapshotService(db)
    expired = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )
    service.insert_row(
        DEFAULT_TENANT_ID, expired, 0,
        company_id=company.id, source_ref="AED_SORENTO:A1", payload={"code": "A1"},
    )
    service.stamp_ready(
        DEFAULT_TENANT_ID, expired, record_count=1, complete=True,
        content_hash="x" * 64, metadata={},
        extracted_at=NOW - timedelta(hours=48), expires_at=NOW - timedelta(hours=1),
    )

    prune_pull_snapshots(db, now=NOW)

    assert db.get(AcPullSnapshot, expired.id) is None
    assert (
        db.query(AcPullSnapshotRow)
        .filter(AcPullSnapshotRow.snapshot_id == expired.id)
        .count()
        == 0
    )


def test_prune_keeps_only_the_newest_3_ready_snapshots_per_triple(db):
    from modules.autocount.models import AcPullSnapshot
    from modules.autocount.services.pull_service import (
        SnapshotService,
        prune_pull_snapshots,
    )

    company = _company(db)
    service = SnapshotService(db)
    made = []
    for i in range(4):
        snap = service.create_building(
            DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
            company_code=company.sorento_company_code, requested_via="operator",
        )
        service.stamp_ready(
            DEFAULT_TENANT_ID, snap, record_count=0, complete=True,
            content_hash=f"{i}" * 64, metadata={},
            extracted_at=NOW - timedelta(hours=i), expires_at=NOW + timedelta(hours=24 - i),
        )
        # Deliberately INVERTED against extracted_at (made[0] gets the
        # EARLIEST created_at, made[3] the LATEST): if the coder's retention
        # query orders by created_at instead of extracted_at, this fixture
        # keeps the wrong 3 and the assertion below catches it, rather than
        # the two orderings coincidentally agreeing.
        snap.created_at = NOW - timedelta(days=1, hours=3 - i)
        db.commit()
        made.append(snap)
    # made[0] is the NEWEST BY extracted_at (closest to NOW), made[3] the
    # oldest by extracted_at (and, deliberately, the NEWEST by created_at).
    oldest = made[3]

    prune_pull_snapshots(db, now=NOW)

    remaining = {
        row.id
        for row in db.query(AcPullSnapshot).filter(AcPullSnapshot.company_id == company.id).all()
    }
    assert oldest.id not in remaining
    assert len(remaining) == 3


def test_prune_leaves_a_fresh_building_snapshot_untouched(db):
    """CONTROL: a snapshot with NO expires_at (still building) must never be
    swept by the TTL rule - only the liveness-based orphan sweep may fail it,
    and that is a different mechanism (the module's on_job_orphaned hook,
    not this beat)."""
    from modules.autocount.models import AcPullSnapshot
    from modules.autocount.services.pull_service import (
        SnapshotService,
        prune_pull_snapshots,
    )

    company = _company(db)
    service = SnapshotService(db)
    building = service.create_building(
        DEFAULT_TENANT_ID, company.id, ENTITY_PRODUCT,
        company_code=company.sorento_company_code, requested_via="operator",
    )

    prune_pull_snapshots(db, now=NOW)

    assert db.get(AcPullSnapshot, building.id) is not None


# ── kill tests (leave uncommented; they document what a correct
# implementation needs and what happens if it is missing) ───────────────────
#
# * test_a_second_insert_at_the_same_row_index_is_a_pk_violation dies if the
#   coder gives ``AcPullSnapshotRow`` a surrogate PK instead of the composite
#   one AC-10-18 specifies - the second insert would then silently succeed.
# * test_insert_row_against_a_ready_snapshot_raises_and_writes_nothing dies
#   if ``SnapshotService`` skips the status check (it would insert row 1
#   cleanly) OR if the check runs AFTER the insert (the control count would
#   read 2, not 1).
# * test_prune_keeps_only_the_newest_3_ready_snapshots_per_triple dies if the
#   retention rule is global instead of per (tenant, company, entity), or if
#   it orders by ``created_at`` instead of ``extracted_at`` - the fixture
#   deliberately inverts the two orderings so a wrong-column bug keeps the
#   wrong snapshot rather than coincidentally passing.
