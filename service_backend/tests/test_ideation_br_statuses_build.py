"""BR Send to build - S1: new status + edges + permission + grant sweep + models
(AC-STB-13, AC-STB-14) and the generic-move refusal.

RED until: ``BR_STATUS_IDS["sent_to_build"]`` + edges are seeded, the CSV row
``ideation.business_requirements.send_to_build`` exists,
``modules.ideation.bootstrap.sweep_send_to_build_grants(db)`` exists and the
three new models exist.
"""
from sqlalchemy.orm import Session

from app.models import DEFAULT_TENANT_ID
from tests.ideation_build_helpers import (  # noqa: F401
    _FULL_ANSWERS,
    _auth,
    _make_user,
    _product,
    br_status_key,
    ideation_client,
    make_br,
)

SEND_EDGES = {
    "br-tr-send-to-build-draft": "br-status-draft",
    "br-tr-send-to-build-grilling": "br-status-grilling",
    "br-tr-send-to-build-ready": "br-status-ready",
}
SENT_ID = "br-status-sent-to-build"
SEND_PERM = "ideation.business_requirements.send_to_build"


def _edges(db: Session):
    from app.models.status_transition import StatusTransition
    from modules.ideation.services.statuses import BR_ENTITY

    return {
        t.id: t
        for t in db.query(StatusTransition)
        .filter(StatusTransition.entity_type == BR_ENTITY)
        .all()
    }


def test_ac_stb_13_status_id_constant():
    from modules.ideation.services.statuses import BR_STATUS_IDS

    assert BR_STATUS_IDS["sent_to_build"] == SENT_ID


def test_ac_stb_13_status_seeded_with_label_color_sort(ideation_session_factory):
    from app.models.status import Status
    from modules.ideation.services.statuses import BR_ENTITY, BR_STATUS_IDS

    db = ideation_session_factory()
    try:
        rows = {
            s.key: s
            for s in db.query(Status).filter(
                Status.entity_type == BR_ENTITY, Status.tenant_id.is_(None)
            )
        }
        sent = rows["sent_to_build"]
        assert sent.id == BR_STATUS_IDS["sent_to_build"]
        assert sent.label == "Sent to build"
        assert sent.color == "violet"
        assert sent.sort_order == 4
        assert sent.sort_order < rows["in_fr"].sort_order
        assert (rows["in_fr"].sort_order, rows["delivered"].sort_order, rows["archived"].sort_order) == (5, 6, 7)
        # Trait flags: the new status is neither initial nor archived.
        assert not sent.is_initial and not sent.is_archived
    finally:
        db.close()


def test_ac_stb_13_send_edges_seeded(ideation_session_factory):
    db = ideation_session_factory()
    try:
        edges = _edges(db)
        for edge_id, from_id in SEND_EDGES.items():
            assert edge_id in edges, edge_id
            assert edges[edge_id].from_status_id == from_id
            assert edges[edge_id].to_status_id == SENT_ID
    finally:
        db.close()


def test_ac_stb_13_delivered_and_back_edges_seeded(ideation_session_factory):
    db = ideation_session_factory()
    try:
        edges = _edges(db)
        assert edges["br-tr-build-delivered"].from_status_id == SENT_ID
        assert edges["br-tr-build-delivered"].to_status_id == "br-status-delivered"
        assert edges["br-tr-build-back"].from_status_id == SENT_ID
        assert edges["br-tr-build-back"].to_status_id == "br-status-ready"
        assert edges["br-tr-build-back"].label == "Back to ready"
    finally:
        db.close()


def test_ac_stb_13_seed_is_idempotent(ideation_session_factory):
    from app.models.status import Status
    from modules.ideation.services.statuses import BR_ENTITY, seed_br_statuses

    db = ideation_session_factory()
    try:
        seed_br_statuses(db)
        db.commit()
        before_s = db.query(Status).filter(Status.entity_type == BR_ENTITY).count()
        before_e = len(_edges(db))
        seed_br_statuses(db)
        seed_br_statuses(db)
        db.commit()
        assert db.query(Status).filter(Status.entity_type == BR_ENTITY).count() == before_s
        assert len(_edges(db)) == before_e
        assert SENT_ID in {
            s.id for s in db.query(Status).filter(Status.entity_type == BR_ENTITY)
        }
    finally:
        db.close()


def test_ac_stb_13_seed_converges_when_new_rows_missing(ideation_session_factory):
    """Existing DBs converge at the next bootstrap: delete the new status + its
    edges, re-run the seed, they come back."""
    from app.models.status import Status
    from app.models.status_transition import StatusTransition
    from modules.ideation.services.statuses import BR_ENTITY, seed_br_statuses

    db = ideation_session_factory()
    try:
        db.query(StatusTransition).filter(
            StatusTransition.entity_type == BR_ENTITY,
            (StatusTransition.from_status_id == SENT_ID)
            | (StatusTransition.to_status_id == SENT_ID),
        ).delete(synchronize_session=False)
        db.query(Status).filter(Status.id == SENT_ID).delete(synchronize_session=False)
        db.commit()
        seed_br_statuses(db)
        db.commit()
        assert db.get(Status, SENT_ID) is not None
        edges = _edges(db)
        for edge_id in (*SEND_EDGES, "br-tr-build-delivered", "br-tr-build-back"):
            assert edge_id in edges
    finally:
        db.close()


def test_ac_stb_13_graph_endpoint_carries_new_edges(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get("/ideation/business-requirements/status-graph", headers=h)
    assert res.status_code == 200, res.text
    ids = {t["id"] for t in res.json()["transitions"]}
    assert "br-tr-build-back" in ids and "br-tr-build-delivered" in ids


def test_ac_stb_13_generic_move_to_sent_to_build_refused_409(ideation_client):
    """Only the Send endpoint may fire the send edges: the generic move is 409
    from every source status, and the BR never moves."""
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    bid = make_br(ideation_client, h, pid)
    res = ideation_client.post(
        f"/ideation/business-requirements/{bid}/status",
        headers=h,
        json={"status": "sent_to_build"},
    )
    assert res.status_code == 409, res.text
    assert br_status_key(ideation_client, h, bid) == "draft"

    # From ready (via promote, a complete BR) the generic move is refused too.
    assert (
        ideation_client.post(
            f"/ideation/business-requirements/{bid}/status", headers=h, json={"status": "ready"}
        ).status_code
        == 200
    )
    res = ideation_client.post(
        f"/ideation/business-requirements/{bid}/status",
        headers=h,
        json={"status": "sent_to_build"},
    )
    assert res.status_code == 409, res.text
    assert br_status_key(ideation_client, h, bid) == "ready"


def test_ac_stb_13_back_to_ready_offered_on_sent_br(ideation_client, ideation_session_factory):
    """The generic menu DOES offer "Back to ready" on a sent BR."""
    from tests.ideation_build_helpers import insert_sent_br

    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    bid = insert_sent_br(ideation_session_factory, product_id=pid)
    res = ideation_client.post(
        f"/ideation/business-requirements/{bid}/status",
        headers=h,
        json={"status": "ready"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "ready"


# ── AC-STB-14 permission + grant sweep ────────────────────────────────────────


def test_ac_stb_14_permission_in_catalog_with_label(ideation_session_factory):
    from app.models.permission import Permission

    db = ideation_session_factory()
    try:
        perm = db.query(Permission).filter(Permission.key == SEND_PERM).first()
        assert perm is not None
        assert perm.module == "ideation"
        assert perm.action_label == "Send to build"
    finally:
        db.close()


def test_ac_stb_14_admin_holds_send_to_build(ideation_client):
    h = _auth(ideation_client)
    perms = set(ideation_client.get("/auth/me", headers=h).json()["permissions"])
    assert SEND_PERM in perms


def _role_with(db: Session, name: str, keys):
    from app.models import Role
    from app.models.permission import Permission

    role = Role(tenant_id=DEFAULT_TENANT_ID, name=name, description="t", is_system=False)
    role.permissions = db.query(Permission).filter(Permission.key.in_(list(keys))).all()
    db.add(role)
    db.commit()
    return role.id


def _held(db: Session, role_id: str) -> set:
    from app.models import Role

    role = db.get(Role, role_id)
    db.refresh(role)
    return {p.key for p in role.permissions}


def test_ac_stb_14_sweep_grants_send_to_build_to_every_promote_holder(ideation_session_factory):
    from modules.ideation.bootstrap import sweep_send_to_build_grants

    db = ideation_session_factory()
    try:
        promote_only = _role_with(db, "PromoteOnly", ["ideation.business_requirements.promote"])
        manage_only = _role_with(db, "ManageOnly", ["ideation.business_requirements.manage"])
        both = _role_with(
            db, "Both", ["ideation.business_requirements.promote", SEND_PERM]
        )
        assert SEND_PERM not in _held(db, promote_only)

        sweep_send_to_build_grants(db)
        db.commit()

        assert SEND_PERM in _held(db, promote_only)
        assert SEND_PERM not in _held(db, manage_only)  # never over-grants
        assert SEND_PERM in _held(db, both)
    finally:
        db.close()


def test_ac_stb_14_sweep_is_idempotent_and_scoped_per_tenant(ideation_session_factory):
    """A second run adds no duplicate grant; a role in another tenant that holds
    promote gets ITS OWN grant (grants are tenant-scoped through the role)."""
    from sqlalchemy import text

    from app.models import Role
    from app.models.permission import Permission
    from modules.ideation.bootstrap import sweep_send_to_build_grants
    from tests.ideation_build_helpers import ensure_other_tenant

    other = ensure_other_tenant(ideation_session_factory)
    db = ideation_session_factory()
    try:
        promote = db.query(Permission).filter(
            Permission.key == "ideation.business_requirements.promote"
        ).first()
        foreign = Role(tenant_id=other, name="ForeignPromote", description="t", is_system=False)
        foreign.permissions = [promote]
        db.add(foreign)
        db.commit()
        foreign_id = foreign.id

        sweep_send_to_build_grants(db)
        db.commit()
        sweep_send_to_build_grants(db)
        db.commit()

        perm = db.query(Permission).filter(Permission.key == SEND_PERM).first()
        rows = db.execute(
            text(
                "SELECT tenant_id FROM role_permissions "
                "WHERE role_id = :r AND permission_id = :p"
            ),
            {"r": foreign_id, "p": perm.id},
        ).fetchall()
        assert len(rows) == 1
        assert rows[0][0] == other
    finally:
        db.close()


def test_ac_stb_14_send_endpoint_403_without_permission(ideation_client, ideation_session_factory):
    _make_user(
        ideation_session_factory,
        "nosend@example.com",
        "NoSend123!",
        {"ideation.business_requirements.read", "ideation.business_requirements.manage"},
    )
    admin = _auth(ideation_client)
    pid = _product(ideation_client, admin)
    bid = make_br(ideation_client, admin, pid)
    h = _auth(ideation_client, email="nosend@example.com", password="NoSend123!")
    res = ideation_client.post(f"/ideation/business-requirements/{bid}/send-to-build", headers=h)
    assert res.status_code == 403, res.text
    assert ideation_client.post("/ideation/build-keys", headers=h, json={"name": "x"}).status_code == 403
    assert ideation_client.get("/ideation/build-keys", headers=h).status_code == 403


# ── new models (S1) ───────────────────────────────────────────────────────────


def test_ac_stb_s1_br_builds_model_columns():
    from modules.ideation.models import BrBuild

    cols = BrBuild.__table__.c
    for name in (
        "id", "tenant_id", "business_requirement_id", "repo", "state",
        "issue_number", "issue_url", "issue_node_id", "sent_by", "sent_at",
        "created_at", "updated_at",
    ):
        assert name in cols, name
    assert BrBuild.__tablename__ == "br_builds"
    assert cols.business_requirement_id.unique or any(
        {c.name for c in ix.columns} == {"business_requirement_id"} and ix.unique
        for ix in BrBuild.__table__.indexes
    ) or any(
        {c.name for c in uc.columns} == {"business_requirement_id"}
        for uc in BrBuild.__table__.constraints
        if uc.__class__.__name__ == "UniqueConstraint"
    )


def test_ac_stb_s1_br_build_events_model_columns():
    from modules.ideation.models import BrBuildEvent

    cols = BrBuildEvent.__table__.c
    for name in (
        "seq", "id", "tenant_id", "business_requirement_id", "kind", "stage",
        "message", "pr_url", "handtest_url", "status", "actor_user_id", "key_id",
        "status_moved", "created_at",
    ):
        assert name in cols, name
    assert BrBuildEvent.__tablename__ == "br_build_events"
    assert cols.seq.primary_key
    assert cols.stage.type.length == 40


def test_ac_stb_s1_br_build_keys_model_columns():
    from modules.ideation.models import BrBuildKey

    cols = BrBuildKey.__table__.c
    for name in (
        "id", "tenant_id", "name", "key_prefix", "key_hash", "last_used_at",
        "revoked_at", "created_by", "created_at",
    ):
        assert name in cols, name
    assert BrBuildKey.__tablename__ == "br_build_keys"
