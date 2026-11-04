"""Lane SS-MIGRATION-SYNC (plan 52) - reviewer round 1 regression tests."""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_DONE, JOB_FAILED, JOB_PENDING, JOB_RUNNING, BackgroundJob

from modules.omnichannel.repositories.migration_sync_repository import MigrationSyncRepository
from tests.test_omnichannel_migration_sync_support import (
    SYNCS,
    aware,
    close_all_worlds,
    get_sync,
    hint_ids,
    make_due,
    new_world,
    not_due,
    post_hint,
    run_due_syncs,
    set_sync,
    start_sync,
    stub_enqueue,
    sync_jobs,
    sync_row,
    utcnow,
    webhook_path,
)
from tests.test_omnichannel_migration_sync_ticks import _ready
from tests.test_omnichannel_respondio_migration_jobs import _auth


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


# B1 ─────────────────────────────────────────────────────────────────────────
def test_b1_hint_arriving_mid_tick_for_an_already_processed_contact_is_kept(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch, contacts=(910001, 910002))
    path = webhook_path(client, h, sid)
    w.fake.add_message(910001, 2, text="first news")
    assert post_hint(client, path, {"contact": {"id": 910001}}).status_code == 200
    w.fake.add_message(910002, 2, text="b news")
    assert post_hint(client, path, {"contact": {"id": 910002}}).status_code == 200
    not_due(w.db, sid)
    fired = []

    def late(method, p):
        if p.endswith("/contact/id:910002/message/list") and not fired:
            w.fake.add_message(910001, 3, text="late news")
            fired.append(
                MigrationSyncRepository(w.db).add_hint(DEFAULT_TENANT_ID, sid, "910001", datetime.now(timezone.utc))
            )

    w.fake.hooks.append(late)
    run_due_syncs(w.db)
    w.fake.hooks.clear()
    assert fired, "the mid-tick webhook fired"
    assert hint_ids(w.db, sid) == ["910001"], "the late hint survives the tick"

    make_due(w.db, sid, full_sweep="not_due")
    run_due_syncs(w.db)
    assert "late news" in [m.body for m in w.messages_of(w.contact_by_cid(910001))]
    assert hint_ids(w.db, sid) == []
