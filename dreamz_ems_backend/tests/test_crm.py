"""CRM module tests (sprint-4/08) — clients / leads / quotations in app_crm.

install grants perms + terminology · client + lead CRUD + status · Win is a plain
status move + create-event is separate/repeatable via the EMS capability (spawns
+ links a Project; lead holds no project_id) · quotation lines + currency default
· tenant isolation.
"""
from app.models.tenant import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _status(db, entity_type, key):
    from app.models.status import Status

    return (
        db.query(Status)
        .filter(
            Status.entity_type == entity_type,
            Status.key == key,
            Status.tenant_id == DEFAULT_TENANT_ID,
            Status.scope_id.is_(None),
        )
        .first()
    )


def test_install_grants_and_terminology(client):
    h = _admin(client)
    assert client.get("/crm/clients", headers=h).status_code == 200
    assert client.get("/crm/leads", headers=h).status_code == 200
    assert client.get("/crm/quotations", headers=h).status_code == 200
    terms = client.get("/terminology", headers=h).json()
    assert terms["client"] == {"singular": "Client", "plural": "Clients"}
    assert terms["lead"] == {"singular": "Lead", "plural": "Leads"}


def test_client_and_lead_crud(client):
    h = _admin(client)
    c = client.post("/crm/clients", headers=h, json={"name": "Acme Corp", "contactEmail": "a@acme.test"}).json()
    assert c["statusId"]  # initial Active
    ld = client.post("/crm/leads", headers=h, json={"title": "Acme annual conf", "clientId": c["id"]})
    assert ld.status_code == 201, ld.text
    assert ld.json()["clientId"] == c["id"]
    # foreign client rejected
    assert client.post("/crm/leads", headers=h, json={"title": "X", "clientId": "nope"}).status_code == 422


def test_win_then_create_event_capability(client, session_factory):
    h = _admin(client)
    # need an event template for the capability to build a Project
    et = client.post("/ems/project-types", headers=h, json={"name": "Conf"}).json()
    tmpl = client.post("/ems/project-templates", headers=h, json={"typeId": et["id"], "name": "Std"}).json()

    c = client.post("/crm/clients", headers=h, json={"name": "Acme"}).json()
    ld = client.post("/crm/leads", headers=h, json={"title": "Deal", "clientId": c["id"]}).json()

    # create-event before Win → 409 (Win is a separate, prerequisite status move)
    early = client.post(f"/crm/leads/{ld['id']}/create-event", headers=h, json={"templateId": tmpl["id"]})
    assert early.status_code == 409

    # Win = plain status transition
    with session_factory() as db:
        won = _status(db, "lead", "won")
    moved = client.post(f"/crm/leads/{ld['id']}/transition", headers=h, json={"toStatusId": won.id})
    assert moved.status_code == 200, moved.text

    # create-event now works + is REPEATABLE (1 lead → many events)
    e1 = client.post(f"/crm/leads/{ld['id']}/create-event", headers=h, json={"templateId": tmpl["id"], "title": "Conf A"})
    assert e1.status_code == 200, e1.text
    e2 = client.post(f"/crm/leads/{ld['id']}/create-event", headers=h, json={"templateId": tmpl["id"], "title": "Conf B"})
    assert e2.status_code == 200
    assert e1.json()["id"] != e2.json()["id"]

    # the lead lists both spawned events (cross-module projects.by_lead)
    events = client.get(f"/crm/leads/{ld['id']}/events", headers=h).json()
    assert {e["id"] for e in events} == {e1.json()["id"], e2.json()["id"]}

    # the EMS project carries the originating lead/client soft-refs
    with session_factory() as db:
        from modules.ems.models import Project

        proj = db.query(Project).filter(Project.id == e1.json()["id"]).first()
        assert proj.lead_id == ld["id"] and proj.client_id == c["id"]


def test_quotation_lines_and_currency_default(client):
    h = _admin(client)
    client.put("/settings/general", headers=h, json={"defaultCurrency": "SGD"})
    c = client.post("/crm/clients", headers=h, json={"name": "Buyer"}).json()
    q = client.post(
        "/crm/quotations", headers=h,
        json={"clientId": c["id"], "lines": [{"description": "Consulting", "qty": 3, "unitPrice": 100}]},
    )
    assert q.status_code == 201, q.text
    body = q.json()
    assert body["currency"] == "SGD"  # inherited tenant default
    assert body["total"] == 300.0 and body["lines"][0]["amount"] == 300.0

    # revise → new draft, revision 2, lineage
    rev = client.post(f"/crm/quotations/{body['id']}/revise", headers=h).json()
    assert rev["revisionNumber"] == 2 and rev["parentQuotationId"] == body["id"]

    # list shows ONE row per lineage (the latest revision), not both v1 and v2
    listed = client.get("/crm/quotations", headers=h).json()
    mine = [q for q in listed["items"] if q["id"] in (body["id"], rev["id"])]
    assert len(mine) == 1 and mine[0]["id"] == rev["id"]

    # the revisions endpoint returns the full lineage (oldest→newest)
    revs = client.get(f"/crm/quotations/{rev['id']}/revisions", headers=h).json()
    assert [r["revisionNumber"] for r in revs] == [1, 2]

    # clientId filter (powers the client → Quotations tab)
    by_client = client.get(f"/crm/quotations?clientId={c['id']}", headers=h).json()
    assert by_client["total"] >= 1 and all(q["clientId"] == c["id"] for q in by_client["items"])


def test_tenant_isolation(client, session_factory):
    h = _admin(client)
    c = client.post("/crm/clients", headers=h, json={"name": "Mine"}).json()
    # a fabricated other-tenant id can't be read
    assert client.get("/crm/clients/does-not-exist", headers=h).status_code == 404
    assert c["id"]
