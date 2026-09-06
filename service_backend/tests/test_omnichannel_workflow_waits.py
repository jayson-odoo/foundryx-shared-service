"""Plan sprint-4/31 (A5b) S4 - park/resume, `workflow_waits`, Ask a question,
Wait, the inbound resume hook and the beat sweep. Covers AC-WFP-41..54.

Reuses the existing omnichannel/workflow test seams (`_seed_thread`,
`_channel_id`, `_process`, `_wa_payload`, `_runs_for`) rather than duplicating
fixtures.
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import (
    NODE_SKIPPED,
    NODE_SUCCESS,
    RUN_CANCELLED,
    RUN_PENDING,
    RUN_SUCCESS,
    RUN_WAITING,
    Workflow,
    WorkflowRun,
    WorkflowRunNode,
)
from app.services.workflow_service import WorkflowService
from app.workflow_engine.schemas import WorkflowValidationError, validate_definition
from modules.omnichannel.models import ConversationMessage, WorkflowWait
from modules.omnichannel.services import workflow_waits as waits
from modules.omnichannel.services.workflow_actions import (
    ActionError,
    omnichannel_ask_question,
    omnichannel_wait,
)
from tests.test_omnichannel_conversations import _seed_thread
from tests.test_omnichannel_webhooks import _channel_id, _process, _wa_payload
from tests.test_omnichannel_workflow_parity_triggers import _runs_for


def _now() -> datetime:
    return datetime.now(timezone.utc)


ASK_CONFIG = {
    "contactId": "{{ trigger.contact.id }}",
    "mode": "text",
    "message": "Which plan do you want?",
    "answerType": "choice",
    "choices": ["Basic", "Pro"],
    "retryLimit": "1",
    "retryMessage": "Please pick Basic or Pro.",
    "timeoutValue": "1",
    "timeoutUnit": "hours",
}


def _ask_doc(ask_config=None, *, serialized=True, tail=True):
    """message_received -> ask -> (answer: comment) / (timeout: comment)."""
    nodes = [
        {
            "id": "trg",
            "kind": "trigger",
            "type": "omnichannel.message_received",
            "config": {},
        },
        {
            "id": "ask_1",
            "kind": "action",
            "type": "omnichannel.ask_question",
            "config": ask_config or dict(ASK_CONFIG),
        },
    ]
    edges = [{"id": "e1", "source": "trg", "target": "ask_1"}]
    if tail:
        nodes += [
            {
                "id": "answered",
                "kind": "action",
                "type": "omnichannel.add_comment",
                "config": {
                    "name": "Answered note",
                    "contactId": "{{ trigger.contact.id }}",
                    "body": "Picked {{ nodes.ask_1.answer }}",
                },
            },
            {
                "id": "gaveup",
                "kind": "action",
                "type": "omnichannel.add_comment",
                "config": {
                    "name": "Gave up note",
                    "contactId": "{{ trigger.contact.id }}",
                    "body": "No answer ({{ nodes.ask_1.reason }})",
                },
            },
        ]
        edges += [
            {"id": "e2", "source": "ask_1", "target": "answered", "sourcePort": "answer"},
            {"id": "e3", "source": "ask_1", "target": "gaveup", "sourcePort": "timeout"},
        ]
    doc = {"schemaVersion": 2, "nodes": nodes, "edges": edges}
    if serialized:
        doc["execution"] = {"mode": "serialized", "correlationKey": "{{ trigger.contact.id }}"}
    return doc


def _publish_doc(db, doc, name="S4 ask"):
    service = WorkflowService(db)
    wf = service.create(
        DEFAULT_TENANT_ID, name=name, description="", draft=doc, actor_id=None
    )
    service.set_active(wf.id, DEFAULT_TENANT_ID, True)
    service.publish(wf.id, DEFAULT_TENANT_ID, actor_id=None)
    db.refresh(wf)
    return wf


def _inbound(session_factory, channel_id, *, wamid, phone="60111222333", text="hello"):
    return _process(
        session_factory, channel_id, _wa_payload(wamid=wamid, from_=phone, text=text)
    )


def _run_of(db, wf_id):
    runs = _runs_for(db, wf_id)
    assert len(runs) == 1, [r.status for r in runs]
    return runs[0]


def _wait_rows(db):
    return db.query(WorkflowWait).all()


def _park_via_inbound(session_factory, *, doc=None, phone="60111222333"):
    """Publish an ask workflow, drive one inbound message, return (wf_id, contact_id)
    with the run PARKED."""
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        wf = _publish_doc(db, doc or _ask_doc())
        wf_id = wf.id
    finally:
        db.close()
    _inbound(session_factory, channel_id, wamid="wamid.s4-1", phone=phone, text="hi")
    db = session_factory()
    try:
        from modules.omnichannel.models import Contact

        contact = db.query(Contact).filter(Contact.phone == f"+{phone}").first()
        return wf_id, contact.id, channel_id
    finally:
        db.close()


# ── AC-WFP-41/43: park + wait row ───────────────────────────────────────────
def test_ask_question_parks_the_run_and_writes_one_wait_row(session_factory):
    wf_id, contact_id, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        assert run.status == RUN_WAITING
        assert run.paused_node_id == "ask_1"
        assert run.finished_at is None
        state = run.resume_state_json
        assert state["active"] and "ask_1" in state["active"]
        assert state["ctx"]["trigger.contact.id"] == contact_id
        assert isinstance(state["index"], int)

        rows = {rn.node_id: rn for rn in run.nodes}
        # The parked node succeeded + is flagged parked; DOWNSTREAM nodes have
        # NO trace row at all (they are not skipped - they have not happened).
        assert rows["ask_1"].status == NODE_SUCCESS
        assert rows["ask_1"].output_json["parked"] is True
        assert rows["ask_1"].output_json["answerType"] == "choice"
        assert "answered" not in rows and "gaveup" not in rows

        wait = db.query(WorkflowWait).one()
        assert wait.kind == "question"
        assert wait.contact_id == contact_id
        assert wait.run_id == run.id and wait.node_id == "ask_1"
        assert wait.retry_count == 0
        assert wait.answer_spec_json["answerType"] == "choice"
        assert wait.answer_spec_json["choices"] == ["Basic", "Pro"]
        assert wait.deadline_at > _now()

        # AC-WFP-48: the sent message lists the numbered choices.
        sent = (
            db.query(ConversationMessage)
            .filter(
                ConversationMessage.contact_id == contact_id,
                ConversationMessage.sender_type == "AGENT",
            )
            .all()
        )
        assert len(sent) == 1
        assert "Which plan do you want?" in sent[0].body
        assert "1. Basic" in sent[0].body and "2. Pro" in sent[0].body
    finally:
        db.close()


# ── AC-WFP-45/46/42: inbound resume, message CONSUMED ───────────────────────
def test_inbound_answer_resumes_the_run_and_is_not_dispatched_as_message_received(
    session_factory,
):
    wf_id, contact_id, channel_id = _park_via_inbound(session_factory)
    _inbound(session_factory, channel_id, wamid="wamid.s4-2", text="pro")

    db = session_factory()
    try:
        # Exactly ONE run: the answering message did NOT start a second
        # `message_received` run (D-A5-8 / AC-WFP-45).
        run = _run_of(db, wf_id)
        assert run.status == RUN_SUCCESS
        assert run.paused_node_id is None and run.resume_state_json is None
        assert run.finished_at is not None
        assert _wait_rows(db) == []

        rows = {rn.node_id: rn for rn in run.nodes}
        # The parked node's ORIGINAL trace row was completed in place - one row.
        assert len([rn for rn in run.nodes if rn.node_id == "ask_1"]) == 1
        assert rows["ask_1"].output_json["answer"] == "Pro"
        assert rows["ask_1"].output_json["answerRaw"] == "pro"
        assert rows["ask_1"].output_json["answerKey"] == "2"
        assert rows["ask_1"].output_json["timedOut"] is False
        # Only the ANSWER branch ran; the timeout branch is skipped.
        assert rows["answered"].status == NODE_SUCCESS
        assert rows["gaveup"].status == NODE_SKIPPED
        # And the trigger node's original trace row was NOT re-executed.
        assert len([rn for rn in run.nodes if rn.node_id == "trg"]) == 1

        notes = [
            m.body
            for m in db.query(ConversationMessage)
            .filter(ConversationMessage.contact_id == contact_id)
            .all()
            if (m.body or "").startswith("Picked")
        ]
        assert notes == ["Picked Pro"]
    finally:
        db.close()


# ── AC-WFP-48: choice matching by label (case/space) and by position ─────────
@pytest.mark.parametrize("reply,expected", [("  BASIC ", "Basic"), ("1", "Basic"), ("Pro", "Pro")])
def test_choice_answers_match_case_insensitively_and_by_position(reply, expected):
    spec = {"answerType": "choice", "choices": ["Basic", "Pro"]}
    ok, out = waits.validate_answer(spec, reply)
    assert ok and out["answer"] == expected


@pytest.mark.parametrize(
    "answer_type,reply,ok",
    [
        ("text", "anything", True),
        ("text", "   ", False),
        ("number", "42", True),
        ("number", "forty two", False),
        ("email", "a@b.co", True),
        ("email", "a@b", False),
        ("phone", "+60 12-345 6789", True),
        ("phone", "12", False),
        ("choice", "Gold", False),
    ],
)
def test_answer_validation_matrix(answer_type, reply, ok):
    spec = {"answerType": answer_type, "choices": ["Basic", "Pro"]}
    assert waits.validate_answer(spec, reply)[0] is ok


# ── AC-WFP-47: retry then timeout-port exhaustion ────────────────────────────
def test_invalid_answer_re_asks_then_exhausts_onto_the_timeout_port(session_factory):
    wf_id, contact_id, channel_id = _park_via_inbound(session_factory)
    _inbound(session_factory, channel_id, wamid="wamid.s4-bad1", text="maybe")

    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        assert run.status == RUN_WAITING  # still parked
        wait = db.query(WorkflowWait).one()
        assert wait.retry_count == 1
        bodies = [
            m.body
            for m in db.query(ConversationMessage)
            .filter(ConversationMessage.sender_type == "AGENT")
            .all()
        ]
        assert "Please pick Basic or Pro." in bodies
    finally:
        db.close()

    # Second invalid answer - retry cap (1) reached -> timeout port, reason invalid.
    _inbound(session_factory, channel_id, wamid="wamid.s4-bad2", text="nope")
    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        assert run.status == RUN_SUCCESS
        assert _wait_rows(db) == []
        rows = {rn.node_id: rn for rn in run.nodes}
        assert rows["ask_1"].output_json["timedOut"] is True
        assert rows["ask_1"].output_json["reason"] == "invalid"
        assert rows["gaveup"].status == NODE_SUCCESS
        assert rows["answered"].status == NODE_SKIPPED
    finally:
        db.close()


# ── AC-WFP-44: one open question per contact ────────────────────────────────
def test_second_ask_for_the_same_contact_fails_and_keeps_the_first_wait(session_factory):
    wf_id, contact_id, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        first = db.query(WorkflowWait).one()
        first_id, first_run = first.id, first.run_id
        ctx = {
            "_workflow.runId": "other-run",
            "_workflow.workflowId": "other-wf",
            "_workflow.nodeId": "ask_x",
            "_workflow.canPark": True,
            "trigger.contact.id": contact_id,
        }
        with pytest.raises(ActionError) as exc:
            omnichannel_ask_question(
                db, DEFAULT_TENANT_ID, {**ASK_CONFIG, "contactId": contact_id}, ctx
            )
        assert "already has an open question" in str(exc.value)
        db.expire_all()
        rows = _wait_rows(db)
        assert len(rows) == 1 and rows[0].id == first_id and rows[0].run_id == first_run
        # It never messaged the contact for the refused ask.
        sent = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.sender_type == "AGENT")
            .count()
        )
        assert sent == 1
    finally:
        db.close()


# ── AC-WFP-49: the beat sweep times a question out ──────────────────────────
def test_sweep_times_out_a_question_on_the_timeout_port_and_is_idempotent(session_factory):
    wf_id, contact_id, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        db.query(WorkflowWait).update({WorkflowWait.deadline_at: _now() - timedelta(minutes=5)})
        db.commit()
        result = waits.sweep_due_waits(db, now=_now())
        assert result["resumed"] == 1
    finally:
        db.close()

    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        assert run.status == RUN_SUCCESS
        assert _wait_rows(db) == []
        rows = {rn.node_id: rn for rn in run.nodes}
        assert rows["ask_1"].output_json["reason"] == "timeout"
        assert rows["ask_1"].output_json["timedOut"] is True
        assert rows["gaveup"].status == NODE_SUCCESS
        # A second tick has nothing to do - never resumes the same wait twice.
        assert waits.sweep_due_waits(db, now=_now()) == {"resumed": 0, "discarded": 0}
        assert len(_runs_for(db, wf_id)) == 1
    finally:
        db.close()


def test_sweep_discards_a_wait_whose_run_is_gone(session_factory):
    _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        db.add(
            WorkflowWait(
                tenant_id=DEFAULT_TENANT_ID,
                run_id="ghost-run",
                workflow_id="ghost-wf",
                node_id="ask_1",
                kind="question",
                deadline_at=_now() - timedelta(minutes=1),
            )
        )
        db.commit()
        assert waits.sweep_due_waits(db, now=_now()) == {"resumed": 0, "discarded": 1}
        assert _wait_rows(db) == []
    finally:
        db.close()


def test_sweep_is_bounded_per_tick(session_factory):
    db = session_factory()
    try:
        for i in range(5):
            db.add(
                WorkflowWait(
                    tenant_id=DEFAULT_TENANT_ID,
                    run_id=f"ghost-{i}",
                    workflow_id="ghost-wf",
                    node_id="ask_1",
                    kind="question",
                    deadline_at=_now() - timedelta(minutes=1),
                )
            )
        db.commit()
        assert waits.sweep_due_waits(db, now=_now(), limit=2)["discarded"] == 2
        assert len(_wait_rows(db)) == 3
    finally:
        db.close()


# ── AC-WFP-50: the plain Wait step ──────────────────────────────────────────
def _wait_doc():
    return {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trg", "kind": "trigger", "type": "omnichannel.message_received", "config": {}},
            {
                "id": "hold",
                "kind": "action",
                "type": "omnichannel.wait",
                "config": {"waitValue": "2", "waitUnit": "hours"},
            },
            {
                "id": "after",
                "kind": "action",
                "type": "omnichannel.add_comment",
                "config": {
                    "contactId": "{{ trigger.contact.id }}",
                    "body": "Resumed at {{ nodes.hold.resumedAt }}",
                },
            },
        ],
        "edges": [
            {"id": "e1", "source": "trg", "target": "hold"},
            {"id": "e2", "source": "hold", "target": "after"},
        ],
    }


def test_wait_step_parks_on_a_deadline_only_and_the_sweep_resumes_its_out_port(
    session_factory,
):
    _seed_thread(session_factory, messages=[])
    channel_id = _channel_id(session_factory)
    db = session_factory()
    try:
        wf_id = _publish_doc(db, _wait_doc(), name="S4 wait").id
    finally:
        db.close()
    _inbound(session_factory, channel_id, wamid="wamid.s4-w1", phone="60999888777", text="hi")

    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        run_id = run.id
        assert run.status == RUN_WAITING and run.paused_node_id == "hold"
        wait = db.query(WorkflowWait).one()
        wait_id, deadline = wait.id, wait.deadline_at
        assert wait.kind == "delay"
        # A delay wait has NO contact - it can never collide with, or be
        # resumed by, a question for that contact.
        assert wait.contact_id is None and wait.workspace_id is None
    finally:
        db.close()

    # An inbound message does NOT shorten a plain Wait: the parked run stays
    # parked on its original deadline (the new message just starts its own run,
    # since nothing consumed it - a delay is not a question).
    _inbound(session_factory, channel_id, wamid="wamid.s4-w2", phone="60999888777", text="hello?")
    db = session_factory()
    try:
        first = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert first.status == RUN_WAITING and first.paused_node_id == "hold"
        held = db.query(WorkflowWait).filter(WorkflowWait.id == wait_id).one()
        assert held.deadline_at == deadline
        # Only the beat sweep moves it.
        db.query(WorkflowWait).filter(WorkflowWait.id == wait_id).update(
            {WorkflowWait.deadline_at: _now() - timedelta(minutes=1)}
        )
        db.commit()
        assert waits.sweep_due_waits(db, now=_now())["resumed"] == 1
    finally:
        db.close()

    db = session_factory()
    try:
        run = db.query(WorkflowRun).filter(WorkflowRun.id == run_id).one()
        assert run.status == RUN_SUCCESS
        rows = {rn.node_id: rn for rn in run.nodes}
        assert rows["after"].status == NODE_SUCCESS
        assert rows["hold"].output_json["resumedAt"]
    finally:
        db.close()


def test_wait_duration_is_validated_and_capped(session_factory):
    db = session_factory()
    try:
        ctx = {
            "_workflow.runId": "r",
            "_workflow.workflowId": "w",
            "_workflow.nodeId": "n",
            "_workflow.canPark": True,
        }
        for config in (
            {"waitValue": "0", "waitUnit": "hours"},
            {"waitValue": "abc", "waitUnit": "hours"},
            {"waitValue": "5", "waitUnit": "weeks"},
            {"waitValue": "31", "waitUnit": "days"},
        ):
            with pytest.raises(ActionError):
                omnichannel_wait(db, DEFAULT_TENANT_ID, config, ctx)
        assert _wait_rows(db) == []
    finally:
        db.close()


# ── AC-WFP-51: publish refuses a non-serialized Ask graph ───────────────────
def test_publish_refuses_an_ask_graph_without_serialized_execution(session_factory):
    db = session_factory()
    try:
        with pytest.raises(WorkflowValidationError) as exc:
            validate_definition(_ask_doc(serialized=False))
        assert (
            "Ask a question requires serialized execution and a Correlation key."
            in exc.value.issues
        )
        # Serialized + a valid key publishes.
        validate_definition(_ask_doc())
    finally:
        db.close()


def test_parked_run_carries_the_resolved_correlation_key(session_factory):
    wf_id, contact_id, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        assert run.correlation_key == contact_id
        assert run.correlation_key_digest
    finally:
        db.close()


# ── AC-WFP-42: a parked run holds NO serialized lease ───────────────────────
def test_a_parked_run_does_not_block_its_correlation_scope(session_factory):
    from app.workflow_engine.serialization import _live_running_run_id, _LOCAL_LEASES, _lease_key

    wf_id, contact_id, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        # `waiting` is not `running`, so nothing blocks the scope...
        assert (
            _live_running_run_id(
                db,
                DEFAULT_TENANT_ID,
                run.workflow_id,
                run.correlation_key_digest,
                timedelta(seconds=60),
            )
            is None
        )
        # ...and the local (eager) lease was released when the drain returned.
        key = _lease_key(DEFAULT_TENANT_ID, run.workflow_id, run.correlation_key_digest)
        assert _LOCAL_LEASES.acquire(key, "probe", 5) is True
        _LOCAL_LEASES.release(key, "probe")
    finally:
        db.close()


# ── AC-WFP-52: retention / cancel / workflow delete ─────────────────────────
def test_retention_never_prunes_a_waiting_run(session_factory):
    from app.workflow_engine.scheduler import prune_runs

    wf_id, _, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        db.query(WorkflowRun).update({WorkflowRun.created_at: _now() - timedelta(days=400)})
        db.commit()
        prune_runs(db, now=_now())
        db.expire_all()
        assert len(_runs_for(db, wf_id)) == 1
        assert len(_wait_rows(db)) == 1
    finally:
        db.close()


def test_cancelling_a_waiting_run_deletes_its_wait_row(session_factory):
    wf_id, _, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        item = WorkflowService(db).cancel_run(run.id, DEFAULT_TENANT_ID)
        assert item.status == RUN_CANCELLED
        db.expire_all()
        assert _wait_rows(db) == []
        refreshed = db.query(WorkflowRun).filter(WorkflowRun.id == run.id).one()
        assert refreshed.paused_node_id is None and refreshed.resume_state_json is None
    finally:
        db.close()


def test_deleting_the_workflow_clears_its_waits(session_factory):
    wf_id, _, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        WorkflowService(db).remove(wf_id, DEFAULT_TENANT_ID)
        db.commit()
        db.expire_all()
        assert _wait_rows(db) == []
    finally:
        db.close()


def test_unpublishing_leaves_the_parked_run_resumable(session_factory):
    wf_id, contact_id, channel_id = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        WorkflowService(db).unpublish(wf_id, DEFAULT_TENANT_ID)
    finally:
        db.close()
    # The run executes its own SNAPSHOT, so the answer still resumes it.
    _inbound(session_factory, channel_id, wamid="wamid.s4-unpub", text="basic")
    db = session_factory()
    try:
        run = _run_of(db, wf_id)
        assert run.status == RUN_SUCCESS
        assert run.nodes[0].run_id == run.id
        assert _wait_rows(db) == []
    finally:
        db.close()


# ── AC-WFP-53: a test/manual run parks the same way ─────────────────────────
def test_a_test_run_parks_with_a_test_flagged_sandbox_wait(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ctx = {
            "_workflow.runId": "test-run",
            "_workflow.workflowId": "test-wf",
            "_workflow.nodeId": "ask_1",
            "_workflow.canPark": True,
            "_workflow.isTest": True,
            "_workflow.sandboxOnly": True,
        }
        from app.workflow_engine.parking import WorkflowPaused

        with pytest.raises(WorkflowPaused):
            omnichannel_ask_question(
                db, DEFAULT_TENANT_ID, {**ASK_CONFIG, "contactId": cid}, ctx
            )
        wait = db.query(WorkflowWait).one()
        assert wait.is_test is True
        assert wait.answer_spec_json["sandboxOnly"] is True
        # The question message was sandbox-only.
        sent = (
            db.query(ConversationMessage)
            .filter(ConversationMessage.sender_type == "AGENT")
            .order_by(ConversationMessage.created_at.desc())
            .first()
        )
        assert (sent.metadata_json or {}).get("workflowTest", {}).get("sandboxOnly") is True
    finally:
        db.close()


def test_a_parking_step_refuses_to_run_outside_a_resumable_walk(session_factory):
    cid = _seed_thread(session_factory, messages=[])
    db = session_factory()
    try:
        ctx = {
            "_workflow.runId": "r",
            "_workflow.workflowId": "w",
            "_workflow.nodeId": "n",
            "_workflow.canPark": False,  # a debug/partial re-run
        }
        with pytest.raises(ActionError) as exc:
            omnichannel_ask_question(db, DEFAULT_TENANT_ID, {**ASK_CONFIG, "contactId": cid}, ctx)
        assert "run the whole workflow" in str(exc.value)
        assert _wait_rows(db) == []
    finally:
        db.close()


# ── AC-WFP-54: uninstall cancels parked runs + drops the rows ───────────────
def test_uninstalling_the_module_cancels_parked_runs_and_wipes_waits(session_factory):
    wf_id, _, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        from modules.omnichannel.bootstrap import uninstall_tenant

        uninstall_tenant(db, DEFAULT_TENANT_ID)
        db.commit()
        db.expire_all()
        run = _run_of(db, wf_id)
        assert run.status == RUN_CANCELLED
        assert _wait_rows(db) == []
    finally:
        db.close()


# ── AC-WFP-16 parity: waits are tenant-scoped ───────────────────────────────
def test_waits_never_resolve_across_tenants(session_factory):
    wf_id, contact_id, _ = _park_via_inbound(session_factory)
    db = session_factory()
    try:
        assert waits.find_open_question(db, "other-tenant", contact_id) is None
        assert waits.find_open_question(db, DEFAULT_TENANT_ID, contact_id) is not None
        # A foreign-tenant cancel sweep touches nothing.
        assert waits.cancel_parked_runs_for_tenant(db, "other-tenant") == 0
        db.expire_all()
        assert _run_of(db, wf_id).status == RUN_WAITING
    finally:
        db.close()
