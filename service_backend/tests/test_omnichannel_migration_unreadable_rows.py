"""Plan 44 - source rows the respond.io migration cannot read
(AC-44-01..05, 10..12, 20..22).

Only the respond.io client transport is stubbed (the neighbouring migration
tests' pattern); routes, services and the job path are real. The shared
``client`` fixture re-raises server exceptions, which would hide a 500 as a
Python exception, so this file uses ``soft_client`` (``raise_server_exceptions
=False``) and asserts on the status the caller would actually see.

All data is placeholder. Rows we cannot read carry ``MARKER-*`` values so a
leak of any row value into a response or a stored report is caught.
"""
import json
import re

import httpx
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.team import Team
from app.services.team_capabilities import ensure_team_capabilities

from modules.omnichannel.models import Contact

from tests.test_omnichannel_respondio_migration_jobs import (
    _auth,
    _create_connection,
    _default_workspace,
    _default_workspace_id,
    _make_connection,
    _minimal_job_body,
    _patch_client_factory,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s3 import (
    _make_channel,
    _make_full_job,
    _pages_handler_full,
)
from tests.test_omnichannel_respondio_migration_s5 import _csv_bytes


# ── fixtures and builders ───────────────────────────────────────────────────


@pytest.fixture
def soft_client(session_factory):
    def override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


MARKERS = ("MARKER-", "marker@example.com")

GOOD_CHANNEL = {"id": 7001, "name": "Main WA", "source": "whatsapp_cloud"}
GOOD_USER = {
    "id": 7101, "firstName": "Jane", "lastName": "Doe", "email": "jane@example.com",
    "role": "agent", "team": {"id": 30, "name": "Support"},
}
GOOD_FIELD = {"id": 7201, "name": "Membership", "dataType": "text"}
GOOD_CONTACT = {"id": 7301, "lifecycle": "Trial", "firstName": "Good", "phone": "+15550007301"}


def bad_channel(row_id=7011):
    """No `source`."""
    return {"id": row_id, "name": "MARKER-NAME", "phone": "MARKER-PHONE"}


def bad_user(row_id):
    """No `email`."""
    return {"id": row_id, "firstName": "MARKER-FIRST", "lastName": "MARKER-LAST", "phone": "MARKER-PHONE"}


def bad_field(row_id=7221):
    """No `dataType`."""
    return {"id": row_id, "name": "MARKER-NAME", "description": "MARKER-DESC"}


def bad_contact(row_id=7321):
    """`tags` is a string, the shape wants a list."""
    return {
        "id": row_id, "firstName": "MARKER-FIRST", "phone": "MARKER-PHONE",
        "email": "marker@example.com", "lifecycle": "MARKER-LIFECYCLE", "tags": "MARKER-TAGS",
    }


def _state(**overrides):
    state = {
        "channels": [GOOD_CHANNEL],
        "users": [GOOD_USER],
        "fields": [GOOD_FIELD],
        "contacts": [GOOD_CONTACT],
        "calls": [],
    }
    state.update(overrides)
    return state


def _handler(state):
    """Answers from `state` AT CALL TIME, so a test can change what the
    source says between two requests."""

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        state["calls"].append(path)
        if path.endswith("/space/channel"):
            items = state["channels"]
        elif path.endswith("/space/user"):
            items = state["users"]
        elif path.endswith("/space/custom_field"):
            items = state["fields"]
        elif path.endswith("/contact/list"):
            items = state["contacts"]
        else:
            raise AssertionError(f"unexpected path {path}")
        return httpx.Response(200, json={"items": items, "pagination": {"next": None}})

    return handler


def _setup(soft_client, monkeypatch, state):
    h = _auth(soft_client)
    connection_id = _create_connection(soft_client, h)
    ws_id = _default_workspace_id(soft_client, h)
    _patch_client_factory(monkeypatch, _handler(state))
    return h, connection_id, ws_id


def _preflight(soft_client, h, connection_id, ws_id):
    return soft_client.get(
        "/omnichannel/migration/preflight",
        headers=h,
        params={"connectionId": connection_id, "workspaceId": ws_id},
    )


def _post_job(soft_client, h, connection_id, ws_id, *, mode, channel_map=None):
    body = _minimal_job_body(connection_id, ws_id, mode=mode)
    body["channelMap"] = channel_map or []
    return soft_client.post("/omnichannel/migration/jobs", headers=h, json=body)


def _warnings_naming(body, token):
    return [w for w in body["warnings"] if token in w]


def _assert_no_markers(text):
    for marker in MARKERS:
        assert marker not in text, f"{marker!r} leaked"


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-01 / 02 - preflight answers 200 and lists the good rows
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_01_a_user_with_no_email_does_not_fail_preflight(soft_client, monkeypatch):
    """The reproduction. Today a user row with no `email` raises a pydantic
    ValidationError outside any try and the route answers 500."""
    state = _state(users=[GOOD_USER, bad_user(7121)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    assert [u["id"] for u in body["users"]] == ["7101"]
    assert body["teams"] == [{"id": "30", "name": "Support"}]
    assert body["apiAvailable"] is True


def test_ac_44_02_a_channel_with_no_source_does_not_fail_preflight(soft_client, monkeypatch):
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    assert [c["id"] for c in body["channels"]] == ["7001"]
    assert [u["id"] for u in body["users"]] == ["7101"]
    assert [f["id"] for f in body["fields"]] == ["7201"]


def test_ac_44_02_a_custom_field_with_no_data_type_does_not_fail_preflight(soft_client, monkeypatch):
    state = _state(fields=[GOOD_FIELD, bad_field(7221)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    assert [f["id"] for f in body["fields"]] == ["7201"]
    assert [c["id"] for c in body["channels"]] == ["7001"]
    assert [u["id"] for u in body["users"]] == ["7101"]


def test_ac_44_02_a_contact_with_a_bad_id_does_not_fail_the_lifecycle_scan(soft_client, monkeypatch):
    state = _state(
        contacts=[
            GOOD_CONTACT,
            {"id": "zzz-bad-id", "lifecycle": "MARKER-LIFECYCLE"},
            {"id": 7302, "lifecycle": "Customer"},
        ]
    )
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    # The good contacts' labels are still read, the unreadable row's is not.
    assert set(body["lifecycles"]) == {"Trial", "Customer"}


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-03 - warnings: count and source ids, capped, never row values
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_03_each_kind_gets_one_warning_with_count_and_ids_and_no_values(soft_client, monkeypatch):
    state = _state(
        channels=[GOOD_CHANNEL, bad_channel(7011)],
        users=[GOOD_USER, bad_user(7121), bad_user(7122)],
        fields=[GOOD_FIELD, bad_field(7221), bad_field(7222), bad_field(7223)],
        contacts=[GOOD_CONTACT, bad_contact(7321), bad_contact(7322), bad_contact(7323), bad_contact(7324)],
    )
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    for count, ids in (
        (1, ["7011"]),
        (2, ["7121", "7122"]),
        (3, ["7221", "7222", "7223"]),
        (4, ["7321", "7322", "7323", "7324"]),
    ):
        lines = _warnings_naming(body, ids[0])
        assert len(lines) == 1, (ids, body["warnings"])
        line = lines[0]
        assert re.search(rf"\b{count}\b", line), line
        for row_id in ids:
            assert row_id in line, line
    # Not one row value anywhere in the answer: not a name, phone, email,
    # description or label of a row we could not read.
    _assert_no_markers(res.text)


def test_ac_44_03_ids_are_capped_at_twenty_then_and_n_more(soft_client, monkeypatch):
    bad = [bad_user(8000 + i) for i in range(1, 26)]
    state = _state(users=[GOOD_USER, *bad])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    lines = _warnings_naming(res.json(), "8001")
    assert len(lines) == 1
    line = lines[0]
    for i in range(1, 21):
        assert str(8000 + i) in line, (i, line)
    for i in range(21, 26):
        assert str(8000 + i) not in line, (i, line)
    assert "and 5 more" in line
    assert re.search(r"\b25\b", line), line


def test_ac_44_03_exactly_twenty_ids_are_all_shown_with_no_more_suffix(soft_client, monkeypatch):
    bad = [bad_user(8000 + i) for i in range(1, 21)]
    state = _state(users=[GOOD_USER, *bad])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    lines = _warnings_naming(res.json(), "8001")
    assert len(lines) == 1
    for i in range(1, 21):
        assert str(8000 + i) in lines[0]
    assert "more" not in lines[0]


def test_ac_44_03_a_row_with_no_usable_id_counts_and_shows_no_id(soft_client, monkeypatch):
    no_id = {"firstName": "MARKER-FIRST", "phone": "MARKER-PHONE"}
    wrong_type_id = {"id": "zzz-bad-id", "firstName": "MARKER-FIRST", "phone": "MARKER-PHONE"}
    state = _state(users=[GOOD_USER, bad_user(7121), no_id, wrong_type_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    lines = _warnings_naming(body, "7121")
    assert len(lines) == 1
    assert re.search(r"\b3\b", lines[0]), lines[0]
    assert "zzz-bad-id" not in res.text
    _assert_no_markers(res.text)


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-04 / 05 - unreadableChannelIds, nothing auto-mapped
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_04_unreadable_channel_ids_is_empty_when_every_channel_reads(soft_client, monkeypatch):
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state())

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.text
    body = res.json()
    assert body["unreadableChannelIds"] == []
    # Existing fields are unchanged.
    for key in (
        "apiAvailable", "spaceLabel", "channels", "users", "teams", "fields",
        "lifecycles", "targetChannels", "targetStages", "warnings",
    ):
        assert key in body, key
    assert [c["id"] for c in body["channels"]] == ["7001"]


def test_ac_44_04_unreadable_channel_ids_holds_the_ids_it_could_not_read(soft_client, monkeypatch):
    no_id = {"name": "MARKER-NAME", "source": "whatsapp_cloud"}
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011), bad_channel(7012), no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    # The row with no usable id has nothing to list; it is counted in the
    # warning instead (AC-44-03).
    assert body["unreadableChannelIds"] == ["7011", "7012"]


def test_ac_44_05_nothing_is_auto_mapped_for_an_unreadable_channel(soft_client, monkeypatch, session_factory):
    from app.models.background_job import BackgroundJob

    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)
    assert res.status_code == 200, res.status_code
    body = res.json()
    assert "7011" not in [c["id"] for c in body["channels"]]
    assert not any("map" in key.lower() for key in body), sorted(body)

    # A dry run with an empty map keeps it empty: the server adds no entry.
    dry = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run")
    assert dry.status_code == 201, dry.text
    db = session_factory()
    try:
        job = db.query(BackgroundJob).filter(BackgroundJob.id == dry.json()["id"]).one()
        assert job.payload_json["channelMap"] == []
    finally:
        db.close()


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-10 - dry run proceeds, report lists what was skipped
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_10_dry_run_proceeds_and_reports_the_skipped_rows(soft_client, monkeypatch):
    state = _state(
        channels=[GOOD_CHANNEL, bad_channel(7011)],
        users=[GOOD_USER, bad_user(7121), bad_user(7122)],
    )
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run")

    assert res.status_code == 201, res.text
    job = res.json()
    assert job["status"] == "done", job
    rows = job["failureSample"]
    channel_rows = [r for r in rows if r["entity"].startswith("channel")]
    user_rows = [r for r in rows if r["entity"].startswith("user")]
    assert [r["sourceId"] for r in channel_rows] == ["7011"]
    assert sorted(r["sourceId"] for r in user_rows) == ["7121", "7122"]
    assert all(r["action"] == "skipped" for r in channel_rows + user_rows)
    blockers = job["report"]["blockers"]
    channel_lines = [b for b in blockers if "channel" in b.lower() and re.search(r"\b1\b", b)]
    user_lines = [b for b in blockers if "user" in b.lower() and re.search(r"\b2\b", b)]
    assert len(channel_lines) == 1, blockers
    assert len(user_lines) == 1, blockers
    _assert_no_markers(res.text)


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-11 - a stored reason holds field names only
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_11_stored_reason_for_an_unreadable_contact_holds_field_names_only(session_factory, monkeypatch):
    """Both existing contact sites: the walk (`malformed contact payload`)
    and the event re-fetch. The control is that BOTH sites are reached and
    each stores a reason naming the failing field."""
    from modules.omnichannel.services.migration_service import MigrationService, run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    good = {"id": 910001, "firstName": "Good", "phone": "+15550910001"}
    walk_bad = {
        "id": 910002, "firstName": "MARKER-FIRST", "phone": "MARKER-PHONE",
        "email": "marker@example.com", "tags": "MARKER-TAGS",
    }
    refetch_bad = {"id": 910001, "firstName": "MARKER-FIRST2", "phone": "MARKER-PHONE2", "tags": "MARKER-TAGS2"}
    inner = _pages_handler_full({None: ([good, walk_bad], None)})

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/id:910001"):
            return httpx.Response(200, json=refetch_bad)
        return inner(request)

    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    rows = job.result_json["failures"]["sample"]
    walk_rows = [r for r in rows if r["entity"] == "contacts" and r["sourceId"] == "910002"]
    event_rows = [r for r in rows if r["entity"] == "events" and r["sourceId"] == "910001"]
    assert len(walk_rows) == 1, rows
    assert len(event_rows) == 1, rows
    for row in walk_rows + event_rows:
        assert "tags" in row["reason"], row

    everything = json.dumps(
        [
            job.result_json, job.cursor_json, job.logs_json, job.error,
            MigrationService(db).failures_csv(DEFAULT_TENANT_ID, job.id),
        ],
        default=str,
    )
    _assert_no_markers(everything)
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-12 - the team lookup skips a bad user row and counts it
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_12_team_lookup_skips_a_bad_user_row_and_the_job_goes_on(session_factory, monkeypatch):
    ensure_team_capabilities()
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    target_team = Team(tenant_id=DEFAULT_TENANT_ID, name="Support Unreadable", is_active=True)
    db.add(target_team)
    db.commit()
    target_team_id = target_team.id

    contact_row = {
        "id": 920001, "firstName": "Teamed", "phone": "+15550920001",
        "assignee": {"id": 501, "firstName": "Priya", "email": "priya-unreadable@example.com"},
    }
    # The unreadable user comes FIRST, so a job that stops at it never sees
    # the readable one after it.
    space_users = [
        bad_user(502),
        {
            "id": 501, "firstName": "Priya", "lastName": "Nair", "email": "priya-unreadable@example.com",
            "team": {"id": 701, "name": "Support"},
        },
    ]
    _stub_client(monkeypatch, _pages_handler_full({None: ([contact_row], None)}, space_users=space_users))

    from modules.omnichannel.services.migration_service import run_migration_job

    job = _make_full_job(
        db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run",
        team_map=[{"sourceTeamId": "701", "targetTeamId": target_team_id}],
    )
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    contact = db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550920001"
    ).first()
    assert contact is not None
    assert contact.assigned_team_id == target_team_id, "other users' teams still apply"
    rows = job.result_json["failures"]["sample"]
    skipped = [r for r in rows if r["entity"].startswith("user") and r["sourceId"] == "502"]
    assert len(skipped) == 1, rows
    assert skipped[0]["action"] == "skipped"
    _assert_no_markers(json.dumps([job.result_json, job.logs_json, job.error], default=str))
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-20 / 22 - an unreadable channel blocks the real run
# ═══════════════════════════════════════════════════════════════════════════


def _channel_map_error(res):
    assert res.status_code == 422, (res.status_code, res.text)
    return res.json()["detail"]["fieldErrors"]["channelMap"]


def test_ac_44_20_run_is_refused_naming_count_and_ids_of_unreadable_channels(soft_client, monkeypatch):
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011), bad_channel(7012)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    # A dry run with unreadable rows is allowed (AC-44-10) and makes the
    # real run reach the channel check rather than `dry_run_required`.
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    message = _channel_map_error(res)
    assert re.search(r"\b2\b", message), message
    assert "7011" in message and "7012" in message, message
    _assert_no_markers(res.text)


def test_ac_44_20_the_check_reads_the_source_at_that_moment_not_at_preflight(soft_client, monkeypatch):
    """The source is clean for the dry run and goes bad before the run is
    created: the run must be refused on what the source says now."""
    state = _state(channels=[GOOD_CHANNEL])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    state["channels"] = [GOOD_CHANNEL, bad_channel(7011)]

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert "7011" in _channel_map_error(res)


def test_ac_44_20_control_a_channel_that_reads_again_no_longer_blocks(soft_client, monkeypatch):
    """The other direction: bad at the dry run, readable when the run is
    created. Nothing is remembered from the earlier read."""
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    state["channels"] = [GOOD_CHANNEL, {"id": 7011, "name": "Fixed", "source": "facebook"}]

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert res.status_code == 201, res.text


def test_ac_44_20_marking_the_channel_skip_with_a_null_target_lets_the_run_through(soft_client, monkeypatch):
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    skip_map = [{"sourceChannelId": "7011", "targetChannelId": None}]

    # Without the entry: refused (red today, the check does not exist).
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    _channel_map_error(_post_job(soft_client, h, connection_id, ws_id, mode="run"))

    # With the entry, for the exact map the dry run covered: accepted.
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run", channel_map=skip_map).status_code == 201
    res = _post_job(soft_client, h, connection_id, ws_id, mode="run", channel_map=skip_map)
    assert res.status_code == 201, res.text
    assert res.json()["status"] == "done"


def test_ac_44_20_a_map_entry_with_a_real_target_does_not_unblock_an_unreadable_channel(
    soft_client, monkeypatch, session_factory
):
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    db = session_factory()
    target = _make_channel(db, DEFAULT_TENANT_ID, ws_id, name="Target WA")
    db.commit()
    target_id = target.id
    db.close()
    mapped = [{"sourceChannelId": "7011", "targetChannelId": target_id}]

    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run", channel_map=mapped).status_code == 201
    res = _post_job(soft_client, h, connection_id, ws_id, mode="run", channel_map=mapped)

    assert "7011" in _channel_map_error(res)


def test_ac_44_22_a_channel_with_no_usable_id_blocks_the_run_and_cannot_be_marked(soft_client, monkeypatch):
    no_id = {"name": "MARKER-NAME", "source": "whatsapp_cloud"}
    state = _state(channels=[GOOD_CHANNEL, no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    # An entry for some other id changes nothing: there is no id to mark.
    other_skip = [{"sourceChannelId": "99999", "targetChannelId": None}]
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run", channel_map=other_skip).status_code == 201

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run", channel_map=other_skip)

    message = _channel_map_error(res)
    assert "mark" in message.lower(), message
    assert re.search(r"\b1\b", message), message
    _assert_no_markers(res.text)


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-21 - a skipped user, field or contact never blocks the real run
# ═══════════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"users": [GOOD_USER, bad_user(7121)]}, id="user"),
        pytest.param({"fields": [GOOD_FIELD, bad_field(7221)]}, id="field"),
        pytest.param({"contacts": [GOOD_CONTACT, bad_contact(7321)]}, id="contact"),
    ],
)
def test_ac_44_21_an_unreadable_user_field_or_contact_does_not_block_the_run(
    soft_client, monkeypatch, overrides
):
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state(**overrides))

    dry = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run")
    assert dry.status_code == 201, dry.text
    assert dry.json()["status"] == "done", dry.json()

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert res.status_code == 201, res.text
    assert res.json()["status"] == "done", res.json()


# ═══════════════════════════════════════════════════════════════════════════
# Control - CSV mode has no channels and is unaffected
# ═══════════════════════════════════════════════════════════════════════════


def test_ac_44_20_control_csv_mode_never_reads_channels_and_runs(soft_client, monkeypatch):
    """CONTROL: passes today and must keep passing. A source that would
    refuse an API run is irrelevant to a CSV run, and no channel is read."""
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, _connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    content = _csv_bytes(["First Name", "Phone"], [["Csv", "+15559990044"]])
    up = soft_client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert up.status_code == 201, up.text
    body = {
        "workspaceId": ws_id, "source": "csv",
        "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
        "contactsUploadId": up.json()["id"],
    }

    dry = soft_client.post("/omnichannel/migration/jobs", headers=h, json={**body, "mode": "dry_run"})
    assert dry.status_code == 201, dry.text
    run = soft_client.post("/omnichannel/migration/jobs", headers=h, json={**body, "mode": "run"})

    assert run.status_code == 201, run.text
    assert not any(p.endswith("/space/channel") for p in state["calls"]), state["calls"]


# ═══════════════════════════════════════════════════════════════════════════
# The dry run's user read: a source error is survivable, anything else is not
# swallowed into a false success
# ═══════════════════════════════════════════════════════════════════════════


def _dry_run_with_user_read_raising(soft_client, monkeypatch, exc):
    from modules.omnichannel.respondio.client import RespondIoClient

    def raiser(self):
        raise exc

    state = _state()
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    monkeypatch.setattr(RespondIoClient, "list_space_users", raiser)
    res = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run")
    assert res.status_code == 201, res.text
    job = soft_client.get(f"/omnichannel/migration/jobs/{res.json()['id']}", headers=h)
    assert job.status_code == 200, job.text
    return job.json()


def test_ac_44_12_a_source_error_reading_users_still_completes_the_dry_run_with_a_warning(
    soft_client, monkeypatch
):
    from modules.omnichannel.respondio.client import RespondIoError

    job = _dry_run_with_user_read_raising(
        soft_client, monkeypatch, RespondIoError("upstream error", status_code=500)
    )

    assert job["status"] == "done", job
    texts = [log.get("message", "") if isinstance(log, dict) else str(log) for log in job["logs"]]
    texts += job["report"]["blockers"]
    assert any("user" in t.lower() for t in texts), texts


def test_ac_44_12_a_non_source_error_reading_users_never_reports_success(soft_client, monkeypatch):
    """Pins today's behaviour for an error that is not a RespondIoError (a
    bug or an odd payload): the job is not marked done."""
    job = _dry_run_with_user_read_raising(soft_client, monkeypatch, KeyError("boom"))

    assert job["status"] == "failed", job


# ═══════════════════════════════════════════════════════════════════════════
# AC-44-10 / 11 (round 2) - contact blocker line, resume, id marker, non-object
# ═══════════════════════════════════════════════════════════════════════════


def _full_handler(contact_pages, *, channels=None, space_users=None):
    """`_pages_handler_full` with the channel list answered from `channels`
    (the shared helper always answers an empty channel list)."""
    inner = _pages_handler_full(contact_pages, space_users=space_users)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/channel"):
            handler.channel_calls += 1
            return httpx.Response(200, json={"items": channels or [], "pagination": {"next": None}})
        return inner(request)

    handler.channel_calls = 0
    return handler


def _sample(job):
    return job.result_json["failures"]["sample"]


def test_ac_44_10_a_dry_run_blocker_line_gives_the_unreadable_contact_count(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    pages = {None: ([dict(GOOD_CONTACT), bad_contact(7321)], None)}
    _stub_client(monkeypatch, _full_handler(pages))

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    blockers = job.result_json["report"]["blockers"]
    assert "1 source contact(s) could not be read and were skipped." in blockers, blockers
    _assert_no_markers(json.dumps(job.result_json, default=str))
    db.close()


def test_ac_44_10_a_resumed_job_lists_a_row_once(session_factory, monkeypatch):
    """A job picked up again after a crash (status running, result and cursor
    from the first pass still stored) lists each unreadable channel and user
    once, and the blocker counts do not grow."""
    from modules.omnichannel.services.migration_service import MigrationService, run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    handler = _full_handler(
        {None: ([dict(GOOD_CONTACT)], None)},
        channels=[GOOD_CHANNEL, bad_channel(7011)],
        space_users=[GOOD_USER, bad_user(7121)],
    )
    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error
    assert handler.channel_calls >= 1, "the channel stub was never reached"
    first_ids = [r["sourceId"] for r in _sample(job)]
    assert "7011" in first_ids and "7121" in first_ids, first_ids
    calls_after_first = handler.channel_calls

    # The crash resume: same job, same stored result, status back to running.
    from app.models.background_job import JOB_RUNNING

    job.status = JOB_RUNNING
    db.commit()
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    assert handler.channel_calls > calls_after_first, "the resume never re-read the channels"
    rows = _sample(job)
    assert [r["sourceId"] for r in rows if r["sourceId"] == "7011"] == ["7011"], rows
    assert [r["sourceId"] for r in rows if r["sourceId"] == "7121"] == ["7121"], rows
    assert job.result_json["failures"]["rowCount"] == len(rows), job.result_json["failures"]
    csv_text = MigrationService(db).failures_csv(DEFAULT_TENANT_ID, job.id)
    assert csv_text.count("7011") == 1, csv_text
    assert csv_text.count("7121") == 1, csv_text
    blockers = job.result_json["report"]["blockers"]
    assert len([b for b in blockers if "channel" in b.lower() and "could not be read" in b]) == 1, blockers
    assert len([b for b in blockers if "user" in b.lower() and "could not be read" in b]) == 1, blockers
    db.close()


@pytest.mark.parametrize("marker_id", ["MARKER-NAME", "Jane Placeholder", "-5", "1e3", "12 34"])
def test_ac_44_11_a_contact_id_that_is_not_an_id_is_stored_as_empty(session_factory, monkeypatch, marker_id):
    from modules.omnichannel.services.migration_service import MigrationService, run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    bad = bad_contact(7321)
    bad["id"] = marker_id
    pages = {None: ([bad, dict(bad_contact(7322))], None)}
    _stub_client(monkeypatch, _full_handler(pages))

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert sorted(r["sourceId"] for r in rows) == ["", "7322"], rows
    everything = json.dumps(
        [job.result_json, job.cursor_json, job.logs_json, job.error,
         MigrationService(db).failures_csv(DEFAULT_TENANT_ID, job.id)],
        default=str,
    )
    assert marker_id not in everything.replace("MARKER-TAGS", ""), marker_id
    db.close()


def test_ac_44_11_a_contact_row_that_is_not_an_object_is_skipped_and_counted(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    pages = {None: (["MARKER-STRING", dict(GOOD_CONTACT)], None)}
    _stub_client(monkeypatch, _full_handler(pages))

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    contacts = job.result_json["report"]["entities"]["contacts"]
    assert contacts["fetched"] == 2, contacts
    assert contacts["errors"] == 1, contacts
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert len(rows) == 1 and rows[0]["sourceId"] == "" and rows[0]["action"] == "skipped", rows
    assert db.query(Contact).filter(
        Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == GOOD_CONTACT["phone"]
    ).count() == 1
    _assert_no_markers(json.dumps(job.result_json, default=str))
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# Round 3 - edge cases that pin the helpers and the run-time check
# ═══════════════════════════════════════════════════════════════════════════


def _line_for(body, label):
    lines = [w for w in body["warnings"] if f"source {label}(s) could not be read" in w]
    assert len(lines) == 1, body["warnings"]
    return lines[0]


def test_ac_44_02_rows_that_are_not_objects_are_skipped_counted_with_no_id(soft_client, monkeypatch):
    state = _state(
        channels=[GOOD_CHANNEL, "MARKER-STRING"],
        users=[GOOD_USER, "MARKER-STRING"],
        fields=[GOOD_FIELD, "MARKER-STRING"],
    )
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    body = res.json()
    assert _line_for(body, "channel") == "1 source channel(s) could not be read and were skipped."
    assert _line_for(body, "user") == "1 source user(s) could not be read and were skipped."
    assert _line_for(body, "custom field") == "1 source custom field(s) could not be read and were skipped."
    assert [c["id"] for c in body["channels"]] == ["7001"]
    _assert_no_markers(res.text)


def test_ac_44_03_an_id_with_trailing_text_shows_no_id(soft_client, monkeypatch):
    bad = bad_user("7011abc")
    state = _state(users=[GOOD_USER, bad, bad_user(7122)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    line = _line_for(res.json(), "user")
    assert "7122" in line, line
    assert "7011" not in line, line
    assert "7011abc" not in res.text


def test_ac_44_03_an_id_of_twenty_five_digits_shows_no_id(soft_client, monkeypatch):
    long_id = int("9" * 25)
    state = _state(users=[GOOD_USER, bad_user(long_id), bad_user(7122)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    line = _line_for(res.json(), "user")
    assert "7122" in line, line
    assert "9" * 25 not in res.text


def test_ac_44_03_a_mix_of_rows_with_and_without_an_id_shows_both(soft_client, monkeypatch):
    no_id = {"firstName": "MARKER-FIRST", "phone": "MARKER-PHONE"}
    state = _state(users=[GOOD_USER, bad_user(7121), bad_user(7122), no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _preflight(soft_client, h, connection_id, ws_id)

    assert res.status_code == 200, res.status_code
    line = _line_for(res.json(), "user")
    assert line == "3 source user(s) could not be read and were skipped (source ids: 7121, 7122); 1 had no readable id.", line


def test_ac_44_11_a_reason_lists_at_most_ten_field_names():
    from pydantic import BaseModel

    from modules.omnichannel.services.migration_service import parse_rows

    class Wide(BaseModel):
        f01: int
        f02: int
        f03: int
        f04: int
        f05: int
        f06: int
        f07: int
        f08: int
        f09: int
        f10: int
        f11: int
        f12: int

    parsed, unreadable = parse_rows([{}], Wide)

    assert parsed == []
    assert len(unreadable) == 1
    reason = unreadable[0].reason
    assert reason == "could not read: " + ", ".join(f"f{i:02d}" for i in range(1, 11)), reason


def test_ac_44_11_a_reason_for_a_failure_that_is_not_a_validation_error_keeps_its_message():
    from modules.omnichannel.services.migration_service import _failure_reason

    assert _failure_reason(RuntimeError("source went away")) == "source went away"


def test_ac_44_11_the_event_refetch_failure_keeps_the_source_error_message(session_factory, monkeypatch):
    from modules.omnichannel.services.migration_service import run_migration_job

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()
    good = {"id": 910001, "firstName": "Good", "phone": "+15550910001"}
    inner = _pages_handler_full({None: ([good], None)})
    refetched = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/contact/id:910001"):
            refetched.append(request.url.path)
            return httpx.Response(404, json={"code": "not_found", "message": "source contact vanished"})
        return inner(request)

    _stub_client(monkeypatch, handler)

    job = _make_full_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert job.status == "done", job.error
    assert refetched, "the re-fetch stub was never reached"
    rows = [r for r in _sample(job) if r["entity"] == "events" and r["sourceId"] == "910001"]
    assert len(rows) == 1, _sample(job)
    assert rows[0]["reason"].endswith("source contact vanished"), rows[0]
    db.close()


def test_ac_44_10_a_dry_run_blocker_and_failure_row_for_an_unreadable_custom_field(soft_client, monkeypatch):
    state = _state(fields=[GOOD_FIELD, bad_field(7221)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run")

    assert res.status_code == 201, res.text
    job = res.json()
    assert job["status"] == "done", job
    assert "1 source custom field(s) could not be read and were skipped." in job["report"]["blockers"], job["report"]["blockers"]
    rows = [r for r in job["failureSample"] if r["sourceId"] == "7221"]
    assert len(rows) == 1, job["failureSample"]
    assert rows[0]["entity"].startswith("field") and rows[0]["action"] == "skipped", rows[0]
    _assert_no_markers(res.text)


def test_ac_44_20_a_csv_run_with_a_connection_never_reads_or_refuses_on_channels(soft_client, monkeypatch):
    state = _state(channels=[GOOD_CHANNEL, bad_channel(7011)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    content = _csv_bytes(["First Name", "Phone"], [["Csv", "+15559990045"]])
    up = soft_client.post(
        "/omnichannel/migration/uploads", headers=h,
        files={"file": ("contacts.csv", content, "text/csv")}, data={"kind": "contacts"},
    )
    assert up.status_code == 201, up.text
    body = {
        "connectionId": connection_id, "workspaceId": ws_id, "source": "csv",
        "channelMap": [], "userMap": [], "teamMap": [], "lifecycleMap": [],
        "contactsUploadId": up.json()["id"],
    }
    dry = soft_client.post("/omnichannel/migration/jobs", headers=h, json={**body, "mode": "dry_run"})
    assert dry.status_code == 201, dry.text
    channel_reads_before = len([p for p in state["calls"] if p.endswith("/space/channel")])

    run = soft_client.post("/omnichannel/migration/jobs", headers=h, json={**body, "mode": "run"})

    assert run.status_code == 201, run.text
    channel_reads_after = len([p for p in state["calls"] if p.endswith("/space/channel")])
    assert channel_reads_after == channel_reads_before, state["calls"]


def test_ac_44_22_an_empty_channel_id_entry_does_not_mark_a_channel_with_no_id(soft_client, monkeypatch):
    no_id = {"name": "MARKER-NAME", "source": "whatsapp_cloud"}
    state = _state(channels=[GOOD_CHANNEL, no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    empty_skip = [{"sourceChannelId": "", "targetChannelId": None}]
    dry = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run", channel_map=empty_skip)
    assert dry.status_code == 201, dry.text

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run", channel_map=empty_skip)

    message = _channel_map_error(res)
    assert re.search(r"\b1\b", message), message


def test_ac_44_22_the_refusal_says_a_channel_with_no_readable_id_cannot_be_marked_skip(soft_client, monkeypatch):
    no_id = {"name": "MARKER-NAME", "source": "whatsapp_cloud"}
    state = _state(channels=[GOOD_CHANNEL, no_id])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201

    message = _channel_map_error(_post_job(soft_client, h, connection_id, ws_id, mode="run"))

    assert "A channel with no readable id cannot be marked Skip." in message, message

    # Control: a channel that has an id gets no such sentence.
    state["channels"] = [GOOD_CHANNEL, bad_channel(7011)]
    message = _channel_map_error(_post_job(soft_client, h, connection_id, ws_id, mode="run"))
    assert "7011" in message
    assert "cannot be marked Skip" not in message, message


def test_ac_44_20_a_source_error_during_the_run_check_refuses_and_creates_no_job(
    soft_client, monkeypatch, session_factory
):
    from app.models.background_job import BackgroundJob
    from modules.omnichannel.respondio.client import RespondIoClient, RespondIoError

    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state())
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    db = session_factory()
    jobs_before = db.query(BackgroundJob).count()
    db.close()
    reached = []

    def raiser(self):
        reached.append(1)
        raise RespondIoError("upstream error", status_code=500)

    monkeypatch.setattr(RespondIoClient, "list_space_channels", raiser)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert reached, "the channel read stub was never reached"
    _channel_map_error(res)
    db = session_factory()
    assert db.query(BackgroundJob).count() == jobs_before
    db.close()


def test_ac_44_20_the_read_transaction_is_released_before_the_channel_read(soft_client, monkeypatch):
    from modules.omnichannel.respondio.client import RespondIoClient
    from modules.omnichannel.services import migration_service

    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state())
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    events = []
    real_release = migration_service.release_read_transactions
    real_list = RespondIoClient.list_space_channels

    def release_spy(*args, **kwargs):
        events.append("release")
        return real_release(*args, **kwargs)

    def list_spy(self):
        events.append("channels")
        return real_list(self)

    monkeypatch.setattr(migration_service, "release_read_transactions", release_spy)
    monkeypatch.setattr(RespondIoClient, "list_space_channels", list_spy)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert res.status_code == 201, res.text
    assert "channels" in events, events
    assert "release" in events[: events.index("channels")], events


def test_ac_44_20_credentials_that_cannot_be_decrypted_do_not_fail_the_create(
    soft_client, monkeypatch, session_factory
):
    """Same as before the check existed: the run is created and the job
    itself fails with the credentials message."""
    from app.models.connection import Connection

    h, connection_id, ws_id = _setup(soft_client, monkeypatch, _state())
    assert _post_job(soft_client, h, connection_id, ws_id, mode="dry_run").status_code == 201
    db = session_factory()
    row = db.query(Connection).filter(Connection.id == connection_id).one()
    row.credentials_json = "not-a-valid-token"
    db.commit()
    db.close()

    res = _post_job(soft_client, h, connection_id, ws_id, mode="run")

    assert res.status_code == 201, res.text
    job = res.json()
    assert job["status"] == "failed", job
    from app.models.background_job import BackgroundJob

    db = session_factory()
    stored = db.query(BackgroundJob).filter(BackgroundJob.id == job["id"]).one()
    assert "could not be decrypted" in (stored.error or ""), stored.error
    db.close()


def test_ac_44_12_a_source_error_reading_channels_in_the_dry_run_still_finishes_with_users_and_fields(
    soft_client, monkeypatch
):
    from modules.omnichannel.respondio.client import RespondIoClient, RespondIoError

    state = _state(users=[GOOD_USER, bad_user(7121)], fields=[GOOD_FIELD, bad_field(7221)])
    h, connection_id, ws_id = _setup(soft_client, monkeypatch, state)
    reached = []

    def raiser(self):
        reached.append(1)
        raise RespondIoError("upstream error", status_code=500)

    monkeypatch.setattr(RespondIoClient, "list_space_channels", raiser)

    res = _post_job(soft_client, h, connection_id, ws_id, mode="dry_run")

    assert res.status_code == 201, res.text
    assert reached, "the channel read stub was never reached"
    job = soft_client.get(f"/omnichannel/migration/jobs/{res.json()['id']}", headers=h).json()
    assert job["status"] == "done", job
    ids = sorted(r["sourceId"] for r in job["failureSample"])
    assert ids == ["7121", "7221"], job["failureSample"]
    texts = [log.get("message", "") if isinstance(log, dict) else str(log) for log in job["logs"]]
    assert any("channel" in t.lower() for t in texts), texts


def test_ac_44_11_a_csv_contact_that_fails_stores_field_names_only(session_factory, monkeypatch):
    from pydantic import BaseModel

    from modules.omnichannel.services.migration_service import MigrationService, run_migration_job
    from modules.omnichannel.services.migration_writer import MigrationWriter
    from tests.test_omnichannel_respondio_migration_s5 import _make_csv_job, _upload_key

    class Shape(BaseModel):
        tags: list[str]

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    db.commit()
    content = _csv_bytes(["First Name", "Phone"], [["MARKER-FIRST", "+15550000001"]])
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    reached = []

    def failing(self, source):
        reached.append(1)
        Shape(tags="MARKER-TAGS")

    monkeypatch.setattr(MigrationWriter, "write_contact", failing)

    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job)
    db.refresh(job)

    assert reached, "the CSV contact site never reached the failing writer"
    assert job.status == "done", job.error
    rows = [r for r in _sample(job) if r["entity"] == "contacts"]
    assert len(rows) == 1, _sample(job)
    assert rows[0]["reason"] == "could not read: tags", rows[0]
    everything = json.dumps(
        [job.result_json, job.cursor_json, job.logs_json, job.error,
         MigrationService(db).failures_csv(DEFAULT_TENANT_ID, job.id)],
        default=str,
    )
    _assert_no_markers(everything)
    db.close()
