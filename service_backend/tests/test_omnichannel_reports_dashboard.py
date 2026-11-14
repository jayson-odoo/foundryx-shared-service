"""Plan 30 (roadmap A9), slice S1 - the aggregation core + dashboard route.

Covers AC-RPT-01..16 against the shared fixture (`tests.omnichannel_report_
fixture.seed_report_fixture`), plus the two-dialect golden compile and the
DST-spanning bucket test. `reports/meta`'s catalog half (AC-RPT-17) is
smoke-tested here too since S1 ships the route; S2 owns the report builders
themselves.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.dialects import postgresql, sqlite

from app.models import DEFAULT_TENANT_ID
from modules.omnichannel.models import Contact, ConversationEvent
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD
from tests.omnichannel_report_fixture import seed_report_fixture
from tests.test_omnichannel_contact_data_model import _other_tenant_auth


def _token(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD, tenant_slug=None) -> str:
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth(client, **kw) -> dict:
    return {"Authorization": f"Bearer {_token(client, **kw)}"}


def _dashboard(client, h, ws_id, **params):
    return client.get(f"/omnichannel/workspaces/{ws_id}/dashboard", params=params, headers=h)


@pytest.fixture
def fixture_ids(session_factory):
    db = session_factory()
    ids = seed_report_fixture(db)
    db.close()
    return ids


FIXTURE_RANGE = {"from": "2026-03-01", "to": "2026-03-07"}


# ── AC-RPT-01: state tiles ────────────────────────────────────────────────────
def test_tiles_current_state_ignores_range(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    tiles = res.json()["tiles"]
    assert tiles == {"open": 2, "assigned": 1, "unassigned": 2, "snoozed": 1}

    # AC-RPT-01: tiles ignore from/to entirely - a range with zero events in
    # it still reports the SAME current-state tiles.
    res2 = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **{"from": "2020-01-01", "to": "2020-01-02"})
    assert res2.json()["tiles"] == tiles


# ── AC-RPT-02: lifecycle stage tiles ──────────────────────────────────────────
def test_lifecycle_stage_counts(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    lifecycle = {row["key"]: row for row in res.json()["lifecycle"]}
    assert lifecycle["new_lead"]["count"] == 4
    assert lifecycle["new_lead"]["percent"] == 50.0
    assert lifecycle["hot_lead"]["count"] == 2
    assert lifecycle["hot_lead"]["percent"] == 25.0
    assert lifecycle["payment"]["count"] == 1
    assert lifecycle["payment"]["percent"] == 12.5
    assert lifecycle["customer"]["count"] == 1
    assert lifecycle["customer"]["percent"] == 12.5
    # A stage with no contacts is still listed, never dropped.
    assert lifecycle["cold_lead"]["count"] == 0
    assert lifecycle["cold_lead"]["percent"] == 0.0
    # sortOrder is present and stages are listed in that order.
    ordered = res.json()["lifecycle"]
    assert [s["sortOrder"] for s in ordered] == sorted(s["sortOrder"] for s in ordered)


def test_lifecycle_percent_denominator_is_the_workspace_total_not_just_staged(client, session_factory, fixture_ids):
    """S-3 (review round 1): AC-RPT-02 says `percent` is against the
    workspace's TOTAL contact count - an unstaged contact
    (`lifecycle_status_id IS NULL`) still counts against the denominator, it
    just never appears in any stage's numerator. The fixture's 8 contacts are
    all staged, so summing only the staged counts happened to equal the
    total; adding one unstaged 9th contact exposes the bug (every percent
    would otherwise be computed over 8, not 9)."""
    db = session_factory()
    db.add(
        Contact(
            tenant_id=fixture_ids.tenant_id,
            workspace_id=fixture_ids.workspace_id,
            first_name="Unstaged",
            last_name="Customer",
            status_id=fixture_ids.thread_statuses["OPEN"],
            lifecycle_status_id=None,
        )
    )
    db.commit()
    db.close()

    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    lifecycle = {row["key"]: row for row in res.json()["lifecycle"]}
    assert lifecycle["new_lead"]["count"] == 4
    assert lifecycle["new_lead"]["percent"] == 44.4
    assert lifecycle["hot_lead"]["count"] == 2
    assert lifecycle["hot_lead"]["percent"] == 22.2
    assert lifecycle["payment"]["percent"] == 11.1
    assert lifecycle["customer"]["percent"] == 11.1
    assert lifecycle["cold_lead"]["count"] == 0
    assert lifecycle["cold_lead"]["percent"] == 0.0


# ── AC-RPT-03/04: opened/closed series, two timezones ────────────────────────
def test_opened_closed_series_kuala_lumpur(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    body = res.json()
    assert [b["key"] for b in body["buckets"]] == [
        "2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06", "2026-03-07",
    ]
    assert body["series"]["opened"] == [2, 2, 1, 0, 1, 1, 0]
    assert body["series"]["closed"] == [1, 2, 1, 1, 0, 1, 0]


def test_opened_closed_series_utc(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="UTC", **FIXTURE_RANGE)
    body = res.json()
    assert body["series"]["opened"] == [3, 1, 1, 0, 2, 0, 0]
    assert body["series"]["closed"] == [1, 2, 1, 1, 0, 1, 0]


# ── AC-RPT-05/06: response + resolution totals, legacy derivation ────────────
def test_response_and_resolution_totals(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    body = res.json()
    assert body["responseTotals"] == {
        "medianSeconds": 150, "p90Seconds": 660, "averageSeconds": 278,
        "sampleCount": 6, "derivedFromMessages": 1,
    }
    assert body["resolutionTotals"]["medianSeconds"] == 12600
    assert body["resolutionTotals"]["p90Seconds"] == 278100
    assert body["resolutionTotals"]["sampleCount"] == 6
    assert body["resolutionTotals"].get("derivedFromMessages") is None


# ── Blocker B-1 (review round 1) ──────────────────────────────────────────────
def test_legacy_derivation_bounded_statements_no_per_contact_in_list(client, session_factory, fixture_ids):
    """Blocker B-1: the legacy first-response derivation used to fetch every
    no-reply contact's id into an `IN (...)` list (unbounded - a Postgres
    65535-bind 500 on a large workspace), then pull EVERY message of those
    contacts into Python. The SQL-bound version identifies each contact's
    first-ever AGENT message and its preceding CONTACT message via correlated
    scalar subqueries in ONE statement - seed a batch of extra no-reply
    contacts and prove the round-trip count stays constant (never scales with
    contact count, and never touches a per-contact `IN` list)."""
    from sqlalchemy import event

    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services import report_service
    from modules.omnichannel.services.report_filters import build_query

    db = session_factory()
    extra_ids = []
    for i in range(25):
        c = Contact(
            tenant_id=fixture_ids.tenant_id,
            workspace_id=fixture_ids.workspace_id,
            first_name="Bulk",
            last_name=f"NoReply{i}",
            phone=f"+60191{i:06d}",
            phone_digits=f"60191{i:06d}",
            status_id=fixture_ids.thread_statuses["OPEN"],
            lifecycle_status_id=fixture_ids.lifecycle["new_lead"],
        )
        db.add(c)
        db.flush()
        extra_ids.append(c.id)
        db.add(ConversationMessage(
            tenant_id=fixture_ids.tenant_id, contact_id=c.id, channel_id=fixture_ids.channel_id,
            sender_type="CONTACT", message_type="TEXT", body="hi",
            created_at=datetime(2026, 3, 2, 1, 0, 0, tzinfo=timezone.utc),
        ))
        db.add(ConversationMessage(
            tenant_id=fixture_ids.tenant_id, contact_id=c.id, channel_id=fixture_ids.channel_id,
            sender_type="AGENT", sender_id=fixture_ids.users["ann"], message_type="TEXT", body="hello",
            created_at=datetime(2026, 3, 2, 1, 5, 0, tzinfo=timezone.utc),
        ))
    db.commit()

    rq = build_query(
        db, fixture_ids.tenant_id, fixture_ids.workspace_id, from_="2026-03-01", to="2026-03-07", tz="UTC"
    )

    statements: list = []

    def _capture(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        samples = report_service._derived_response_samples(db, rq)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)
    db.close()

    # ONE round trip regardless of how many no-reply contacts exist - the
    # NOT EXISTS + two correlated scalar subqueries compile into a SINGLE SQL
    # statement, never a per-contact IN list or an N+1 message fetch.
    assert len(statements) == 1
    derived_ids = {s.contact_id for s in samples if s.derived}
    assert set(extra_ids) <= derived_ids


def test_legacy_derivation_tied_first_agent_messages_yield_one_sample(session_factory, fixture_ids):
    """N-2 (review round 2): `created_at == MIN(created_at)` matches EVERY
    agent message sharing the contact's first-reply second (bulk / seeded
    sends land on identical timestamps). Two AGENT messages with the EXACT
    same `created_at` must still produce ONE derived sample for the contact -
    never two - so median/p90/avg and `groupBy=user` cannot double-count."""
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services.report_service import _derived_response_samples
    from modules.omnichannel.services.report_filters import build_query

    db = session_factory()
    c = Contact(
        tenant_id=fixture_ids.tenant_id,
        workspace_id=fixture_ids.workspace_id,
        first_name="Tied",
        last_name="FirstReply",
        phone="+60199000001",
        phone_digits="60199000001",
        status_id=fixture_ids.thread_statuses["OPEN"],
        lifecycle_status_id=fixture_ids.lifecycle["new_lead"],
    )
    db.add(c)
    db.flush()
    tied_contact_id = c.id
    db.add(ConversationMessage(
        tenant_id=fixture_ids.tenant_id, contact_id=c.id, channel_id=fixture_ids.channel_id,
        sender_type="CONTACT", message_type="TEXT", body="hi",
        created_at=datetime(2026, 3, 2, 1, 0, 0, tzinfo=timezone.utc),
    ))
    tied_at = datetime(2026, 3, 2, 1, 5, 0, tzinfo=timezone.utc)
    for body in ("hello", "hello again"):
        db.add(ConversationMessage(
            tenant_id=fixture_ids.tenant_id, contact_id=c.id, channel_id=fixture_ids.channel_id,
            sender_type="AGENT", sender_id=fixture_ids.users["ann"], message_type="TEXT", body=body,
            created_at=tied_at,
        ))
    db.commit()

    rq = build_query(
        db, fixture_ids.tenant_id, fixture_ids.workspace_id, from_="2026-03-01", to="2026-03-07", tz="UTC"
    )
    samples = _derived_response_samples(db, rq)
    db.close()

    tied = [s for s in samples if s.contact_id == tied_contact_id]
    assert len(tied) == 1
    assert tied[0].seconds == 300
    assert tied[0].derived is True


def test_legacy_derivation_cap_raises_before_cap_plus_two(session_factory, fixture_ids, monkeypatch):
    """B-1: the SQL-bound derivation still routes through `duration_samples`,
    so `SampleCapExceeded` (AC-RPT-13) fires reading `cap + 1` rows - never
    `cap + 2` or the full set."""
    from modules.omnichannel.models import ConversationMessage
    from modules.omnichannel.services import report_queries
    from modules.omnichannel.services.report_service import _derived_response_samples
    from modules.omnichannel.services.report_filters import build_query

    db = session_factory()
    for i in range(4):
        c = Contact(
            tenant_id=fixture_ids.tenant_id,
            workspace_id=fixture_ids.workspace_id,
            first_name="Cap",
            last_name=f"Test{i}",
            phone=f"+60192{i:06d}",
            phone_digits=f"60192{i:06d}",
            status_id=fixture_ids.thread_statuses["OPEN"],
            lifecycle_status_id=fixture_ids.lifecycle["new_lead"],
        )
        db.add(c)
        db.flush()
        db.add(ConversationMessage(
            tenant_id=fixture_ids.tenant_id, contact_id=c.id, channel_id=fixture_ids.channel_id,
            sender_type="CONTACT", message_type="TEXT", body="hi",
            created_at=datetime(2026, 3, 2, 1, 0, 0, tzinfo=timezone.utc),
        ))
        db.add(ConversationMessage(
            tenant_id=fixture_ids.tenant_id, contact_id=c.id, channel_id=fixture_ids.channel_id,
            sender_type="AGENT", sender_id=fixture_ids.users["ann"], message_type="TEXT", body="hello",
            created_at=datetime(2026, 3, 2, 1, 5, 0, tzinfo=timezone.utc),
        ))
    db.commit()

    rq = build_query(
        db, fixture_ids.tenant_id, fixture_ids.workspace_id, from_="2026-03-01", to="2026-03-07", tz="UTC"
    )
    monkeypatch.setattr(report_queries, "REPORT_MAX_SAMPLE_ROWS", 2)
    with pytest.raises(report_queries.SampleCapExceeded) as exc_info:
        _derived_response_samples(db, rq)
    assert exc_info.value.count == 3  # cap + 1 rows read, never cap + 2 or all 4
    assert exc_info.value.cap == 2
    db.close()


# ── AC-RPT-07: top agents ─────────────────────────────────────────────────────
def test_top_agents_ordered_by_closed_count(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    top_agents = res.json()["topAgents"]
    assert [(a["name"], a["closedCount"], a["medianResponseSeconds"]) for a in top_agents] == [
        ("Ann Lee", 4, 30),
        ("Ben Ooi", 2, 420),
    ]
    # u_cara (no activity) never appears.
    assert "Cara Tan" not in [a["name"] for a in top_agents]


def test_top_agent_actor_id_from_another_tenant_renders_empty_name(client, session_factory, fixture_ids):
    """AC-RPT-07 (nit, review round 1): `_top_agents` resolves every stored
    `actor_user_id` tenant-scoped in ONE batched pass - a planted/corrupt id
    belonging to ANOTHER tenant must render an EMPTY name, never that other
    tenant's real user name (the polymorphic stored-id house rule)."""
    from app.models import User as CoreUser
    from app.services.tenant_service import TenantService

    db = session_factory()
    foreign_tenant = TenantService(db).provision(
        name="Foreign RPT Actor",
        slug="foreign-rpt-actor",
        admin_email="admin-foreign-rpt-actor@example.com",
        admin_password="Password123!",
        admin_name="Foreign Admin",
    )
    db.commit()
    foreign_user_id = (
        db.query(CoreUser.id)
        .filter(CoreUser.tenant_id == foreign_tenant.id, CoreUser.email == "admin-foreign-rpt-actor@example.com")
        .scalar()
    )
    assert foreign_user_id

    db.add(
        ConversationEvent(
            tenant_id=fixture_ids.tenant_id,
            workspace_id=fixture_ids.workspace_id,
            contact_id=fixture_ids.contacts["C6"],
            event_type="closed",
            actor_user_id=foreign_user_id,
            created_at=datetime(2026, 3, 5, 4, 0, 0, tzinfo=timezone.utc),
        )
    )
    db.commit()
    db.close()

    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    top_agents = res.json()["topAgents"]
    planted = next(a for a in top_agents if a["userId"] == foreign_user_id)
    assert planted["name"] == ""
    assert "Foreign Admin" not in [a["name"] for a in top_agents]


# ── AC-RPT-08: granularity auto-selection + range/tz validation ─────────────
def test_granularity_auto_selects_hour_for_a_two_day_range(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(
        client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **{"from": "2026-03-01", "to": "2026-03-02"}
    )
    assert res.json()["granularity"] == "hour"


def test_granularity_auto_selects_day_for_the_fixture_range(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    assert res.json()["granularity"] == "day"


def test_explicit_granularity_over_bucket_cap_is_422(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(
        client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur",
        granularity="hour", **{"from": "2026-01-01", "to": "2026-03-01"},
    )
    assert res.status_code == 422
    assert "granularity" in res.json()["detail"]["fieldErrors"]


def test_to_before_from_is_422(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **{"from": "2026-03-07", "to": "2026-03-01"})
    assert res.status_code == 422
    assert "to" in res.json()["detail"]["fieldErrors"]


def test_range_wider_than_max_is_422(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **{"from": "2020-01-01", "to": "2026-01-01"})
    assert res.status_code == 422
    assert "to" in res.json()["detail"]["fieldErrors"]


def test_unknown_timezone_is_422(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Not/AZone", **FIXTURE_RANGE)
    assert res.status_code == 422
    assert "tz" in res.json()["detail"]["fieldErrors"]


def test_bad_date_format_is_422(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **{"from": "01-03-2026", "to": "2026-03-07"})
    assert res.status_code == 422
    assert "from" in res.json()["detail"]["fieldErrors"]


# ── AC-RPT-09: userId filter ──────────────────────────────────────────────────
def test_user_filter_scopes_tiles_and_totals(client, fixture_ids):
    h = _auth(client)
    ann_id = fixture_ids.users["ann"]
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", userId=ann_id, **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    # Only C3 is currently assigned to ann.
    assert body["tiles"] == {"open": 1, "assigned": 1, "unassigned": 0, "snoozed": 0}
    assert body["responseTotals"]["sampleCount"] == 3
    assert [a["name"] for a in body["topAgents"]] == ["Ann Lee"]
    assert body["topAgents"][0]["closedCount"] == 4


def test_unknown_user_id_is_422_not_403_not_data(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", userId="not-a-real-user", **FIXTURE_RANGE)
    assert res.status_code == 422
    assert "userId" in res.json()["detail"]["fieldErrors"]


# ── AC-RPT-10: tenant scoping / uniform 404 ───────────────────────────────────
def test_foreign_tenant_workspace_is_uniform_404(client, session_factory, fixture_ids):
    h2 = _other_tenant_auth(client, session_factory, slug="other-rpt")
    res = client.get(
        f"/omnichannel/workspaces/{fixture_ids.workspace_id}/dashboard",
        params={**FIXTURE_RANGE, "tz": "Asia/Kuala_Lumpur"},
        headers=h2,
    )
    assert res.status_code == 404


def test_unknown_workspace_id_is_404(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, "not-a-real-workspace", tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    assert res.status_code == 404


# ── AC-RPT-11: golden two-dialect compile ─────────────────────────────────────
def test_bucket_query_compiles_dialect_free():
    """S-8 (review round 1): compile the ACTUAL columns `bucketed_counts`
    builds (`report_queries.bucketed_select_columns` - the same helper every
    report/dashboard series query runs through), not a hand-built stand-in
    column with no series dimension - a multi-series, multi-bucket statement
    is exactly what production emits."""
    from modules.omnichannel.services import report_queries
    from modules.omnichannel.services.report_windows import Bucket

    edges = [
        Bucket(key="2026-03-01", starts_at=datetime(2026, 3, 1, tzinfo=timezone.utc), ends_at=datetime(2026, 3, 2, tzinfo=timezone.utc)),
        Bucket(key="2026-03-02", starts_at=datetime(2026, 3, 2, tzinfo=timezone.utc), ends_at=datetime(2026, 3, 3, tzinfo=timezone.utc)),
    ]
    series_predicates = {
        "opened": ConversationEvent.event_type == "opened",
        "closed": ConversationEvent.event_type == "closed",
    }
    columns = report_queries.bucketed_select_columns(ConversationEvent.created_at, edges, series_predicates)
    assert len(columns) == 4  # 2 series x 2 buckets

    from sqlalchemy import select

    stmt = select(*columns)
    sqlite_sql = str(stmt.compile(dialect=sqlite.dialect())).lower()
    postgres_sql = str(stmt.compile(dialect=postgresql.dialect())).lower()
    for sql in (sqlite_sql, postgres_sql):
        assert "date_trunc" not in sql
        assert "strftime" not in sql
        assert "case" in sql
        assert "sum" in sql


# ── AC-RPT-12: DST-spanning day buckets ───────────────────────────────────────
def test_dst_spanning_day_buckets_no_gap_no_overlap(client, session_factory, fixture_ids):
    db = session_factory()
    london = ZoneInfo("Europe/London")
    extra = Contact(
        tenant_id=fixture_ids.tenant_id,
        workspace_id=fixture_ids.workspace_id,
        first_name="DST",
        status_id=fixture_ids.thread_statuses["OPEN"],
        lifecycle_status_id=fixture_ids.lifecycle["new_lead"],
    )
    db.add(extra)
    db.flush()
    for day in (28, 29, 30):
        local_noon = datetime(2026, 3, day, 12, tzinfo=london)
        db.add(
            ConversationEvent(
                tenant_id=fixture_ids.tenant_id,
                workspace_id=fixture_ids.workspace_id,
                contact_id=extra.id,
                event_type="opened",
                created_at=local_noon.astimezone(timezone.utc),
            )
        )
    db.commit()
    db.close()

    h = _auth(client)
    res = _dashboard(
        client, h, fixture_ids.workspace_id, tz="Europe/London", granularity="day",
        **{"from": "2026-03-28", "to": "2026-03-30"},
    )
    assert res.status_code == 200, res.text
    body = res.json()
    buckets = body["buckets"]
    assert len(buckets) == 3
    widths_hours = [
        (datetime.fromisoformat(b["endsAt"].replace("Z", "+00:00")) - datetime.fromisoformat(b["startsAt"].replace("Z", "+00:00"))).total_seconds()
        / 3600
        for b in buckets
    ]
    assert widths_hours == [24.0, 23.0, 24.0]
    assert body["series"]["opened"] == [1, 1, 1]
    assert sum(body["series"]["opened"]) == 3


# ── AC-RPT-13: sample cap fails fast ──────────────────────────────────────────
def test_sample_cap_exceeded_is_422(client, fixture_ids, monkeypatch):
    from modules.omnichannel.services import report_queries

    monkeypatch.setattr(report_queries, "REPORT_MAX_SAMPLE_ROWS", 2)
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    assert res.status_code == 422
    detail = res.json()["detail"]
    assert isinstance(detail, str)
    assert "row" in detail.lower() or "cap" in detail.lower()


def test_duration_samples_raises_before_cap_plus_two():
    from modules.omnichannel.services.report_queries import SampleCapExceeded, duration_samples

    class FakeQuery:
        def __init__(self, rows):
            self._rows = rows

        def limit(self, n):
            return FakeQueryLimited(self._rows[:n])

    class FakeQueryLimited:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    with pytest.raises(SampleCapExceeded) as exc_info:
        duration_samples(FakeQuery(list(range(5))), cap=3)
    assert exc_info.value.count == 4
    assert exc_info.value.cap == 3

    # Exactly at the cap never raises.
    assert duration_samples(FakeQuery(list(range(3))), cap=3) == [0, 1, 2]


# ── AC-RPT-14: empty workspace ────────────────────────────────────────────────
def test_empty_workspace_returns_zeroed_dashboard(client, session_factory):
    from modules.omnichannel.schemas import WorkspaceCreate
    from modules.omnichannel.services.workspace_service import WorkspaceService

    db = session_factory()
    ws = WorkspaceService(db).create(WorkspaceCreate(name="Empty Reports WS"), DEFAULT_TENANT_ID)
    db.close()

    h = _auth(client)
    res = _dashboard(client, h, ws.id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["tiles"] == {"open": 0, "assigned": 0, "unassigned": 0, "snoozed": 0}
    assert all(stage["count"] == 0 and stage["percent"] == 0.0 for stage in body["lifecycle"])
    assert body["responseTotals"]["medianSeconds"] is None
    assert body["responseTotals"]["p90Seconds"] is None
    assert body["responseTotals"]["sampleCount"] == 0
    assert body["topAgents"] == []
    assert len(body["buckets"]) == 7


# ── AC-RPT-15: team dimension - gated on `Contact.assigned_team_id` ──────────
# Plan 28 (A8) landed AFTER plan 30 (A9): the column now exists, so the
# `team_available()` seam (D-A9-13, `report_filters.team_column`) flips to
# True. These two tests pinned the pre-A8 state ("422 until A8" / "available:
# false"); at the A8 merge they pin the post-A8 state instead - an unknown
# team id is a valid filter that narrows to zero (no existence oracle), and
# `reports/meta` advertises the dimension.
def test_team_id_filter_accepted_once_a8_landed(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", teamId="some-team", **FIXTURE_RANGE)
    assert res.status_code == 200, res.text
    body = res.json()
    # The dimension is applied by A9's own query builder (its per-report
    # team-scoped semantics are A9's contract, not pinned here) - this test
    # only pins that the filter is ACCEPTED and the envelope still renders.
    assert body["granularity"] == "day"
    assert len(body["buckets"]) == 7


def test_reports_meta_reports_team_available(client, fixture_ids):
    h = _auth(client)
    res = client.get(f"/omnichannel/workspaces/{fixture_ids.workspace_id}/reports/meta", headers=h)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["dimensions"]["team"]["available"] is True
    keys = {r["key"] for r in body["reports"]}
    assert keys == {"conversations", "responses", "resolutions", "messages", "users", "leaderboard", "assignments"}
    assert set(body["granularities"]) == {"hour", "day", "week", "month"}


# ── AC-RPT-16: wire shape ─────────────────────────────────────────────────────
def test_dashboard_wire_shape_camel_case_and_z_suffixed(client, fixture_ids):
    h = _auth(client)
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    body = res.json()
    assert body["timezone"] == "Asia/Kuala_Lumpur"
    assert body["range"] == {"from": "2026-03-01", "to": "2026-03-07"}
    assert body["granularity"] == "day"
    for bucket in body["buckets"]:
        assert bucket["startsAt"].endswith("Z")
        assert bucket["endsAt"].endswith("Z")
    # camelCase throughout, no snake_case leaks.
    assert "responseTotals" in body and "response_totals" not in body
    assert "topAgents" in body and "top_agents" not in body


# ── permission gate ────────────────────────────────────────────────────────────
def test_missing_reports_read_permission_is_403(client, session_factory, fixture_ids):
    from sqlalchemy.sql import func as sa_func

    from app.models import Role, User, UserStatus
    from app.repositories.permission_repository import PermissionRepository
    from app.security import hash_password

    db = session_factory()
    user = User(
        tenant_id=DEFAULT_TENANT_ID,
        email="no-reports-perm@fixture.example",
        password=hash_password("pw12345678"),
        name="No Reports",
        status=UserStatus.ACTIVE.value,
        email_verified_at=sa_func.now(),
    )
    role = Role(tenant_id=DEFAULT_TENANT_ID, name="role-no-reports")
    role.permissions = PermissionRepository(db).get_by_keys(["conversations.read"])
    db.add(role)
    db.flush()
    user.roles = [role]
    db.add(user)
    db.commit()
    db.close()

    h = _auth(client, email="no-reports-perm@fixture.example", password="pw12345678")
    res = _dashboard(client, h, fixture_ids.workspace_id, tz="Asia/Kuala_Lumpur", **FIXTURE_RANGE)
    assert res.status_code == 403

    res2 = client.get(f"/omnichannel/workspaces/{fixture_ids.workspace_id}/reports/meta", headers=h)
    assert res2.status_code == 403
