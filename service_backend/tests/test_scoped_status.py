"""Scoped status machines — sprint-3/01 Phase 0 spike (a) + D4 contract.

A synthetic scoped ``review_item`` entity (scope = its ``board_id``, the way
``form_submission`` scopes on ``form_id``) exercises: materialize-on-create ·
per-scope key reuse · cross-scope transition refusal (defense class of the
polymorphic target_id rule) · scope-filtered listing/fireable ids ·
delete-scope teardown · registry validation. The pre-existing engine suite
(tenant lifecycle, unscoped ticket) must stay green untouched.
"""
import uuid

import pytest
from sqlalchemy import Column, String

from app.database import Base
from app.models import DEFAULT_TENANT_ID, User
from app.services import status_machine
from app.services.status_machine import TransitionNotAllowed
from app.status_engine.registry import StatusEntity, register_status_entity
from app.status_engine.scoped import (
    ScopeSeedEdge,
    ScopeSeedStatus,
    delete_scope,
    initial_scope_status,
    materialize_scope,
    scope_status_ids,
)
from tests.conftest import ACTIVE_EMAIL


class ReviewItemRecord(Base):
    """Test-only scoped entity — what form_submission looks like to the engine."""

    __tablename__ = "test_review_items"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    tenant_id = Column(String, nullable=False, index=True)
    board_id = Column(String, nullable=False, index=True)  # the scope
    name = Column(String, nullable=False, default="Item")
    status_id = Column(String, nullable=False, index=True)


def _item_count(db, status_id, tenant_id):
    q = db.query(ReviewItemRecord).filter(ReviewItemRecord.status_id == status_id)
    if tenant_id is not None:
        q = q.filter(ReviewItemRecord.tenant_id == tenant_id)
    return q.count()


def _item_migrate(db, from_status_id, to_status_id, tenant_id):
    q = db.query(ReviewItemRecord).filter(ReviewItemRecord.status_id == from_status_id)
    if tenant_id is not None:
        q = q.filter(ReviewItemRecord.tenant_id == tenant_id)
    count = q.update({ReviewItemRecord.status_id: to_status_id}, synchronize_session=False)
    db.flush()
    return count


register_status_entity(
    StatusEntity(
        entity_type="review_item",
        label="Review Item",
        module="test",
        count_records=_item_count,
        migrate_records=_item_migrate,
        scoped=True,
        scope_attr="board_id",
        scope_label="Board",
    )
)

# The minimal seed contract from the plan (D4): Draft (initial, active=may
# still edit) → Submitted (active False).
SEED_STATUSES = [
    ScopeSeedStatus("draft", "Draft", "blue", 1, {"is_initial": True, "is_active": True}),
    ScopeSeedStatus("submitted", "Submitted", "green", 2, {"is_active": False}),
]
SEED_EDGES = [ScopeSeedEdge("draft", "submitted", "Submit", 1)]


@pytest.fixture
def db(session_factory):
    session = session_factory()
    yield session
    session.close()


def _demo_user(db) -> User:
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


def _seed_scope(db, scope_id):
    return materialize_scope(
        db, "review_item", DEFAULT_TENANT_ID, scope_id, SEED_STATUSES, SEED_EDGES
    )


def _make_item(db, scope_id, status_id):
    item = ReviewItemRecord(
        tenant_id=DEFAULT_TENANT_ID, board_id=scope_id, status_id=status_id
    )
    db.add(item)
    db.flush()
    return item


# ---- registry validation ----


def test_scoped_entity_requires_scope_attr():
    with pytest.raises(ValueError):
        StatusEntity(
            entity_type="bad",
            label="Bad",
            module="test",
            count_records=_item_count,
            migrate_records=_item_migrate,
            scoped=True,
        )


def test_scoped_entity_cannot_be_platform_owned():
    with pytest.raises(ValueError):
        StatusEntity(
            entity_type="bad",
            label="Bad",
            module="test",
            count_records=_item_count,
            migrate_records=_item_migrate,
            scoped=True,
            scope_attr="board_id",
            platform_owned=True,
        )


# ---- materialization ----


def test_materialize_seeds_graph_and_initial(db):
    by_key = _seed_scope(db, "board-1")
    db.commit()
    assert set(by_key) == {"draft", "submitted"}
    initial = initial_scope_status(db, "review_item", DEFAULT_TENANT_ID, "board-1")
    assert initial is not None and initial.key == "draft"
    assert initial.is_active is True and by_key["submitted"].is_active is False


def test_two_scopes_reuse_keys(db):
    a = _seed_scope(db, "board-1")
    b = _seed_scope(db, "board-2")
    db.commit()
    # Same keys, distinct rows per scope — unique constraint includes scope_id.
    assert a["draft"].id != b["draft"].id
    assert len(scope_status_ids(db, "review_item", DEFAULT_TENANT_ID, "board-1")) == 2
    assert len(scope_status_ids(db, "review_item", DEFAULT_TENANT_ID, "board-2")) == 2


def test_double_seed_refused(db):
    _seed_scope(db, "board-1")
    db.commit()
    with pytest.raises(ValueError):
        _seed_scope(db, "board-1")


# ---- transitions ----


def test_transition_within_scope(db):
    by_key = _seed_scope(db, "board-1")
    item = _make_item(db, "board-1", by_key["draft"].id)
    db.commit()
    actor = _demo_user(db)
    edge = status_machine.transition(
        db, "review_item", item, by_key["submitted"].id, actor
    )
    assert edge.label == "Submit"
    assert item.status_id == by_key["submitted"].id


def test_cross_scope_transition_refused(db):
    a = _seed_scope(db, "board-1")
    b = _seed_scope(db, "board-2")
    item = _make_item(db, "board-1", a["draft"].id)
    db.commit()
    actor = _demo_user(db)
    # Target from ANOTHER board's graph — the scope guard must refuse before
    # any edge lookup ambiguity.
    with pytest.raises(TransitionNotAllowed) as exc:
        status_machine.transition(db, "review_item", item, b["submitted"].id, actor)
    assert "Board" in str(exc.value)
    assert item.status_id == a["draft"].id


def test_strict_graph_no_reverse_edge(db):
    by_key = _seed_scope(db, "board-1")
    item = _make_item(db, "board-1", by_key["submitted"].id)
    db.commit()
    with pytest.raises(TransitionNotAllowed):
        status_machine.transition(
            db, "review_item", item, by_key["draft"].id, _demo_user(db)
        )


def test_available_transitions_scope_filtered(db):
    a = _seed_scope(db, "board-1")
    _seed_scope(db, "board-2")
    item = _make_item(db, "board-1", a["draft"].id)
    db.commit()
    actor = _demo_user(db)
    edges = status_machine.available_transitions(db, "review_item", item, actor)
    assert [e.to_status_id for e in edges] == [a["submitted"].id]
    # Submitted has no outgoing edge.
    item.status_id = a["submitted"].id
    db.flush()
    assert status_machine.available_transitions(db, "review_item", item, actor) == []


def test_fireable_edge_ids_scoped(db):
    a = _seed_scope(db, "board-1")
    b = _seed_scope(db, "board-2")
    item_a = _make_item(db, "board-1", a["draft"].id)
    item_b = _make_item(db, "board-2", b["draft"].id)
    db.commit()
    actor = _demo_user(db)
    # No conditioned edge anywhere → None (cheap-probe contract preserved).
    assert (
        status_machine.fireable_edge_ids(db, "review_item", [item_a, item_b], actor)
        is None
    )
    # Condition one edge: per-record results must stay within each record's scope.
    from app.models.status_transition import StatusTransition

    edge_a = (
        db.query(StatusTransition)
        .filter(StatusTransition.from_status_id == a["draft"].id)
        .one()
    )
    edge_b = (
        db.query(StatusTransition)
        .filter(StatusTransition.from_status_id == b["draft"].id)
        .one()
    )
    edge_a.conditions_json = {
        "combinator": "and",
        "rules": [{"fact": "actor.email", "operator": "eq", "value": ACTIVE_EMAIL}],
    }
    db.commit()
    result = status_machine.fireable_edge_ids(db, "review_item", [item_a, item_b], actor)
    assert result[item_a.id] == [edge_a.id]
    assert result[item_b.id] == [edge_b.id]


# ---- teardown ----


def test_delete_scope_removes_only_that_scope(db):
    _seed_scope(db, "board-1")
    _seed_scope(db, "board-2")
    db.commit()
    statuses_deleted, edges_deleted = delete_scope(
        db, "review_item", DEFAULT_TENANT_ID, "board-1"
    )
    db.commit()
    assert (statuses_deleted, edges_deleted) == (2, 1)
    assert scope_status_ids(db, "review_item", DEFAULT_TENANT_ID, "board-1") == []
    assert len(scope_status_ids(db, "review_item", DEFAULT_TENANT_ID, "board-2")) == 2


def test_delete_missing_scope_noop(db):
    assert delete_scope(db, "review_item", DEFAULT_TENANT_ID, "nope") == (0, 0)
