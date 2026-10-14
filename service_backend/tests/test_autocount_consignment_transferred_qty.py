"""AC-CONSIGN-PULL - Consignment `TransferedQty` on the wire (CRM contract 2.9).

Plan/AC: documentation/plans/sprint-5/31-autocount-consignment-transferred-qty-
acceptance-criteria.md. One ADDITIVE line field for the `consignment` entity,
sent only when the CRM advertises contract >= 2.9 - below that the 2.8 shape
(#122) goes out byte-identical. Existing consignment tasks are backfilled when
their stored queries are still the #122 preset text.

All rows below are fake. Never real AutoCount data.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.documents import (
    ENTITY_CANCEL_SALES_ORDER,
    ENTITY_CONSIGNMENT,
    ENTITY_CONSIGNMENT_RETURN,
    CanonicalCancelSalesOrder,
    CanonicalConsignment,
    linked_document_ref,
)
from modules.autocount.mapping import SCOPE_LINE
from modules.autocount.mapping_catalog import (
    line_accepted_field_names,
    line_required_field_names,
)
from modules.autocount.models import (
    SOURCE_IMPL_SQL_DB,
    AcCompany,
    AcEntityConfig,
    AcFieldMapping,
)
from modules.autocount.presets import (
    CANCEL_PO_PRESET,
    CANCEL_SO_PRESET,
    CONSIGNMENT_PRESET,
    CONSIGNMENT_RETURN_PRESET,
)
from modules.autocount.sinks_sorento import SorentoContractInfo, SorentoSink

from tests.test_s13_stock_push_contract_gate import _stock_gate_rig  # noqa: F401
from tests.test_autocount_linked_documents import _with_doc_feed_book

BOOK = "db1"


# ── AC-31-01: the preset SQL ─────────────────────────────────────────────────


def test_the_consignment_preset_selects_transferred_qty_and_its_aggregate():
    assert "d.TransferedQty AS TransferedQty" in CONSIGNMENT_PRESET.line_query
    # A transfer may not bump the header LastModified: the header hash and
    # the line fingerprint must both move on it.
    assert "SUM(d.TransferedQty) AS TransferedSum" in CONSIGNMENT_PRESET.header_query
    assert "l.TransferedSum AS TransferedSum" in CONSIGNMENT_PRESET.header_query
    assert "SUM(d.TransferedQty) AS TransferedSum" in CONSIGNMENT_PRESET.fingerprint_query


def test_the_other_linked_presets_are_unchanged():
    """Kill test: only the consignment preset grows the column."""
    for preset in (CANCEL_SO_PRESET, CANCEL_PO_PRESET, CONSIGNMENT_RETURN_PRESET):
        for sql in (preset.header_query, preset.line_query, preset.fingerprint_query):
            assert "TransferedQty" not in sql, preset.label


# ── AC-31-03: the mapping layer ──────────────────────────────────────────────


def test_the_preset_maps_transferred_qty_as_an_optional_line_field():
    rows = {row.source_path: row for row in CONSIGNMENT_PRESET.line}
    row = rows["TransferedQty"]
    assert (row.canonical_field, row.transform, row.required) == ("qty_transferred", "decimal", False)
    assert "qty_transferred" in line_accepted_field_names(ENTITY_CONSIGNMENT)
    assert "qty_transferred" not in line_required_field_names(ENTITY_CONSIGNMENT)
    assert "TransferedQty" not in {r.source_path for r in CANCEL_SO_PRESET.line}


# ── AC-31-02: the 2.9 wire gate ──────────────────────────────────────────────


def _raw(**line_overrides) -> dict:
    line = {
        "DocKey": 7001, "DtlKey": 70011, "Seq": 1, "ItemAutoKey": 10442,
        "ItemCode": "CHAIR-01", "Description": "Office chair", "LocationAutoKey": 7,
        "Location": "HQ", "Qty": Decimal("5.00000000"), "UOM": "UNIT",
        "UnitPrice": Decimal("150.50000000"), "SubTotal": Decimal("752.50"),
        "TransferedQty": Decimal("3.00000000"),
        "FromDocType": None, "FromDocNo": None, "FromDocDtlKey": None,
    }
    line.update(line_overrides)
    return {
        "DocKey": 7001, "DocNo": "CG-000001", "DocDate": datetime(2026, 10, 1),
        "DebtorAutoKey": 300, "DebtorCode": "300-A001", "DebtorName": "Acme Sdn Bhd",
        "SalesAgent": "JOHN", "Ref": None, "Description": None, "RefDocNo": None,
        "CurrencyCode": "MYR", "Note": None, "Cancelled": "F",
        "LastModified": datetime(2026, 10, 1, 9, 0, 0),
        "LineCount": 1, "QtySum": Decimal("5"), "SubTotalSum": Decimal("752.50"),
        "MaxDtlKey": 70011, "LinkedLineCount": 0, "FromDocKeySum": None,
        "TransferedSum": Decimal("3"),
        "_lines": [line],
    }


def _consignment(raw=None) -> CanonicalConsignment:
    raw = raw if raw is not None else _raw()
    return CanonicalConsignment(
        source_ref=linked_document_ref(ENTITY_CONSIGNMENT, BOOK, raw["DocKey"]),
        doc_no=raw["DocNo"], source_record=raw,
    )


@pytest.mark.parametrize("advertised", [None, 2.7, 2.8, 2.85])
def test_below_2_9_the_record_is_the_unchanged_2_8_shape(advertised):
    payload = _consignment().sink_payload(advertised_contract=advertised)
    line = payload["Details"][0]
    assert "TransferedQty" not in line
    assert "TransferedSum" not in payload
    # Everything #122 already sends is still there.
    for key in ("DebtorCode", "DebtorName", "SalesAgent"):
        assert key in payload, key
    for key in ("UnitPrice", "SubTotal", "UOM", "Qty", "ItemCode", "Location"):
        assert key in line, key


@pytest.mark.parametrize("advertised", [2.9, 2.91, 3.0])
def test_at_2_9_each_line_carries_transferred_qty_as_a_number(advertised):
    payload = _consignment().sink_payload(advertised_contract=advertised)
    line = payload["Details"][0]
    assert line["TransferedQty"] == 3 and isinstance(line["TransferedQty"], int)
    assert "TransferedSum" not in payload  # ESB-internal, never on the wire


def test_the_2_8_shape_is_byte_identical_to_a_record_without_the_new_columns():
    """Kill test: below 2.9 the new columns leave NO trace - the same record
    a pre-backfill task (no TransferedQty/TransferedSum selected) sends."""
    raw_old = _raw()
    raw_old.pop("TransferedSum")
    raw_old["_lines"][0].pop("TransferedQty")
    assert _consignment().sink_payload(advertised_contract=2.8) == _consignment(
        raw_old
    ).sink_payload(advertised_contract=2.8)


def test_the_staged_json_round_trip_keeps_the_gate_working():
    record = _consignment()
    rehydrated = CanonicalConsignment(**record.model_dump(mode="json"))
    assert "TransferedQty" in rehydrated.sink_payload(advertised_contract=2.9)["Details"][0]
    assert "TransferedQty" not in rehydrated.sink_payload(advertised_contract=2.8)["Details"][0]


def test_other_linked_documents_never_carry_transferred_qty_even_at_2_9():
    """A custom query on another linked document selecting the column must not
    leak it onto a door that never agreed to it."""
    raw = _raw()
    record = CanonicalCancelSalesOrder(
        source_ref=linked_document_ref(ENTITY_CANCEL_SALES_ORDER, BOOK, 7001),
        doc_no="XS-1", source_record=raw,
    )
    assert "TransferedQty" not in record.sink_payload(advertised_contract=2.9)["Details"][0]


# ── sink plumbing: the advertised contract reaches the payload ──────────────


@pytest.mark.parametrize("advertised,expect", [(2.8, False), (2.9, True)])
def test_the_sink_sends_transferred_qty_only_at_2_9(advertised, expect):
    requests: List[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        body = json.loads(request.content)
        return httpx.Response(200, json={
            "summary": {"total": 1, "created": 1},
            "records": [{"source_ref": f"{BOOK}:CSGN:{r['DocKey']}", "outcome": "created"}
                        for r in body["records"]],
        })

    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_CONSIGNMENT,
                       company_code="SOR", book=BOOK, transport=httpx.MockTransport(handle))
    sink.advertised_contract_version = advertised
    [result] = sink.write_batch([_consignment()], request_id="t")
    line = json.loads(requests[0].content)["records"][0]["Details"][0]
    assert ("TransferedQty" in line) is expect
    assert result.delivered is True


@pytest.mark.parametrize("advertised", [2.8, 2.9])
def test_sink_for_company_carries_the_live_advertised_contract(monkeypatch, _stock_gate_rig, advertised):
    from modules.autocount.services.company_service import CompanyService

    monkeypatch.setattr(
        SorentoSink, "fetch_contract_detail",
        lambda self: SorentoContractInfo(version=advertised, entities=["consignments"]),
    )
    db, company = _stock_gate_rig
    _with_doc_feed_book(db, company)
    sink = CompanyService(db).sink_for_company(DEFAULT_TENANT_ID, company, ENTITY_CONSIGNMENT)
    assert isinstance(sink, SorentoSink)
    assert sink.advertised_contract_version == advertised


def test_a_sink_built_without_a_probe_sends_the_2_8_shape():
    """Fail closed: no advertised contract known = the 2.8 shape."""
    sink = SorentoSink(base_url="http://x", api_key="k", entity_type=ENTITY_CONSIGNMENT, book=BOOK)
    assert sink.advertised_contract_version is None
    [record] = sink._to_records([_consignment()])
    assert "TransferedQty" not in record["Details"][0]


# ── AC-31-04: backfill of existing consignment tasks ────────────────────────


@pytest.fixture
def db(session_factory):
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


def _company(db, database: str) -> AcCompany:
    api = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="autocount", type="erp", name=f"AC {database}",
        config_json={"baseUrl": "https://ac.example.com", "userId": "ADMIN"},
        credentials_json=encrypt_secret({"appId": "app-1", "password": "secret"}),
        is_active=True,
    )
    db.add(api)
    db.flush()
    company = AcCompany(
        tenant_id=DEFAULT_TENANT_ID, connection_id=api.id, database_name=database,
        company_name=f"{database} Sdn Bhd", name=database, is_active=True,
    )
    db.add(company)
    db.commit()
    db.refresh(company)
    return company


def _config(db, company, *, query, line_query, fingerprint_query) -> AcEntityConfig:
    config = AcEntityConfig(
        tenant_id=DEFAULT_TENANT_ID, company_id=company.id, entity_type=ENTITY_CONSIGNMENT,
        source_impl=SOURCE_IMPL_SQL_DB,
    )
    config.source_config = {
        "connectionId": "conn-x", "query": query, "lineQuery": line_query,
        "fingerprintQuery": fingerprint_query, "keyColumns": ["DocKey"],
        "watermarkColumn": "LastModified", "comparedColumns": [],
    }
    config.result_columns = ["DocKey", "DocNo", "LastModified", "FromDocKeySum"]
    config.line_result_columns = ["DocKey", "DtlKey", "ItemCode", "FromDocDtlKey"]
    db.add(config)
    db.commit()
    db.refresh(config)
    return config


def _line_rows(db, company_id: str) -> List[AcFieldMapping]:
    return (
        db.query(AcFieldMapping)
        .filter(
            AcFieldMapping.company_id == company_id,
            AcFieldMapping.entity_type == ENTITY_CONSIGNMENT,
            AcFieldMapping.scope == SCOPE_LINE,
            AcFieldMapping.canonical_field == "qty_transferred",
        )
        .all()
    )


def _old(database):
    from modules.autocount.backfill import (
        _OLD_CONSIGNMENT_FINGERPRINT_QUERY,
        _OLD_CONSIGNMENT_HEADER_QUERY,
        _OLD_CONSIGNMENT_LINE_QUERY,
    )

    return {
        "query": _OLD_CONSIGNMENT_HEADER_QUERY.replace("{database}", database),
        "line_query": _OLD_CONSIGNMENT_LINE_QUERY.replace("{database}", database),
        "fingerprint_query": _OLD_CONSIGNMENT_FINGERPRINT_QUERY.replace("{database}", database),
    }


def test_the_frozen_old_texts_are_the_122_preset_and_differ_from_the_new():
    """The backfill only recognises the #122 text (pinned verbatim); the
    new preset is what it rewrites to."""
    from modules.autocount.backfill import _OLD_CONSIGNMENT_LINE_QUERY

    assert "TransferedQty" not in _OLD_CONSIGNMENT_LINE_QUERY
    assert _OLD_CONSIGNMENT_LINE_QUERY.replace(
        "d.SubTotal AS SubTotal, ", "d.SubTotal AS SubTotal, d.TransferedQty AS TransferedQty, ", 1,
    ) == CONSIGNMENT_PRESET.line_query


def test_backfill_rewrites_a_122_preset_task_and_seeds_the_line_row(db):
    from modules.autocount.backfill import backfill_consignment_transferred_qty

    company = _company(db, "AED_CG_OLD")
    config = _config(db, company, **_old("AED_CG_OLD"))
    config_id = config.id
    db.expire_all()

    assert backfill_consignment_transferred_qty(db, schema=None) == 2
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    sc = after.source_config
    assert sc["query"] == CONSIGNMENT_PRESET.header_query.replace("{database}", "AED_CG_OLD")
    assert sc["lineQuery"] == CONSIGNMENT_PRESET.line_query.replace("{database}", "AED_CG_OLD")
    assert sc["fingerprintQuery"] == CONSIGNMENT_PRESET.fingerprint_query.replace(
        "{database}", "AED_CG_OLD"
    )
    assert after.result_columns[-1] == "TransferedSum"
    assert after.line_result_columns[-1] == "TransferedQty"
    [row] = _line_rows(db, company.id)
    assert (row.source_path, row.transform, row.is_enabled, row.is_required) == (
        "TransferedQty", "decimal", True, False,
    )

    db.expire_all()
    assert backfill_consignment_transferred_qty(db, schema=None) == 0, "must be idempotent"
    db.expire_all()
    assert len(_line_rows(db, company.id)) == 1
    assert db.get(AcEntityConfig, config_id).result_columns.count("TransferedSum") == 1


def test_backfill_leaves_a_customised_query_alone_and_warns(db, caplog):
    from modules.autocount.backfill import backfill_consignment_transferred_qty

    company = _company(db, "AED_CG_CUSTOM")
    texts = _old("AED_CG_CUSTOM")
    texts["query"] = texts["query"] + " WHERE h.DocNo LIKE 'CG-%'"
    config = _config(db, company, **texts)
    config_id = config.id
    db.expire_all()

    with caplog.at_level(logging.WARNING):
        backfill_consignment_transferred_qty(db, schema=None)
    db.expire_all()
    after = db.get(AcEntityConfig, config_id)
    assert after.source_config["query"] == texts["query"]
    assert "TransferedSum" not in after.result_columns
    assert config_id in caplog.text
    # The mapping row is still offered (DISABLED: the customised query does
    # not select the column, so an enabled row would map nothing).
    [row] = _line_rows(db, company.id)
    assert row.is_enabled is False


def test_backfill_never_touches_other_entities(db):
    from modules.autocount.backfill import backfill_consignment_transferred_qty

    company = _company(db, "AED_CG_OTHER")
    config = _config(db, company, **_old("AED_CG_OTHER"))
    config.entity_type = ENTITY_CONSIGNMENT_RETURN
    db.commit()
    db.expire_all()
    assert backfill_consignment_transferred_qty(db, schema=None) == 0
