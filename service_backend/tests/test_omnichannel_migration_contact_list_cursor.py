"""Lane SS-MIGRATION-CURSOR - respond.io list pagination must send the
documented ``cursorId``. After #187 went live the owner's MyFuji dry run
processed 99/796 contacts, then failed with 'respond.io error: Invalid
cursorId': page 1 worked, the page 2 cursor was wrong.

Official contract (developers.respond.io, API v2, every list endpoint):
query ``cursorId`` ("Pointer to the contact id from where the next batch of
records should start from.") + ``limit``; response
``{items, pagination: {next, previous}}`` where ``next`` is a FULL URL that
carries the cursor in its own ``cursorId`` query parameter, e.g.
``https://api.respond.io/contact/list?limit=10&cursorId=-10`` (contact list),
``https://api.respond.io/contact/{identifier}/message/list?limit=10&cursorId=10``
(message list), ``https://api.respond.io/space/contact_field?limit=10&cursorId=10``
(custom fields). Doc pages: ``docs/api/0759d02787ab3-list-the-contacts``,
``docs/api/m4ay6be8n8ckc-list-messages``, ``docs/api/96d00b7396970-list-users``,
``docs/api/172e05dbb955d-list-custom-fields``, ``docs/api/57c6923fef9e9-list-channels``.

The vendor below is STRICT: every page answers ``next`` in the documented
full-URL form, and any request whose ``cursorId`` is not exactly the one the
PREVIOUS page of that list issued is the live 400 'Invalid cursorId'. So a
walk only reaches page 2 when the client sends the documented cursor.
"""
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE

from modules.omnichannel.respondio.client import RespondIoClient, RespondIoError
from modules.omnichannel.services.migration_service import run_migration_job

from tests.test_omnichannel_migration_sync_support import (
    SOURCE_CHANNEL,
    SYNCS,
    close_all_worlds,
    make_due,
    new_world,
    run_due_syncs,
    start_sync,
)
from tests.test_omnichannel_respondio_migration_jobs import _auth, _stub_client
from tests.test_omnichannel_respondio_migration_s3 import _make_full_job

INVALID_CURSOR = {"code": 400, "message": "Invalid cursorId"}
BASE = "https://api.respond.io/v2"


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


def _is_list(method: str, path: str) -> bool:
    return (
        (method == "POST" and path.endswith("/contact/list"))
        or path.endswith("/message/list")
        or path.endswith("/space/channel")
        or path.endswith("/space/user")
        or path.endswith("/space/custom_field")
        or (path.startswith("/v2/contact/") and path.endswith("/channels"))
    )


def _cursor_of(path: str, row: Dict[str, Any]) -> str:
    # "Pointer to the contact id / message id from where the next batch of
    # records should start from" - the last row's own id, as issued.
    key = "messageId" if path.endswith("/message/list") else "id"
    return str(row[key])


def _next_url(path: str, limit: int, cursor: str) -> str:
    # The documented examples carry no /v2 prefix, and the custom-field list
    # names /space/contact_field: the client must only take `cursorId` out of
    # this URL, never request it.
    shown = path[len("/v2"):] if path.startswith("/v2") else path
    shown = shown.replace("/space/custom_field", "/space/contact_field")
    return f"https://api.respond.io{shown}?{urlencode({'limit': limit, 'cursorId': cursor})}"


class StrictPaging:
    """Pages any list answer of ``source`` (a handler that returns every row in
    one ``{items}`` envelope) the documented way, and rejects any cursor the
    previous page of that list did not issue. Non-list calls pass through."""

    def __init__(self, source, *, last_page: str = "null") -> None:
        self.source = source
        self.last_page = last_page
        self.issued: Dict[str, tuple] = {}  # path -> (cursor, offset)
        self.requests: List[tuple] = []  # (path, cursorId-or-None)
        self.rejected: List[tuple] = []

    def preissue(self, path: str, cursor: str, offset: int) -> None:
        self.issued[path] = (cursor, offset)

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if not _is_list(request.method, path):
            return self.source(request)
        cursor = request.url.params.get("cursorId")
        self.requests.append((path, cursor))
        if cursor is None:
            offset = 0
        else:
            expected = self.issued.get(path)
            if expected is None or cursor != expected[0]:
                self.rejected.append((path, cursor))
                return httpx.Response(400, json=INVALID_CURSOR)
            offset = expected[1]
        upstream = self.source(request)
        if upstream.status_code != 200:
            return upstream
        rows = upstream.json().get("items") or []
        limit = int(request.url.params.get("limit", "10"))
        page = rows[offset:offset + limit]
        pagination: Dict[str, Any] = {"previous": None}
        if offset + limit < len(rows):
            nxt = _cursor_of(path, page[-1])
            self.issued[path] = (nxt, offset + limit)
            pagination["next"] = _next_url(path, limit, nxt)
        else:
            self.issued.pop(path, None)
            if self.last_page == "null":
                pagination["next"] = None
            elif self.last_page == "empty":
                pagination["next"] = ""
            # "missing": no `next` key at all
        return httpx.Response(200, json={"items": page, "pagination": pagination})


def _rows(n: int, start: int = 900001) -> List[Dict[str, Any]]:
    return [{"id": start + i, "firstName": f"C{i}"} for i in range(n)]


def _source_from(rows_by_path: Dict[str, List[Dict[str, Any]]]):
    def source(request: httpx.Request) -> httpx.Response:
        for suffix, rows in rows_by_path.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json={"items": list(rows), "pagination": {"next": None}})
        return httpx.Response(404, json={"code": 404, "message": "unknown route"})

    return source


def _client(handler, blockers: Optional[list] = None) -> RespondIoClient:
    sink = blockers if blockers is not None else []
    return RespondIoClient(
        api_token="t", client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _s: None, on_blocker=sink.append,
    )


# ── the client: every paginated call follows the documented cursor ─────────


def test_contact_list_pages_walk_every_page_with_the_cursor_from_pagination_next():
    rows = _rows(250)
    vendor = StrictPaging(_source_from({"/contact/list": rows}))
    blockers: list = []
    pages = list(_client(vendor, blockers).list_contacts_pages(timezone="Asia/Kuala_Lumpur"))

    assert vendor.rejected == []
    assert [len(items) for items, _c in pages] == [99, 99, 52]
    assert [r["id"] for items, _c in pages for r in items] == [r["id"] for r in rows]
    # The checkpointed cursor is the bare vendor cursor, never the URL.
    assert [c for _i, c in pages] == [str(rows[98]["id"]), str(rows[197]["id"]), None]
    assert [c for _p, c in vendor.requests] == [None, str(rows[98]["id"]), str(rows[197]["id"])]
    assert blockers == []


def test_preflight_contact_list_reads_past_page_one():
    rows = _rows(130)
    vendor = StrictPaging(_source_from({"/contact/list": rows}))
    got = list(_client(vendor).list_contacts(timezone="Asia/Kuala_Lumpur"))
    assert vendor.rejected == []
    assert [r["id"] for r in got] == [r["id"] for r in rows]


def test_message_list_walks_every_page_with_the_message_cursor():
    msgs = [{"messageId": 7000 + i, "message": {"type": "text", "text": str(i)}} for i in range(120)]
    vendor = StrictPaging(_source_from({"/message/list": msgs}))
    pages = list(_client(vendor).list_messages_pages("id:42"))
    assert vendor.rejected == []
    assert [len(items) for items, _c in pages] == [50, 50, 20]
    assert [c for _p, c in vendor.requests] == [None, "7049", "7099"]


@pytest.mark.parametrize("method_name, suffix", [
    ("list_space_channels", "/space/channel"),
    ("list_space_users", "/space/user"),
    ("list_custom_fields", "/space/custom_field"),
])
def test_space_reads_walk_every_page(method_name, suffix):
    rows = _rows(150, start=1)
    vendor = StrictPaging(_source_from({suffix: rows}))
    got = getattr(_client(vendor), method_name)()
    assert vendor.rejected == []
    assert [r["id"] for r in got] == [r["id"] for r in rows]


@pytest.mark.parametrize("n_channels, pages", [(25, [25]), (150, [99, 51])])
def test_contact_channels_read_every_page(n_channels, pages):
    """`GET /contact/{identifier}/channels` is paginated too
    (docs/api/a17bccb520d2e-list-contact-channels: `limit` default 10,
    `pagination.next` =
    `https://api.respond.io/contact/{identifier}/channels?limit=10&cursorId=10`).
    Reading only the first page drops every channel past the vendor's
    default 10, so the contact's identities are silently incomplete."""
    rows = _rows(n_channels, start=500)
    vendor = StrictPaging(_source_from({"/channels": rows}))
    got = _client(vendor).get_contact_channels("id:42")
    assert vendor.rejected == []
    assert [r["id"] for r in got] == [r["id"] for r in rows]
    assert len(vendor.requests) == len(pages)


@pytest.mark.parametrize("last_page", ["null", "missing", "empty"])
def test_last_page_stops_cleanly_whatever_the_end_signal(last_page):
    rows = _rows(120)
    vendor = StrictPaging(_source_from({"/contact/list": rows}), last_page=last_page)
    blockers: list = []
    pages = list(_client(vendor, blockers).list_contacts_pages(timezone="Asia/Kuala_Lumpur"))
    assert [len(items) for items, _c in pages] == [99, 21]
    assert pages[-1][1] is None
    assert len(vendor.requests) == 2
    assert blockers == []


def test_resume_from_a_checkpoint_that_stored_the_full_next_url():
    """A job checkpointed before this fix stored `pagination.next` (the URL)
    as its cursor; the prod dry run that failed did exactly that. Resuming
    it must send the bare cursor, not the URL."""
    rows = _rows(250)
    vendor = StrictPaging(_source_from({"/contact/list": rows}))
    cursor = str(rows[98]["id"])
    vendor.preissue("/v2/contact/list", cursor, 99)
    stored = _next_url("/v2/contact/list", 99, cursor)

    pages = list(_client(vendor).list_contacts_pages(timezone="Asia/Kuala_Lumpur", start_cursor=stored))
    assert vendor.rejected == []
    assert vendor.requests[0] == ("/v2/contact/list", cursor)
    assert [len(items) for items, _c in pages] == [99, 52]


def test_a_next_url_without_a_cursor_id_stops_with_a_blocker():
    """A `next` URL we cannot take a cursor from is never sent back as a
    cursor; the walk stops and says why (a blocker on the report)."""
    def source(_request):
        return httpx.Response(200, json={
            "items": _rows(3), "pagination": {"next": "https://api.respond.io/contact/list?limit=99"},
        })

    blockers: list = []
    seen: list = []

    def handler(request):
        seen.append(request.url.params.get("cursorId"))
        return source(request)

    pages = list(_client(handler, blockers).list_contacts_pages(timezone="Asia/Kuala_Lumpur"))
    assert seen == [None]
    assert [c for _i, c in pages] == [None]
    assert len(blockers) == 1 and "cursor" in blockers[0].lower()


def test_strict_vendor_rejects_a_cursor_it_did_not_issue():
    """Guard on the mock itself: a made-up cursor is the live 400."""
    vendor = StrictPaging(_source_from({"/contact/list": _rows(5)}))
    with pytest.raises(RespondIoError) as exc:
        list(_client(vendor).list_contacts_pages(timezone="Asia/Kuala_Lumpur", start_cursor="12345"))
    assert exc.value.message == "Invalid cursorId"


# ── call site 1: the migration job, dry run and run, more than one page ────


def _seed_world(w, n_contacts: int, messages_for_first: int = 0):
    base = 910000
    for i in range(n_contacts):
        w.fake.add_contact(base + i, first=f"P{i}")
    for m in range(messages_for_first):
        w.fake.add_message(base, m + 1, text=f"m{m}")
    return base


@pytest.mark.parametrize("mode", ["dry_run", "run"])
def test_migration_job_walks_every_contact_page(session_factory, monkeypatch, mode):
    w = new_world(session_factory, monkeypatch)
    base = _seed_world(w, 230, messages_for_first=120)
    vendor = StrictPaging(w.fake.handler)
    _stub_client(monkeypatch, vendor)

    job = _make_full_job(
        w.db, DEFAULT_TENANT_ID, connection_id=w.conn.id, workspace_id=w.ws.id, mode=mode,
        channel_map=[{"sourceChannelId": str(SOURCE_CHANNEL), "targetChannelId": w.channel.id}],
    )
    run_migration_job(w.db, job)
    w.db.refresh(job)

    assert vendor.rejected == []
    assert job.status == JOB_DONE, job.error
    report = job.result_json["report"]
    assert report["entities"]["contacts"]["fetched"] == 230
    assert not [b for b in report.get("blockers") or [] if "cursor" in b.lower()]
    contact_cursors = [c for p, c in vendor.requests if p.endswith("/contact/list")]
    assert contact_cursors == [None, str(base + 98), str(base + 197)]
    msg_cursors = [c for p, c in vendor.requests if p.endswith(f"/contact/id:{base}/message/list")]
    assert len(msg_cursors) == 3 and msg_cursors[0] is None
    if mode == "run":
        assert w.contact_by_cid(base + 229) is not None, "the last contact (page 3) was migrated"
        assert len(w.messages_of(w.contact_by_cid(base))) == 120


# ── call site 2: the continuous sync tick walks past page one ──────────────


def test_sync_tick_walks_every_contact_page(client, session_factory, monkeypatch):
    w = new_world(session_factory, monkeypatch)
    base = _seed_world(w, 150)
    vendor = StrictPaging(w.fake.handler)
    _stub_client(monkeypatch, vendor)
    w.run_migration(channel_target="mapped")
    w.db.commit()
    h = _auth(client)
    sid = start_sync(client, w.ws.id, h)["id"]
    vendor.requests.clear()

    late = base + 150
    w.fake.add_contact(late, first="Late")
    w.fake.add_message(late, 1, text="after migration")
    make_due(w.db, sid, full_sweep="due")
    run_due_syncs(w.db)
    res = client.post(f"{SYNCS}/{sid}/stop", headers=h)
    assert res.status_code == 200, res.text
    run_due_syncs(w.db)

    assert vendor.rejected == []
    assert w.contact_by_cid(late) is not None, "the tick reached page 2 and created the new contact"
    contact_cursors = [c for p, c in vendor.requests if p.endswith("/contact/list")]
    assert contact_cursors.count(str(base + 98)) >= 2, "the poll and the final tick both read page 2"
