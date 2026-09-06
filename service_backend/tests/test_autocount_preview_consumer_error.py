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


# ═══════════════════════════════════════════════════════════════════════════
#  Review round 1 (73814855)
# ═══════════════════════════════════════════════════════════════════════════

import logging  # noqa: E402

from modules.autocount.services.sync_service import PreviewFailed, SyncService  # noqa: E402
from tests.test_autocount_pipeline import (  # noqa: E402,F401 - fixtures re-exported
    _company as _api_company,
    _point_at_sorento,
    _sorento_connection,
    _staged_supplier_job,
    db,
    sorento_sink,
    transports,
)
from tests.test_autocount_pipeline import _auth as _pipeline_auth  # noqa: E402

UNKNOWN_ENTITY_404 = {"code": "UNKNOWN_ENTITY", "message": "No such entity 'customers'."}
URL_BODY = {"detail": "see https://sorento.example/api/v1/external/ingest for the schema"}


# ── (1) a typed sink error with an HTTP answer is "Consumer said", never "unreachable"


def test_a_rate_limited_dry_run_is_consumer_said_http_429(session_factory, rig, consumer, monkeypatch):
    monkeypatch.setattr("modules.autocount.sinks_sorento.time.sleep", lambda *_: None)
    consumer.responder = lambda _body: httpx.Response(
        429, headers={"Retry-After": "3"}, json={"code": "rate_limited"}
    )
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert "Consumer said: HTTP 429" in exc.message
    assert exc.status_code == 429
    assert "unreachable" not in exc.message.lower()


def test_an_unknown_entity_dry_run_is_consumer_said_http_404(session_factory, rig, consumer):
    consumer.responder = lambda _body: httpx.Response(404, json=UNKNOWN_ENTITY_404)
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert "Consumer said: HTTP 404" in exc.message
    assert exc.status_code == 404
    assert "unreachable" not in exc.message.lower()


# ── (2) a URL in the consumer body is scrubbed, not echoed ──────────────────


def test_a_url_in_the_consumer_body_is_scrubbed_from_message_and_route_detail(
    client, session_factory, rig, consumer
):
    consumer.responder = lambda _body: httpx.Response(500, json=URL_BODY)
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)
    assert "HTTP 500" in exc.message
    assert "[url]" in exc.message
    assert "://" not in exc.message
    assert "sorento.example" not in exc.message

    response = client.post(_url(company_id, "/preview"), headers=_auth(client))
    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "[url]" in detail
    assert "://" not in detail


# ── (3) key redaction through the REAL sink + MockTransport, message AND log ─


def test_the_real_sinks_key_is_redacted_from_message_and_warning_log(
    session_factory, rig, monkeypatch, caplog
):
    import modules.autocount.services.company_service as company_module
    from modules.autocount.sinks_sorento import sorento_sink_from_connection as real

    secret = "sk_live_SECRET_DO_NOT_LEAK_456"
    company_id, _sql_id = rig

    db_ = session_factory()
    company = db_.get(AcCompany, company_id)
    sorento = db_.get(Connection, company.sink_connection_id)
    sorento.credentials_json = encrypt_secret({"apiKey": secret})
    db_.commit()
    db_.close()

    def echo_key(request: httpx.Request) -> httpx.Response:
        # A misbehaving consumer that echoes the caller's own header back.
        return httpx.Response(
            500, json={"message": f"rejected key {request.headers.get('X-API-Key')}"}
        )

    def fake(config, credentials, *, entity_type, company_code=None, transport=None):
        return real(
            config, credentials, entity_type=entity_type, company_code=company_code,
            transport=httpx.MockTransport(echo_key),
        )

    monkeypatch.setattr(company_module, "sorento_sink_from_connection", fake)

    with caplog.at_level(logging.WARNING, logger="foundryx.autocount"):
        exc = _preview(session_factory, company_id)

    assert "HTTP 500" in exc.message
    assert "rejected key" in exc.message
    assert secret not in exc.message
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING and "preview" in r.getMessage()]
    assert warnings, "preview_task must log the failed dry run at WARNING"
    assert all(secret not in r.getMessage() for r in warnings)
    assert any(company_id in r.getMessage() and "500" in r.getMessage() for r in warnings)


# ── (4) a 1-char key is never substituted inside unrelated words ────────────


def test_a_one_character_key_does_not_redact_letters_inside_words(session_factory, rig, consumer):
    """The rig's connection key is the single letter ``k``: a naive
    ``replace(api_key, ...)`` would mangle every word containing a ``k``."""
    consumer.responder = lambda _body: httpx.Response(
        500, json={"message": "SorentoSinkError: kaput, back off"}
    )
    company_id, _sql_id = rig

    exc = _preview(session_factory, company_id)

    assert "HTTP 500" in exc.message
    assert "SorentoSinkError" in exc.message
    assert "kaput, back off" in exc.message
    assert "[redacted]" not in exc.message


# ── (5) the approve gate's dry run carries the same consumer line ───────────


def test_the_approve_gate_preview_carries_the_consumer_line(db, transports, sorento_sink):
    company = _api_company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1",))
    sorento_sink.responder = lambda _request: httpx.Response(504, text=HTML_504)

    with pytest.raises(PreviewFailed) as exc:
        SyncService(db).preview(DEFAULT_TENANT_ID, job.id)

    assert "The dry run against the consumer failed" in exc.value.message
    assert "Consumer said: HTTP 504" in exc.value.message
    assert "Gateway Time-out" in exc.value.message
    assert "\r" not in exc.value.message


def test_the_approve_gate_preview_route_502_detail_carries_http_504(
    client, db, transports, sorento_sink
):
    company = _api_company(db, transports)
    _point_at_sorento(db, company, _sorento_connection(db))
    job = _staged_supplier_job(db, company, refs=("AED_VSOFT:1",))
    sorento_sink.responder = lambda _request: httpx.Response(504, text=HTML_504)

    response = client.post(f"/autocount/jobs/{job.id}/preview", headers=_pipeline_auth(client))

    assert response.status_code == 502, response.text
    detail = response.json()["detail"]
    assert "HTTP 504" in detail
    assert "Gateway Time-out" in detail
    assert "://" not in detail
