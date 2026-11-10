"""Plan 20 S3 - Similar ideas (AC-20-20..22).

TEST-FIRST: written before ``GET /ideation/ideas/{id}/similar`` exists. The
ranking is ONE AI call (faked per test); there is NO text-match
fallback - an AI failure returns ``available: false``.
"""
from types import SimpleNamespace

from tests.test_ideation_clustering import (  # noqa: F401 - fixture re-export
    _auth,
    _idea,
    _product,
    _seed_llm_connection,
    ideation_client,
)


def _script(monkeypatch, structured=None, error=None):
    """Fake the ONE AI call. The AI stub is thread-local and TestClient runs
    the app on another thread, so patch ``AiClient.complete`` instead."""
    import modules.ideation.services.similar as similar_mod

    calls = []

    def fake(self, **kwargs):
        calls.append(kwargs)
        if error:
            raise RuntimeError(error)
        return SimpleNamespace(structured=structured), None

    monkeypatch.setattr(similar_mod.AiClient, "complete", fake)
    return calls


def _similar(client, h, idea_id):
    return client.get(f"/ideation/ideas/{idea_id}/similar", headers=h)


def _setup(client):
    h = _auth(client)
    pid = _product(client, h)
    other_pid = _product(client, h, name="Other product")
    cur = _idea(client, h, pid, "Dealers cannot track the status after they place an order.")
    portal = _idea(client, h, pid, "Dealer portal to see my orders")
    ship = _idea(client, h, pid, "Notify dealer when an order ships")
    quote = _idea(client, h, pid, "Quotation knowledge capture")
    foreign = _idea(client, h, other_pid, "Dealer order tracking in another product")
    return h, pid, cur, portal, ship, quote, foreign


def test_similar_ranked_by_ai_and_scoped(ideation_client, monkeypatch):
    client = ideation_client
    h, _pid, cur, portal, ship, quote, foreign = _setup(client)
    _seed_llm_connection(client._factory)
    calls = _script(
        monkeypatch, structured={"ideaIds": [ship, foreign, cur, "made-up-id", portal]}
    )
    res = _similar(client, h, cur)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["available"] is True
    # Order kept; ids outside the candidate set (other product, self, invented)
    # are dropped.
    assert [i["id"] for i in body["ideas"]] == [ship, portal]
    # ONE call; the candidate listing is the same product only, never self.
    assert len(calls) == 1
    content = calls[0]["messages"][0]["content"]
    for iid in (portal, ship, quote):
        assert iid in content
    assert foreign not in content
    assert f"- {cur}:" not in content


def test_similar_candidates_exclude_merged_and_test(ideation_client, monkeypatch):
    client = ideation_client
    h, _pid, cur, portal, ship, quote, _foreign = _setup(client)
    _seed_llm_connection(client._factory)
    client.post(
        "/ideation/ideas/merge", headers=h, json={"survivorId": cur, "ideaIds": [cur, quote]}
    )
    _script(monkeypatch, structured={"ideaIds": [quote, portal]})
    res = _similar(client, h, cur)
    assert [i["id"] for i in res.json()["ideas"]] == [portal]


def test_similar_unavailable_on_ai_error_no_fallback(ideation_client, monkeypatch):
    client = ideation_client
    h, *_rest = _setup(client)
    cur = _rest[1]
    _seed_llm_connection(client._factory)
    _script(monkeypatch, error="provider exploded")
    res = _similar(client, h, cur)
    assert res.status_code == 200, res.text
    assert res.json() == {"available": False, "ideas": []}


def test_similar_unavailable_on_unusable_output(ideation_client):
    client = ideation_client
    h, _pid, cur, *_ = _setup(client)
    # No scripted reply: the offline stub never fills an array -> unavailable,
    # never a word-match fallback.
    res = _similar(client, h, cur)
    assert res.json() == {"available": False, "ideas": []}


def test_similar_unavailable_on_unexpected_exception(ideation_client, monkeypatch):
    import modules.ideation.services.similar as similar_mod

    client = ideation_client
    h, _pid, cur, *_ = _setup(client)
    _seed_llm_connection(client._factory)

    def boom(self, **kwargs):
        raise RuntimeError("transport")

    monkeypatch.setattr(similar_mod.AiClient, "complete", boom)
    res = _similar(client, h, cur)
    assert res.status_code == 200
    assert res.json()["available"] is False


def test_similar_no_candidates_makes_no_ai_call(ideation_client, monkeypatch):
    import modules.ideation.services.similar as similar_mod

    client = ideation_client
    h = _auth(client)
    pid = _product(client, h)
    lone = _idea(client, h, pid, "Only idea on this product")

    def boom(self, **kwargs):
        raise AssertionError("AI must not be called with no candidates")

    monkeypatch.setattr(similar_mod.AiClient, "complete", boom)
    res = _similar(client, h, lone)
    assert res.json() == {"available": True, "ideas": []}


def test_similar_404_outside_tenant(ideation_client):
    client = ideation_client
    h = _auth(client)
    res = _similar(client, h, "no-such-idea")
    assert res.status_code == 404


def test_similar_never_rewrites_the_agent_connection(ideation_client, monkeypatch):
    """A read must not persist ``agent.connection_id`` (any viewer / the embed
    could otherwise rewrite tenant AI config)."""
    from app.models import DEFAULT_TENANT_ID
    from app.repositories.ai_repository import AgentRepository

    client = ideation_client
    h, _pid, cur, portal, *_ = _setup(client)
    _seed_llm_connection(client._factory)
    db = client._factory()
    try:
        agent = AgentRepository(db).get_by_key(DEFAULT_TENANT_ID, "ideation-grill")
        agent.connection_id = None
        db.commit()
    finally:
        db.close()
    seen = []

    def fake(self, **kwargs):
        seen.append(kwargs["agent"].connection_id)
        return SimpleNamespace(structured={"ideaIds": [portal]}), None

    import modules.ideation.services.similar as similar_mod

    monkeypatch.setattr(similar_mod.AiClient, "complete", fake)
    res = _similar(client, h, cur)
    assert res.json()["available"] is True
    assert seen and seen[0]  # this call used a connection
    db = client._factory()
    try:
        assert AgentRepository(db).get_by_key(DEFAULT_TENANT_ID, "ideation-grill").connection_id is None
    finally:
        db.close()
