"""Plan 38 gap 7, slice S1: workflows under the API key, ownership and CRUD
(AC-38-120..127). RED tests written before the implementation.

Contract: documentation/plans/sprint-5/38-gap7-key-workflows.md, "Wire contract".
Every route is `/api/v1/omnichannel/workflows...` with a Bearer workspace key.
A workflow is reachable by a key only through an owner row in
`modules.omnichannel.models.WorkflowOwner` (table `workflow_owners`). The model
is imported lazily so each test fails on its own, not at collection.

Every test seeds its own workspaces, keys and workflows. Controls (tests that
pass today) say so in their docstring.
"""
import ast
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.test_omnichannel_api_gateway import _auth, _default_workspace_id, _mint

BASE = "/api/v1/omnichannel"
FOREIGN_TENANT = "foreign-tenant-s1"
EMPTY_DEF = {"schemaVersion": 1, "nodes": [], "edges": []}
NOT_FOUND = {"error": {"code": "not_found", "message": "Workflow not found."}}


# -- helpers ------------------------------------------------------------------
def _key(client, ws, name="K"):
    body = _mint(client, ws, name).json()
    return body["key"]["id"], {"Authorization": f"Bearer {body['fullKey']}"}


def _new_workspace(session_factory, name="Second"):
    from modules.omnichannel.models import Workspace

    db = session_factory()
    try:
        ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name=name, is_default=False)
        db.add(ws)
        db.commit()
        return ws.id
    finally:
        db.close()


def _owner_cls():
    from modules.omnichannel.models import WorkflowOwner

    return WorkflowOwner


def _seed_wf(
    session_factory,
    *,
    owner_ws=None,
    owner_tenant=DEFAULT_TENANT_ID,
    wf_tenant=DEFAULT_TENANT_ID,
    name="WF",
    trashed=False,
    active=False,
    version_id=None,
    created_by="seed",
    created_at=None,
):
    """Insert a core Workflow, plus an owner row when `owner_ws` is given."""
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        wf = Workflow(
            id=str(uuid.uuid4()),
            tenant_id=wf_tenant,
            name=name,
            description="",
            draft_definition_json=dict(EMPTY_DEF),
            is_trashed=trashed,
            is_active=active,
            current_version_id=version_id,
            created_by=created_by,
        )
        if created_at is not None:
            wf.created_at = created_at
        db.add(wf)
        db.flush()
        if owner_ws is not None:
            db.add(
                _owner_cls()(
                    tenant_id=owner_tenant,
                    workflow_id=wf.id,
                    workspace_id=owner_ws,
                    created_by="apikey:seed",
                )
            )
        db.commit()
        return wf.id
    finally:
        db.close()


def _wf_row(session_factory, wf_id):
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        w = db.query(Workflow).filter(Workflow.id == wf_id).first()
        if w is None:
            return None
        return {
            "tenant_id": w.tenant_id,
            "name": w.name,
            "description": w.description,
            "draft": json.dumps(w.draft_definition_json, sort_keys=True),
            "is_active": w.is_active,
            "is_trashed": w.is_trashed,
            "current_version_id": w.current_version_id,
            "created_by": w.created_by,
            "updated_at": w.updated_at,
        }
    finally:
        db.close()


def _counts(session_factory):
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        return db.query(Workflow).count(), db.query(_owner_cls()).count()
    finally:
        db.close()


def _wf_count(session_factory):
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        return db.query(Workflow).count()
    finally:
        db.close()


def _owner_rows(session_factory, wf_id):
    db = session_factory()
    try:
        return [
            (o.tenant_id, o.workspace_id, o.created_by)
            for o in db.query(_owner_cls()).filter(_owner_cls().workflow_id == wf_id).all()
        ]
    finally:
        db.close()


def _create(client, hdr, **extra):
    body = {"name": "From key", "description": "d", "draftDefinition": dict(EMPTY_DEF)}
    body.update(extra)
    return client.post(f"{BASE}/workflows", json=body, headers=hdr)


# -- AC-38-120 ------------------------------------------------------------------
def test_ac_38_120_every_key_reaches_workflow_routes(client, session_factory):
    """A plain minted key (no scope, setting or permission) reaches all five routes."""
    ws = _default_workspace_id(session_factory)
    _, hdr = _key(client, ws)

    r = client.get(f"{BASE}/workflows", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json() == {"data": [], "nextCursor": None}

    r = _create(client, hdr)
    assert r.status_code == 201, r.text
    wid = r.json()["id"]

    r = client.get(f"{BASE}/workflows/{wid}", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == wid

    r = client.patch(f"{BASE}/workflows/{wid}", json={"name": "Renamed"}, headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "Renamed"

    r = client.delete(f"{BASE}/workflows/{wid}", headers=hdr)
    assert r.status_code == 204, r.text


ROUTES_120 = [
    ("GET", "/workflows", None),
    ("POST", "/workflows", {"name": "n", "draftDefinition": EMPTY_DEF}),
    ("GET", "/workflows/{id}", None),
    ("PATCH", "/workflows/{id}", {"name": "n"}),
    ("DELETE", "/workflows/{id}", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES_120, ids=[f"{m} {p}" for m, p, _ in ROUTES_120])
def test_ac_38_120_revoked_401_and_limit_429(client, session_factory, monkeypatch, method, path, body):
    """Revoked key -> 401 invalid_api_key; over the plan 50 per-minute bound -> 429 rate_limited."""
    ws = _default_workspace_id(session_factory)
    wid = _seed_wf(session_factory, owner_ws=ws)
    url = BASE + path.replace("{id}", wid)

    # revoked
    kid, hdr = _key(client, ws, "to-revoke")
    rev = client.post(f"/omnichannel/workspaces/{ws}/api-keys/{kid}/revoke", headers=_auth(client))
    assert rev.status_code == 200
    r = client.request(method, url, json=body, headers=hdr)
    assert r.status_code == 401, r.text
    assert r.json()["error"]["code"] == "invalid_api_key"

    # over the per-minute bound: the first call is the 1 allowed, the second is refused
    monkeypatch.setitem(settings.__dict__, "omni_key_max_per_minute", 1)
    _, hdr2 = _key(client, ws, "limited")
    first = client.request(method, url, json=body, headers=hdr2)
    assert first.status_code != 429
    assert first.status_code in (200, 201, 204), first.text
    r = client.request(method, url, json=body, headers=hdr2)
    assert r.status_code == 429, r.text
    assert r.json()["error"]["code"] == "rate_limited"
    assert int(r.headers["Retry-After"]) >= 1


# -- AC-38-121 ------------------------------------------------------------------
def test_ac_38_121_create_owned_body_tenant_ignored(client, session_factory):
    from app.models.workflow import Workflow

    ws = _default_workspace_id(session_factory)
    other_ws = _new_workspace(session_factory)
    kid, hdr = _key(client, ws)
    before = _counts(session_factory)

    r = _create(client, hdr, tenantId=FOREIGN_TENANT, workspaceId=other_ws)
    assert r.status_code == 201, r.text
    item = r.json()
    assert set(item) >= {
        "id", "name", "description", "isActive", "publishedVersionId", "triggerType",
        "draftDefinition", "createdBy", "createdAt", "updatedAt",
    }
    assert item["name"] == "From key"
    assert item["description"] == "d"
    assert item["isActive"] is False
    assert item["publishedVersionId"] is None
    assert item["draftDefinition"] == EMPTY_DEF
    assert item["createdBy"] == f"apikey:{kid}"
    assert item["createdAt"].endswith("Z") and item["updatedAt"].endswith("Z")

    row = _wf_row(session_factory, item["id"])
    assert row["tenant_id"] == DEFAULT_TENANT_ID
    assert row["created_by"] == f"apikey:{kid}"
    assert row["is_active"] is False
    assert row["current_version_id"] is None
    assert _owner_rows(session_factory, item["id"]) == [(DEFAULT_TENANT_ID, ws, f"apikey:{kid}")]
    assert _counts(session_factory) == (before[0] + 1, before[1] + 1)


@pytest.mark.parametrize(
    "body",
    [
        {"draftDefinition": EMPTY_DEF},
        {"name": "", "draftDefinition": EMPTY_DEF},
        {"name": "x"},
        {"name": "x", "draftDefinition": "nope"},
    ],
    ids=["no-name", "empty-name", "no-definition", "definition-not-object"],
)
def test_ac_38_121_create_validation_writes_nothing(client, session_factory, body):
    ws = _default_workspace_id(session_factory)
    _, hdr = _key(client, ws)
    before = _wf_count(session_factory)
    r = client.post(f"{BASE}/workflows", json=body, headers=hdr)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_request"
    assert _wf_count(session_factory) == before


# -- AC-38-122 ------------------------------------------------------------------
def test_ac_38_122_list_own_workspace_only_paged(client, session_factory):
    ws = _default_workspace_id(session_factory)
    ws2 = _new_workspace(session_factory)
    _, hdr = _key(client, ws)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)

    mine = [
        _seed_wf(session_factory, owner_ws=ws, name=f"mine-{i}", created_at=base + timedelta(minutes=i))
        for i in range(5)
    ]
    # a tie on createdAt: ordering by id must still page without dupes or gaps
    tie_at = base + timedelta(minutes=10)
    mine.append(_seed_wf(session_factory, owner_ws=ws, name="tie-a", created_at=tie_at))
    mine.append(_seed_wf(session_factory, owner_ws=ws, name="tie-b", created_at=tie_at))

    excluded = {
        _seed_wf(session_factory, name="unowned"),
        _seed_wf(session_factory, owner_ws=ws2, name="other-workspace"),
        # a foreign tenant's owner row that carries the SAME workspace id
        _seed_wf(
            session_factory, owner_ws=ws, owner_tenant=FOREIGN_TENANT, wf_tenant=FOREIGN_TENANT,
            name="foreign-same-ws",
        ),
        _seed_wf(session_factory, owner_ws=ws, name="archived", trashed=True),
    }

    seen, stamps, cursor, pages = [], [], None, 0
    while True:
        url = f"{BASE}/workflows?limit=3" + (f"&cursor={cursor}" if cursor else "")
        r = client.get(url, headers=hdr)
        assert r.status_code == 200, r.text
        page = r.json()
        assert len(page["data"]) <= 3
        seen += [i["id"] for i in page["data"]]
        stamps += [i["createdAt"] for i in page["data"]]
        pages += 1
        cursor = page["nextCursor"]
        if cursor is None:
            break
        assert pages < 10
    assert pages == 3
    assert len(seen) == len(set(seen)), "duplicate across pages"
    assert set(seen) == set(mine)
    assert not (set(seen) & excluded)
    assert stamps == sorted(stamps, reverse=True), "newest createdAt first"


def test_ac_38_122_default_limit_is_50_and_max_100(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _, hdr = _key(client, ws)
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        for i in range(60):
            wid = str(uuid.uuid4())
            db.add(Workflow(id=wid, tenant_id=DEFAULT_TENANT_ID, name=f"w{i}", description="",
                            draft_definition_json=dict(EMPTY_DEF), created_by="seed",
                            created_at=base + timedelta(seconds=i)))
            db.flush()
            db.add(_owner_cls()(tenant_id=DEFAULT_TENANT_ID, workflow_id=wid, workspace_id=ws,
                                created_by="apikey:seed"))
        db.commit()
    finally:
        db.close()
    r = client.get(f"{BASE}/workflows", headers=hdr)
    assert r.status_code == 200
    assert len(r.json()["data"]) == 50 and r.json()["nextCursor"] is not None
    r = client.get(f"{BASE}/workflows?limit=100", headers=hdr)
    assert r.status_code == 200 and len(r.json()["data"]) == 60 and r.json()["nextCursor"] is None


@pytest.mark.parametrize(
    "query", ["limit=0", "limit=101", "limit=-1", "limit=abc", "cursor=not-a-real-cursor"]
)
def test_ac_38_122_bad_limit_or_cursor_is_422(client, session_factory, query):
    ws = _default_workspace_id(session_factory)
    _, hdr = _key(client, ws)
    r = client.get(f"{BASE}/workflows?{query}", headers=hdr)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_request"


# -- AC-38-123 ------------------------------------------------------------------
# S3 extends this table with more routes (publish, versions, runs, ...). Each row:
# (method, path with {id}, json body or None).
NOT_OWNED_ROUTES = [
    ("GET", "/workflows/{id}", None),
    ("PATCH", "/workflows/{id}", {"name": "hijack"}),
    ("DELETE", "/workflows/{id}", None),
    # S3 routes (plan 38 S3)
    ("POST", "/workflows/{id}/unpublish", None),
    ("PUT", "/workflows/{id}/active", {"isActive": True}),
    ("GET", "/workflows/{id}/versions", None),
    ("GET", "/workflows/{id}/runs", None),
    ("POST", "/workflows/{id}/runs", {"contact": "phone:+60177099999"}),
]
NOT_OWNED_REASONS = ["unowned", "other_workspace", "foreign_tenant", "archived", "unknown"]


def _reason_workflow(session_factory, reason, ws, ws2):
    if reason == "unowned":
        return _seed_wf(session_factory, name="unowned")
    if reason == "other_workspace":
        return _seed_wf(session_factory, owner_ws=ws2, name="other-ws")
    if reason == "foreign_tenant":
        return _seed_wf(
            session_factory, owner_ws=ws, owner_tenant=FOREIGN_TENANT, wf_tenant=FOREIGN_TENANT,
            name="foreign",
        )
    if reason == "archived":
        return _seed_wf(session_factory, owner_ws=ws, trashed=True, name="archived")
    return str(uuid.uuid4())


@pytest.mark.parametrize("reason", NOT_OWNED_REASONS)
@pytest.mark.parametrize(
    "method,path,body", NOT_OWNED_ROUTES, ids=[f"{m} {p}" for m, p, _ in NOT_OWNED_ROUTES]
)
def test_ac_38_123_not_owned_uniform_404_every_route(client, session_factory, method, path, body, reason):
    ws = _default_workspace_id(session_factory)
    ws2 = _new_workspace(session_factory)
    _, hdr = _key(client, ws)
    wid = _reason_workflow(session_factory, reason, ws, ws2)

    rows_before = _wf_row(session_factory, wid)
    counts_before = _counts(session_factory)
    r = client.request(method, BASE + path.replace("{id}", wid), json=body, headers=hdr)

    assert r.status_code == 404, r.text
    assert r.json() == NOT_FOUND
    # byte-identical for every reason: compare against a plain unknown id
    ref = client.request(
        method, BASE + path.replace("{id}", str(uuid.uuid4())), json=body, headers=hdr
    )
    assert ref.status_code == 404
    assert r.content == ref.content
    # nothing changed
    assert _wf_row(session_factory, wid) == rows_before
    assert _counts(session_factory) == counts_before


# -- AC-38-124 ------------------------------------------------------------------
def test_ac_38_124_delete_archives_restore_keeps_owner(client, session_factory):
    from app.services.workflow_service import WorkflowService

    ws = _default_workspace_id(session_factory)
    kid, hdr = _key(client, ws)
    wid = _create(client, hdr).json()["id"]
    owner_before = _owner_rows(session_factory, wid)
    assert owner_before == [(DEFAULT_TENANT_ID, ws, f"apikey:{kid}")]
    counts = _counts(session_factory)

    r = client.delete(f"{BASE}/workflows/{wid}", headers=hdr)
    assert r.status_code == 204
    assert r.content == b""
    row = _wf_row(session_factory, wid)
    assert row is not None and row["is_trashed"] is True and row["is_active"] is False
    assert _counts(session_factory) == counts, "archived, never deleted"
    assert _owner_rows(session_factory, wid) == owner_before

    for method, body in (("GET", None), ("PATCH", {"name": "x"}), ("DELETE", None)):
        r = client.request(method, f"{BASE}/workflows/{wid}", json=body, headers=hdr)
        assert r.status_code == 404 and r.json() == NOT_FOUND
    assert wid not in [i["id"] for i in client.get(f"{BASE}/workflows", headers=hdr).json()["data"]]

    db = session_factory()
    try:
        WorkflowService(db).restore(wid, DEFAULT_TENANT_ID)
    finally:
        db.close()
    r = client.get(f"{BASE}/workflows/{wid}", headers=hdr)
    assert r.status_code == 200, r.text
    assert r.json()["id"] == wid
    assert _owner_rows(session_factory, wid) == owner_before


# -- AC-38-126 ------------------------------------------------------------------
def test_ac_38_126_second_key_sees_revoke_keeps_running(client, session_factory):
    ws = _default_workspace_id(session_factory)
    kid1, hdr1 = _key(client, ws, "creator")
    _, hdr2 = _key(client, ws, "second")
    wid = _create(client, hdr1).json()["id"]

    # make it look live: published, active
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        w = db.query(Workflow).filter(Workflow.id == wid).one()
        w.is_active = True
        w.current_version_id = "version-live-1"
        db.commit()
    finally:
        db.close()

    assert wid in [i["id"] for i in client.get(f"{BASE}/workflows", headers=hdr2).json()["data"]]
    r = client.patch(f"{BASE}/workflows/{wid}", json={"name": "By second"}, headers=hdr2)
    assert r.status_code == 200, r.text
    assert r.json()["name"] == "By second"

    before = _wf_row(session_factory, wid)
    rev = client.post(f"/omnichannel/workspaces/{ws}/api-keys/{kid1}/revoke", headers=_auth(client))
    assert rev.status_code == 200
    after = _wf_row(session_factory, wid)
    assert (after["is_active"], after["current_version_id"], after["is_trashed"]) == (True, "version-live-1", False)
    assert after == before
    assert _owner_rows(session_factory, wid) == [(DEFAULT_TENANT_ID, ws, f"apikey:{kid1}")]
    assert client.get(f"{BASE}/workflows/{wid}", headers=hdr2).status_code == 200


# -- AC-38-127 ------------------------------------------------------------------
def _seed_many_owned(session_factory, ws, n, *, trashed_extra=0):
    from app.models.workflow import Workflow

    db = session_factory()
    try:
        for i in range(n + trashed_extra):
            wid = str(uuid.uuid4())
            db.add(Workflow(id=wid, tenant_id=DEFAULT_TENANT_ID, name=f"cap-{i}", description="",
                            draft_definition_json=dict(EMPTY_DEF), created_by="seed",
                            is_trashed=i >= n))
            db.flush()
            db.add(_owner_cls()(tenant_id=DEFAULT_TENANT_ID, workflow_id=wid, workspace_id=ws,
                                created_by="apikey:seed"))
        db.commit()
    finally:
        db.close()


def test_ac_38_127_cap_200(client, session_factory):
    ws = _default_workspace_id(session_factory)
    _, hdr = _key(client, ws)
    # 199 live + 5 archived: archived rows must not count
    _seed_many_owned(session_factory, ws, 199, trashed_extra=5)
    r = _create(client, hdr)
    assert r.status_code == 201, r.text  # the 200th live one still fits

    counts = _counts(session_factory)
    r = _create(client, hdr)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "invalid_request"
    assert _counts(session_factory) == counts, "no new Workflow and no new owner row"

    # another workspace of the same tenant is not capped by this one
    ws2 = _new_workspace(session_factory)
    _, hdr2 = _key(client, ws2)
    assert _create(client, hdr2).status_code == 201


# -- AC-38-125 ------------------------------------------------------------------
def test_ac_38_125_migration_file():
    versions = Path(__file__).resolve().parents[1] / "modules/omnichannel/alembic/versions"
    target = versions / "0024_omni_workflow_owner.py"
    assert target.exists(), "migration 0024_omni_workflow_owner.py is missing"

    def _consts(path):
        out = {}
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ("revision", "down_revision"):
                    try:
                        out[node.targets[0].id] = ast.literal_eval(node.value)
                    except ValueError:
                        pass
        return out

    mine = _consts(target)
    assert mine.get("revision") == "0024_omni_workflow_owner"
    assert len(mine["revision"]) <= 32
    assert mine.get("down_revision") == "0023_omni_webhook_all_channels"

    revs, downs = {}, set()
    for f in versions.glob("*.py"):
        c = _consts(f)
        if "revision" in c:
            revs[c["revision"]] = f.name
            parents = c.get("down_revision")
            if isinstance(parents, str):
                parents = [parents]
            downs.update(parents or [])
    heads = [r for r in revs if r not in downs]
    assert heads == ["0024_omni_workflow_owner"], f"expected one head, got {heads}"
    text = target.read_text()
    assert "workflow_owners" in text and re.search(r"inspect|has_table|IF NOT EXISTS|checkfirst", text), (
        "migration must create workflow_owners idempotently"
    )


@pytest.mark.parametrize("reason", NOT_OWNED_REASONS)
def test_ac_38_123_run_detail_of_not_owned_workflow_uniform_404(client, session_factory, reason):
    """GET /workflows/runs/{runId} on a run of an unowned / other-workspace / foreign-tenant /
    archived workflow, or an unknown run id: the same 404 body, nothing changed."""
    from app.models.workflow import WorkflowRun

    ws = _default_workspace_id(session_factory)
    ws2 = _new_workspace(session_factory)
    _, hdr = _key(client, ws)
    wid = _reason_workflow(session_factory, reason, ws, ws2)
    if reason == "unknown":
        run_id = str(uuid.uuid4())
    else:
        db = session_factory()
        try:
            wf_tenant = FOREIGN_TENANT if reason == "foreign_tenant" else DEFAULT_TENANT_ID
            run = WorkflowRun(tenant_id=wf_tenant, workflow_id=wid, status="success",
                              definition_snapshot_json=dict(EMPTY_DEF), trigger_payload_json={})
            db.add(run)
            db.commit()
            run_id = run.id
        finally:
            db.close()
    before = _counts(session_factory)
    r = client.get(f"{BASE}/workflows/runs/{run_id}", headers=hdr)
    assert r.status_code == 404, r.text
    assert r.json() == NOT_FOUND
    ref = client.get(f"{BASE}/workflows/runs/{uuid.uuid4()}", headers=hdr)
    assert r.content == ref.content
    assert _counts(session_factory) == before


# -- AC-38-145 ------------------------------------------------------------------
def _key_activity(session_factory, key_id):
    from app.models.integration_activity import IntegrationActivity

    db = session_factory()
    try:
        return [(r.operation, r.status_code, r.status, r.workspace_id, r.api_key_id, r.method)
                for r in db.query(IntegrationActivity)
                .filter(IntegrationActivity.api_key_id == key_id).all()]
    finally:
        db.close()


def _shortcut_doc():
    return {
        "schemaVersion": 1,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "entity.shortcut",
             "config": {"entityType": "omnichannel_contact"}},
            {"id": "note_1", "kind": "action", "type": "omnichannel.add_comment",
             "config": {"contactId": "{{ trigger.record.id }}", "body": "hello"}},
        ],
        "edges": [{"id": "e1", "source": "trg", "target": "note_1"}],
    }


def test_ac_38_145_logs_and_actor_attribution(client, session_factory):
    from app.models.workflow import Workflow, WorkflowRun, WorkflowVersion
    from tests.test_omnichannel_contacts_module import _seed_contact

    ws = _default_workspace_id(session_factory)
    kid, hdr = _key(client, ws)
    contact = _seed_contact(session_factory, ws, first="Log", phone="+60177050001")
    unknown = str(uuid.uuid4())
    seen = []

    def call(method, path, status, **kw):
        url = BASE + path
        r = client.request(method, url, headers=hdr, **kw)
        assert r.status_code == status, (method, path, r.status_code, r.text)
        rows = _key_activity(session_factory, kid)
        assert len(rows) == len(seen) + 1, f"{method} {path}: exactly one Developer Logs row"
        newest = [x for x in rows if x not in seen]
        assert len(newest) == 1
        op, code, st, row_ws, row_key, row_method = newest[0]
        assert op == f"{method} {path.split('?')[0]}"
        assert code == status and row_ws == ws and row_key == kid and row_method == method
        assert st == ("success" if status < 400 else "error")
        seen.append(newest[0])
        return r

    call("GET", "/workflows/catalog", 200)
    call("POST", "/workflows/validate", 200, json={"draftDefinition": _shortcut_doc()})
    created = call("POST", "/workflows", 201, json={"name": "Logged", "draftDefinition": _shortcut_doc()}).json()
    wid = created["id"]
    assert created["createdBy"] == f"apikey:{kid}"
    call("GET", "/workflows", 200)
    call("GET", f"/workflows/{wid}", 200)
    call("PATCH", f"/workflows/{wid}", 200, json={"name": "Logged 2"})
    call("POST", f"/workflows/{wid}/publish", 200)
    call("PUT", f"/workflows/{wid}/active", 200, json={"isActive": True})
    call("GET", f"/workflows/{wid}/versions", 200)
    run = call("POST", f"/workflows/{wid}/runs", 202, json={"contact": contact}).json()
    call("GET", f"/workflows/{wid}/runs", 200)
    call("GET", f"/workflows/runs/{run['id']}", 200)
    call("GET", "/business-hours", 200)
    call("PUT", "/business-hours", 200, json={"timezone": "UTC", "windows": {d: [] for d in
         ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}})
    call("POST", f"/workflows/{wid}/unpublish", 200)
    # refusals to a valid key are logged too
    call("GET", f"/workflows/{unknown}", 404)
    call("POST", "/workflows", 422, json={"name": "", "draftDefinition": _shortcut_doc()})
    call("POST", f"/workflows/{wid}/runs", 409, json={"contact": contact})  # unpublished now
    call("POST", f"/workflows/{wid}/runs", 404, json={"contact": unknown})
    call("PUT", "/business-hours", 422, json={"timezone": "Mars/Olympus", "windows": {}})
    call("DELETE", f"/workflows/{wid}", 204)

    # attribution: the stored author, publisher and run actor are the key
    db = session_factory()
    try:
        assert db.query(Workflow).filter(Workflow.id == wid).one().created_by == f"apikey:{kid}"
        assert {v.published_by for v in db.query(WorkflowVersion)
                .filter(WorkflowVersion.workflow_id == wid).all()} == {f"apikey:{kid}"}
        assert {r.actor_id for r in db.query(WorkflowRun).filter(WorkflowRun.workflow_id == wid).all()} \
            == {f"apikey:{kid}"}
    finally:
        db.close()


def _name_fields(node, path=""):
    """Every (path, value) of a key ending in `Name` in a JSON structure."""
    if isinstance(node, dict):
        for k, v in node.items():
            if k.endswith("Name") and isinstance(v, str):
                yield f"{path}.{k}", v
            yield from _name_fields(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _name_fields(v, f"{path}[{i}]")


def test_ac_38_145_dashboard_routes_serve_key_owned_workflow(client, session_factory):
    from tests.test_omnichannel_contacts_module import _seed_contact

    ws = _default_workspace_id(session_factory)
    kid, hdr = _key(client, ws)
    contact = _seed_contact(session_factory, ws, first="Dash", phone="+60177050002")
    wid = client.post(f"{BASE}/workflows", json={"name": "Dash wf", "draftDefinition": _shortcut_doc()},
                      headers=hdr).json()["id"]
    assert client.post(f"{BASE}/workflows/{wid}/publish", headers=hdr).status_code == 200
    assert client.put(f"{BASE}/workflows/{wid}/active", json={"isActive": True}, headers=hdr).status_code == 200
    run = client.post(f"{BASE}/workflows/{wid}/runs", json={"contact": contact}, headers=hdr)
    assert run.status_code == 202, run.text
    run_id = run.json()["id"]

    staff = _auth(client)
    responses = {
        "list": client.get("/workflows", headers=staff),
        "detail": client.get(f"/workflows/{wid}", headers=staff),
        "versions": client.get(f"/workflows/{wid}/versions", headers=staff),
        "runs": client.get(f"/workflows/{wid}/runs", headers=staff),
        "run detail": client.get(f"/workflows/runs/{run_id}", headers=staff),
    }
    for label, r in responses.items():
        assert r.status_code == 200, (label, r.status_code, r.text)
        for path, value in _name_fields(r.json()):
            assert "apikey:" not in value, f"{label} leaks the raw author in {path}: {value!r}"
    assert wid in [i["id"] for i in responses["list"].json()["data"]]
    assert responses["detail"].json()["id"] == wid
    assert len(responses["versions"].json()["data"]) == 1
    assert [x["id"] for x in responses["runs"].json()["data"]] == [run_id]
    assert responses["run detail"].json()["id"] == run_id
