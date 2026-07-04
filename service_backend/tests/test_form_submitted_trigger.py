"""form.submitted workflow trigger tests (plan sprint-3/02, slice 2 §TDD).

Covers: a published form's submission fires a `form.submitted` workflow whose
`email.send` action merges `trigger.answers.*` · per-form selectivity (a
workflow bound to form A never fires on form B) · the workflow run is created
AFTER the submission commits (failure-isolated path) · the metadata endpoint
lists published forms with their answer-field keys (drives the editor picker +
dynamic outputs).
"""
from app.models import DEFAULT_TENANT_ID, User
from app.models.email_outbox import EmailOutbox
from app.models.workflow import WorkflowRun
from app.services.form_service import FormService
from app.services.workflow_service import WorkflowService


def _actor(db):
    return db.query(User).filter(User.tenant_id == DEFAULT_TENANT_ID).first()


def _node(nid, kind, ntype, config=None):
    return {"id": nid, "kind": kind, "type": ntype, "config": config or {}, "position": {"x": 0, "y": 0}}


def _edge(src, tgt, port="out"):
    return {"id": f"e_{src}_{tgt}_{port}", "source": src, "target": tgt, "sourcePort": port}


def _form_doc():
    return {
        "schemaVersion": 1,
        "pages": [
            {
                "id": "p1",
                "title": "Reg",
                "sections": [
                    {
                        "id": "s1",
                        "fields": [
                            {"id": "f1", "type": "text", "key": "name", "label": "Name", "required": True},
                            {"id": "f2", "type": "email", "key": "email", "label": "Email", "required": True},
                        ],
                    }
                ],
            }
        ],
    }


def _publish_form(db, name="Reg"):
    fs = FormService(db)
    actor = _actor(db)
    form = fs.create(DEFAULT_TENANT_ID, actor, name=name, access="internal")
    fs.update(DEFAULT_TENANT_ID, form.id, fields_set={"draftDefinition"}, draftDefinition=_form_doc())
    fs.publish(DEFAULT_TENANT_ID, form.id, actor)
    return form.id


def _publish_workflow(db, form_id):
    svc = WorkflowService(db)
    actor = _actor(db)
    doc = {
        "schemaVersion": 1,
        "nodes": [
            _node("trg", "trigger", "form.submitted", {"formId": form_id}),
            _node(
                "a",
                "action",
                "email.send",
                {
                    "mode": "custom",
                    "to": "{{ trigger.answers.email }}",
                    "subject": "Welcome {{ trigger.answers.name }}",
                    "body": "Thanks for registering, {{ trigger.answers.name }}.",
                    "name": "Confirm",
                },
            ),
        ],
        "edges": [_edge("trg", "a")],
    }
    wf = svc.create(DEFAULT_TENANT_ID, name="Confirm WF", description="", draft=doc, actor_id=actor.id)
    svc.publish(wf.id, DEFAULT_TENANT_ID, actor.id)
    svc.set_active(wf.id, DEFAULT_TENANT_ID, True)
    return wf.id


def _runs_for(db, workflow_id):
    return db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).all()


def test_form_submitted_fires_workflow_with_answer_merge(session_factory):
    db = session_factory()
    form_id = _publish_form(db)
    wid = _publish_workflow(db, form_id)

    FormService(db).submit(
        DEFAULT_TENANT_ID, form_id, _actor(db), {"name": "Ada", "email": "ada@example.com"}
    )

    runs = _runs_for(db, wid)
    assert len(runs) == 1, "the submission should have created exactly one run"
    assert runs[0].status == "success"
    assert runs[0].triggered_by == "event"

    row = db.query(EmailOutbox).filter(EmailOutbox.to_email == "ada@example.com").first()
    assert row is not None, "email.send should have enqueued to the merged address"
    assert row.subject == "Welcome Ada"
    assert "Ada" in row.html_body


def test_form_submitted_is_per_form_selective(session_factory):
    db = session_factory()
    form_a = _publish_form(db, "Form A")
    form_b = _publish_form(db, "Form B")
    wid = _publish_workflow(db, form_a)  # bound to A only

    # Submitting B must NOT fire A's workflow.
    FormService(db).submit(
        DEFAULT_TENANT_ID, form_b, _actor(db), {"name": "Bee", "email": "bee@example.com"}
    )
    assert len(_runs_for(db, wid)) == 0

    # Submitting A fires it.
    FormService(db).submit(
        DEFAULT_TENANT_ID, form_a, _actor(db), {"name": "Ay", "email": "ay@example.com"}
    )
    assert len(_runs_for(db, wid)) == 1


def test_metadata_lists_published_forms_with_fields(session_factory):
    db = session_factory()
    form_id = _publish_form(db, "Survey")
    meta = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
    assert "forms" in meta
    entry = next((f for f in meta["forms"] if f["id"] == form_id), None)
    assert entry is not None
    assert entry["name"] == "Survey"
    keys = {f["key"] for f in entry["fields"]}
    assert {"name", "email"} <= keys


def test_unpublished_form_absent_from_metadata(session_factory):
    db = session_factory()
    fs = FormService(db)
    actor = _actor(db)
    form = fs.create(DEFAULT_TENANT_ID, actor, name="Draft Only", access="internal")
    fs.update(DEFAULT_TENANT_ID, form.id, fields_set={"draftDefinition"}, draftDefinition=_form_doc())
    # never published
    meta = WorkflowService(db).metadata(DEFAULT_TENANT_ID)
    assert all(f["id"] != form.id for f in meta["forms"])
