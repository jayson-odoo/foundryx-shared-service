"""sprint-5/14 S0 - structure/parity/isolation tests (AC-14-70, 71, 80..82, T).

Confirms the new doc-feed entities NEVER collide with the existing ETL task
framework's entity-type space, the legacy `goods_received_note` canonical
stays pathless (D20), the manifest mounts the new router, and the module
migration is well-formed. The live-Postgres `alembic upgrade`/`downgrade`
check (AC-14-82's real gate) is a MANUAL S2 step per the plan's own note -
not repeatable under pytest's sqlite `create_all` (the migration is invisible
to it); this file only pins the STATIC shape (revision id length, single
head, `create_all` producing the five tables via `models.py`).
"""
from __future__ import annotations

import pytest

from app.models import DEFAULT_TENANT_ID
from modules.autocount.services.etl_service import ETL_ENTITY_TYPES
from modules.autocount.sinks_sorento import CONTRACT_GATED_ENTITIES, _ENTITY_PATH

from .s14_doc_feed_helpers import auth_headers, company, limited_user, other_tenant, wired_company


DOC_FEED_KEYS = {"delivery_orders", "goods_receive_notes"}  # plan 14 section 11: branches is an entity now


def test_doc_feed_keys_are_disjoint_from_etl_entity_types():
    assert DOC_FEED_KEYS.isdisjoint(set(ETL_ENTITY_TYPES))


def test_doc_feed_keys_are_present_in_entity_path_and_contract_gated():
    assert DOC_FEED_KEYS.issubset(set(_ENTITY_PATH))
    for key in DOC_FEED_KEYS:
        assert key in CONTRACT_GATED_ENTITIES
        required_version, entity_name = CONTRACT_GATED_ENTITIES[key]
        assert required_version == 2.7
        assert entity_name == key


def test_legacy_goods_received_note_still_has_no_ingest_path():
    """D20 - the legacy canonical entity keeps NO Sorento path (falls back to
    the logging sink), disjoint from the new `goods_receive_notes` DOOR key
    even though the words are nearly identical."""
    from modules.autocount.canonical.grn import ENTITY_GOODS_RECEIVED_NOTE

    assert ENTITY_GOODS_RECEIVED_NOTE not in _ENTITY_PATH
    assert ENTITY_GOODS_RECEIVED_NOTE != "goods_receive_notes"


def test_so_po_spo_task_paths_are_unchanged():
    from modules.autocount.canonical.documents import (
        ENTITY_PURCHASE_ORDER, ENTITY_SALES_ORDER, ENTITY_SHIPPING_ORDER,
    )

    assert _ENTITY_PATH[ENTITY_SALES_ORDER] == "sales_orders"
    assert _ENTITY_PATH[ENTITY_PURCHASE_ORDER] == "purchase_orders"
    assert _ENTITY_PATH[ENTITY_SHIPPING_ORDER] == "shipping_orders"


# ── manifest mounts the router ──────────────────────────────────────────────


def test_manifest_declares_the_doc_feeds_router():
    import json
    from pathlib import Path

    manifest_path = Path(__file__).resolve().parent.parent / "modules" / "autocount" / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    router_names = [
        r.get("name") for r in manifest.get("routers", []) if isinstance(r, dict)
    ] or manifest.get("routers", [])
    assert "doc_feeds" in router_names or any(
        "/autocount/doc-feeds" in str(r) for r in manifest.get("routers", [])
    )


# ── runs / issues lists: tenant-scoped, filterable (AC-14-70/71) ────────────


def test_runs_list_is_tenant_scoped_and_filterable_by_feed(client, session_factory):
    from modules.autocount.models import AcDocFeed, AcDocFeedRun
    from datetime import datetime, timezone

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed_do = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    feed_grn = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="goods_receive_notes",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add_all([feed_do, feed_grn])
    db.flush()
    db.add(
        AcDocFeedRun(
            tenant_id=co.tenant_id, company_id=co.id, feed_id=feed_do.id, feed="delivery_orders",
            kind="poll", dry_run=False, outcome="SUCCESS", started_at=datetime.now(timezone.utc),
        )
    )
    db.add(
        AcDocFeedRun(
            tenant_id=co.tenant_id, company_id=co.id, feed_id=feed_grn.id, feed="goods_receive_notes",
            kind="poll", dry_run=False, outcome="SUCCESS", started_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    headers = auth_headers(client)
    response = client.get(f"/autocount/doc-feeds/{co.id}/runs?feed=delivery_orders", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert all(item["feed"] == "delivery_orders" for item in body["data"])
    assert body["total"] >= 1


def test_runs_list_of_a_cross_tenant_company_404s(client, session_factory):
    db = session_factory()
    tenant_b = other_tenant(db)
    co = company(db, tenant_id=tenant_b)
    headers = auth_headers(client)
    response = client.get(f"/autocount/doc-feeds/{co.id}/runs", headers=headers)
    assert response.status_code == 404


def test_issues_list_is_searchable_by_docno(client, session_factory):
    from modules.autocount.models import AcDocFeed, AcDocFeedIssue
    from datetime import date, datetime, timezone

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add(feed)
    db.flush()
    db.add(
        AcDocFeedIssue(
            tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders", book="db1",
            doc_key=1, kind="failed", doc_no="DO-FINDME-1", doc_date=date(2026, 9, 29),
            record_json={"DocKey": 1}, errors_json={"DocNo": "clash"},
            attempts=1, first_at=datetime.now(timezone.utc), last_at=datetime.now(timezone.utc),
        )
    )
    db.commit()

    headers = auth_headers(client)
    response = client.get(f"/autocount/doc-feeds/{co.id}/issues?search=FINDME", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["data"]) == 1
    assert body["data"][0]["docNo"] == "DO-FINDME-1"


# ── migration shape (AC-14-82) ───────────────────────────────────────────────


def test_the_doc_feed_migration_revision_id_is_well_formed():
    import glob
    from pathlib import Path

    versions_dir = (
        Path(__file__).resolve().parent.parent / "modules" / "autocount" / "alembic" / "versions"
    )
    matches = list(versions_dir.glob("0023_autocount_doc_feed*.py"))
    assert matches, f"no 0023_autocount_doc_feed migration found under {versions_dir}"
    module_text = matches[0].read_text()
    import re

    rev_match = re.search(r'revision[:=].*?["\']([\w]+)["\']', module_text)
    assert rev_match, "no revision id found in the migration"
    assert len(rev_match.group(1)) <= 32


def test_create_all_produces_the_five_doc_feed_tables(session_factory):
    """pytest's `create_all` template-DB (no Alembic) still needs `models.py`
    to declare the five tables so they exist under sqlite - the DoD-2 note
    in the plan ("rows are created on first configure", no backfill needed)
    presumes the tables themselves are always present. A plain `.count()`
    query on each ORM class is the robust check here (never a raw
    schema-name reflection, which the sqlite `schema_translate_map` test
    harness does not expose the same way Postgres would)."""
    from modules.autocount.models import (
        AcDocFeed, AcDocFeedBackfill, AcDocFeedIssue, AcDocFeedLedger, AcDocFeedRun,
    )

    db = session_factory()
    for model in (AcDocFeed, AcDocFeedLedger, AcDocFeedIssue, AcDocFeedRun, AcDocFeedBackfill):
        assert db.query(model).count() == 0


# ── B1 (review round 2) - the HOUSE list envelope `{data, total, page}` +
# snake_case `page_size` (companies.py), row shape the frontend types read ──


def _seed_runs(db, co, ac_conn, count):
    from datetime import datetime, timedelta, timezone

    from modules.autocount.models import AcDocFeed, AcDocFeedRun

    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add(feed)
    db.flush()
    base = datetime(2026, 9, 29, 10, 0, tzinfo=timezone.utc)
    for i in range(count):
        db.add(
            AcDocFeedRun(
                tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id,
                feed="delivery_orders", kind="poll", dry_run=False, outcome="SUCCESS",
                started_at=base + timedelta(minutes=i),
            )
        )
    db.commit()
    return feed


def test_runs_list_answers_data_total_page_and_honours_page_size(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _seed_runs(db, co, ac_conn, 3)
    headers = auth_headers(client)

    first = client.get(f"/autocount/doc-feeds/{co.id}/runs?page=0&page_size=2", headers=headers)
    assert first.status_code == 200, first.text
    body = first.json()
    assert set(body) == {"data", "total", "page"}
    assert len(body["data"]) == 2
    assert body["total"] == 3
    assert body["page"] == 0

    second = client.get(f"/autocount/doc-feeds/{co.id}/runs?page=1&page_size=2", headers=headers).json()
    assert len(second["data"]) == 1
    assert second["page"] == 1


def _seed_issues(db, co, ac_conn, count):
    from datetime import date, datetime, timezone

    from modules.autocount.models import AcDocFeed, AcDocFeedIssue

    db.add(
        AcDocFeed(
            tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
            connection_id=ac_conn.id, book="db1", mode="push",
        )
    )
    db.flush()
    stamp = datetime(2026, 9, 29, 9, 0, tzinfo=timezone.utc)
    for i in range(count):
        db.add(
            AcDocFeedIssue(
                tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders", book="db1",
                doc_key=100 + i, kind="failed", doc_no=f"DO-{i}", doc_date=date(2026, 9, 29),
                source_modified_at=stamp, record_json={"DocKey": 100 + i},
                errors_json={"DocNo": "clash"}, warnings_json=["stale_ignored"],
                attempts=1, first_at=stamp, last_at=stamp,
            )
        )
    db.commit()


def test_issues_list_answers_data_total_page_and_honours_page_size(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _seed_issues(db, co, ac_conn, 3)
    headers = auth_headers(client)

    body = client.get(f"/autocount/doc-feeds/{co.id}/issues?page=1&page_size=2", headers=headers).json()
    assert set(body) == {"data", "total", "page"}
    assert len(body["data"]) == 1
    assert body["total"] == 3
    assert body["page"] == 1


def test_an_issue_row_carries_the_fields_the_frontend_type_declares(client, session_factory):
    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    _seed_issues(db, co, ac_conn, 1)
    headers = auth_headers(client)

    row = client.get(f"/autocount/doc-feeds/{co.id}/issues", headers=headers).json()["data"][0]
    assert row["id"] == "delivery_orders:db1:100"
    assert row["book"] == "db1"
    assert row["docKey"] == 100
    assert row["warnings"] == ["stale_ignored"]
    assert row["firstAt"].endswith("Z")
    assert row["sourceModifiedAt"].endswith("Z")
    assert row["lastAt"].endswith("Z")


# ── N1 - stop/resume/discard 404 uniformly on a foreign-tenant company ──────


@pytest.mark.parametrize("action", ["stop", "resume", "discard"])
def test_backfill_actions_on_a_cross_tenant_company_404(client, session_factory, action):
    db = session_factory()
    tenant_b = other_tenant(db)
    co = company(db, tenant_id=tenant_b)
    headers = auth_headers(client)
    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill/{action}", headers=headers,
    )
    assert response.status_code == 404, response.text


# ── B3 - resume while the previous job is live is a 409, never a 500 ────────


def test_resume_route_409s_with_backfill_job_live(client, session_factory):
    from datetime import date, datetime, timezone

    from app.models.background_job import BackgroundJob
    from modules.autocount.models import AcDocFeed, AcDocFeedBackfill

    db = session_factory()
    co, ac_conn, _crm = wired_company(db)
    feed = AcDocFeed(
        tenant_id=co.tenant_id, company_id=co.id, feed="delivery_orders",
        connection_id=ac_conn.id, book="db1", mode="push",
    )
    db.add(feed)
    job = BackgroundJob(tenant_id=co.tenant_id, type="autocount_doc_feed_backfill", status="running")
    db.add(job)
    db.flush()
    db.add(
        AcDocFeedBackfill(
            tenant_id=co.tenant_id, company_id=co.id, feed_id=feed.id, feed="delivery_orders",
            book="db1", dry_run=False, from_day=date(2026, 9, 1), to_day=date(2026, 9, 10),
            next_day=date(2026, 9, 3), status="stopped", job_id=job.id,
            started_at=datetime(2026, 9, 29, tzinfo=timezone.utc),
        )
    )
    db.commit()
    headers = auth_headers(client)

    response = client.post(
        f"/autocount/doc-feeds/{co.id}/delivery_orders/backfill/resume", headers=headers,
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "BACKFILL_JOB_LIVE"


# ── N8 - the models declare the migration's index names, no duplicates ──────


def test_models_declare_no_auto_named_single_column_indexes():
    from modules.autocount.models import (
        AcDocFeed, AcDocFeedBackfill, AcDocFeedRun,
    )

    for model in (AcDocFeed, AcDocFeedRun, AcDocFeedBackfill):
        names = {ix.name for ix in model.__table__.indexes}
        assert not any(n.startswith("ix_app_autocount") for n in names), names
    assert {"ix_ac_doc_feed_tenant", "ix_ac_doc_feed_company", "ix_ac_doc_feed_connection",
            "ix_ac_doc_feed_next_poll_at"} <= {ix.name for ix in AcDocFeed.__table__.indexes}


# ── AC-14-46 / D28: the model index carries no branch step ──────────────────


def test_ac_14_46_backfill_model_has_no_branch_step_column():
    from modules.autocount.models import AcDocFeedBackfill

    assert not hasattr(AcDocFeedBackfill, "branch_step")
    assert "branch_step" not in AcDocFeedBackfill.__table__.columns
