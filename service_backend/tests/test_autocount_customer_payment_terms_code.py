"""AutoCount Debtor ``DisplayTerm`` on the customer feed (lane SS-PAYMENT-TERMS,
partner of sorento-crm #2305 QUOTE-TERMS-SELECT, contract 2.14 addendum).

RED before the implementation. Same shape as ``market_segment_code``
(SS-DEBTOR-TYPE): every AutoCount Debtor row (vendor API AND the open REST
``/debtorbypage``) carries ``DisplayTerm`` (the debtor's AutoCount Terms code),
and the ESB dropped it on purpose while the CRM treated
``payment_terms_code`` as an unconditional ``retryable`` (AC-14-12).
Contract 2.14 accepts it again on customers: optional string <= 50, absent =
untouched, ``""`` = cleared, not validated against ``payment_terms``.

Wire contract:
* key ``payment_terms_code``, trimmed, the code exactly as AutoCount holds it;
* OMITTED (never ``null``) when the Debtor's ``DisplayTerm`` is blank/absent;
* PUSHED ONLY to a CRM that advertises >= 2.14: the push strips it for an
  older or unprovable consumer (``advertised_contract`` below 2.14 or None),
  so an older CRM never sees the key it lists in ``fields_removed``;
* suppliers never carry it (``suppliers.payment_terms_code`` stays removed).

Existing tenants: every existing ``customer`` task gets a
``DisplayTerm -> payment_terms_code`` row via
``backfill_customer_display_term`` (module Alembic 0043 + ``update_tenant``
from < 0.23.0).
"""
from __future__ import annotations

import importlib.util
import json
import logging
import pathlib
import re
from typing import Any, Dict

import pytest
import sqlalchemy as sa

import modules.autocount as autocount_module
from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER, CanonicalCustomer
from modules.autocount.mapping import (
    DEFAULT_CUSTOMER_MAPPING,
    DEFAULT_SUPPLIER_MAPPING,
    SCOPE_HEADER,
    MappingEngine,
    MappingRow,
    flat_profile,
)
from modules.autocount.mapping_catalog import accepted_field_names, ac_source_fields
from modules.autocount.models import (
    SOURCE_IMPL_AUTOCOUNT_HTTP,
    SOURCE_IMPL_AUTOCOUNT_READ,
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import CUSTOMER_HTTP_PRESET

MODULE_ROOT = pathlib.Path(autocount_module.__file__).resolve().parent
VERSIONS_DIR = MODULE_ROOT / "alembic" / "versions"
FIXTURE = pathlib.Path(__file__).resolve().parent / "fixtures" / "autocount_http" / "debtor_page.json"

HELPER_NAME = "backfill_customer_display_term"
PREVIOUS_REVISION = "0042_autocount_queue_wait"


def _backfill():
    from modules.autocount import backfill

    helper = getattr(backfill, HELPER_NAME, None)
    if helper is None:
        pytest.fail(f"modules.autocount.backfill has no `{HELPER_NAME}` helper yet")
    return helper


# ═════════════════════════ Group A - canonical, preset, wire ════════════════


def test_canonical_customer_sends_payment_terms_code_right_after_payment_terms_code():
    fields = CanonicalCustomer.SINK_FIELDS
    assert "payment_terms_code" in fields
    assert fields.index("payment_terms_code") == fields.index("market_segment_code") + 1


def test_sink_payload_carries_payment_terms_code_verbatim():
    customer = CanonicalCustomer(source_ref="DB:1", code="300-A001", name="A",
                                 payment_terms_code="C.B.D.")
    assert customer.sink_payload()["payment_terms_code"] == "C.B.D."


def test_sink_payload_omits_payment_terms_code_when_none():
    payload = CanonicalCustomer(source_ref="DB:1", code="300-A001", name="A").sink_payload()
    assert "payment_terms_code" not in payload


def test_supplier_never_carries_payment_terms_code():
    """Creditor rows have no debtor type - the field is customer-only."""
    from modules.autocount.canonical.masters import CanonicalSupplier

    assert "payment_terms_code" not in CanonicalSupplier.SINK_FIELDS
    assert all(r.canonical_field != "payment_terms_code" for r in DEFAULT_SUPPLIER_MAPPING)


def test_mapping_catalog_accepts_payment_terms_code_for_customer_only():
    assert "payment_terms_code" in accepted_field_names(ENTITY_CUSTOMER)
    assert "payment_terms_code" not in accepted_field_names("supplier")


def test_customer_source_catalog_offers_display_term():
    assert "DisplayTerm" in ac_source_fields(ENTITY_CUSTOMER)


def test_default_vendor_customer_mapping_maps_display_term():
    rows = [r for r in DEFAULT_CUSTOMER_MAPPING if r.canonical_field == "payment_terms_code"]
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_path, row.transform, row.scope) == ("DisplayTerm", "string", SCOPE_HEADER)
    assert row.is_enabled is True and row.is_required is False


def test_customer_preset_maps_display_term_enabled_after_display_term():
    pairs = [(f.source_path, f.canonical_field) for f in CUSTOMER_HTTP_PRESET.rows]
    assert ("DisplayTerm", "payment_terms_code") in pairs
    assert pairs.index(("DisplayTerm", "payment_terms_code")) == pairs.index(("DebtorType", "market_segment_code")) + 1
    row = CUSTOMER_HTTP_PRESET.rows[pairs.index(("DisplayTerm", "payment_terms_code"))]
    assert row.transform == "string"
    assert row.enabled is True
    assert row.required is False
    assert row.formula is None


def _engine() -> MappingEngine:
    rows = [
        MappingRow(
            source_path=f.source_path, canonical_field=f.canonical_field,
            transform=f.transform, formula=f.formula, is_required=f.required,
            is_enabled=f.enabled,
        )
        for f in CUSTOMER_HTTP_PRESET.rows
    ]
    return MappingEngine(
        rows, entity_type=ENTITY_CUSTOMER,
        profile=flat_profile(ENTITY_CUSTOMER, list(CUSTOMER_HTTP_PRESET.key_fields)),
        database_name="AED_SORENTO",
    )


def _raw(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "AccNo": "300-X001", "CompanyName": "Example Trading", "Phone1": "",
        "SalesAgent": "AGENT A", "DebtorType": "SORENTO", "DisplayTerm": "C.O.D.", "IsActive": "T",
    }
    base.update(overrides)
    return base


@pytest.mark.parametrize(
    "display_term, expected",
    [("C.O.D.", "C.O.D."), ("Net 30 days", "Net 30 days"), ("  C.B.D. ", "C.B.D."), ("net 60", "net 60")],
)
def test_preset_maps_display_term_onto_the_wire(display_term, expected):
    mapped = _engine().map_document(_raw(DisplayTerm=display_term))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert mapped.record.sink_payload()["payment_terms_code"] == expected


@pytest.mark.parametrize("blank", ["", "   ", None])
def test_blank_display_term_is_omitted_never_null(blank):
    mapped = _engine().map_document(_raw(DisplayTerm=blank))
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert "payment_terms_code" not in mapped.record.sink_payload()


def test_absent_display_term_column_is_omitted():
    raw = _raw()
    raw.pop("DisplayTerm")
    mapped = _engine().map_document(raw)
    assert mapped.ok, [e.message() for e in mapped.errors]
    assert "payment_terms_code" not in mapped.record.sink_payload()


def test_blank_display_term_leaves_the_payload_byte_identical_to_before():
    """Only a NON-blank type changes the payload (and so the staged hash): a
    customer with a blank type never re-stages because of this lane."""
    without_row = MappingEngine(
        [r for r in _engine().header_rows if r.canonical_field != "payment_terms_code"],
        entity_type=ENTITY_CUSTOMER,
        profile=flat_profile(ENTITY_CUSTOMER, list(CUSTOMER_HTTP_PRESET.key_fields)),
        database_name="AED_SORENTO",
    )
    raw = _raw(DisplayTerm="")
    assert _engine().map_document(dict(raw)).record.sink_payload() == \
        without_row.map_document(dict(raw)).record.sink_payload()
    raw = _raw(DisplayTerm="C.B.D.")
    assert _engine().map_document(dict(raw)).record.sink_payload() != \
        without_row.map_document(dict(raw)).record.sink_payload()


def test_fixture_debtor_row_delivers_display_term():
    """The recorded ``/debtorbypage`` rows carry ``Net 60 days``."""
    rows = json.loads(FIXTURE.read_text())["Data"]
    got = [_engine().map_document(dict(r)).record.sink_payload()["payment_terms_code"] for r in rows]
    assert got == ["Net 60 days", "Net 60 days"]


# ═════════════════════════ Group B - backfill for existing tasks ════════════


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, *, database: str, tenant_id: str = DEFAULT_TENANT_ID) -> AcCompany:
    api = Connection(
        tenant_id=tenant_id, provider="autocount", type="erp", name=f"AutoCount {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=tenant_id, connection_id=api.id, database_name=database,
        company_name=f"{database} Sdn Bhd", name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _customer_config(db, company: AcCompany, *, source_impl: str = SOURCE_IMPL_AUTOCOUNT_HTTP,
                     path: str = "/debtorbypage", result_columns=None,
                     tenant_id: str = None, seed_rows: bool = True) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=tenant_id or company.tenant_id, company_id=company.id,
        entity_type=ENTITY_CUSTOMER, source_impl=source_impl,
    )
    if source_impl == SOURCE_IMPL_AUTOCOUNT_HTTP:
        config.source_config = {"connectionId": "conn-x", "path": path, "keyFields": ["AccNo"]}
    elif source_impl == SOURCE_IMPL_SQL_DB:
        config.source_config = {"connectionId": "conn-x", "query": "SELECT 1", "keyColumns": ["AccNo"]}
    config.result_columns = list(result_columns or [])
    db.add(config)
    db.commit()
    db.refresh(config)
    if seed_rows:
        # A real task already maps something (its default/preset seed).
        _seed_existing_rows(db, company)
    return config


def _seed_existing_rows(db, company: AcCompany) -> None:
    for order, (src, dst) in enumerate(
        (("AccNo", "code"), ("CompanyName", "name"), ("Phone1", "phone_number"))
    ):
        db.add(AcFieldMapping(
            tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_CUSTOMER,
            scope=SCOPE_HEADER, source_path=src, canonical_field=dst,
            transform="string", is_enabled=True, is_required=(dst == "code"), sort_order=order,
        ))
    db.commit()


def _rows(db, company_id: str, field: str = "payment_terms_code"):
    return [
        r for r in (
            db.query(AcFieldMapping)
            .filter(
                AcFieldMapping.company_id == company_id,
                AcFieldMapping.entity_type == ENTITY_CUSTOMER,
                AcFieldMapping.scope == SCOPE_HEADER,
            )
            .order_by(AcFieldMapping.sort_order)
            .all()
        )
        if r.canonical_field == field
    ]


def test_backfill_seeds_an_enabled_row_on_an_http_debtor_task(db):
    company = _company(db, database="AED_PT_HTTP")
    _customer_config(db, company)
    db.expire_all()

    assert _backfill()(db, schema=None) == 1
    db.expire_all()

    rows = _rows(db, company.id)
    assert len(rows) == 1
    row = rows[0]
    assert (row.source_path, row.transform, row.formula) == ("DisplayTerm", "string", None)
    assert row.is_enabled is True and row.is_required is False and row.is_source_owned is True
    assert row.sort_order == 3  # next after the existing rows
    assert row.tenant_id == company.tenant_id


def test_backfill_enables_on_the_vendor_api_source(db):
    """The vendor Debtor payload always carries ``DisplayTerm`` (Postman
    collection) - the default-mapping path is a known-good source."""
    company = _company(db, database="AED_PT_READ")
    _customer_config(db, company, source_impl=SOURCE_IMPL_AUTOCOUNT_READ)
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_backfill_enables_when_result_columns_carry_display_term(db):
    company = _company(db, database="AED_PT_SQL_OK")
    _customer_config(db, company, source_impl=SOURCE_IMPL_SQL_DB,
                     result_columns=["AccNo", "CompanyName", "DisplayTerm"])
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_backfill_seeds_disabled_with_a_warning_when_source_lacks_display_term(db, caplog):
    company = _company(db, database="AED_PT_SQL_NO")
    config = _customer_config(db, company, source_impl=SOURCE_IMPL_SQL_DB,
                              result_columns=["AccNo", "CompanyName"])
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [False]
    assert [r for r in caplog.records if config_id in r.getMessage()]


def test_backfill_disables_on_a_custom_http_path(db):
    company = _company(db, database="AED_PT_PATH")
    _customer_config(db, company, path="/somethingelse")
    _backfill()(db, schema=None)
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [False]


def test_backfill_skips_a_task_with_no_mapping_rows(db):
    """A never-mapped task gets its WHOLE default/preset mapping (which
    already carries the row) from the seed gated on an EMPTY mapping - a
    lone backfilled row would block that seed forever."""
    company = _company(db, database="AED_PT_EMPTY")
    _customer_config(db, company, seed_rows=False)
    assert _backfill()(db, schema=None) == 0
    db.expire_all()
    assert db.query(AcFieldMapping).filter(AcFieldMapping.company_id == company.id).count() == 0


def test_update_tenant_still_seeds_the_full_default_on_an_unmapped_vendor_task(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_PT_FULLSEED")
    _customer_config(db, company, source_impl=SOURCE_IMPL_AUTOCOUNT_READ, seed_rows=False)
    update_tenant(db, DEFAULT_TENANT_ID, "0.22.0")
    db.commit()
    db.expire_all()
    fields = {
        r.canonical_field for r in db.query(AcFieldMapping).filter(
            AcFieldMapping.company_id == company.id,
            AcFieldMapping.entity_type == ENTITY_CUSTOMER,
        )
    }
    assert {r.canonical_field for r in DEFAULT_CUSTOMER_MAPPING} <= fields
    assert len(_rows(db, company.id)) == 1


def test_backfill_leaves_an_existing_row_alone_in_any_state(db):
    company = _company(db, database="AED_PT_OWN")
    _customer_config(db, company, seed_rows=False)
    db.add(AcFieldMapping(
        tenant_id=company.tenant_id, company_id=company.id, entity_type=ENTITY_CUSTOMER,
        scope=SCOPE_HEADER, source_path="Attention", canonical_field="payment_terms_code",
        transform="string", is_enabled=False, is_required=False, sort_order=0,
    ))
    db.commit()
    existing_id = _rows(db, company.id)[0].id
    db.expire_all()

    assert _backfill()(db, schema=None) == 0
    db.expire_all()
    rows = _rows(db, company.id)
    assert [r.id for r in rows] == [existing_id]
    assert rows[0].source_path == "Attention" and rows[0].is_enabled is False


def test_backfill_is_idempotent(db):
    company = _company(db, database="AED_PT_TWICE")
    _customer_config(db, company)
    helper = _backfill()
    assert helper(db, schema=None) == 1
    assert helper(db, schema=None) == 0
    db.expire_all()
    assert len(_rows(db, company.id)) == 1


def test_backfill_touches_only_customer_tasks(db):
    company = _company(db, database="AED_PT_OTHER")
    config = AcEntityConfig(
        tenant_id=company.tenant_id, company_id=company.id,
        entity_type="supplier", source_impl=SOURCE_IMPL_AUTOCOUNT_READ,
    )
    db.add(config)
    db.commit()
    assert _backfill()(db, schema=None) == 0
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.canonical_field == "payment_terms_code"
    ).count() == 0


def test_backfill_skips_a_config_whose_company_belongs_to_another_tenant(db, caplog):
    leaking = _company(db, database="AED_PT_LEAK", tenant_id="tenant-leak-payment-term")
    config = _customer_config(db, leaking, tenant_id=DEFAULT_TENANT_ID)
    config_id = config.id
    with caplog.at_level(logging.WARNING):
        _backfill()(db, schema=None)
    db.expire_all()
    assert db.query(AcFieldMapping).filter(
        AcFieldMapping.company_id == leaking.id,
        AcFieldMapping.canonical_field == "payment_terms_code",
    ).count() == 0
    assert [r for r in caplog.records if config_id in r.getMessage()]


def test_backfill_is_a_no_op_on_a_schema_that_predates_its_tables():
    helper = _backfill()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "CREATE TABLE ac_entity_config (id TEXT PRIMARY KEY, tenant_id TEXT, "
            "company_id TEXT, entity_type TEXT)"
        )
        conn.exec_driver_sql("INSERT INTO ac_entity_config VALUES ('c', 't', 'c', 'customer')")
    with engine.begin() as conn:
        assert helper(conn, schema=None) == 0
    with sa.create_engine("sqlite://").begin() as conn:
        assert helper(conn, schema=None) == 0


def test_revision_0043_chains_onto_0042_and_calls_the_helper():
    candidates = sorted(VERSIONS_DIR.glob("0043_*.py"))
    assert len(candidates) == 1, [p.name for p in candidates]
    path = candidates[0]
    text = path.read_text()
    revision = re.search(r'^revision[^=]*=\s*"([^"]+)"', text, re.M)
    assert revision and len(revision.group(1)) <= 32
    spec = importlib.util.spec_from_file_location("_ac_rev_0043", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.down_revision == PREVIOUS_REVISION
    assert HELPER_NAME in text
    for other in VERSIONS_DIR.glob("*.py"):
        if other == path:
            continue
        down = re.search(r'^down_revision[^=]*=\s*"([^"]+)"', other.read_text(), re.M)
        assert not (down and down.group(1) == PREVIOUS_REVISION), other.name


def test_manifest_version_is_bumped_past_0_22_0():
    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert tuple(int(p) for p in manifest["version"].split(".")) >= (0, 23, 0)


def test_user_agent_matches_the_manifest_version():
    from modules.autocount.http_source.client import USER_AGENT

    manifest = json.loads((MODULE_ROOT / "manifest.json").read_text())
    assert USER_AGENT.endswith("/" + manifest["version"])


def test_update_tenant_from_0_22_seeds_the_row(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_PT_UPD")
    _customer_config(db, company)
    update_tenant(db, DEFAULT_TENANT_ID, "0.22.0")
    db.commit()
    db.expire_all()
    assert [r.is_enabled for r in _rows(db, company.id)] == [True]


def test_update_tenant_from_0_23_never_reseeds_a_row_an_operator_deleted(db):
    from modules.autocount.bootstrap import update_tenant

    company = _company(db, database="AED_PT_DEL")
    _customer_config(db, company)
    update_tenant(db, DEFAULT_TENANT_ID, "0.22.0")
    db.commit()
    rows = _rows(db, company.id)
    assert len(rows) == 1
    db.delete(rows[0])
    db.commit()

    update_tenant(db, DEFAULT_TENANT_ID, "0.23.0")
    db.commit()
    db.expire_all()
    assert _rows(db, company.id) == []


def test_scoped_backfill_touches_only_that_tenant(db):
    mine = _company(db, database="AED_PT_SCOPE_A")
    other = _company(db, database="AED_PT_SCOPE_B", tenant_id="tenant-payment-term-b")
    _customer_config(db, mine)
    _customer_config(db, other)

    assert _backfill()(db, schema=None, tenant_id=DEFAULT_TENANT_ID) == 1
    db.expire_all()
    assert len(_rows(db, mine.id)) == 1
    assert _rows(db, other.id) == []


# ═════════════════════════ Group C - contract 2.14 gate on the push ═════════


def test_supplier_payload_never_carries_payment_terms_code_even_on_2_14():
    from modules.autocount.canonical.masters import CanonicalSupplier
    from modules.autocount.sinks_sorento import ContractVersion

    payload = CanonicalSupplier(source_ref="DB:1", code="400-A", name="S").sink_payload()
    assert "payment_terms_code" not in payload
    assert ContractVersion(2, 14)  # imported for parity with the customer case


@pytest.mark.parametrize("advertised, sent", [
    ((2, 14), True), ((2, 15), True), ((3, 0), True),
    ((2, 13), False), ((2, 9), False), (None, False),
])
def test_push_payload_carries_payment_terms_code_only_from_contract_2_14(advertised, sent):
    from modules.autocount.sinks_sorento import ContractVersion

    version = ContractVersion(*advertised) if advertised else None
    customer = CanonicalCustomer(source_ref="DB:1", code="300-A001", name="A", payment_terms_code="C.O.D.")
    payload = customer.sink_payload(advertised_contract=version)
    assert ("payment_terms_code" in payload) is sent
    # Nothing else moves with the gate.
    assert {k: v for k, v in payload.items() if k != "payment_terms_code"} == \
        {k: v for k, v in customer.sink_payload().items() if k != "payment_terms_code"}


def _crm_customer_posts(posts):
    import httpx

    def handler(request):
        posts.append(request)
        body = json.loads(request.content.decode("utf-8"))
        records = body.get("records") or []
        return httpx.Response(200, json={
            "dry_run": False, "summary": {"total": len(records), "created": len(records)},
            "records": [{"source_ref": r["source_ref"], "outcome": "created"} for r in records],
        })

    return handler


@pytest.mark.parametrize("version, sent", [("2.14", True), ("2.13", False)])
def test_sink_for_company_probes_the_contract_for_the_customer_feed(db, monkeypatch, version, sent):
    """The customer feed is not entity-gated, so the sink factory probes the
    consumer's contract for the FIELD gate; the write then carries
    ``payment_terms_code`` only on a 2.14 CRM."""
    import httpx

    from modules.autocount.services.company_service import CompanyService
    from modules.autocount.sinks_sorento import ContractVersion, SorentoContractInfo, SorentoSink
    import modules.autocount.services.company_service as company_module

    info = SorentoContractInfo(version=ContractVersion.parse(version), entities=["customers"])
    monkeypatch.setattr(SorentoSink, "fetch_contract_detail", lambda self: info)
    posts = []
    real = company_module.sorento_sink_from_connection

    def spy(config, credentials, *, entity_type, company_code=None, transport=None, **kw):
        return real(config, credentials, entity_type=entity_type, company_code=company_code,
                    transport=httpx.MockTransport(_crm_customer_posts(posts)), **kw)

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", spy)

    sorento = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": "https://sorento.example.com"},
        credentials_json=encrypt_secret({"apiKey": "k" * 12}), is_active=True,
    )
    db.add(sorento)
    db.commit()
    company = _company(db, database="AED_PT_GATE_" + version.replace(".", "_"))
    company.sink_impl = "sorento"
    company.sink_connection_id = sorento.id
    company.sorento_company_code = "SRT"
    db.commit()

    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_CUSTOMER)
    assert isinstance(sink, SorentoSink)
    sink.write_batch(
        [CanonicalCustomer(source_ref="DB:1", code="300-A001", name="A", payment_terms_code="C.O.D.")],
        request_id="t",
    )
    sent_records = json.loads(posts[-1].content.decode("utf-8"))["records"]
    assert ("payment_terms_code" in sent_records[0]) is sent


def test_payment_terms_code_cap_matches_the_term_code_cap():
    """A customer must be able to name ANY term code exactly: both are capped
    at 100 (CRM #2305, crew decision 10 Nov)."""
    from pydantic import ValidationError

    from modules.autocount.canonical.masters import CanonicalPaymentTerm

    CanonicalCustomer(source_ref="DB:1", code="300-A", name="A", payment_terms_code="T" * 100)
    CanonicalPaymentTerm(source_ref="DB:T", code="T" * 100)
    with pytest.raises(ValidationError):
        CanonicalCustomer(source_ref="DB:1", code="300-A", name="A", payment_terms_code="T" * 101)
