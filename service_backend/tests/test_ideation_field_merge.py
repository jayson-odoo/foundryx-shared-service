"""Plan 20 S2 - field-level N-way merge (AC-20-10..15).

TEST-FIRST: written before ``MergeIn.fields``, the merge snapshot/restore and
the comment/attachment read-through exist.
"""
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_merge import (  # noqa: F401 - fixture re-export
    _auth,
    _create_software_product,
    _idea_row,
    _insert_idea,
    _unmerge,
    _vote,
    ideation_client,
)


def _set(factory, idea_id, **values):
    from modules.ideation.models import Idea

    db = factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        for k, v in values.items():
            setattr(idea, k, v)
        db.commit()
    finally:
        db.close()


def _merge(client, h, survivor_id, idea_ids, fields=None, path="/ideation/ideas/merge"):
    body = {"survivorId": survivor_id, "ideaIds": idea_ids}
    if fields is not None:
        body["fields"] = fields
    return client.post(path, headers=h, json=body)


def _three(client):
    h = _auth(client)
    pid = _create_software_product(client, h)
    f = client._factory
    a = _insert_idea(f, pid, problem="Dealers cannot track order status", idea_number="IDEA-0010")
    b = _insert_idea(f, pid, problem="No self-service order view", idea_number="IDEA-0004")
    c = _insert_idea(f, pid, problem="Dealer not told when shipped", idea_number="IDEA-0017")
    _set(f, a, title="Order tracking", use_cases=["Check shipping"], raw_text="msg a")
    _set(
        f,
        b,
        title="Dealer portal",
        desired_outcome="Self-service status",
        use_cases=["Check shipping", "Reorder"],
        current_workaround="Call sales",
        raw_text="msg b",
    )
    _set(f, c, title="Ship notice", use_cases=["Tell customer ship date"], raw_text="msg c")
    return h, pid, a, b, c


# ── AC-20-10 ─────────────────────────────────────────────────────────────────
def test_field_merge_picks_and_combines(ideation_client):
    client = ideation_client
    h, _pid, a, b, c = _three(client)
    res = _merge(
        client,
        h,
        a,
        [a, b, c],
        fields={
            "title": [b],
            "problem": [a, b],
            "desiredOutcome": [b],
            "useCases": [a, b, c],
            "currentWorkaround": [a],  # empty on a -> survivor value becomes empty
            "rawText": [a, c],
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == a
    assert body["title"] == "Dealer portal"
    assert body["problem"] == (
        "Dealers cannot track order status\n\n--- from IDEA-0004 ---\nNo self-service order view"
    )
    assert body["desiredOutcome"] == "Self-service status"
    assert body["useCases"] == ["Check shipping", "Reorder", "Tell customer ship date"]
    assert body["currentWorkaround"] is None
    assert body["rawText"] == "msg a\n\n--- from IDEA-0017 ---\nmsg c"
    # Absorbed ideas keep their own text untouched.
    row_b = _idea_row(client._factory, b)
    assert row_b.title == "Dealer portal" and row_b.problem == "No self-service order view"


def test_combined_skips_empty_values(ideation_client):
    client = ideation_client
    h, _pid, a, b, c = _three(client)
    res = _merge(client, h, a, [a, b, c], fields={"desiredOutcome": [a, b, c]})
    assert res.status_code == 200, res.text
    assert res.json()["desiredOutcome"] == "Self-service status"


def test_merge_without_fields_keeps_survivor_values(ideation_client):
    client = ideation_client
    h, _pid, a, b, _c = _three(client)
    res = _merge(client, h, a, [a, b])
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Order tracking"
    assert res.json()["problem"] == "Dealers cannot track order status"


# ── AC-20-11 ─────────────────────────────────────────────────────────────────
def test_field_merge_validation_writes_nothing(ideation_client):
    client = ideation_client
    h, pid, a, b, c = _three(client)
    outsider = _insert_idea(client._factory, pid, problem="Other")
    for fields in (
        {"title": [outsider]},
        {"title": []},
        {"impact": [a]},
        {"problem": [a, a]},
    ):
        res = _merge(client, h, a, [a, b], fields=fields)
        assert res.status_code == 422, (fields, res.text)
    assert _idea_row(client._factory, b).merged_into_id is None
    assert _idea_row(client._factory, a).title == "Order tracking"


# ── AC-20-12 ─────────────────────────────────────────────────────────────────
def test_votes_still_move_with_field_merge(ideation_client):
    client = ideation_client
    h, _pid, a, b, _c = _three(client)
    _vote(client._factory, b, "voter-1")
    res = _merge(client, h, a, [a, b], fields={"title": [b]})
    assert res.json()["upvotes"] == 1


# ── AC-20-13 ─────────────────────────────────────────────────────────────────
def test_unmerge_restores_unedited_fields(ideation_client):
    client = ideation_client
    h, _pid, a, b, _c = _three(client)
    res = _merge(
        client, h, a, [a, b], fields={"title": [b], "desiredOutcome": [b], "problem": [a, b]}
    )
    assert res.status_code == 200, res.text
    assert res.json()["title"] == "Dealer portal"
    # Edit one merged field afterwards - it must survive unmerge.
    client.patch(f"/ideation/ideas/{a}", headers=h, json={"desiredOutcome": "Edited later"})

    assert _unmerge(client, h, b).status_code == 200
    row_a = _idea_row(client._factory, a)
    assert row_a.title == "Order tracking"
    assert row_a.problem == "Dealers cannot track order status"
    assert row_a.desired_outcome == "Edited later"
    row_b = _idea_row(client._factory, b)
    assert row_b.merge_snapshot_json is None
    assert row_b.title == "Dealer portal"


def test_dissolve_group_restores_fields(ideation_client):
    client = ideation_client
    h, _pid, a, b, c = _three(client)
    res = _merge(client, h, a, [a, b, c], fields={"title": [c], "useCases": [b, c]})
    assert res.json()["title"] == "Ship notice"
    assert _unmerge(client, h, a).status_code == 200
    row_a = _idea_row(client._factory, a)
    assert row_a.title == "Order tracking"
    assert row_a.use_cases == ["Check shipping"]


def test_two_layered_merges_unwind(ideation_client):
    client = ideation_client
    h, _pid, a, b, c = _three(client)
    _merge(client, h, a, [a, b], fields={"title": [b]})
    _merge(client, h, a, [a, c], fields={"title": [c]})
    assert _idea_row(client._factory, a).title == "Ship notice"
    _unmerge(client, h, c)
    assert _idea_row(client._factory, a).title == "Dealer portal"
    _unmerge(client, h, b)
    assert _idea_row(client._factory, a).title == "Order tracking"


# ── AC-20-14 ─────────────────────────────────────────────────────────────────
def _comment(client, h, idea_id, body):
    res = client.post(f"/ideation/ideas/{idea_id}/comments", headers=h, json={"body": body})
    assert res.status_code == 201, res.text


def _attach(factory, idea_id, name):
    from modules.ideation.models import IdeaAttachment

    db = factory()
    try:
        db.add(
            IdeaAttachment(
                tenant_id=DEFAULT_TENANT_ID,
                idea_id=idea_id,
                kind="image",
                url="https://cdn.example/x.png",
                filename=name,
                source_msg_id=f"msg-{name}",
            )
        )
        db.commit()
    finally:
        db.close()


def test_survivor_reads_through_child_comments_and_attachments(ideation_client):
    client = ideation_client
    h, _pid, a, b, _c = _three(client)
    _comment(client, h, a, "on a")
    _comment(client, h, b, "on b")
    _attach(client._factory, a, "a.png")
    _attach(client._factory, b, "b.png")
    _merge(client, h, a, [a, b])

    comments = client.get(f"/ideation/ideas/{a}/comments", headers=h).json()
    by_body = {c["body"]: c for c in comments}
    assert set(by_body) == {"on a", "on b"}
    assert by_body["on a"]["fromIdea"] is None
    assert by_body["on b"]["fromIdea"] == {"id": b, "ideaNumber": "IDEA-0004"}
    assert by_body["on b"]["canEdit"] is False and by_body["on b"]["canDelete"] is False

    idea = client.get(f"/ideation/ideas/{a}", headers=h).json()
    names = {x["name"]: x for x in idea["attachments"]}
    assert set(names) == {"a.png", "b.png"}
    assert names["b.png"]["fromIdea"] == {"id": b, "ideaNumber": "IDEA-0004"}
    assert names["a.png"]["fromIdea"] is None

    # Child reads unchanged.
    child_comments = client.get(f"/ideation/ideas/{b}/comments", headers=h).json()
    assert [c["body"] for c in child_comments] == ["on b"]

    _unmerge(client, h, b)
    comments = client.get(f"/ideation/ideas/{a}/comments", headers=h).json()
    assert [c["body"] for c in comments] == ["on a"]
    idea = client.get(f"/ideation/ideas/{a}", headers=h).json()
    assert [x["name"] for x in idea["attachments"]] == ["a.png"]


def test_flatten_drops_stale_snapshot(ideation_client):
    """b merged into a (snapshot vs a), then a merged into d (b flattens onto
    d). Unmerging b must never 'restore' d from a snapshot taken against a."""
    client = ideation_client
    h, pid, a, b, _c = _three(client)
    d = _insert_idea(client._factory, pid, problem="Order visibility", idea_number="IDEA-0030")
    _set(client._factory, d, title="Visibility")
    assert _merge(client, h, a, [a, b], fields={"title": [b]}).json()["title"] == "Dealer portal"
    assert _merge(client, h, d, [d, a], fields={"title": [a]}).json()["title"] == "Dealer portal"
    assert _idea_row(client._factory, b).merged_into_id == d
    _unmerge(client, h, b)
    assert _idea_row(client._factory, d).title == "Dealer portal"
