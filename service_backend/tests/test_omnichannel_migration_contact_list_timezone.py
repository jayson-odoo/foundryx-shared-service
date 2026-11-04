"""Lane SS-MIGRATION-TZ-HOTFIX - respond.io's ``POST /contact/list`` rejects a
body whose ``timezone`` is not an IANA name. After #182 (filter) and #184
(search) went live, the owner's dry run failed with the vendor's 400:
'Please check if timezone is a valid IANA timezone name, such as
"Asia/Kuala_Lumpur".' The timezone came straight from the free-text
"Workspace timezone" connection field, so whatever was typed (``GMT+8``,
``+08:00``, blank, ...) went to the vendor as is.

Official contract (https://developers.respond.io/docs/api/0759d02787ab3-list-the-contacts):
body ``{search, filter, timezone}`` - every official example is
``{"search": "", "filter": {"$and": []}, "timezone": "Asia/Kuala_Lumpur"}``;
query ``limit`` integer ``minimum: 1, exclusiveMaximum: 100`` plus
``cursorId``. The message list (``GET /contact/{id}/message/list``)
documents ``limit`` ``maximum: 50``.

The mock below is STRICT: it answers the live 400 for a non-IANA timezone and
a 400 for a page size outside the documented range, so the job and the sync
tick only pass when the client sends the documented request.
"""
import json
import re
from zoneinfo import available_timezones

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.respondio.client import RespondIoClient
from modules.omnichannel.services.migration_service import run_migration_job

from tests.test_omnichannel_migration_sync_support import (
    SYNCS,
    close_all_worlds,
    make_due,
    new_world,
    run_due_syncs,
    start_sync,
)
from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _default_workspace,
    _make_connection,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import _make_full_job, _pages_handler_full

LIVE_TIMEZONE_MESSAGE = (
    'Sorry, there are errors in your request. Please check if timezone is a valid IANA '
    'timezone name, such as "Asia/Kuala_Lumpur".'
)
FALLBACK = "Asia/Kuala_Lumpur"
EXPECTED_BODY = {"search": "", "filter": {"$and": []}, "timezone": FALLBACK}
_IANA = available_timezones()
_OFFSET = re.compile(r"[+-]\d")

# Stored connection timezones the vendor rejects - each must be replaced by
# the fallback, never sent.
BAD_TIMEZONES = ["GMT+8", "+08:00", "UTC+8", "UTC+08:00", "Etc/GMT-8", "", "   ", "Malaysia", "Asia/Nowhere",
                 "../etc/passwd", None, 8]


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


def _strict(inner):
    """Wrap a handler: a contact-list body whose timezone is not an IANA name
    is the live 400; a page size outside the documented range is a 400. Every
    contact-list (query, body) and message-list query is recorded."""
    seen = {"contact_list": [], "message_list": []}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        params = dict(request.url.params)
        if request.method == "POST" and path.endswith("/contact/list"):
            body = json.loads(request.content or b"null")
            seen["contact_list"].append((params, body))
            tz = body.get("timezone") if isinstance(body, dict) else None
            if not isinstance(tz, str) or tz not in _IANA or _OFFSET.search(tz):
                return httpx.Response(400, json={"code": 400, "message": LIVE_TIMEZONE_MESSAGE})
            if not 1 <= int(params.get("limit", "10")) < 100:
                return httpx.Response(400, json={"code": 400, "message": "limit out of range"})
        if path.endswith("/message/list"):
            seen["message_list"].append(params)
            if not 1 <= int(params.get("limit", "10")) <= 50:
                return httpx.Response(400, json={"code": 400, "message": "limit out of range"})
        return inner(request)

    handler.seen = seen
    return handler


def _empty_page(_request):
    return httpx.Response(200, json={"items": [], "pagination": {"next": None}})


def _client(handler):
    return RespondIoClient(
        api_token="t", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )


# ── client: the exact documented request ───────────────────────────────────


@pytest.mark.parametrize("stored", BAD_TIMEZONES)
def test_bad_stored_timezone_is_sent_as_asia_kuala_lumpur(stored):
    handler = _strict(_empty_page)
    client = _client(handler)
    assert list(client.list_contacts(timezone=stored)) == []
    assert [items for items, _c in client.list_contacts_pages(timezone=stored)] == [[]]
    bodies = [body for _params, body in handler.seen["contact_list"]]
    assert bodies == [EXPECTED_BODY, EXPECTED_BODY]


@pytest.mark.parametrize(
    "stored, sent",
    [
        ("Asia/Kuala_Lumpur", "Asia/Kuala_Lumpur"),
        ("  Asia/Singapore  ", "Asia/Singapore"),
        ("asia/kuala_lumpur", "Asia/Kuala_Lumpur"),
        ("America/Port-au-Prince", "America/Port-au-Prince"),
        ("UTC", "UTC"),
    ],
)
def test_valid_iana_timezone_is_sent_in_canonical_form(stored, sent):
    handler = _strict(_empty_page)
    list(_client(handler).list_contacts(timezone=stored))
    assert handler.seen["contact_list"][0][1] == {"search": "", "filter": {"$and": []}, "timezone": sent}


def test_contact_list_query_is_the_documented_limit_and_cursor():
    handler = _strict(_empty_page)
    client = _client(handler)
    list(client.list_contacts(timezone="GMT+8"))
    list(client.list_contacts_pages(timezone="GMT+8", limit=100, start_cursor="123"))
    list(client.list_contacts_pages(timezone="GMT+8", limit=50))
    params = [p for p, _b in handler.seen["contact_list"]]
    # limit: minimum 1, exclusiveMaximum 100 -> the default and an oversized
    # request both become 99; a smaller caller value is kept.
    assert params == [{"limit": "99"}, {"limit": "99", "cursorId": "123"}, {"limit": "50"}]


def test_message_list_query_never_exceeds_the_documented_50():
    handler = _strict(_empty_page)
    client = _client(handler)
    list(client.list_messages_pages("id:1"))
    list(client.list_messages_pages("id:1", limit=100, start_cursor="9"))
    assert handler.seen["message_list"] == [{"limit": "50"}, {"limit": "50", "cursorId": "9"}]


# ── call site 1: the migration job (dry run + run) ──────────────────────────


def _job_handler():
    contact_row = {"id": 990001, "firstName": "Tz", "lastName": "Case", "phone": "+15557770000"}
    return _strict(
        _pages_handler_full(
            {None: ([contact_row], None)},
            channels_by_contact={
                "id:990001": [{"id": 701, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15557770000"}}],
            },
            messages_by_contact={
                "id:990001": {
                    None: ([{"messageId": 21, "traffic": "incoming", "channelId": 701,
                             "message": {"type": "text", "text": "hello"}}], None)
                }
            },
        )
    )


@pytest.mark.parametrize("stored", ["GMT+8", "+08:00", ""])
def test_migration_job_with_a_bad_stored_timezone_sends_the_documented_request(session_factory, monkeypatch, stored):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID, timezone=stored)
    db.commit()
    handler = _job_handler()
    _stub_client(monkeypatch, handler)
    skip_all = [{"sourceChannelId": "701", "targetChannelId": None}]

    for mode in ("dry_run", "run"):
        job = _make_full_job(
            db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode=mode, channel_map=skip_all,
        )
        run_migration_job(db, job)
        db.refresh(job)
        assert job.status == "done", job.error
        assert job.result_json["report"]["entities"]["contacts"]["fetched"] == 1

    contact_calls = handler.seen["contact_list"]
    assert len(contact_calls) >= 2, "the dry run and the run both walk the contact list"
    for params, body in contact_calls:
        assert body == EXPECTED_BODY
        assert params == {"limit": "99"}
    assert handler.seen["message_list"], "the history phase read the message list"
    for params in handler.seen["message_list"]:
        assert params["limit"] == "50"


# ── call site 2: the continuous sync tick (poll, full sweep, final) ────────


def test_sync_tick_with_a_bad_stored_timezone_sends_the_documented_request(client, session_factory, monkeypatch):
    w = new_world(session_factory, monkeypatch)
    w.conn.config_json = {**w.conn.config_json, "timezone": "+08:00"}
    w.db.commit()
    handler = _strict(w.fake.handler)
    _stub_client(monkeypatch, handler)
    w.fake.add_contact(990101, first="Tz")
    w.fake.add_message(990101, 1, text="hello tz")
    w.run_migration(channel_target="mapped")
    w.db.commit()
    h = _auth(client)
    sid = start_sync(client, w.ws.id, h)["id"]
    handler.seen["contact_list"].clear()
    handler.seen["message_list"].clear()

    w.fake.add_contact(990102, first="New")
    w.fake.add_message(990102, 1, text="after migration")
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    res = client.post(f"{SYNCS}/{sid}/stop", headers=h)
    assert res.status_code == 200, res.text
    run_due_syncs(w.db)

    assert w.contact_by_phone("+601000990102") is not None, "the tick walked the list and created the new contact"
    contact_calls = handler.seen["contact_list"]
    assert len(contact_calls) >= 2, "the poll and the final tick both walk the contact list"
    for params, body in contact_calls:
        assert body == EXPECTED_BODY
        assert params == {"limit": "99"}
    for params in handler.seen["message_list"]:
        assert params["limit"] == "50"
