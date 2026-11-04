"""Lane SS-MIGRATION-FILTER-HOTFIX - respond.io's ``POST /contact/list``
REQUIRES a ``filter`` object in the body. Without it the vendor answers 400
"Sorry, there are errors in the request. Please check if filter is provided."
and the whole migration job failed with 0 processed (live dry run, every
channel on "Skip for now").

Lane SS-MIGRATION-SEARCH-HOTFIX - once the filter shipped, the vendor rejected
the body again: "Please check if search exists, but value can be empty." The
body must carry ``search`` (empty string OK) as well.

The mock below is STRICT: it rejects a body with no ``search`` string or no
``filter`` object exactly like the live API, so the dry run / run (all
channels skipped, or some) only pass when the client sends the full body.
"""
import json

import httpx

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.models import Contact
from modules.omnichannel.respondio.client import RespondIoClient, RespondIoError
from modules.omnichannel.services.migration_service import run_migration_job, _respondio_job_error

from tests.test_omnichannel_respondio_migration_jobs import (
    _default_workspace,
    _make_connection,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import (
    _make_channel,
    _make_full_job,
    _pages_handler_full,
)

LIVE_FILTER_MESSAGE = "Sorry, there are errors in the request. Please check if filter is provided."
# Lane SS-MIGRATION-SEARCH-HOTFIX: after the filter fix went live the vendor
# rejected the body again, this time for the missing `search` key.
LIVE_SEARCH_MESSAGE = "Sorry, there are errors in the request. Please check if search exists, but value can be empty."


def _strict(inner):
    """Wrap a handler: `POST /contact/list` without a `search` string or a
    `filter` object is a 400 with respond.io's own body, before the inner
    handler ever runs."""
    bodies = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/list"):
            body = json.loads(request.content or b"{}")
            bodies.append(body)
            if not isinstance(body.get("search"), str):
                return httpx.Response(400, json={"code": 400, "message": LIVE_SEARCH_MESSAGE})
            flt = body.get("filter")
            if not isinstance(flt, dict) or not any(isinstance(flt.get(k), list) for k in ("$and", "$or")):
                return httpx.Response(400, json={"code": 400, "message": LIVE_FILTER_MESSAGE})
        return inner(request)

    handler.bodies = bodies
    return handler


def _two_channel_contact_handler():
    contact_row = {"id": 980001, "firstName": "Skip", "lastName": "All", "phone": "+15558880000"}
    channels_by_contact = {
        "id:980001": [{"id": 701, "name": "WA", "source": "whatsapp", "meta": {"phone": "+15558880000"}}],
    }
    messages_by_contact = {
        "id:980001": {
            None: (
                [
                    {"messageId": 11, "traffic": "incoming", "channelId": 701,
                     "message": {"type": "text", "text": "hello"}},
                    {"messageId": 12, "traffic": "incoming", "channelId": 702,
                     "message": {"type": "text", "text": "other"}},
                ],
                None,
            )
        }
    }
    return _strict(
        _pages_handler_full(
            {None: ([contact_row], None)},
            channels_by_contact=channels_by_contact,
            messages_by_contact=messages_by_contact,
        )
    )


def test_client_always_sends_the_full_contact_list_body():
    handler = _strict(lambda r: httpx.Response(200, json={"items": [], "pagination": {"next": None}}))
    client = RespondIoClient(
        api_token="t", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )
    assert list(client.list_contacts(timezone="Asia/Kuala_Lumpur")) == []
    assert [items for items, _c in client.list_contacts_pages(timezone="Asia/Kuala_Lumpur")] == [[]]
    # Exact body for BOTH call sites: search present (empty string), match-all
    # filter, timezone. limit/cursorId ride the query string, never the body.
    expected = {"search": "", "filter": {"$and": []}, "timezone": "Asia/Kuala_Lumpur"}
    assert handler.bodies[0] == expected
    assert handler.bodies[1] == expected
    # An explicit caller filter still wins.
    custom = {"$and": [{"category": "contactField", "field": "phone", "operator": "isNotEmpty"}]}
    list(client.list_contacts(timezone="UTC", filter_=custom))
    assert handler.bodies[-1] == {"search": "", "filter": custom, "timezone": "UTC"}
    # An explicit caller search is sent verbatim.
    list(client.list_contacts_pages(timezone="UTC", search="needle"))
    assert handler.bodies[-1] == {"search": "needle", "filter": {"$and": []}, "timezone": "UTC"}


def test_contact_list_query_carries_limit_and_cursor_not_body():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((dict(request.url.params), json.loads(request.content or b"{}")))
        return httpx.Response(200, json={"items": [], "pagination": {"next": None}})

    client = RespondIoClient(
        api_token="t", client=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda _s: None
    )
    list(client.list_contacts_pages(timezone="UTC", limit=50, start_cursor="123"))
    params, body = seen[0]
    assert params == {"limit": "50", "cursorId": "123"}
    assert set(body) == {"search", "filter", "timezone"}


def _run(db, ws, conn, *, mode, channel_map):
    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode=mode, channel_map=channel_map,
    )
    run_migration_job(db, job)
    db.refresh(job)
    return job


def test_dry_run_and_run_with_every_channel_skipped_import_contacts_and_history(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    handler = _two_channel_contact_handler()
    _stub_client(monkeypatch, handler)
    skip_all = [
        {"sourceChannelId": "701", "targetChannelId": None},
        {"sourceChannelId": "702", "targetChannelId": None},
    ]

    dry = _run(db, ws, conn, mode="dry_run", channel_map=skip_all)
    assert dry.status == "done", dry.error
    assert dry.result_json["report"]["entities"]["contacts"]["fetched"] == 1

    run = _run(db, ws, conn, mode="run", channel_map=skip_all)
    assert run.status == "done", run.error
    contact = db.query(Contact).filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15558880000").first()
    assert contact is not None
    assert handler.bodies and all(
        b.get("filter") == {"$and": []} and b.get("search") == "" for b in handler.bodies
    )
    db.close()


def test_dry_run_with_some_channels_skipped(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    wa = _make_channel(db, DEFAULT_TENANT_ID, ws.id, channel_type="WHATSAPP")
    db.commit()
    _stub_client(monkeypatch, _two_channel_contact_handler())
    some_skipped = [
        {"sourceChannelId": "701", "targetChannelId": wa.id},
        {"sourceChannelId": "702", "targetChannelId": None},
    ]
    dry = _run(db, ws, conn, mode="dry_run", channel_map=some_skipped)
    assert dry.status == "done", dry.error
    assert dry.result_json["report"]["entities"]["contacts"]["fetched"] == 1
    db.close()


def test_filter_error_maps_to_a_clear_job_error():
    exc = RespondIoError(LIVE_FILTER_MESSAGE, status_code=400, code=400)
    text = _respondio_job_error(exc)
    assert "contact list request" in text
    assert LIVE_FILTER_MESSAGE in text
    search = _respondio_job_error(RespondIoError(LIVE_SEARCH_MESSAGE, status_code=400, code=400))
    assert "contact list request" in search
    assert LIVE_SEARCH_MESSAGE in search
    other = RespondIoError("Unauthorized", status_code=401)
    assert _respondio_job_error(other) == "respond.io error: Unauthorized"
