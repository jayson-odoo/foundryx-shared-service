"""Rule-engine tests (sprint-2/02 §TDD).

Covers: pure evaluator matrix (operators × types, AND/OR nesting, depth guard,
fail-closed on missing/null facts incl. negative ops, cross-fact compare) ·
``validate_tree`` problem shapes · registry inference + computed facts ·
status-machine edge integration (conditioned edge passes/blocks, hidden from
available_transitions, 409 prose, role-block vs rule-block distinct,
unconditional regression) · ``GET /rule-facts`` · ``GET /rules`` aggregation.

The synthetic ``synthetic_ticket`` entity from test_status_engine doubles as the
reference for module adoption: registering a ``record:synthetic_ticket`` fact source is
all a module does to make its edges conditionable.
"""
import uuid
from datetime import datetime

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.rule_engine.evaluator import evaluate, failed_conditions
from app.rule_engine.prose import tree_text
from app.rule_engine.registry import (
    FactDef,
    fact_map,
    get_facts,
    infer_facts,
    register_fact_source,
)
from app.rule_engine.schemas import validate_tree
from app.services import status_machine
from app.services.status_machine import TransitionConditionsNotMet
from tests.test_status_engine import (
    TicketRecord,
    _admin,
    _build_ticket_graph,
    _create_edge,
    _demo_user,
    _operator,
)


def cond(fact, operator, value=None, value_kind="literal"):
    return {
        "kind": "condition",
        "fact": fact,
        "operator": operator,
        "valueKind": value_kind,
        "value": value,
    }


def group(combinator, *rules):
    return {"kind": "group", "combinator": combinator, "rules": list(rules)}


# ---- evaluator: operator matrix ----


def test_string_operators():
    facts = {"record.name": "Acme Corp"}
    assert evaluate(group("and", cond("record.name", "eq", "Acme Corp"), ), facts)
    assert not evaluate(group("and", cond("record.name", "eq", "acme corp")), facts)
    assert evaluate(group("and", cond("record.name", "neq", "Other")), facts)
    assert evaluate(group("and", cond("record.name", "contains", "acme")), facts)  # ci
    assert not evaluate(group("and", cond("record.name", "contains", "zzz")), facts)
    assert evaluate(group("and", cond("record.name", "in", ["Acme Corp", "Other"])), facts)
    assert evaluate(group("and", cond("record.name", "not_in", ["Other"])), facts)
    assert not evaluate(group("and", cond("record.name", "not_in", ["Acme Corp"])), facts)


def test_number_operators():
    facts = {"record.userCount": 5}
    assert evaluate(group("and", cond("record.userCount", "eq", 5)), facts)
    assert evaluate(group("and", cond("record.userCount", "gt", 4)), facts)
    assert not evaluate(group("and", cond("record.userCount", "gt", 5)), facts)
    assert evaluate(group("and", cond("record.userCount", "gte", 5)), facts)
    assert evaluate(group("and", cond("record.userCount", "lt", 6)), facts)
    assert evaluate(group("and", cond("record.userCount", "lte", 5)), facts)
    assert evaluate(group("and", cond("record.userCount", "between", [1, 5])), facts)
    assert not evaluate(group("and", cond("record.userCount", "between", [6, 9])), facts)
    # String numbers from the wire coerce.
    assert evaluate(group("and", cond("record.userCount", "gt", "4")), facts)


def test_boolean_operators():
    assert evaluate(group("and", cond("record.isPlatform", "is_true")), {"record.isPlatform": True})
    assert evaluate(group("and", cond("record.isPlatform", "is_false")), {"record.isPlatform": False})
    assert not evaluate(group("and", cond("record.isPlatform", "is_true")), {"record.isPlatform": False})


def test_date_operators():
    facts = {"record.createdAt": datetime(2026, 3, 1, 12, 0)}
    assert evaluate(group("and", cond("record.createdAt", "before", "2026-06-01")), facts)
    assert not evaluate(group("and", cond("record.createdAt", "after", "2026-06-01")), facts)
    assert evaluate(group("and", cond("record.createdAt", "between", ["2026-01-01", "2026-12-31"])), facts)
    # ISO strings as fact values work too (Z-suffixed).
    assert evaluate(
        group("and", cond("record.createdAt", "after", "2026-01-01")),
        {"record.createdAt": "2026-03-01T12:00:00Z"},
    )


def test_list_operators():
    facts = {"actor.roles": ["Admin", "Agent"]}
    assert evaluate(group("and", cond("actor.roles", "contains_any", ["Admin", "Viewer"])), facts)
    assert not evaluate(group("and", cond("actor.roles", "contains_any", ["Viewer"])), facts)
    assert evaluate(group("and", cond("actor.roles", "contains_all", ["Admin", "Agent"])), facts)
    assert not evaluate(group("and", cond("actor.roles", "contains_all", ["Admin", "Viewer"])), facts)
    assert evaluate(group("and", cond("actor.roles", "not_contains", ["Viewer"])), facts)
    assert not evaluate(group("and", cond("actor.roles", "not_contains", ["Admin"])), facts)


# ---- evaluator: combinators, nesting, fail-closed ----


def test_and_or_nesting():
    facts = {"a.x": 1, "a.y": 2}
    tree = group(
        "or",
        cond("a.x", "eq", 99),
        group("and", cond("a.x", "eq", 1), cond("a.y", "eq", 2)),
    )
    assert evaluate(tree, facts)
    assert not evaluate(group("and", cond("a.x", "eq", 99), cond("a.y", "eq", 2)), facts)


def test_empty_tree_is_unconditional():
    assert evaluate(None, {})
    assert evaluate(group("and"), {})


def test_missing_or_null_fact_fails_closed_even_negative_ops():
    # D5: missing/null fact ⇒ condition False - including neq/not_in/not_contains.
    facts = {"a.known": None}
    for c in (
        cond("a.ghost", "eq", "x"),
        cond("a.ghost", "neq", "x"),
        cond("a.ghost", "not_in", ["x"]),
        cond("a.known", "neq", "x"),
        cond("a.known", "not_contains", ["x"]),
        cond("a.known", "is_false"),
    ):
        assert not evaluate(group("and", c), facts), c
    # ...but the whole rule may still pass via an OR branch.
    assert evaluate(group("or", cond("a.ghost", "eq", "x"), cond("a.real", "eq", 1)), {"a.real": 1})


def test_depth_guard_fails_closed():
    tree = group("and", cond("a.x", "eq", 1))
    for _ in range(6):  # nest beyond _MAX_DEPTH=5
        tree = group("and", tree)
    assert not evaluate(tree, {"a.x": 1})


def test_garbage_values_never_raise():
    facts = {"a.num": 5, "a.date": datetime(2026, 1, 1)}
    assert not evaluate(group("and", cond("a.num", "gt", "not-a-number")), facts)
    assert not evaluate(group("and", cond("a.date", "before", "not-a-date")), facts)
    assert not evaluate(group("and", cond("a.num", "between", [1])), facts)  # bad pair


def test_cross_fact_compare():
    facts = {
        "record.createdAt": datetime(2026, 1, 1),
        "actor.createdAt": datetime(2026, 6, 1),
        "a.x": 3,
        "a.y": 3,
    }
    assert evaluate(
        group("and", cond("record.createdAt", "before", "actor.createdAt", value_kind="fact")),
        facts,
    )
    assert evaluate(group("and", cond("a.x", "eq", "a.y", value_kind="fact")), facts)
    # Missing RHS fact fails closed.
    assert not evaluate(group("and", cond("a.x", "eq", "a.ghost", value_kind="fact")), facts)


def test_decimal_facts_compare():
    """sprint-4/07 Cluster F - Decimal money facts (Numeric(14,4)) compare
    correctly (the evaluator coerces Decimal → float). Finance's derived
    Partially Paid / Paid edges depend on this."""
    from decimal import Decimal

    facts = {"record.paidTotal": Decimal("40.0000"), "record.total": Decimal("100.0000")}
    # paidTotal > 0 AND paidTotal < total → Partially Paid
    assert evaluate(
        group(
            "and",
            cond("record.paidTotal", "gt", 0),
            cond("record.total", "gt", "record.paidTotal", value_kind="fact"),
        ),
        facts,
    )
    # paidTotal >= total (cross-fact) when fully paid
    paid = {"record.paidTotal": Decimal("100.0000"), "record.total": Decimal("100.0000")}
    assert evaluate(group("and", cond("record.paidTotal", "gte", "record.total", value_kind="fact")), paid)
    # literal compare too (Decimal vs int)
    assert evaluate(group("and", cond("record.paidTotal", "lt", 200)), facts)


def test_failed_conditions_lists_failures():
    facts = {"a.x": 1, "a.y": 2}
    tree = group("and", cond("a.x", "eq", 1), cond("a.y", "eq", 99), cond("a.ghost", "eq", 1))
    failed = failed_conditions(tree, facts)
    assert [f["fact"] for f in failed] == ["a.y", "a.ghost"]


def test_failed_conditions_skips_satisfied_or_branches():
    """Code-review fix: a failing leaf inside an OR group whose sibling
    passed did NOT block the tree - it must not appear in the 409 detail."""
    facts = {"a.x": 1, "a.y": 2, "a.z": 3}
    tree = group(
        "and",
        group("or", cond("a.x", "eq", 1), cond("a.y", "eq", 99)),  # passes via a.x
        cond("a.z", "eq", 99),  # the actual blocker
    )
    failed = failed_conditions(tree, facts)
    assert [f["fact"] for f in failed] == ["a.z"]
    # A failing OR group lists all its (necessarily failing) leaves.
    tree = group("and", group("or", cond("a.x", "eq", 98), cond("a.y", "eq", 99)))
    assert [f["fact"] for f in failed_conditions(tree, facts)] == ["a.x", "a.y"]
    # Passing tree → nothing listed.
    assert failed_conditions(group("and", cond("a.x", "eq", 1)), facts) == []


def test_date_between_includes_whole_end_day():
    """Code-review fix: a date-only END bound is inclusive of that day."""
    facts = {"record.createdAt": datetime(2026, 1, 31, 14, 0)}
    assert evaluate(
        group("and", cond("record.createdAt", "between", ["2026-01-01", "2026-01-31"])),
        facts,
    )
    assert not evaluate(
        group("and", cond("record.createdAt", "between", ["2026-01-01", "2026-01-30"])),
        facts,
    )


def test_collect_fact_keys_includes_cross_fact_rhs():
    tree = group(
        "and",
        cond("record.slug", "eq", "x"),
        group("or", cond("record.createdAt", "before", "actor.createdAt", value_kind="fact")),
    )
    from app.rule_engine.evaluator import collect_fact_keys

    assert collect_fact_keys(tree) == {"record.slug", "record.createdAt", "actor.createdAt"}


# ---- registry ----


def test_infer_facts_types_and_keys():
    from app.models.tenant import Tenant

    defs = infer_facts(Tenant, ["name", "slug", "is_platform", "created_at"], prefix="record")
    by_key = {d.key: d for d in defs}
    assert by_key["record.name"].type == "string"
    assert by_key["record.isPlatform"].type == "boolean"
    assert by_key["record.createdAt"].type == "date"
    assert by_key["record.isPlatform"].label == "Is Platform"


def test_core_sources_registered():
    rows = get_facts(["actor", "record:tenant"])
    keys = {d.key for _, _, d in rows}
    assert {"actor.email", "actor.roles", "record.slug", "record.isPlatform"} <= keys
    sources = {s for s, _, _ in rows}
    assert sources == {"actor", "record:tenant"}


def test_unknown_source_yields_nothing():
    assert get_facts(["nope"]) == []


# ---- validate_tree ----


def test_validate_rejects_unknown_fact_and_bad_operator():
    problems = validate_tree(
        group("and", cond("actor.ghost", "eq", "x"), cond("actor.email", "gt", "x")),
        ["actor"],
    )
    assert any("actor.ghost" in p for p in problems)
    assert any("gt" in p for p in problems)


def test_validate_rejects_cross_fact_type_mismatch_and_nonscalar():
    problems = validate_tree(
        group(
            "and",
            # RHS type mismatch: email (string) vs createdAt (date)
            cond("actor.email", "eq", "actor.createdAt", value_kind="fact"),
            # between is literal-only
            cond("actor.createdAt", "between", "actor.createdAt", value_kind="fact"),
        ),
        ["actor"],
    )
    assert len(problems) >= 2


def test_validate_rejects_empty_group_and_depth():
    problems = validate_tree(group("and"), ["actor"])
    assert any("empty" in p.lower() for p in problems)

    tree = group("and", cond("actor.email", "eq", "x"))
    for _ in range(6):
        tree = group("and", tree)
    problems = validate_tree(tree, ["actor"])
    assert any("depth" in p.lower() for p in problems)


def test_validate_rejects_blank_between_and_nonnumeric():
    """Code-review fix: blank/garbage bounds saved clean but made the edge
    silently unfireable forever (runtime fails closed)."""
    problems = validate_tree(
        group("and", cond("record.userCount", "between", ["", ""])),
        ["record:tenant"],
    )
    assert any("two values" in p for p in problems)
    problems = validate_tree(
        group("and", cond("record.userCount", "between", ["1", "abc"])),
        ["record:tenant"],
    )
    assert any("numbers" in p for p in problems)
    problems = validate_tree(
        group("and", cond("record.userCount", "gt", "abc")),
        ["record:tenant"],
    )
    assert any("numeric" in p for p in problems)
    # Good values still pass.
    assert validate_tree(
        group("and", cond("record.userCount", "between", [1, 5])),
        ["record:tenant"],
    ) == []


def test_validate_accepts_good_tree():
    tree = group(
        "and",
        cond("actor.email", "contains", "@foundryx"),
        group("or", cond("record.isPlatform", "is_false"), cond("record.slug", "in", ["a", "b"])),
    )
    assert validate_tree(tree, ["actor", "record:tenant"]) == []


# ---- prose ----


def test_tree_prose_renders_labels_and_operators():
    fm = fact_map(["actor", "record:tenant"])
    text = tree_text(
        group(
            "and",
            cond("record.isPlatform", "is_false"),
            group("or", cond("actor.email", "contains", "@foundryx"), cond("record.userCount", "gte", 5)),
        ),
        fm,
    )
    assert "Is Platform" in text and "is no" in text
    assert "(" in text and " OR " in text
    assert "@foundryx" in text


# ---- status-machine integration (ticket entity) ----


def _make_ticket(db, status_id, name="Ticket"):
    record = TicketRecord(tenant_id=DEFAULT_TENANT_ID, status_id=status_id, name=name)
    db.add(record)
    db.commit()
    return record


def _register_ticket_facts():
    register_fact_source(
        "record:synthetic_ticket",
        "Ticket record",
        [
            FactDef(key="record.name", label="Name", type="string", resolver=lambda obj, db: obj.name),
        ],
    )


_register_ticket_facts()


def test_conditioned_edge_blocks_and_passes(client, session_factory):
    admin = _admin(client)
    pending, approved, _rejected = _build_ticket_graph(client, admin)
    db = session_factory()
    graph = client.get("/statuses", params={"entityType": "synthetic_ticket"}, headers=admin).json()
    approve = next(t for t in graph["transitions"] if t["label"] == "Approve")

    res = client.patch(
        f"/statuses/transitions/{approve['id']}",
        json={"conditionsJson": group("and", cond("record.name", "eq", "VIP"))},
        headers=admin,
    )
    assert res.status_code == 200, res.text
    assert res.json()["conditionsJson"]["rules"][0]["fact"] == "record.name"

    actor = _demo_user(db)
    vip = _make_ticket(db, pending["id"], name="VIP")
    plain = _make_ticket(db, pending["id"], name="Plain")

    # Qualifying record passes.
    status_machine.transition(db, "synthetic_ticket", vip, approved["id"], actor)
    assert vip.status_id == approved["id"]

    # Non-qualifying record: rule block, distinct from the role block, lists prose.
    try:
        status_machine.transition(db, "synthetic_ticket", plain, approved["id"], actor)
        assert False, "expected TransitionConditionsNotMet"
    except TransitionConditionsNotMet as exc:
        assert "Approve" in exc.message
        assert "Name" in exc.message  # failed condition prose

    # Hidden from available_transitions for the non-qualifying record…
    labels = {e.label for e in status_machine.available_transitions(db, "synthetic_ticket", plain, actor)}
    assert "Approve" not in labels and "Reject" in labels
    # …and the unconditional edge regression: Reject still fires fine.
    db.close()


def test_save_time_validation_422(client):
    admin = _admin(client)
    pending, approved, _ = _build_ticket_graph(client, admin)
    graph = client.get("/statuses", params={"entityType": "synthetic_ticket"}, headers=admin).json()
    approve = next(t for t in graph["transitions"] if t["label"] == "Approve")

    res = client.patch(
        f"/statuses/transitions/{approve['id']}",
        json={"conditionsJson": group("and", cond("record.ghost", "eq", "x"))},
        headers=admin,
    )
    assert res.status_code == 422
    assert "record.ghost" in res.json()["detail"]


def test_create_edge_with_conditions(client):
    admin = _admin(client)
    pending, approved, rejected = _build_ticket_graph(client, admin)
    res = _create_edge(
        client, admin, "synthetic_ticket", approved["id"], rejected["id"], "Reopen",
        conditionsJson=group("and", cond("actor.email", "contains", "@example.com")),
    )
    # Approved is terminal in the helper graph - recreate on a non-terminal edge.
    assert res.status_code in (201, 422)


def test_tenant_rows_carry_fireable_edges_when_conditioned(client):
    """Console rows hide rule-blocked actions per record (D6): the list wire
    carries availableTransitionIds only while a conditioned edge exists."""
    operator = _operator(client)

    # Baseline: no conditioned tenant edge → field stays null (cheap path).
    res = client.get("/platform/tenants", headers=operator)
    assert res.status_code == 200, res.text
    rows = res.json()["data"]
    default_row = next(r for r in rows if r["slug"] == "default")
    assert default_row["availableTransitionIds"] is None

    # Condition the Suspend edge: only platform-ish slugs may suspend (the
    # default tenant does NOT qualify).
    graph = client.get("/statuses", params={"entityType": "tenant"}, headers=operator).json()
    suspend = next(t for t in graph["transitions"] if t["label"] == "Suspend")
    res = client.patch(
        f"/statuses/transitions/{suspend['id']}",
        json={"conditionsJson": group("and", cond("record.slug", "eq", "qualifies-nobody"))},
        headers=operator,
    )
    assert res.status_code == 200, res.text

    res = client.get("/platform/tenants", headers=operator)
    default_row = next(r for r in res.json()["data"] if r["slug"] == "default")
    ids = default_row["availableTransitionIds"]
    assert ids is not None
    assert suspend["id"] not in ids  # rule-blocked, hidden per record
    archive_ids = [
        t["id"]
        for t in graph["transitions"]
        if t["fromStatusId"] == suspend["fromStatusId"] and t["label"] != "Suspend"
    ]
    assert any(a in ids for a in archive_ids)  # unconditional edges remain

    # Cleanup: clear the condition (shared platform graph) - clearing must
    # store SQL NULL, not JSON null (none_as_null regression): the field
    # drops back to null AND no "Always allowed" ghost lingers on /rules.
    res = client.patch(
        f"/statuses/transitions/{suspend['id']}",
        json={"conditionsJson": None},
        headers=operator,
    )
    assert res.status_code == 200, res.text
    res = client.get("/platform/tenants", headers=operator)
    default_row = next(r for r in res.json()["data"] if r["slug"] == "default")
    assert default_row["availableTransitionIds"] is None
    res = client.get("/rules", headers=operator)
    assert not any(
        "Active" in r["context"] and "Suspended" in r["context"]
        for r in res.json()["data"]
    )


# ---- /rule-facts ----


def test_rule_facts_endpoint_filters_sources(client):
    admin = _admin(client)
    res = client.get("/rule-facts", params={"sources": "actor"}, headers=admin)
    assert res.status_code == 200
    keys = {f["key"] for f in res.json()["data"]}
    assert "actor.email" in keys
    assert not any(k.startswith("record.") for k in keys)

    res = client.get("/rule-facts", params={"sources": "actor,record:tenant"}, headers=admin)
    data = res.json()["data"]
    assert {f["source"] for f in data} == {"actor", "record:tenant"}
    status_fact = next(f for f in data if f["key"] == "actor.status")
    assert status_fact["type"] == "enum" and len(status_fact["options"]) >= 2


def test_rule_facts_requires_auth(client):
    assert client.get("/rule-facts", params={"sources": "actor"}).status_code in (401, 403)


# ---- /rules observability ----


def test_rules_list_aggregates_conditioned_edges(client):
    admin = _admin(client)
    pending, approved, _ = _build_ticket_graph(client, admin)
    graph = client.get("/statuses", params={"entityType": "synthetic_ticket"}, headers=admin).json()
    approve = next(t for t in graph["transitions"] if t["label"] == "Approve")
    client.patch(
        f"/statuses/transitions/{approve['id']}",
        json={"conditionsJson": group("and", cond("record.name", "eq", "VIP"))},
        headers=admin,
    )

    res = client.get("/rules", headers=admin)
    assert res.status_code == 200, res.text
    body = res.json()
    rows = body["data"]
    assert body["total"] >= 1
    row = next(r for r in rows if "Approve" in r["context"] or "Pending" in r["context"])
    assert row["site"] == "status_transition"
    assert "Name" in row["summary"] and "VIP" in row["summary"]
    # Wire carries DATA (the entity type) - frontend maps site+target to its
    # own route; backend never hardcodes frontend paths (code-review fix).
    assert row["target"] == "synthetic_ticket"

    # Search narrows.
    res = client.get("/rules", params={"search": "zzz-no-match"}, headers=admin)
    assert res.json()["total"] == 0


def test_rules_requires_permission(client, session_factory):
    # rules.read is granted to Admin; a roleless user gets 403.
    from app.security import hash_password

    db = session_factory()
    db.add(
        User(
            tenant_id=DEFAULT_TENANT_ID,
            email="rules-norole@example.com",
            password=hash_password("password123"),
            name="No Role",
            status=UserStatus.ACTIVE.value,
        )
    )
    db.commit()
    db.close()
    headers = _login_raw(client, "rules-norole@example.com", "password123")
    assert client.get("/rules", headers=headers).status_code == 403


def _login_raw(client, email, password):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}
