"""Sorento contract 2.1 - masters (sprint-5/04), REQUEST CHANGES round.

Delivery + guard gaps the first review found in the ``credit_limit`` removal:

1. **Delivery path (kill test M4 survived).** ``update_tenant`` calls
   ``backfill_disable_credit_limit_mapping_rows`` but no test reached the
   sweep THROUGH ``update_tenant`` - the call could be deleted and the suite
   stayed green. A saved ENABLED customer row targeting ``credit_limit`` must
   come back disabled from the version upgrade itself.
2. **Migration delivery.** A Postgres host that never runs ``update_tenant``
   (module Alembic is the only path there) needs revision ``0013`` chaining
   onto ``0012_autocount_disable_stale`` plus a manifest bump past ``0.4.0``
   so the loader actually invokes the per-tenant upgrade. Module Alembic is
   invisible to the SQLite suite, so this is structural.
3. **Seed + catalog.** ``DEFAULT_CUSTOMER_MAPPING`` must stop seeding a
   ``credit_limit`` row (every NEW company would otherwise be born with a
   row the sweep then disables) and ``mapping_catalog`` must stop suggesting
   ``CreditLimit`` as a master source column.
4. **Required means ENABLED.** ``missing_required`` in the save gate counts a
   DISABLED row as covering its target, so a draft carrying ``is_active`` only
   as ``isEnabled: false`` saves fine, the engine drops the disabled row, and
   the required field is silently absent on the wire (a blacklisted supplier
   activates under Sorento's default). Simulate must mirror the same gate.
5. **Sweep scope.** The sweep must touch CUSTOMER rows only.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import re

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, ENTITY_SUPPLIER
from modules.autocount.mapping import SCOPE_HEADER
from modules.autocount.models import AcFieldMapping
from modules.autocount.services.company_service import (
    AutocountServiceError,
    CompanyService,
    MappingWriteRow,
)

from tests.test_autocount_pipeline import (
    _company,
    _supplier,
    transports,  # noqa: F401 - re-exported as a fixture for this module
)

MODULE_ROOT = pathlib.Path(__file__).resolve().parents[1] / "modules" / "autocount"
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
PREVIOUS_REVISION = "0012_autocount_disable_stale"


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _credit_limit_row(entity_type: str, *, enabled: bool = True) -> AcFieldMapping:
    return AcFieldMapping(
        tenant_id=DEFAULT_TENANT_ID, company_id="company-a", entity_type=entity_type,
        scope=SCOPE_HEADER, source_path="CreditLimit",
        canonical_field="credit_limit", transform="decimal",
        is_required=False, is_enabled=enabled, sort_order=5,
    )


# ── (1) the sweep is DELIVERED by update_tenant, not just defined ────────────


def test_update_tenant_disables_a_saved_enabled_customer_credit_limit_row(db):
    """The one path an existing ``init_db``/``create_all`` host actually runs
    on a version bump. Fails if the ``backfill_disable_credit_limit_mapping_
    rows`` call is removed from ``update_tenant`` (kill test M4)."""
    from modules.autocount.bootstrap import update_tenant

    stale = _credit_limit_row(ENTITY_CUSTOMER)
    db.add(stale)
    db.commit()
    stale_id = stale.id

    update_tenant(db, DEFAULT_TENANT_ID, "0.4.0")
    db.commit()
    db.expire_all()

    assert db.get(AcFieldMapping, stale_id).is_enabled is False


# ── (2) module Alembic revision + manifest bump ─────────────────────────────


def _revision_ids(path: pathlib.Path):
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    down = re.search(r'^down_revision[^=]*=\s*(?:"([^"]+)"|None)', text, re.M)
    assert revision, f"{path.name} declares no revision id"
    assert down, f"{path.name} declares no down_revision"
    return revision.group(1), down.group(1)


def test_manifest_version_is_bumped_past_0_4_0():
    """``update_tenant`` only runs when the manifest version moves - without
    the bump every already-installed tenant keeps its stale rows forever."""
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    version = tuple(int(part) for part in manifest["version"].split("."))
    assert version >= (0, 5, 0), f"manifest still at {manifest['version']}"


def test_revision_0013_exists_and_chains_onto_0012():
    candidates = sorted(VERSIONS_DIR.glob("0013_*.py"))
    assert candidates, "no 0013_* module revision under modules/autocount/alembic/versions"
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]

    spec = importlib.util.spec_from_file_location("_ac_rev_0013", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert len(module.revision) <= 32, f"'{module.revision}' is {len(module.revision)} chars"
    assert module.down_revision == PREVIOUS_REVISION
    # The migration must deliver the SAME sweep update_tenant delivers.
    assert "backfill_disable_credit_limit_mapping_rows" in path.read_text()


def test_module_migration_history_has_a_single_head_reaching_back_through_0013():
    """A dangling ``down_revision`` splits the history into two heads and the
    upgrade fails on a live deploy - invisible to pytest otherwise. The head
    is whatever the NEWEST revision file declares (so the next revision does
    not break this test again); walking down from it must pass through the
    0013 revision, which must still chain onto 0012."""
    files = sorted(VERSIONS_DIR.glob("*.py"))
    revisions = {}
    for path in files:
        revision, down = _revision_ids(path)
        revisions[revision] = down
    referenced = {down for down in revisions.values() if down}
    heads = sorted(rev for rev in revisions if rev not in referenced)
    assert len(heads) == 1, f"module history has {len(heads)} heads: {heads}"
    for down in referenced:
        assert down in revisions, f"down_revision '{down}' names no revision file"

    newest_revision, _ = _revision_ids(files[-1])
    assert heads[0] == newest_revision, (
        f"head is {heads[0]} but the newest file declares {newest_revision}"
    )

    # Walk the chain from the head down to the baseline; 0013 must be on it
    # and still chain onto 0012.
    chain = []
    cursor = heads[0]
    while cursor:
        assert cursor not in chain, f"cycle in module history at {cursor}"
        chain.append(cursor)
        cursor = revisions[cursor]
    thirteen = [rev for rev in chain if rev.startswith("0013_")]
    assert thirteen, f"the 0013 revision is not on the chain: {chain}"
    assert revisions[thirteen[0]] == PREVIOUS_REVISION


# ── (3) seed + source catalog no longer carry credit_limit ─────────────────


def test_default_customer_mapping_does_not_seed_a_credit_limit_row():
    from modules.autocount.mapping import DEFAULT_CUSTOMER_MAPPING

    assert "credit_limit" not in {row.canonical_field for row in DEFAULT_CUSTOMER_MAPPING}


@pytest.mark.parametrize("entity_type", [ENTITY_CUSTOMER, ENTITY_SUPPLIER])
def test_source_catalog_does_not_suggest_credit_limit_for_masters(entity_type):
    from modules.autocount.mapping_catalog import AC_SOURCE_FIELDS

    assert "CreditLimit" not in AC_SOURCE_FIELDS[entity_type]


# ── (4) a required target covered only by a DISABLED row is not covered ────


def _master_rows_with_disabled_is_active():
    return [
        MappingWriteRow(source_path="AccNo", transform="string", sorento_field="code"),
        MappingWriteRow(source_path="CompanyName", transform="string", sorento_field="name"),
        MappingWriteRow(
            source_path="IsActive", transform="t_f_bool", sorento_field="is_active",
            is_enabled=False,
        ),
    ]


def test_replace_mapping_rejects_a_required_field_present_only_as_a_disabled_row(db, transports):
    """A disabled row is dropped by the engine, so on the wire ``is_active``
    is ABSENT - the save gate must count only ENABLED rows as coverage."""
    company = _company(db, transports)
    with pytest.raises(AutocountServiceError) as exc:
        CompanyService(db).replace_mapping(
            DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER,
            _master_rows_with_disabled_is_active(),
        )
    assert "is_active" in str(exc.value)


def test_replace_mapping_with_a_disabled_required_row_persists_nothing(db, transports):
    """The rejection must be atomic - the previously saved rows survive."""
    company = _company(db, transports)
    svc = CompanyService(db)
    before = {r.canonical_field: r.is_enabled for r in svc.mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER)}
    assert before["is_active"] is True

    with pytest.raises(AutocountServiceError):
        svc.replace_mapping(
            DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER,
            _master_rows_with_disabled_is_active(),
        )
    db.rollback()
    after = {r.canonical_field: r.is_enabled for r in CompanyService(db).mapping_rows(DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER)}
    assert after == before


def test_simulate_previews_a_disabled_required_row_as_absent_never_as_enabled(db, transports):
    """Simulate writes nothing, so the save gates alone close the is_active
    hole (the sprint-5/02 partial-draft preview contract stands: a draft
    previews even when it would not yet save). What simulate MUST do is
    honour the draft row's own ``is_enabled`` (kill test K4): a disabled
    ``is_active`` previews exactly as it would push - ABSENT from the
    projected fields and from the payload - never as if it were enabled."""
    company = _company(db, transports)
    svc = CompanyService(db)

    result = svc.simulate_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, _supplier(IsActive="T"),
        _master_rows_with_disabled_is_active(),
    )
    projected = {f["canonicalField"] for f in result["headerFields"]}
    assert "is_active" not in projected
    assert "is_active" not in (result["record"] or {})
    # The rest of the draft still previews.
    assert {"code", "name"} <= projected

    # Control: the SAME draft with the row enabled projects the field.
    enabled = [
        MappingWriteRow(
            row.source_path, row.transform, row.sorento_field, is_enabled=True,
        )
        for row in _master_rows_with_disabled_is_active()
    ]
    control = svc.simulate_mapping(
        DEFAULT_TENANT_ID, company.id, ENTITY_SUPPLIER, _supplier(IsActive="T"), enabled
    )
    assert "is_active" in {f["canonicalField"] for f in control["headerFields"]}
    assert control["record"]["is_active"] is True


def test_replace_mapping_rejects_a_required_line_field_present_only_as_a_disabled_row(db, transports):
    """The line-scope twin of the header gate (kill test S2): a document
    draft whose required LINE target (``qty_ordered``) carries
    ``isEnabled: false`` is dropped by the engine on the wire, so the save
    must count only ENABLED line rows as coverage."""
    from modules.autocount.canonical.documents import ENTITY_SALES_ORDER

    from tests.test_autocount_pipeline import _document_entity_config

    company = _company(db, transports)
    _document_entity_config(db, company, ENTITY_SALES_ORDER)
    rows = [
        MappingWriteRow(source_path="DocNo", transform="string", sorento_field="so_number"),
        MappingWriteRow(source_path="Status", transform="string", sorento_field="status"),
        MappingWriteRow(source_path="DtlKey", transform="string", sorento_field="source_ref", scope="line"),
        MappingWriteRow(source_path="ItemAutoKey", transform="ref_product", sorento_field="product_ref", scope="line"),
        MappingWriteRow(
            source_path="Qty", transform="decimal", sorento_field="qty_ordered", scope="line",
            is_enabled=False,
        ),
    ]
    with pytest.raises(AutocountServiceError) as exc:
        CompanyService(db).replace_mapping(DEFAULT_TENANT_ID, company.id, ENTITY_SALES_ORDER, rows)
    assert "qty_ordered" in str(exc.value)


# ── (5) the sweep is scoped to CUSTOMER rows ────────────────────────────────


def test_credit_limit_sweep_leaves_a_non_customer_row_alone(db):
    from modules.autocount.backfill import backfill_disable_credit_limit_mapping_rows

    customer = _credit_limit_row(ENTITY_CUSTOMER)
    supplier = _credit_limit_row(ENTITY_SUPPLIER)
    db.add_all([customer, supplier])
    db.commit()
    customer_id, supplier_id = customer.id, supplier.id

    touched = backfill_disable_credit_limit_mapping_rows(db, schema=None)
    db.expire_all()

    assert touched == 1
    assert db.get(AcFieldMapping, customer_id).is_enabled is False
    assert db.get(AcFieldMapping, supplier_id).is_enabled is True
