"""Plan 57 (RED): write-back pushes through the REAL ``SorentoSink`` (``write_batch``).

Live finding: ``DocStager._push`` calls ``sink.write(record, request_id=...)`` but the real
``SorentoSink`` only has ``write_batch(records, *, request_id, ...)``. Every other write-back
test uses a fake sink with ``write``, so a push to a real Sorento never worked (the
AttributeError is swallowed by ``stage_and_push`` and the row stays STAGED).

Here the stager's DEFAULT sink path runs: the company is set to push to a Sorento consumer
connection (``sink_impl="sorento"``), and ``company_service.sorento_sink_from_connection`` is
wrapped to inject an ``httpx.MockTransport`` that serves ``/external/contract`` and the ingest door.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Dict, List

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.models import STAGED, STAGED_PUSHED, AcStagedRecord
from tests.test_autocount_write_back_operations import (  # noqa: F401
    deleted_a_row,
    PUT_PO,
    OpHarness,
    World,
    ZERO,
    db,
    h,
)
from tests.write_back_host_pin import pin_test_write_host  # noqa: F401

SORENTO_URL = "https://crm.example.test"
ENTITIES = ["purchase_orders", "shipping_orders", "sales_orders", "suppliers", "customers"]


class SorentoMock:
    """Serves ``GET /api/v1/external/contract`` and ``POST /api/v1/external/ingest/<entity>``."""

    def __init__(self, version: str = "2.12", fail: bool = False) -> None:
        self.version = version
        self.fail = fail
        self.posts: List[Dict[str, Any]] = []
        self.contract_gets = 0
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path.endswith("/external/contract"):
            self.contract_gets += 1
            return httpx.Response(200, json={"version": self.version, "entities": ENTITIES})
        if request.method == "POST" and "/external/ingest/" in path and not path.endswith("/deletions"):
            import json

            body = json.loads(request.content)
            self.posts.append({"entity": path.rsplit("/", 1)[-1], "body": body, "query": dict(request.url.params)})
            if self.fail:
                return httpx.Response(500, json={"error": "boom"})
            records = body.get("records", [])
            return httpx.Response(200, json={
                "summary": {"total": len(records), "created": len(records)},
                "records": [{"source_ref": r.get("source_ref"), "outcome": "created"} for r in records]})
        return httpx.Response(404, json={"error": "unknown"})

    def po_posts(self):
        return [p for p in self.posts if p["entity"] == "purchase_orders"]


@pytest.fixture
def rig(h, monkeypatch):
    """The harness company pushes to a Sorento consumer connection served by ``SorentoMock``."""
    import modules.autocount.services.company_service as company_module

    mock = SorentoMock()
    conn = Connection(
        tenant_id=DEFAULT_TENANT_ID, provider="sorento", type="erp", name="Sorento",
        config_json={"baseUrl": SORENTO_URL, "sorentoContractVersion": "2"},
        credentials_json=encrypt_secret({"apiKey": "k" * 24}), is_active=True)
    h.db.add(conn)
    h.db.commit()
    h.company.sink_impl = "sorento"
    h.company.sink_connection_id = conn.id
    h.company.sorento_company_code = "SRT"
    h.db.commit()
    real = company_module.sorento_sink_from_connection

    def with_mock_transport(config, credentials, *, entity_type, company_code=None, transport=None, **kw):
        return real(config, credentials, entity_type=entity_type, company_code=company_code,
                    transport=mock.transport, **kw)

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", with_mock_transport)
    h.sorento = mock
    return h


def prims(h):
    from modules.autocount.write_back.primitives import PrimitiveService

    f = h.factories()
    return PrimitiveService(h.db, client_factory=f["client_factory"], reader_factory=f["reader_factory"])


def ops(h):
    from modules.autocount.write_back.operations import OperationService

    f = h.factories()
    return OperationService(h.db, client_factory=f["client_factory"], reader_factory=f["reader_factory"],
                            receipt_reader=ZERO, notifier=h.alerts.append)


def staged_po(h) -> AcStagedRecord:
    h.db.expire_all()
    return h.db.query(AcStagedRecord).filter(AcStagedRecord.source_ref == "AED_TEST:7001",
                                             AcStagedRecord.entity_type == "purchase_order").one()


def edit(h, **kw):
    return prims(h).edit_doc(**h.args("PO", doc_key=7001, header_changes={"Remark1": "pushed"},
                                      line_changes=[], **kw))


# ---- (1) a primitive edit pushes through the real sink ----------------------------------------------------

def test_a_primitive_edit_on_an_http_sourced_po_is_pushed_through_the_real_sink(rig):
    h = rig
    h.delete_on()
    World(h)
    res = edit(h)
    assert res.outcome == "done", res.error_code
    assert len(h.sorento.po_posts()) == 1, h.sorento.posts
    post = h.sorento.po_posts()[0]["body"]
    assert post["companyCode"] == "SRT"
    (record,) = post["records"]
    assert record["source_ref"] == "AED_TEST:7001"
    assert len(record["lines"]) == 4
    row = staged_po(h)
    assert row.status == STAGED_PUSHED and row.pushed_at is not None


def test_the_push_goes_out_once_not_per_line_or_per_retry(rig):
    h = rig
    h.delete_on()
    World(h)
    edit(h)
    assert len(h.sorento.posts) == 1


# ---- (2) an operation's push carries replaces_line_ref only from contract 2.12 ------------------------------

def _link(h, w):
    return ops(h).run(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, key_id="key-1",
                      idempotency_key="idem-1", op="link_row", params=w.params["link_row"])


def test_an_operation_push_carries_replaces_line_ref_when_the_consumer_advertises_2_12(rig):
    h = rig
    h.sorento.version = "2.12"
    h.delete_on()
    w = World(h)
    res = _link(h, w)
    assert res.outcome == "done", res.error_code
    (old_key, new_key), = res.replaced_lines
    (record,) = h.sorento.po_posts()[-1]["body"]["records"]
    with_ref = [line for line in record["lines"] if "replaces_line_ref" in line]
    assert len(with_ref) == 1 and with_ref[0]["replaces_line_ref"] == f"AED_TEST:7001:{old_key}"
    assert with_ref[0]["source_ref"].endswith(f":{new_key}")


def test_an_operation_push_omits_replaces_line_ref_when_the_consumer_advertises_2_11(rig):
    h = rig
    h.sorento.version = "2.11"
    h.delete_on()
    w = World(h)
    res = _link(h, w)
    assert res.outcome == "done", res.error_code
    (record,) = h.sorento.po_posts()[-1]["body"]["records"]
    assert not any("replaces_line_ref" in line for line in record["lines"])
    assert staged_po(h).status == STAGED_PUSHED


def test_the_advertised_contract_is_probed_so_an_unreachable_contract_omits_the_field(rig):
    h = rig
    h.sorento.version = "garbage"
    h.delete_on()
    w = World(h)
    res = _link(h, w)
    assert res.outcome == "done"
    (record,) = h.sorento.po_posts()[-1]["body"]["records"]
    assert not any("replaces_line_ref" in line for line in record["lines"])  # unknown = fail closed
    assert h.sorento.po_posts()  # and the document itself still went out


# ---- (3) the plan 55 pull path re-pushes a STAGED row ----------------------------------------------------------

def test_pull_documents_re_pushes_a_staged_row_through_the_real_sink(rig):
    from modules.autocount.write_back.pull_docs import MODE_DOC_DATE, pull_documents

    h = rig
    World(h)
    assert staged_po(h).status == STAGED  # not pushed yet
    result = pull_documents(h.db, tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id,
                            date_from=date(2026, 11, 4), date_to=date(2026, 11, 4),
                            mode=MODE_DOC_DATE, reader_factory=h.factories()["reader_factory"])
    assert not result.failed
    refs = [r["source_ref"] for p in h.sorento.po_posts() for r in p["body"]["records"]]
    assert "AED_TEST:7001" in refs, h.sorento.posts
    row = staged_po(h)
    assert row.status == STAGED_PUSHED and row.pushed_at is not None
    assert all(p["body"]["companyCode"] == "SRT" for p in h.sorento.posts)


def test_pull_documents_does_not_re_push_an_unchanged_pushed_row(rig):
    from modules.autocount.write_back.pull_docs import MODE_DOC_DATE, pull_documents

    h = rig
    World(h)
    kwargs = dict(tenant_id=DEFAULT_TENANT_ID, company_id=h.company.id, date_from=date(2026, 11, 4),
                  date_to=date(2026, 11, 4), mode=MODE_DOC_DATE, reader_factory=h.factories()["reader_factory"])
    pull_documents(h.db, **kwargs)
    first = len(h.sorento.po_posts())
    assert first >= 1
    pull_documents(h.db, **kwargs)
    assert len(h.sorento.po_posts()) == first


# ---- (4) a sink HTTP failure leaves the row STAGED, the write still done --------------------------------------

def test_a_sink_http_failure_leaves_the_row_staged_and_the_write_still_done(rig):
    h = rig
    h.sorento.fail = True
    h.delete_on()
    World(h)
    res = edit(h)
    assert res.outcome == "done", res.error_code
    assert h.sorento.po_posts(), "the push must actually have been attempted through the real sink"
    row = staged_po(h)
    assert row.status == STAGED and row.pushed_at is None
    assert row.raw_json["Remark1"] == "pushed"  # the read-back is still staged


def test_a_sink_failure_does_not_break_an_operation_either(rig):
    h = rig
    h.sorento.fail = True
    h.delete_on()
    w = World(h)
    res = _link(h, w)
    assert res.outcome == "done", res.error_code
    assert h.sorento.po_posts()
    assert staged_po(h).status == STAGED
