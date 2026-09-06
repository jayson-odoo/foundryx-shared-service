"""The activation preview surfaces WHAT the consumer said, not a fixed sentence.

Prod, 2026-09-06: the operator hit "Dry run failed" twice with no way to know
whether Sorento answered a 504 (nginx proxy timeout) or a 422 (a payload it
rejects). ``EtlService.preview_task`` catches ``SorentoSinkError`` and raises
``PreviewUnavailable`` with a generic sentence; the router maps it to a 502
carrying only that sentence.

Contract: ``PreviewUnavailable.message`` = the generic sentence + one line
``Consumer said: HTTP <status> <first 300 chars of body, whitespace-collapsed>``
(``Consumer unreachable: <ExceptionClass>: <str>`` for a transport fault); the
status is exposed as ``status_code``; the 502 body's ``detail`` is that
message; the API key never appears in it.

Rig, consumer and URL helpers are the ones ``test_autocount_etl_task_routes``
drives preview with.
"""
from __future__ import annotations

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from modules.autocount.canonical.masters import ENTITY_CUSTOMER
from modules.autocount.models import AcCompany
from modules.autocount.services.etl_service import EtlService, PreviewUnavailable
from modules.autocount.sinks_sorento import SorentoSinkError
from tests.test_autocount_etl_task_routes import (  # noqa: F401 - fixtures re-exported
    _auth,
    _clean_runtime,
    _url,
    consumer,
    rig,
)

GENERIC = "The dry run against the consumer failed"
HTML_504 = (
    "<html>\r\n<head><title>504 Gateway Time-out</title></head>\r\n"
    "<body>\r\n<center><h1>504 Gateway Time-out</h1></center>\r\n"
    "<hr><center>nginx</center>\r\n</body>\r\n</html>\r\n"
)
BODY_422 = {"detail": [{"loc": ["body", "records", 0, "foo"], "msg": "Extra inputs are not permitted"}]}


def _preview(session_factory, company_id: str) -> PreviewUnavailable:
    db = session_factory()
    try:
        with pytest.raises(PreviewUnavailable) as exc:
            EtlService(db).preview_task(DEFAULT_TENANT_ID, company_id, ENTITY_CUSTOMER)
    finally:
        db.close()
    return exc.value


# ── (1) a 504 from the proxy names itself ────────────────────────────────────


def test_a_504_dry_run_surfaces_the_status_and_the_body_beside_the_generic_sentence(
    session_factory, rig, consumer
):
    consumer.responder = lambda _body: httpx.Response(504, text=HTML_504)
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert GENERIC in exc.message
    assert "HTTP 504" in exc.message
    assert "Gateway Time-out" in exc.message
    assert exc.status_code == 504
    # Whitespace-collapsed, one line: the CRLF-laden nginx page never breaks
    # the message into lines.
    assert "\r" not in exc.message
    assert exc.message.count("\n") <= 1


# ── (2) a 422 names the rejected input ───────────────────────────────────────


def test_a_422_dry_run_surfaces_the_status_and_the_validation_message(
    session_factory, rig, consumer
):
    consumer.responder = lambda _body: httpx.Response(422, json=BODY_422)
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert GENERIC in exc.message
    assert "422" in exc.message
    assert "Extra inputs" in exc.message
    assert exc.status_code == 422


# ── the body snippet is bounded ──────────────────────────────────────────────


def test_the_consumer_body_is_capped_at_300_characters(session_factory, rig, consumer):
    long_body = "x" * 2000
    consumer.responder = lambda _body: httpx.Response(502, text=long_body)
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert "HTTP 502" in exc.message
    assert "x" * 300 in exc.message
    assert "x" * 301 not in exc.message


# ── (3) the route carries it in the 502 detail ───────────────────────────────


def test_the_preview_route_502_detail_carries_the_consumer_line(client, rig, consumer):
    consumer.responder = lambda _body: httpx.Response(504, text=HTML_504)
    company_id, _sql_id = rig

    response = client.post(_url(company_id, "/preview"), headers=_auth(client))

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert GENERIC in detail
    assert "HTTP 504" in detail
    assert "Gateway Time-out" in detail
    # No full URL leaks through the detail.
    assert "://" not in detail


# ── (4) the API key never reaches the message ────────────────────────────────


def test_the_api_key_is_never_part_of_the_message_even_when_the_sink_error_carried_it(
    session_factory, rig, monkeypatch
):
    """Build the message from status + body only: a sink error string that
    happens to embed the connection's key (a logged header, a URL with the
    key in it) must not reach the operator surface."""
    import modules.autocount.services.company_service as company_module

    secret = "sk_live_SECRET_DO_NOT_LEAK_123"
    company_id, _sql_id = rig

    db = session_factory()
    company = db.get(AcCompany, company_id)
    sorento = db.get(Connection, company.sink_connection_id)
    sorento.credentials_json = encrypt_secret({"apiKey": secret})
    db.commit()
    db.close()

    class _LeakySink:
        name = "sorento"

        def __init__(self, api_key: str) -> None:
            self._api_key = api_key

        def dry_run(self, records):
            raise SorentoSinkError(
                f"Sorento returned HTTP 500 for ingest/customers: "
                f"X-API-Key {self._api_key} rejected"
            )

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return _LeakySink(credentials["apiKey"])

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)

    exc = _preview(session_factory, company_id)

    assert "HTTP 500" in exc.message
    assert secret not in exc.message
    assert secret not in str(exc)


# ── a transport fault names the exception, not a fixed sentence ─────────────


def test_an_unreachable_consumer_names_the_transport_fault(session_factory, rig, consumer):
    def _boom(_body):
        raise httpx.ConnectError("no route to host")

    consumer.responder = _boom
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert GENERIC in exc.message
    assert "unreachable" in exc.message.lower()
    assert "ConnectError" in exc.message
    assert exc.status_code is None
