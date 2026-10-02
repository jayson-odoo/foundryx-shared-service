"""Plan 33 (roadmap A6) - Opus security review round 2 residuals (round 2
itself was an APPROVE with no blockers; these are the residual fit-and-
finish items the reviewer noted for a follow-up commit).

R1 - the client's three pagination termination guards (same cursor twice, an
empty page that still carries a cursor, the `MAX_PAGES` ceiling) now ALSO
land in `report.blockers`, not only the job's milestone log.
R2 - `checkpoint()`'s running `progressTotal` folds in `job.progress_done`
(never reads BELOW what has already been marked done), and the detail
page's displayed percentage clamps to 100.
R3 - three extra regression tests: a redirect `Location` header that is
itself only "relative" in the network-path sense (`//host/path`, RFC 3986
4.2) must still be re-validated against the SSRF guard; a redirect that
downgrades `https` to `http` must be rejected (the guard is https-only); a
CSV-mode Lifecycle value that matches a stage's key/label in a DIFFERENT
workspace of the SAME tenant must not resolve there.

Reuses the established cross-test-helper-import pattern rather than
duplicating fixtures.
"""
import httpx

from app.models import DEFAULT_TENANT_ID

from modules.omnichannel.models import Contact, Workspace
from modules.omnichannel.services import migration_media
from modules.omnichannel.services.lifecycle_service import (
    initial_status_id,
    materialize_for_workspace,
    stages_for_workspace,
)
from modules.omnichannel.services.migration_service import run_migration_job

from tests.test_omnichannel_respondio_migration_jobs import (
    _default_workspace,
    _make_connection,
    _make_job,
    _stub_client,
)
from tests.test_omnichannel_respondio_migration_s5 import _csv_bytes, _make_csv_job, _upload_key


# ═══════════════════════════════════════════════════════════════════════════
# R1 - pagination termination guards surface as a `report.blockers` entry
# ═══════════════════════════════════════════════════════════════════════════


def test_pagination_same_cursor_guard_surfaces_as_a_report_blocker(session_factory, monkeypatch):
    """A vendor stuck returning the same cursor forever must still produce a
    DONE job (never a hang, never a failure) whose report names the guard
    that fired - not only a milestone log line an operator has to go find."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/custom_field"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        return httpx.Response(
            200,
            json={"items": [{"id": 1, "firstName": "Loop"}], "pagination": {"next": "stuck-cursor"}},
        )

    _stub_client(monkeypatch, handler)
    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    report = job.result_json["report"]
    assert any(
        "same pagination cursor twice" in b for b in report["blockers"]
    ), report["blockers"]
    db.close()


def test_pagination_empty_page_with_cursor_guard_surfaces_as_a_report_blocker(session_factory, monkeypatch):
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/custom_field"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        cursor = request.url.params.get("cursorId")
        if cursor is None:
            return httpx.Response(
                200, json={"items": [{"id": 1, "firstName": "First"}], "pagination": {"next": "c2"}}
            )
        # Empty page, but `next` ("c3") DIFFERS from the cursor just
        # requested ("c2") - isolates this guard from the same-cursor-twice
        # guard above, which would otherwise fire first.
        return httpx.Response(200, json={"items": [], "pagination": {"next": "c3"}})

    _stub_client(monkeypatch, handler)
    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    report = job.result_json["report"]
    assert any(
        "empty page with a cursor still set" in b for b in report["blockers"]
    ), report["blockers"]
    db.close()


def test_pagination_max_pages_ceiling_guard_surfaces_as_a_report_blocker(session_factory, monkeypatch):
    from modules.omnichannel.respondio import client as respondio_client_module

    monkeypatch.setattr(respondio_client_module, "MAX_PAGES", 2)

    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/space/custom_field"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        cursor = request.url.params.get("cursorId") or "0"
        return httpx.Response(
            200,
            json={"items": [{"id": 1, "firstName": "X"}], "pagination": {"next": str(int(cursor) + 1)}},
        )

    _stub_client(monkeypatch, handler)
    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    report = job.result_json["report"]
    assert any("page ceiling" in b for b in report["blockers"]), report["blockers"]
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R2 - checkpoint() progressTotal folds in job.progress_done (never reads
# below what is already marked done)
# ═══════════════════════════════════════════════════════════════════════════


def test_checkpoint_progress_total_never_reads_below_progress_done(session_factory, monkeypatch):
    """A dry-run contacts phase previews identities+messages per contact
    (D-A6-14) - its OWN `service.advance(done=1)` calls only count contacts,
    not the identity/message rows previewed alongside them, so
    `progress_done` can momentarily sit ahead of the fetched-sum estimate
    `checkpoint()` computes. `job.progress_total` must never read below
    `job.progress_done` at any checkpoint - it would render as a >100%
    progress bar on the detail page."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    conn = _make_connection(db, DEFAULT_TENANT_ID)
    db.commit()

    contact_row = {"id": 777001, "firstName": "Prog", "phone": "+15550098001"}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/space/custom_field") or path.endswith("/space/user"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        if path.endswith("/contact/list"):
            return httpx.Response(200, json={"items": [contact_row], "pagination": {"next": None}})
        if path.endswith("/channels"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        if path.endswith("/message/list"):
            return httpx.Response(200, json={"items": [], "pagination": {"next": None}})
        return httpx.Response(200, json=contact_row)

    _stub_client(monkeypatch, handler)
    job = _make_job(db, DEFAULT_TENANT_ID, connection_id=conn.id, workspace_id=ws.id, mode="dry_run")
    # `_make_job` hardcodes `contactsOnly=True`; this test needs the dry
    # run's inline identities/messages preview to actually fire, so flip it
    # on the persisted payload directly rather than adding a new helper
    # kwarg only this test would use.
    job.payload_json = {**job.payload_json, "contactsOnly": False}
    db.commit()

    run_migration_job(db, job)
    db.refresh(job)
    assert job.status in ("done", "needs_review"), job.error
    assert job.progress_total >= job.progress_done
    db.close()


# ═══════════════════════════════════════════════════════════════════════════
# R3 - three extra regression tests
# ═══════════════════════════════════════════════════════════════════════════


def test_media_redirect_network_path_relative_location_to_private_ip_is_blocked(session_factory, monkeypatch):
    """A redirect `Location` header with NO scheme but a `//host` prefix (a
    network-path reference, RFC 3986 section 4.2) is syntactically
    "relative" yet still names a DIFFERENT host once resolved against the
    current URL - `httpx.URL(...).join(...)` follows the spec and resolves
    it to that host under the current scheme. It must be re-validated
    exactly like an absolute redirect, never treated as safe just because
    the header itself carried no `https://` prefix."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.host == "93.184.216.34":
            return httpx.Response(
                302, headers={"location": "//169.254.169.254/latest/meta-data/"}
            )
        return httpx.Response(200, content=b"should never be reached")  # pragma: no cover

    def fake_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(migration_media, "_client_factory", fake_factory)

    db = session_factory()
    result = migration_media.fetch_and_store_media(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-r3a", message_id="msg-r3a",
        url="https://93.184.216.34/redirect-me", filename=None, declared_kind="IMAGE",
    )
    assert result.ok is False
    assert calls == ["https://93.184.216.34/redirect-me"]
    db.close()


def test_media_redirect_downgrade_to_http_is_blocked(session_factory, monkeypatch):
    """A redirect `Location` that downgrades the scheme from `https` to
    `http` must be rejected by the SSRF guard (https-only), even though the
    target host itself is a safe public address - the guard's `parsed.
    scheme != "https"` check applies to every hop, not only the first
    request."""
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.scheme == "https":
            return httpx.Response(302, headers={"location": "http://93.184.216.34/next"})
        return httpx.Response(200, content=b"should never be reached")  # pragma: no cover

    def fake_factory() -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)

    monkeypatch.setattr(migration_media, "_client_factory", fake_factory)

    db = session_factory()
    result = migration_media.fetch_and_store_media(
        db, tenant_id=DEFAULT_TENANT_ID, workspace_id="ws-r3b", message_id="msg-r3b",
        url="https://93.184.216.34/redirect-me", filename=None, declared_kind="IMAGE",
    )
    assert result.ok is False
    assert calls == ["https://93.184.216.34/redirect-me"]
    db.close()


def test_csv_mode_lifecycle_label_matching_a_stage_in_another_workspace_does_not_resolve(session_factory):
    """`find_stage_by_key_or_label`'s key/label fallback (Defect 2 fix) is
    scoped by BOTH tenant_id AND workspace_id via `stages_for_workspace` -
    a Lifecycle value that happens to match a stage's label in a DIFFERENT
    workspace of the SAME tenant must land unmapped (the contact's own
    workspace's initial stage), never that other workspace's stage."""
    db = session_factory()
    ws = _default_workspace(db, DEFAULT_TENANT_ID)
    other_ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="Other Space", is_default=False)
    db.add(other_ws)
    db.flush()
    materialize_for_workspace(db, other_ws)
    db.commit()

    # The seed lifecycle graph is identical (same keys/labels) across every
    # workspace by default, so every label already matches on `ws` too -
    # rename one of `other_ws`'s stage labels to something unique so a leak
    # is unambiguous.
    other_stage = stages_for_workspace(db, DEFAULT_TENANT_ID, other_ws.id)[0]
    other_stage.label = "Only In Other Workspace"
    db.commit()

    initial_id = initial_status_id(db, DEFAULT_TENANT_ID, ws.id)

    content = _csv_bytes(
        ["First Name", "Phone", "Lifecycle"],
        [["Eve", "+15550097399", "Only In Other Workspace"]],
    )
    key = _upload_key(db, DEFAULT_TENANT_ID, "contacts", content)
    job = _make_csv_job(db, DEFAULT_TENANT_ID, workspace_id=ws.id, contacts_csv_key=key, mode="run")
    run_migration_job(db, job)
    db.refresh(job)
    assert job.status == "done", job.error

    contact = (
        db.query(Contact)
        .filter(Contact.tenant_id == DEFAULT_TENANT_ID, Contact.phone == "+15550097399")
        .first()
    )
    assert contact.lifecycle_status_id == initial_id
    assert contact.lifecycle_status_id != other_stage.id

    report = job.result_json["report"]
    assert report["lifecycleUnmappedByValue"] == {"Only In Other Workspace": 1}
    db.close()
