"""Business hours - settings routes + the `omnichannel.business_hours`
workflow action (plan sprint-4/31 S5, D-A5-13/F6, AC-WFP-55/56)."""
from datetime import datetime, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_SUCCESS, Workflow, WorkflowRun, WorkflowRunNode
from modules.omnichannel.services.business_hours import (
    BusinessHoursService,
    BusinessHoursValidationError,
    MissingBusinessHours,
    evaluate,
)
from modules.omnichannel.services.workflow_actions import (
    ActionError,
    omnichannel_business_hours,
)
from tests.test_omnichannel_conversations import _auth


def _default_workspace(db):
    from modules.omnichannel.models import Workspace

    return db.query(Workspace).filter(Workspace.is_default.is_(True)).first()


def _default_windows():
    return {
        "mon": [{"from": "09:00", "to": "18:00"}],
        "tue": [{"from": "09:00", "to": "18:00"}],
        "wed": [{"from": "09:00", "to": "18:00"}],
        "thu": [{"from": "09:00", "to": "18:00"}],
        "fri": [{"from": "09:00", "to": "18:00"}],
        "sat": [],
        "sun": [],
    }


# ── AC-WFP-55: save/read + validation ───────────────────────────────────────


def test_save_and_read_business_hours(client, session_factory):
    hdr = _auth(client)
    db = session_factory()
    ws_id = _default_workspace(db).id
    db.close()

    res = client.put(
        f"/omnichannel/workspaces/{ws_id}/business-hours",
        json={"timezone": "Asia/Kuala_Lumpur", "windows": _default_windows()},
        headers=hdr,
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["timezone"] == "Asia/Kuala_Lumpur"
    assert body["windows"]["mon"] == [{"from": "09:00", "to": "18:00"}]

    got = client.get(f"/omnichannel/workspaces/{ws_id}/business-hours", headers=hdr)
    assert got.status_code == 200
    assert got.json()["timezone"] == "Asia/Kuala_Lumpur"


def test_invalid_timezone_returns_422_and_writes_nothing(client, session_factory):
    hdr = _auth(client)
    db = session_factory()
    ws_id = _default_workspace(db).id
    db.close()

    res = client.put(
        f"/omnichannel/workspaces/{ws_id}/business-hours",
        json={"timezone": "Not/AZone", "windows": _default_windows()},
        headers=hdr,
    )
    assert res.status_code == 422
    assert "timezone" in res.json()["detail"]["fieldErrors"]

    got = client.get(f"/omnichannel/workspaces/{ws_id}/business-hours", headers=hdr)
    assert got.json()["timezone"] is None


@pytest.mark.parametrize(
    "windows,bad_key",
    [
        ({"mon": [{"from": "09:00", "to": "09:00"}]}, "windows.mon.0"),  # end == start
        ({"mon": [{"from": "9am", "to": "18:00"}]}, "windows.mon.0"),  # bad format
        ({"mon": "nope"}, "windows.mon"),  # not a list
        ({"notaday": []}, "windows"),  # unknown day key
    ],
)
def test_malformed_window_returns_422_and_writes_nothing(client, session_factory, windows, bad_key):
    hdr = _auth(client)
    db = session_factory()
    ws_id = _default_workspace(db).id
    db.close()

    res = client.put(
        f"/omnichannel/workspaces/{ws_id}/business-hours",
        json={"timezone": "UTC", "windows": windows},
        headers=hdr,
    )
    assert res.status_code == 422
    assert bad_key in res.json()["detail"]["fieldErrors"]
    got = client.get(f"/omnichannel/workspaces/{ws_id}/business-hours", headers=hdr)
    assert got.json()["timezone"] is None


def test_overnight_window_is_valid(client, session_factory):
    """A window whose `to` is lexically <= `from` spans midnight - explicitly
    allowed, not a validation error (§5.4)."""
    hdr = _auth(client)
    db = session_factory()
    ws_id = _default_workspace(db).id
    db.close()

    windows = _default_windows()
    windows["fri"] = [{"from": "22:00", "to": "02:00"}]
    res = client.put(
        f"/omnichannel/workspaces/{ws_id}/business-hours",
        json={"timezone": "UTC", "windows": windows},
        headers=hdr,
    )
    assert res.status_code == 200, res.text
    assert res.json()["windows"]["fri"] == [{"from": "22:00", "to": "02:00"}]


def test_foreign_tenant_workspace_returns_uniform_404(client, session_factory):
    from app.models import Tenant

    hdr = _auth(client)
    db = session_factory()
    default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).one()
    other = Tenant(name="Other Co", slug="other-co-bh", status_id=default_tenant.status_id)
    db.add(other)
    db.flush()
    from modules.omnichannel.models import Workspace

    foreign_ws = Workspace(tenant_id=other.id, name="Foreign", is_default=True)
    db.add(foreign_ws)
    db.commit()
    foreign_id = foreign_ws.id
    db.close()

    res = client.get(f"/omnichannel/workspaces/{foreign_id}/business-hours", headers=hdr)
    assert res.status_code == 404
    res = client.put(
        f"/omnichannel/workspaces/{foreign_id}/business-hours",
        json={"timezone": "UTC", "windows": _default_windows()},
        headers=hdr,
    )
    assert res.status_code == 404

    res = client.get("/omnichannel/workspaces/does-not-exist/business-hours", headers=hdr)
    assert res.status_code == 404


# ── AC-WFP-56: the workflow action evaluates inside/outside + fallback ─────


def test_evaluate_resolves_inside_and_outside(session_factory):
    db = session_factory()
    ws_id = _default_workspace(db).id
    BusinessHoursService(db).set(
        DEFAULT_TENANT_ID, ws_id, timezone="UTC", windows={**_default_windows()}
    )
    monday_noon = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)  # a Monday
    monday_late = datetime(2026, 9, 7, 23, 0, tzinfo=timezone.utc)
    is_open, tz, _checked = evaluate(db, DEFAULT_TENANT_ID, ws_id, at=monday_noon)
    assert is_open is True and tz == "UTC"
    is_open, _tz, _checked = evaluate(db, DEFAULT_TENANT_ID, ws_id, at=monday_late)
    assert is_open is False


def test_evaluate_overnight_window_spans_midnight():
    windows = {**{d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")}, "fri": [{"from": "22:00", "to": "02:00"}]}
    from modules.omnichannel.services.business_hours import _inside

    friday_2330 = datetime(2026, 9, 11, 23, 30, tzinfo=timezone.utc)  # Friday
    saturday_0100 = datetime(2026, 9, 12, 1, 0, tzinfo=timezone.utc)  # Saturday, still open
    saturday_1000 = datetime(2026, 9, 12, 10, 0, tzinfo=timezone.utc)
    assert _inside(windows, friday_2330) is True
    assert _inside(windows, saturday_0100) is True
    assert _inside(windows, saturday_1000) is False


def test_evaluate_end_boundary_is_exclusive():
    """A 09:00-18:00 window is open through 17:59, closed AT 18:00 (plan 31
    review nit) - the conventional business-hours reading, and consistent
    with the overnight branch's own already-exclusive `end`."""
    from modules.omnichannel.services.business_hours import _inside

    windows = _default_windows()
    monday_1759 = datetime(2026, 9, 7, 17, 59, tzinfo=timezone.utc)
    monday_1800 = datetime(2026, 9, 7, 18, 0, tzinfo=timezone.utc)
    assert _inside(windows, monday_1759) is True
    assert _inside(windows, monday_1800) is False


def test_evaluate_falls_back_to_tenant_default_then_fails_loudly(session_factory):
    from modules.omnichannel.models import Workspace

    db = session_factory()
    ws = Workspace(tenant_id=DEFAULT_TENANT_ID, name="No hours of its own")
    db.add(ws)
    db.commit()
    ws_id = ws.id

    with pytest.raises(MissingBusinessHours):
        evaluate(db, DEFAULT_TENANT_ID, ws_id)

    # A tenant-default row (workspace_id NULL) resolves for a workspace with
    # none of its own.
    BusinessHoursService(db).set(
        DEFAULT_TENANT_ID, None, timezone="UTC", windows=_default_windows()
    )
    monday_noon = datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)
    is_open, tz, _checked = evaluate(db, DEFAULT_TENANT_ID, ws_id, at=monday_noon)
    assert is_open is True and tz == "UTC"


def test_action_executor_branches_and_fails_loud_when_unconfigured(session_factory):
    db = session_factory()
    ws_id = _default_workspace(db).id

    with pytest.raises(ActionError):
        omnichannel_business_hours(db, DEFAULT_TENANT_ID, {"workspaceId": ws_id}, {})

    BusinessHoursService(db).set(DEFAULT_TENANT_ID, ws_id, timezone="UTC", windows=_default_windows())
    out = omnichannel_business_hours(db, DEFAULT_TENANT_ID, {"workspaceId": ws_id}, {})
    assert out["branch"] in ("inside", "outside")
    assert out["timezone"] == "UTC"
    assert set(out) >= {"isOpen", "checkedAt", "timezone", "branch"}


def _doc_with_business_hours(ws_id):
    return {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {
                "id": "bh_1",
                "kind": "action",
                "type": "omnichannel.business_hours",
                "config": {"workspaceId": ws_id},
                "position": {},
            },
            {"id": "inside_1", "kind": "action", "type": "omnichannel.add_tag", "config": {"contactId": "missing", "tagId": "missing"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "bh_1"},
            {"id": "e2", "source": "bh_1", "target": "inside_1", "sourcePort": "inside"},
        ],
    }


def test_branching_activates_only_the_taken_port(session_factory):
    """A registry-driven branching action (D-A5-14): only the taken port's
    targets activate - the untaken branch's descendants are SKIPPED, the same
    contract the IF node uses."""
    db = session_factory()
    ws_id = _default_workspace(db).id
    # Configure hours so "now" is definitely OUTSIDE (empty windows every day).
    BusinessHoursService(db).set(
        DEFAULT_TENANT_ID, ws_id, timezone="UTC",
        windows={d: [] for d in ("mon", "tue", "wed", "thu", "fri", "sat", "sun")},
    )
    doc = _doc_with_business_hours(ws_id)
    workflow = Workflow(tenant_id=DEFAULT_TENANT_ID, name="BH", description="", draft_definition_json=doc)
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status="pending",
        definition_snapshot_json=doc,
        trigger_payload_json={"triggeredBy": "manual", "input": {}},
    )
    db.add(run)
    db.commit()
    from app.workflow_engine.executor import run_workflow

    result = run_workflow(db, run.id)
    nodes = {n.node_id: n for n in db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run.id).all()}
    assert result.status == RUN_SUCCESS
    assert nodes["bh_1"].output_json["branch"] == "outside"
    # `inside_1` is wired to the "inside" port only - never open (empty
    # windows), so it must be SKIPPED, never executed against a bogus contact.
    assert nodes["inside_1"].status == "skipped"
