"""Plan 56 C - `messageCount` / `fileCount` on the STAFF contact reads (list + get), the numbers
the erase dialog shows. RED tests written BEFORE the implementation.

Rules: messageCount = every message of the contact incl. internal notes (the erase response's
`messages`); fileCount = media_key set, or a legacy LOCAL media_url (the erase response's `files`);
an external CDN url is not a file. Tenant scoped. One grouped query per page, not one per row.
The API-key contact routes keep their shape (no new fields).
"""
import sqlalchemy as sa

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import ConversationMessage
from tests.test_omnichannel_api_gateway import _auth
from tests.test_omnichannel_contact_erase import Rig, _contact, _env  # noqa: F401 - _env is autouse
import pytest


@pytest.fixture
def rig(client, session_factory):
    return Rig(client, session_factory)


def _list(client, rig, page_size=100):
    res = client.get(f"/omnichannel/workspaces/{rig.ws}/contacts?pageSize={page_size}", headers=_auth(client))
    assert res.status_code == 200, res.text
    return {c["id"]: c for c in res.json()["data"]}


def test_list_and_get_return_counts_that_match_the_seed_and_the_erase_response(client, rig):
    fp = rig.footprint("+60100000601", "c1")
    db = rig.sf()
    try:  # one external CDN link: a message, not a file
        db.add(ConversationMessage(tenant_id=DEFAULT_TENANT_ID, contact_id=fp["cid"], channel_id=rig.channel,
                                   sender_type="CONTACT", message_type="IMAGE",
                                   media_url="https://cdn.example.com/pic.png"))
        db.commit()
    finally:
        db.close()
    row = _list(client, rig)[fp["cid"]]
    assert row["messageCount"] == 7 and row["fileCount"] == 3
    one = client.get(f"/omnichannel/contacts/{fp['cid']}", headers=_auth(client))
    assert one.status_code == 200, one.text
    assert one.json()["messageCount"] == 7 and one.json()["fileCount"] == 3
    erased = rig.erase(fp["cid"]).json()
    assert (erased["messages"], erased["files"]) == (row["messageCount"], row["fileCount"])


def test_a_contact_with_no_messages_counts_zero_not_null(client, rig):
    cid = _contact(rig.sf, rig.ws, "+60100000602")
    row = _list(client, rig)[cid]
    assert row["messageCount"] == 0 and row["fileCount"] == 0


def test_counts_are_per_contact_and_never_include_another_tenants_rows(client, rig):
    a = rig.footprint("+60100000603", "c2")
    b = rig.footprint("+60100000604", "c3")
    db = rig.sf()
    try:  # a foreign tenant's message pointing at OUR contact id must not count
        db.add(ConversationMessage(tenant_id="other-tenant-erase", contact_id=a["cid"], channel_id=rig.channel,
                                   sender_type="CONTACT", message_type="IMAGE", media_key="foreign/file.png"))
        db.commit()
    finally:
        db.close()
    rows = _list(client, rig)
    assert (rows[a["cid"]]["messageCount"], rows[a["cid"]]["fileCount"]) == (6, 3)
    assert (rows[b["cid"]]["messageCount"], rows[b["cid"]]["fileCount"]) == (6, 3)
    one = client.get(f"/omnichannel/contacts/{a['cid']}", headers=_auth(client)).json()
    assert (one["messageCount"], one["fileCount"]) == (6, 3)


def _count_statements(sf, fn):
    engine = sf().get_bind()
    seen = []

    def hook(conn, cursor, statement, parameters, context, executemany):
        seen.append(statement)

    sa.event.listen(engine, "before_cursor_execute", hook)
    try:
        fn()
    finally:
        sa.event.remove(engine, "before_cursor_execute", hook)
    return len(seen)


def test_the_list_counts_with_the_same_number_of_statements_for_3_and_10_contacts(client, rig):
    cids = [rig.footprint(f"+6010000070{i}", f"p{i}")["cid"] for i in range(3)]
    run = lambda: _list(client, rig)  # noqa: E731
    first = run()
    assert all(first[c]["messageCount"] == 6 for c in cids)  # control: the fields exist and are filled
    n3 = _count_statements(rig.sf, run)
    for i in range(3, 10):
        rig.footprint(f"+6010000070{i}", f"p{i}")
    assert len(run()) == 10
    n10 = _count_statements(rig.sf, run)
    assert n10 == n3, f"statements grew with the page: {n3} -> {n10}"


def _window_statements(sf, fn):
    """(thread id, statement) for every statement the engine runs while `fn` runs."""
    import threading

    engine = sf().get_bind()
    seen = []

    def hook(conn, cursor, statement, parameters, context, executemany):
        seen.append((threading.get_ident(), " ".join(statement.split())))

    sa.event.listen(engine, "before_cursor_execute", hook)
    try:
        fn()
    finally:
        sa.event.remove(engine, "before_cursor_execute", hook)
    return seen


def test_the_measured_window_holds_only_the_list_request(client, rig):
    """The statement count must measure the list request alone: the login (throttle
    bookkeeping + the sign-in write) must not run inside the measured closure."""
    rig.footprint("+60100000710", "w0")
    run = lambda: _list(client, rig)  # noqa: E731 - the closure the 3-vs-10 test measures
    run()  # warm
    seen = _window_statements(rig.sf, run)
    offenders = [s[:120] for _, s in seen if "auth_throttle" in s or s.startswith("UPDATE users")]
    assert not offenders, f"login statements inside the measured window: {offenders}"
    threads = {t for t, _ in seen}
    assert len(threads) == 1, f"statements ran on {len(threads)} threads"


def test_api_key_contact_routes_keep_their_shape(client, rig):
    fp = rig.footprint("+60100000605", "c4")
    lst = client.get("/api/v1/omnichannel/contacts", headers=rig.hdr)
    one = client.get(f"/api/v1/omnichannel/contacts/{fp['cid']}", headers=rig.hdr)
    assert lst.status_code == 200 and one.status_code == 200, (lst.text, one.text)
    assert "messageCount" not in lst.text and "fileCount" not in lst.text
    assert "messageCount" not in one.text and "fileCount" not in one.text
    # control: the staff read of the very same contact does carry them
    assert "messageCount" in client.get(f"/omnichannel/contacts/{fp['cid']}", headers=_auth(client)).text
