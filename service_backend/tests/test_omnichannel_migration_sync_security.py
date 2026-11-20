"""Lane SS-MIGRATION-SYNC (plan sprint-5/52) - security review round 1 tests:
hook robustness (S2, N1), respond.io base URL guard (S3), email escaping (S4),
no-store on the webhook URL routes (N5)."""
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.background_job import JOB_FAILED, JOB_PENDING, JOB_RUNNING
from modules.omnichannel.respondio.client import RespondIoClient, RespondIoError

from tests.conftest import ACTIVE_EMAIL
from tests.test_omnichannel_migration_sync_support import (
    SYNCS,
    close_all_worlds,
    get_sync,
    hint_ids,
    make_due,
    new_world,
    run_due_syncs,
    start_sync,
    sync_jobs,
    webhook_path,
)
from tests.test_omnichannel_respondio_migration_jobs import _auth


@pytest.fixture(autouse=True)
def _close_worlds(session_factory):
    yield
    close_all_worlds()


def _ready(client, session_factory, monkeypatch):
    w = new_world(session_factory, monkeypatch)
    w.fake.add_contact(910001, first="Sec")
    w.fake.add_message(910001, 1, text="hello")
    w.run_migration()
    w.db.commit()
    h = _auth(client)
    sid = start_sync(client, w.ws.id, h)["id"]
    return w, h, sid


def test_s2_deeply_nested_json_is_204_and_stores_nothing(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    path = webhook_path(client, h, sid)
    res = client.post(path, content=b"[" * 50000, headers={"content-type": "application/json"})
    assert res.status_code == 204
    assert hint_ids(w.db, sid) == []


def test_n1_unknown_sync_id_is_the_same_uniform_404(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    res = client.post("/omnichannel/migration-hooks/does-not-exist/abc", json={"contact": {"id": 1}})
    assert res.status_code == 404 and res.json() == {"detail": "Not Found"}


def test_n5_webhook_url_routes_are_no_store(client, session_factory, monkeypatch):
    w, h, sid = _ready(client, session_factory, monkeypatch)
    got = client.get(f"{SYNCS}/{sid}/webhook", headers=h)
    rotated = client.post(f"{SYNCS}/{sid}/webhook/rotate", headers=h)
    assert got.headers["cache-control"] == "no-store"
    assert rotated.headers["cache-control"] == "no-store"


def test_s3_private_or_http_base_url_is_refused_at_save(client):
    h = _auth(client)
    for bad in ("http://api.respond.io/v2", "https://127.0.0.1/v2", "https://10.0.0.5/v2", "https://169.254.169.254/"):
        res = client.post(
            "/integrations/connections", headers=h,
            json={
                "provider": "respondio", "name": f"Bad {bad}",
                "config": {"spaceLabel": "S", "timezone": "Asia/Kuala_Lumpur", "baseUrl": bad},
                "credentials": {"apiToken": "tok"},
            },
        )
        assert res.status_code == 422, (bad, res.text)
    ok = client.post(
        "/integrations/connections", headers=h,
        json={
            "provider": "respondio", "name": "Good",
            "config": {"spaceLabel": "S", "timezone": "Asia/Kuala_Lumpur", "baseUrl": "https://api.respond.io/v2"},
            "credentials": {"apiToken": "tok"},
        },
    )
    assert ok.status_code == 201, ok.text


def test_s3_client_refuses_a_non_public_base_url_with_fixed_text():
    for bad in ("http://api.respond.io/v2", "https://127.0.0.1/v2", "https://10.1.2.3/v2"):
        client = RespondIoClient(base_url=bad, api_token="tok")
        with pytest.raises(RespondIoError) as err:
            client.ping()
        assert err.value.status_code == 0
        assert err.value.message == "The respond.io API address is not allowed."
        assert "tok" not in err.value.message


def test_s3_tick_with_a_private_base_url_fails_the_tick_without_crashing(client, session_factory, monkeypatch):
    real_from_connection = RespondIoClient.__dict__["from_connection"]
    w, h, sid = _ready(client, session_factory, monkeypatch)
    monkeypatch.setattr(RespondIoClient, "from_connection", real_from_connection)
    w.conn.config_json = {**w.conn.config_json, "baseUrl": "http://127.0.0.1:9/v2"}
    w.db.commit()
    make_due(w.db, sid)

    run_due_syncs(w.db)

    item = get_sync(client, h, sid)
    assert item["status"] == "active"
    assert item["lastError"] == "The respond.io API address is not allowed."
    jobs = sync_jobs(w.db)
    assert len(jobs) == 1 and jobs[0].status == JOB_FAILED
    assert jobs[0].status not in (JOB_PENDING, JOB_RUNNING)


def test_s4_paused_email_html_escapes_the_workspace_name(client, session_factory, monkeypatch):
    from app.models.email_outbox import EmailOutbox

    w, h, sid = _ready(client, session_factory, monkeypatch)
    w.ws.name = "<script>alert(1)</script> & Co"
    w.db.commit()
    w.fake.fail_all = 401
    make_due(w.db, sid)

    run_due_syncs(w.db)

    w.db.expire_all()
    rows = w.db.query(EmailOutbox).filter(EmailOutbox.to_email == ACTIVE_EMAIL).all()
    row = next(r for r in rows if r.template_key == "migration_sync_paused")
    assert "<script>" not in row.html_body
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; Co" in row.html_body
