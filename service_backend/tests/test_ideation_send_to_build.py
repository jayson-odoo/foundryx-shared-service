"""BR Send to build - S2: readiness, Send endpoint, issue body, idempotency,
refusals (AC-STB-06, 09, 10, 11, 12, 21, 22).

RED until ``BuildHandoffService`` + ``POST /{id}/send-to-build`` +
``GET /{id}/build`` land. GitHub is faked with ``httpx.MockTransport`` injected
through ``build_handoff.DEFAULT_TRANSPORT``; the fake RECORDS every request so
call shape/count is asserted outside the service's own error handling.
"""
import re

import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.conftest import ACTIVE_EMAIL
from tests.ideation_build_helpers import (  # noqa: F401
    ALL_ANSWERS,
    REPO,
    FakeGitHub,
    _auth,
    _idea,
    _make_user,
    _product,
    br_status_key,
    ensure_other_tenant,
    ideation_client,
    insert_creating_row,
    insert_sent_br,
    make_br,
    marker_tail,
    search_item,
    sendable_setup,
    seed_github_connection,
    set_build_repo,
)

TEMPLATE_LABELS = [
    "Problem statement",
    "Business goal",
    "Stakeholders",
    "Success metric",
    "Scope",
    "Constraints",
]


def _install(monkeypatch, gh: FakeGitHub) -> FakeGitHub:
    from modules.ideation.services import build_handoff

    monkeypatch.setattr(build_handoff, "DEFAULT_TRANSPORT", gh.transport())
    return gh


def _send(client, h, br_id):
    return client.post(f"/ideation/business-requirements/{br_id}/send-to-build", headers=h)


def _detail(client, h, br_id):
    res = client.get(f"/ideation/business-requirements/{br_id}", headers=h)
    assert res.status_code == 200, res.text
    return res.json()


def _build_rows(factory, br_id):
    from modules.ideation.models import BrBuild

    db = factory()
    try:
        return [
            (r.state, r.issue_number, r.issue_url, r.issue_node_id, r.repo, r.sent_by)
            for r in db.query(BrBuild).filter(BrBuild.business_requirement_id == br_id)
        ]
    finally:
        db.close()


def _events(factory, br_id):
    from modules.ideation.models import BrBuildEvent

    db = factory()
    try:
        return [
            (e.kind, e.stage, e.actor_user_id, e.status_moved)
            for e in db.query(BrBuildEvent)
            .filter(BrBuildEvent.business_requirement_id == br_id)
            .order_by(BrBuildEvent.seq)
        ]
    finally:
        db.close()


def _user_id(factory, email=ACTIVE_EMAIL):
    from app.models import User

    db = factory()
    try:
        return db.query(User).filter(User.email == email, User.tenant_id == DEFAULT_TENANT_ID).one().id
    finally:
        db.close()


# ── AC-STB-06 readiness ───────────────────────────────────────────────────────


def test_ac_stb_06_detail_carries_build_can_send_true(ideation_client):
    s = sendable_setup(ideation_client)
    build = _detail(ideation_client, s["h"], s["br_id"])["build"]
    assert build["canSend"] is True
    assert build["blockers"] == []
    assert build["repo"] == REPO
    assert build["issueUrl"] is None and build["issueNumber"] is None
    assert build["sentAt"] is None and build["sentBy"] is None
    for key in ("state", "stage", "prUrl", "handtestUrl"):
        assert key in build


def test_ac_stb_06_blockers_in_order_missing_then_repo_then_github(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h, name="Sorento CRM")
    # Two required fields left blank (business_goal, success_metric).
    br_id = make_br(ideation_client, h, pid, answers={**ALL_ANSWERS, "business_goal": "", "success_metric": None})
    build = _detail(ideation_client, h, br_id)["build"]
    assert build["canSend"] is False
    assert build["blockers"] == [
        "Missing: Business goal, Success metric",
        "Set the build repository on the product Sorento CRM",
        "Connect GitHub in Settings > Integrations",
    ]


def test_ac_stb_06_each_blocker_clears_independently(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h, name="Sorento CRM")
    br_id = make_br(ideation_client, h, pid)  # complete answers
    assert _detail(ideation_client, h, br_id)["build"]["blockers"] == [
        "Set the build repository on the product Sorento CRM",
        "Connect GitHub in Settings > Integrations",
    ]
    set_build_repo(ideation_client._factory, pid)
    assert _detail(ideation_client, h, br_id)["build"]["blockers"] == [
        "Connect GitHub in Settings > Integrations",
    ]
    seed_github_connection(ideation_client._factory)
    build = _detail(ideation_client, h, br_id)["build"]
    assert build["blockers"] == [] and build["canSend"] is True


def test_ac_stb_06_inactive_connection_still_blocks(ideation_client):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    set_build_repo(ideation_client._factory, pid)
    seed_github_connection(ideation_client._factory, active=False)
    br_id = make_br(ideation_client, h, pid)
    build = _detail(ideation_client, h, br_id)["build"]
    assert build["canSend"] is False
    assert "Connect GitHub in Settings > Integrations" in build["blockers"]


def test_ac_stb_06_other_tenants_connection_does_not_count(
    ideation_client, ideation_session_factory
):
    other = ensure_other_tenant(ideation_session_factory)
    seed_github_connection(ideation_session_factory, tenant_id=other)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    set_build_repo(ideation_session_factory, pid)
    br_id = make_br(ideation_client, h, pid)
    build = _detail(ideation_client, h, br_id)["build"]
    assert build["canSend"] is False
    assert build["blockers"] == ["Connect GitHub in Settings > Integrations"]


def test_ac_stb_06_get_build_endpoint_returns_same_object_with_events(ideation_client):
    s = sendable_setup(ideation_client)
    res = ideation_client.get(
        f"/ideation/business-requirements/{s['br_id']}/build", headers=s["h"]
    )
    assert res.status_code == 200, res.text
    build = res.json()
    assert build["canSend"] is True
    assert build["events"] == []


def test_ac_stb_06_get_build_is_tenant_scoped_404(ideation_client, ideation_session_factory):
    ensure_other_tenant(ideation_session_factory)
    from tests.ideation_build_helpers import OTHER_TENANT_ID

    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    foreign = insert_sent_br(
        ideation_session_factory, tenant_id=OTHER_TENANT_ID, product_id=pid
    )
    res = ideation_client.get(f"/ideation/business-requirements/{foreign}/build", headers=h)
    assert res.status_code == 404, res.text


def test_ac_stb_06_read_only_user_can_read_build_but_not_send(
    ideation_client, ideation_session_factory
):
    _make_user(
        ideation_session_factory,
        "buildreader@example.com",
        "Reader123!",
        {"ideation.business_requirements.read"},
    )
    s = sendable_setup(ideation_client)
    h = _auth(ideation_client, email="buildreader@example.com", password="Reader123!")
    got = ideation_client.get(f"/ideation/business-requirements/{s['br_id']}/build", headers=h)
    assert got.status_code == 200, got.text
    assert _send(ideation_client, h, s["br_id"]).status_code == 403


def test_ac_stb_06_after_send_can_send_is_false(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub())
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    assert _detail(ideation_client, s["h"], s["br_id"])["build"]["canSend"] is False


# ── AC-STB-09 send ────────────────────────────────────────────────────────────


def test_ac_stb_09_send_creates_one_issue_and_moves_status(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client, title="Order export")
    gh = _install(monkeypatch, FakeGitHub(issue_number=4242))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["id"] == s["br_id"]
    assert body["status"] == "sent_to_build"
    build = body["build"]
    assert build["state"] == "sent"
    assert build["issueNumber"] == 4242
    assert build["issueUrl"] == f"https://github.com/{REPO}/issues/4242"
    assert build["repo"] == REPO
    assert build["sentAt"] is not None
    assert gh.unexpected == []
    # Exactly one issue create, with the label + title.
    assert len(gh.issue_posts) == 1
    assert gh.issue_posts[0]["title"] == "Order export"
    assert gh.issue_posts[0]["labels"] == ["crew-intake"]
    assert all(a == "Bearer ghp_test" for a in gh.auth_headers)
    # Persisted.
    assert _build_rows(ideation_client._factory, s["br_id"]) == [
        ("sent", 4242, f"https://github.com/{REPO}/issues/4242", "I_node_4242", REPO, _user_id(ideation_client._factory))
    ]
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "sent_to_build"


def test_ac_stb_09_label_ensured_created_once_with_brand_colour(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(label_exists=False))
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    assert f"/repos/{REPO}/labels/crew-intake" in gh.paths("GET")
    assert gh.label_posts == [{"name": "crew-intake", "color": "ff5a00"}]
    # The label exists BEFORE the issue create.
    order = [(c.method, c.url.path) for c in gh.calls]
    assert order.index(("POST", f"/repos/{REPO}/labels")) < order.index(
        ("POST", f"/repos/{REPO}/issues")
    )


def test_ac_stb_09_existing_label_is_not_recreated(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(label_exists=True))
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    assert gh.label_posts == []


def test_ac_stb_09_sent_event_recorded_with_actor(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    uid = _user_id(ideation_client._factory)
    events = _events(ideation_client._factory, s["br_id"])
    assert len(events) == 1
    kind, stage, actor, _moved = events[0]
    assert (kind, stage, actor) == ("sent", "Sent", uid)
    build = res.json()["build"]
    assert build["events"][0]["stage"] == "Sent"
    assert build["sentBy"] == {"id": uid, "name": "Demo User"}
    assert build["stage"] == "Sent"


def test_ac_stb_09_build_endpoint_after_send_lists_the_sent_entry(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub())
    _send(ideation_client, s["h"], s["br_id"])
    build = ideation_client.get(
        f"/ideation/business-requirements/{s['br_id']}/build", headers=s["h"]
    ).json()
    assert [e["stage"] for e in build["events"]] == ["Sent"]
    assert build["events"][0]["kind"] == "sent"


@pytest.mark.parametrize("via", ["draft", "grilling", "ready"])
def test_ac_stb_09_send_allowed_from_draft_grilling_ready(ideation_client, monkeypatch, via):
    s = sendable_setup(ideation_client)
    h, bid = s["h"], s["br_id"]
    if via in ("grilling",):
        assert ideation_client.post(
            f"/ideation/business-requirements/{bid}/status", headers=h, json={"status": "grilling"}
        ).status_code == 200
    if via == "ready":
        assert ideation_client.post(
            f"/ideation/business-requirements/{bid}/status", headers=h, json={"status": "ready"}
        ).status_code == 200
    assert br_status_key(ideation_client, h, bid) == via
    _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, h, bid)
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "sent_to_build"


def test_ac_stb_09_status_move_uses_the_engine_edge(ideation_client, monkeypatch):
    """The move fires through status_machine.transition on the send edge for the
    source status (StatusTransitioned carries the edge id)."""
    from app import events as core_events

    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub())
    seen = []
    core_events.subscribe(core_events.EVENT_STATUS_TRANSITIONED, seen.append)
    try:
        assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    finally:
        core_events.unsubscribe(core_events.EVENT_STATUS_TRANSITIONED, seen.append)
    mine = [p for p in seen if p.get("record_id") == s["br_id"]]
    assert [p["transition_id"] for p in mine] == ["br-tr-send-to-build-draft"]
    assert mine[0]["to_status_id"] == "br-status-sent-to-build"


# ── AC-STB-10 issue body ──────────────────────────────────────────────────────


def _body_of_send(client, monkeypatch, s):
    gh = _install(monkeypatch, FakeGitHub())
    assert _send(client, s["h"], s["br_id"]).status_code == 200
    return gh.issue_posts[0]["body"], gh


def test_ac_stb_10_body_has_one_section_per_template_field_in_order(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    headings = re.findall(r"^## (.+)$", body, flags=re.M)
    assert headings[: len(TEMPLATE_LABELS)] == TEMPLATE_LABELS
    assert "Linked ideas" in headings
    assert "Links" in headings
    assert headings.index("Linked ideas") < headings.index("Links")
    # Answers rendered under their heading; blank optional field -> placeholder.
    assert "CS cannot export orders." in body
    assert "50% fewer support tickets." in body
    assert "Customer support." in body


def test_ac_stb_10_body_iterates_the_stamped_template_not_hardcoded_keys(
    ideation_client, ideation_session_factory, monkeypatch
):
    """A BR stamped at a template v2 with an extra field renders that field's
    label; a BR stamped at v1 does not (no hardcoded keys)."""
    from modules.ideation.models import (
        IdeationArtifactTemplate,
        IdeationArtifactTemplateVersion,
    )
    from modules.ideation.services.br_templates import BR_TEMPLATE_KEY, br_target_schema

    db = ideation_session_factory()
    try:
        template = (
            db.query(IdeationArtifactTemplate)
            .filter(
                IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
                IdeationArtifactTemplate.tenant_id.is_(None),
            )
            .first()
        )
        doc = br_target_schema().model_dump(mode="json")
        doc["pages"][0]["sections"][0]["fields"].append(
            {"id": "f-rollout", "type": "textarea", "key": "rollout_plan",
             "label": "Rollout plan", "required": False}
        )
        v2 = IdeationArtifactTemplateVersion(
            template_id=template.id, tenant_id=None, version=2, doc_json=doc
        )
        db.add(v2)
        db.flush()
        template.active_version_id = v2.id
        db.commit()
    finally:
        db.close()

    s = sendable_setup(ideation_client)
    res = ideation_client.patch(
        f"/ideation/business-requirements/{s['br_id']}",
        headers=s["h"],
        json={"answers": {**ALL_ANSWERS, "rollout_plan": "Phase it."}},
    )
    assert res.status_code == 200, res.text
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    headings = re.findall(r"^## (.+)$", body, flags=re.M)
    assert headings[:7] == TEMPLATE_LABELS + ["Rollout plan"]
    assert "Phase it." in body


def test_ac_stb_10_linked_ideas_with_votes(ideation_client, monkeypatch):
    from modules.ideation.models import Idea

    s = sendable_setup(ideation_client)
    idea_id = _idea(ideation_client, s["h"], s["pid"], "Export orders to CSV")
    db = ideation_client._factory()
    try:
        idea = db.get(Idea, idea_id)
        idea.idea_number = "IDEA-0042"
        idea.upvotes, idea.downvotes = 3, 1
        db.commit()
    finally:
        db.close()
    res = ideation_client.post(
        f"/ideation/business-requirements/{s['br_id']}/ideas",
        headers=s["h"],
        json={"ideaIds": [idea_id]},
    )
    assert res.status_code == 200, res.text
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    section = body.split("## Linked ideas", 1)[1].split("\n## ", 1)[0]
    assert re.search(r"^- IDEA-0042 .*\(\+3 / -1\)$", section, flags=re.M), section


def test_ac_stb_10_links_section_and_markers_last(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    links = body.split("## Links", 1)[1]
    base = settings.frontend_url.rstrip("/")
    assert f"{base}/ideation/business-requirements/{s['br_id']}" in links
    lines = [ln for ln in body.rstrip().splitlines() if ln.strip()]
    assert lines[-2:] == [
        f"<!-- br-id: {s['br_id']} -->",
        f"<!-- br-product: {s['pid']} -->",
    ]


def test_ac_stb_10_no_em_or_en_dash_in_generated_body(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    assert "\u2014" not in body and "\u2013" not in body


def test_ac_stb_10_transcript_omitted_without_grill_messages(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    assert "## Grill transcript" not in body


def _seed_transcript(factory, br_id, turns):
    from app.repositories.ai_repository import ConversationRepository
    from modules.ideation.services.grill import GRILL_DEFINITION_KEY
    from modules.ideation.services.statuses import BR_ENTITY

    db = factory()
    try:
        repo = ConversationRepository(db)
        convo = repo.get_or_create_for_target(
            DEFAULT_TENANT_ID,
            target_type=BR_ENTITY,
            target_id=br_id,
            grill_definition_key=GRILL_DEFINITION_KEY,
        )
        for role, content in turns:
            repo.add_message(
                conversation_id=convo.id, tenant_id=DEFAULT_TENANT_ID, role=role, content=content
            )
        db.commit()
    finally:
        db.close()


def test_ac_stb_10_transcript_rendered_in_order(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _seed_transcript(
        ideation_client._factory,
        s["br_id"],
        [("assistant", "What is the problem?"), ("user", "Orders cannot be exported.")],
    )
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    section = body.split("## Grill transcript", 1)[1].split("\n## ", 1)[0]
    assert section.index("**assistant:** What is the problem?") < section.index(
        "**user:** Orders cannot be exported."
    )


def test_ac_stb_10_huge_transcript_truncated_under_github_limit(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _seed_transcript(
        ideation_client._factory,
        s["br_id"],
        [("user" if i % 2 else "assistant", "x" * 1000) for i in range(200)],
    )
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    assert len(body) < 65536
    assert "(transcript truncated)" in body
    assert body.rstrip().endswith(f"<!-- br-product: {s['pid']} -->")
    # The answers survive; only the transcript is cut.
    assert "CS cannot export orders." in body


# ── AC-STB-11 idempotency ────────────────────────────────────────────────────


def test_ac_stb_11_second_send_returns_same_issue_without_a_github_call(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(issue_number=91))
    first = _send(ideation_client, s["h"], s["br_id"])
    assert first.status_code == 200, first.text
    calls_after_first = len(gh.calls)
    second = _send(ideation_client, s["h"], s["br_id"])
    assert second.status_code == 200, second.text
    assert len(gh.calls) == calls_after_first  # the handler was NOT hit again
    assert second.json()["build"]["issueNumber"] == 91
    assert second.json()["status"] == "sent_to_build"
    assert len(_build_rows(ideation_client._factory, s["br_id"])) == 1
    assert len(_events(ideation_client._factory, s["br_id"])) == 1


def test_ac_stb_11_creating_row_adopts_existing_issue_by_marker(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=300)
    genuine = search_item(55, "## Problem statement\n\nx\n\n" + marker_tail(s["br_id"], s["pid"]))
    gh = _install(monkeypatch, FakeGitHub(search_items=[genuine]))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    searches = [c for c in gh.calls if c.url.path == "/search/issues"]
    assert len(searches) == 1
    q = searches[0].url.params["q"]
    assert f'"br-id: {s["br_id"]}" in:body' in q
    assert f"repo:{REPO}" in q
    assert gh.issue_posts == []  # adopted, not re-created
    build = res.json()["build"]
    assert build["issueNumber"] == 55 and build["state"] == "sent"
    assert res.json()["status"] == "sent_to_build"
    assert len(_build_rows(ideation_client._factory, s["br_id"])) == 1


def test_ac_stb_11_creating_row_with_no_marker_hit_creates_one_issue(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=300)
    gh = _install(monkeypatch, FakeGitHub(search_items=[], issue_number=66))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    assert len(gh.issue_posts) == 1
    assert res.json()["build"]["issueNumber"] == 66
    assert len(_build_rows(ideation_client._factory, s["br_id"])) == 1


# ── SEC F2: in-flight guard + strict adoption ────────────────────────────────


def test_sec_f2_ac_stb_11_fresh_creating_row_is_409_and_makes_no_github_call(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=0)
    gh = _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 409, res.text
    assert gh.calls == []
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"
    # The in-flight row is left for the other request (not dropped).
    assert [r[0] for r in _build_rows(ideation_client._factory, s["br_id"])] == ["creating"]


def test_sec_f2_ac_stb_11_creating_row_older_than_120s_runs_recovery_search(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=121)
    gh = _install(monkeypatch, FakeGitHub(search_items=[], issue_number=70))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    assert len([c for c in gh.calls if c.url.path == "/search/issues"]) == 1
    assert res.json()["build"]["issueNumber"] == 70


def test_sec_f2_ac_stb_11_planted_marker_mid_text_is_not_adopted(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=300)
    planted = search_item(
        13,
        f"someone else's issue <!-- br-id: {s['br_id']} --> and then more text after it\n"
        "unrelated tail\n",
    )
    gh = _install(monkeypatch, FakeGitHub(search_items=[planted], issue_number=80))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    assert len(gh.issue_posts) == 1  # a NEW issue, the planted one was not adopted
    assert res.json()["build"]["issueNumber"] == 80


def test_sec_f2_ac_stb_11_hit_with_only_the_id_marker_is_not_adopted(ideation_client, monkeypatch):
    """The body must end with BOTH exact lines (br-id then br-product)."""
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=300)
    half = search_item(14, f"body\n\n<!-- br-id: {s['br_id']} -->\n")
    gh = _install(monkeypatch, FakeGitHub(search_items=[half], issue_number=81))
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    assert len(gh.issue_posts) == 1


def test_sec_f2_ac_stb_11_hit_for_another_product_is_not_adopted(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=300)
    other = search_item(15, "body\n\n" + marker_tail(s["br_id"], "some-other-product-id"))
    gh = _install(monkeypatch, FakeGitHub(search_items=[other], issue_number=82))
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    assert len(gh.issue_posts) == 1


def test_sec_f2_ac_stb_11_hit_without_crew_intake_label_is_not_adopted(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    insert_creating_row(ideation_client._factory, s["br_id"], age_seconds=300)
    unlabeled = search_item(
        16, "body\n\n" + marker_tail(s["br_id"], s["pid"]), labels=("bug",)
    )
    gh = _install(monkeypatch, FakeGitHub(search_items=[unlabeled], issue_number=83))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    assert len(gh.issue_posts) == 1
    assert res.json()["build"]["issueNumber"] == 83


# ── SEC F4/F5: tenant text cannot forge markers, mentions or cross-references ─


def _send_with_answer(client, monkeypatch, answer: str):
    s = sendable_setup(client)
    res = client.patch(
        f"/ideation/business-requirements/{s['br_id']}",
        headers=s["h"],
        json={"answers": {**ALL_ANSWERS, "problem_statement": answer}},
    )
    assert res.status_code == 200, res.text
    body, _ = _body_of_send(client, monkeypatch, s)
    return s, body


def test_sec_f4_ac_stb_10_planted_marker_in_answer_is_neutralised(ideation_client, monkeypatch):
    s, body = _send_with_answer(
        ideation_client,
        monkeypatch,
        "Real text <!-- br-id: 0000 --> and <!-- br-product: evil -->",
    )
    assert body.count("<!--") == 2
    lines = body.rstrip().splitlines()
    tail_start = len(body.rstrip()) - len("\n".join(lines[-2:]))
    assert body.index("<!--") >= tail_start  # both remaining markers are the final two lines
    assert lines[-2:] == [
        f"<!-- br-id: {s['br_id']} -->",
        f"<!-- br-product: {s['pid']} -->",
    ]
    assert "br-id: 0000" not in body.split("## Links", 1)[0].replace("<!\u200b--", "")  # not a live marker
    assert "Real text" in body  # the text itself is kept


def test_sec_f4_ac_stb_10_planted_marker_in_linked_idea_is_neutralised(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    idea_id = _idea(ideation_client, s["h"], s["pid"], "Idea <!-- br-id: 0000 --> text")
    res = ideation_client.post(
        f"/ideation/business-requirements/{s['br_id']}/ideas",
        headers=s["h"],
        json={"ideaIds": [idea_id]},
    )
    assert res.status_code == 200, res.text
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    assert body.count("<!--") == 2
    assert "Idea" in body.split("## Linked ideas", 1)[1]


def test_sec_f4_ac_stb_10_planted_marker_in_grill_transcript_is_neutralised(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    _seed_transcript(
        ideation_client._factory, s["br_id"], [("user", "hi <!-- br-id: 0000 --> there")]
    )
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    assert body.count("<!--") == 2


def test_sec_f5_ac_stb_10_at_mentions_are_defused(ideation_client, monkeypatch):
    _s, body = _send_with_answer(ideation_client, monkeypatch, "Ping @someone and @org/team please")
    assert "@someone" not in body
    assert "@\u200bsomeone" in body
    assert "@org/team" not in body


def test_sec_f5_ac_stb_10_issue_cross_references_are_defused(ideation_client, monkeypatch):
    _s, body = _send_with_answer(
        ideation_client, monkeypatch, "See #123 and other-org/other-repo#12 for context"
    )
    assert "#123" not in body
    assert "#\u200b123" in body
    assert "repo#12" not in body
    assert "repo#\u200b12" in body


# ── SEC F6: never post tenant text into a public repository ──────────────────


def test_sec_f6_ac_stb_09_public_repo_is_refused_422_and_nothing_created(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(repo_private=False))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 422, res.text
    assert "public" in res.text
    assert gh.issue_posts == [] and gh.label_posts == []
    assert f"/repos/{REPO}" in gh.paths("GET")
    assert _build_rows(ideation_client._factory, s["br_id"]) == []
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"


def test_sec_f6_ac_stb_09_private_repo_checked_before_the_issue_is_created(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(repo_private=True))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    order = [(c.method, c.url.path) for c in gh.calls]
    assert order.index(("GET", f"/repos/{REPO}")) < order.index(("POST", f"/repos/{REPO}/issues"))


def test_ac_stb_11_unique_index_on_business_requirement_id(ideation_client):
    """Kill-test target: with the unique index removed the loser of a concurrent
    send would not fail. One row per BR, enforced by the database."""
    from sqlalchemy.exc import IntegrityError

    from modules.ideation.models import BrBuild

    s = sendable_setup(ideation_client)
    db = ideation_client._factory()
    try:
        db.add(
            BrBuild(tenant_id=DEFAULT_TENANT_ID, business_requirement_id=s["br_id"], repo=REPO, state="creating")
        )
        db.commit()
        db.add(
            BrBuild(tenant_id=DEFAULT_TENANT_ID, business_requirement_id=s["br_id"], repo=REPO, state="creating")
        )
        with pytest.raises(IntegrityError):
            db.commit()
        db.rollback()
        # Control: the first row is intact and a row for ANOTHER BR still inserts.
        other = make_br(ideation_client, s["h"], s["pid"], title="Other")
        db.add(BrBuild(tenant_id=DEFAULT_TENANT_ID, business_requirement_id=other, repo=REPO, state="creating"))
        db.commit()
        assert db.query(BrBuild).count() == 2
    finally:
        db.close()


def test_ac_stb_11_resend_after_back_to_ready_comments_on_same_issue(
    ideation_client, monkeypatch
):
    """Plan D10: a BR sent, sent back to ready, then re-sent reuses the SAME
    issue - an issue comment, never a second issue."""
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(issue_number=12))
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    back = ideation_client.post(
        f"/ideation/business-requirements/{s['br_id']}/status",
        headers=s["h"],
        json={"status": "ready"},
    )
    assert back.status_code == 200, back.text
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 200, res.text
    assert len(gh.issue_posts) == 1
    assert len(gh.comment_posts) == 1
    assert gh.comment_posts[0]["body"].startswith("Re-sent to build")
    assert res.json()["status"] == "sent_to_build"
    assert res.json()["build"]["issueNumber"] == 12
    assert len(_build_rows(ideation_client._factory, s["br_id"])) == 1


# ── AC-STB-12 refusals ───────────────────────────────────────────────────────


def test_ac_stb_12_not_sendable_is_422_with_blockers_and_no_github_call(
    ideation_client, monkeypatch
):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h, name="Sorento CRM")
    seed_github_connection(ideation_client._factory)
    br_id = make_br(ideation_client, h, pid)  # complete, but no build repo
    gh = _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, h, br_id)
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert detail["message"] == "Set the build repository on the product Sorento CRM"
    assert detail["blockers"] == ["Set the build repository on the product Sorento CRM"]
    assert gh.calls == []
    assert _build_rows(ideation_client._factory, br_id) == []
    assert br_status_key(ideation_client, h, br_id) == "draft"


def test_ac_stb_12_incomplete_answers_422_names_the_labels(ideation_client, monkeypatch):
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    set_build_repo(ideation_client._factory, pid)
    seed_github_connection(ideation_client._factory)
    br_id = make_br(ideation_client, h, pid, answers={**ALL_ANSWERS, "business_goal": "", "success_metric": None})
    gh = _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, h, br_id)
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["blockers"][0] == "Missing: Business goal, Success metric"
    assert "Business goal" in res.json()["detail"]["message"]
    assert gh.calls == []


def test_ac_stb_12_unknown_br_404(ideation_client, monkeypatch):
    """Control (the route exists and a real BR sends) + the unknown id is 404."""
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub())
    assert _send(ideation_client, s["h"], "nope").status_code == 404
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200


def test_ac_stb_12_other_tenants_br_404_and_no_github_call(
    ideation_client, ideation_session_factory, monkeypatch
):
    from tests.ideation_build_helpers import OTHER_TENANT_ID

    ensure_other_tenant(ideation_session_factory)
    h = _auth(ideation_client)
    pid = _product(ideation_client, h)
    foreign = insert_sent_br(
        ideation_session_factory,
        tenant_id=OTHER_TENANT_ID,
        product_id=pid,
        status_key="draft",
        with_build=False,
    )
    gh = _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, h, foreign)
    assert res.status_code == 404, res.text
    assert gh.calls == []


@pytest.mark.parametrize("gh_status", [401, 403])
def test_ac_stb_12_github_rejects_token_is_502_and_leaves_nothing_behind(
    ideation_client, monkeypatch, gh_status
):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(issue_status=gh_status))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert "GitHub rejected the token" in res.text
    assert "ghp_test" not in res.text
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"
    assert _build_rows(ideation_client._factory, s["br_id"]) == []
    assert _events(ideation_client._factory, s["br_id"]) == []
    # Control: after the outage clears, the very same BR sends (no stuck row).
    _install(monkeypatch, FakeGitHub())
    ok = _send(ideation_client, s["h"], s["br_id"])
    assert ok.status_code == 200, ok.text
    assert ok.json()["status"] == "sent_to_build"


def test_ac_stb_12_github_404_names_the_repo(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub(issue_status=404))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert REPO in res.text
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"
    assert _build_rows(ideation_client._factory, s["br_id"]) == []


def test_ac_stb_12_github_unreachable_is_502(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub(connect_error=True))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert "ghp_test" not in res.text
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"
    assert _build_rows(ideation_client._factory, s["br_id"]) == []


def test_ac_stb_12_send_without_permission_403_and_no_github_call(
    ideation_client, ideation_session_factory, monkeypatch
):
    _make_user(
        ideation_session_factory,
        "promoteless@example.com",
        "Nope12345!",
        {"ideation.business_requirements.read", "ideation.business_requirements.manage"},
    )
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub())
    h = _auth(ideation_client, email="promoteless@example.com", password="Nope12345!")
    assert _send(ideation_client, h, s["br_id"]).status_code == 403
    assert gh.calls == []
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"


# ── AC-STB-21 test BRs ───────────────────────────────────────────────────────


def _mark_test(factory, br_id):
    from modules.ideation.models import BusinessRequirement

    db = factory()
    try:
        db.get(BusinessRequirement, br_id).is_test = True
        db.commit()
    finally:
        db.close()


def test_ac_stb_21_test_br_cannot_be_sent(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client)
    _mark_test(ideation_client._factory, s["br_id"])
    gh = _install(monkeypatch, FakeGitHub())
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 422, res.text
    assert res.json()["detail"]["message"] == "Test requirements cannot be sent to build"
    assert gh.calls == []
    assert _build_rows(ideation_client._factory, s["br_id"]) == []
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"


def test_ac_stb_21_test_br_readiness_blocker(ideation_client):
    s = sendable_setup(ideation_client)
    _mark_test(ideation_client._factory, s["br_id"])
    build = _detail(ideation_client, s["h"], s["br_id"])["build"]
    assert build["canSend"] is False
    assert "Test requirements cannot be sent to build" in build["blockers"]


# ── AC-STB-22 failure isolation (Send side) ──────────────────────────────────


def test_ac_stb_22_outage_never_leaves_sent_status_without_an_issue(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub(issue_status=500))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert br_status_key(ideation_client, s["h"], s["br_id"]) != "sent_to_build"
    assert [r[1] for r in _build_rows(ideation_client._factory, s["br_id"])] in ([], [None])


# ── R3: the `creating` row is the crash-recovery anchor ──────────────────────


def _states(client, br_id):
    return [r[0] for r in _build_rows(client._factory, br_id)]


def test_r3_ac_stb_11_issue_create_timeout_keeps_creating_row_and_is_502(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(issue_timeout=True))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert len(gh.issue_posts) == 1  # the create WAS attempted (timeout is ambiguous)
    assert _states(ideation_client, s["br_id"]) == ["creating"]
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"


@pytest.mark.parametrize("gh_status", [500, 502, 503])
def test_r3_ac_stb_11_issue_create_5xx_keeps_creating_row_and_is_502(
    ideation_client, monkeypatch, gh_status
):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub(issue_status=gh_status))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert _states(ideation_client, s["br_id"]) == ["creating"]


@pytest.mark.parametrize("gh_status", [401, 403, 404, 422])
def test_r3_ac_stb_12_definitive_issue_create_refusal_deletes_the_row(
    ideation_client, monkeypatch, gh_status
):
    s = sendable_setup(ideation_client)
    _install(monkeypatch, FakeGitHub(issue_status=gh_status))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert _states(ideation_client, s["br_id"]) == []


@pytest.mark.parametrize(
    "knobs",
    [
        {"label_lookup_status": 500},  # label lookup fails (before create)
        {"label_lookup_status": 401},
        {"label_exists": False, "label_create_status": 500},  # label create fails
        {"label_exists": False, "label_create_status": 403},
    ],
)
def test_r3_ac_stb_12_label_step_failure_deletes_the_row(ideation_client, monkeypatch, knobs):
    s = sendable_setup(ideation_client)
    gh = _install(monkeypatch, FakeGitHub(**knobs))
    res = _send(ideation_client, s["h"], s["br_id"])
    assert res.status_code == 502, res.text
    assert gh.issue_posts == []  # never reached the create
    assert _states(ideation_client, s["br_id"]) == []
    assert br_status_key(ideation_client, s["h"], s["br_id"]) == "draft"


# ── R11: body size + title scrub ─────────────────────────────────────────────


def test_r11_ac_stb_10_huge_answers_still_fit_and_keep_the_marker_tail(
    ideation_client, monkeypatch
):
    s = sendable_setup(ideation_client)
    res = ideation_client.patch(
        f"/ideation/business-requirements/{s['br_id']}",
        headers=s["h"],
        json={
            "answers": {
                **ALL_ANSWERS,
                "problem_statement": "p" * 40000,
                "business_goal": "g" * 40000,
            }
        },
    )
    assert res.status_code == 200, res.text
    body, _ = _body_of_send(ideation_client, monkeypatch, s)
    assert len(body) <= 65000
    assert "(truncated)" in body
    lines = [ln for ln in body.rstrip().splitlines() if ln.strip()]
    assert lines[-2:] == [
        f"<!-- br-id: {s['br_id']} -->",
        f"<!-- br-product: {s['pid']} -->",
    ]
    assert re.findall(r"^## (.+)$", body, flags=re.M)[-1] == "Links"


def test_r11_ac_stb_10_title_dashes_are_scrubbed_in_the_issue_title(ideation_client, monkeypatch):
    s = sendable_setup(ideation_client, title="Order \u2014 export \u2013 v2")
    gh = _install(monkeypatch, FakeGitHub())
    assert _send(ideation_client, s["h"], s["br_id"]).status_code == 200
    title = gh.issue_posts[0]["title"]
    assert "\u2014" not in title and "\u2013" not in title
    assert title == "Order - export - v2"
