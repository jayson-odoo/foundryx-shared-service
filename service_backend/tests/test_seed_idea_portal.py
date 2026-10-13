"""The idea portal hand-test seed (lane IDEA-PORTAL): idempotent, covers every
roadmap column + an off-ramp, the two real ideas, a hidden idea and a
delivered idea with a changelog note - all visible through the portal API."""
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_portal import _staff_session  # noqa: F401
from tests.test_ideation_public_status import ideation_client, setup  # noqa: F401


def test_seed_is_idempotent_and_fills_the_portal(setup):
    from scripts.seed_idea_portal import seed_idea_portal

    s = setup
    db = s["factory"]()
    try:
        first = seed_idea_portal(db, DEFAULT_TENANT_ID)
        again = seed_idea_portal(db, DEFAULT_TENANT_ID)
    finally:
        db.close()
    assert first == {"created": 9, "skipped": 0}
    assert again == {"created": 0, "skipped": 9}

    c, h = s["client"], _staff_session(s)
    cols = {col["key"]: col for col in c.get("/portal/ideas/roadmap", headers=h).json()["columns"]}
    assert all(cols[k]["count"] >= 1 for k in ("under_review", "planned", "in_progress", "complete"))
    numbers = {i["ideaNumber"] for i in cols["under_review"]["ideas"]}
    assert {"IDEA-0010", "IDEA-0014"} <= numbers
    rejected = c.get("/portal/ideas?column=closed&includeClosed=true", headers=h).json()["items"]
    assert [i["title"] for i in rejected] == ["[sample] Free delivery for every order"]
    log = c.get("/portal/ideas/changelog", headers=h).json()["items"]
    assert log[0]["note"].startswith("[sample]")
    hidden = [i for i in c.get("/portal/ideas?pageSize=100", headers=h).json()["items"]
              if i["title"].startswith("[sample] Internal margin")]
    assert hidden and c.get(f"/portal/ideas/{hidden[0]['id']}", headers=h).json()["portalHidden"] is True
    price = [i for i in cols["under_review"]["ideas"] if "price list" in i["title"]][0]
    assert c.get(f"/portal/ideas/{price['id']}", headers=h).json()["useCases"] == [
        "Dealer quoting a walk-in customer", "Dealer preparing a project tender"]
    spec = [i for i in cols["planned"]["ideas"]][0]
    voters = c.get(f"/portal/ideas/{spec['id']}/voters", headers=h).json()
    assert {v["role"] for v in voters} == {"Staff", "Dealer"}
    feed = [e["kind"] for e in c.get(f"/portal/ideas/{spec['id']}/activity", headers=h).json()]
    assert {"status_changed", "comment", "upvote", "comment_like", "submitted"} <= set(feed)
