"""Plan 20 S1 - canny-style idea fields (AC-20-01..05).

TEST-FIRST: written before ``desired_outcome`` / ``use_cases`` /
``current_workaround`` exist on ``Idea``. The intake key names are locked with
IDEA-CAPTURE (sorento-crm #1625).
"""
from pathlib import Path

import pytest

from tests.test_ideation_create_idea import _create_idea, _make_contact, _set_delivery
from tests.test_ideation_own import ctx, _one_shot  # noqa: F401 - fixture re-export
from tests.test_ideation_embed import ideation_client  # noqa: F401 - fixture re-export

VERSIONS_DIR = (
    Path(__file__).resolve().parents[1] / "modules" / "ideation" / "alembic" / "versions"
)


# ── AC-20-01 migration ────────────────────────────────────────────────────────
def test_migration_0017_is_additive_and_short_id():
    path = VERSIONS_DIR / "0017_ideation_canny_fields.py"
    src = path.read_text()
    assert 'revision = "0017_ideation_canny_fields"' in src
    assert len("0017_ideation_canny_fields") <= 32
    assert 'down_revision = "0016_ideation_own_ideas"' in src
    for col in ("desired_outcome", "use_cases", "current_workaround", "merge_snapshot_json"):
        assert col in src
    assert "ADD COLUMN IF NOT EXISTS" in src
    upgrade = src.split("def upgrade")[1].split("def downgrade")[0]
    assert "DROP" not in upgrade.upper()


# ── AC-20-02/03 one-shot intake ───────────────────────────────────────────────
def test_one_shot_persists_new_fields(ctx):
    client, h, product_id, key = ctx
    res = _one_shot(
        client,
        key,
        product_id,
        desired_outcome="  Dealers check order status themselves  ",
        use_cases=["Check shipped before promising a date", "  ", "See back-orders"],
        current_workaround="Phone the sales rep",
    )
    assert res.status_code == 201, res.text
    detail = client.get(f"/ideation/ideas/{res.json()['idea_id']}", headers=h).json()
    assert detail["desiredOutcome"] == "Dealers check order status themselves"
    assert detail["useCases"] == ["Check shipped before promising a date", "See back-orders"]
    assert detail["currentWorkaround"] == "Phone the sales rep"


def test_one_shot_without_new_fields_and_unknown_keys_ok(ctx):
    client, h, product_id, key = ctx
    res = _one_shot(client, key, product_id, some_future_key="ignored")
    assert res.status_code == 201, res.text
    detail = client.get(f"/ideation/ideas/{res.json()['idea_id']}", headers=h).json()
    assert detail["desiredOutcome"] is None
    assert detail["useCases"] == []
    assert detail["currentWorkaround"] is None


def test_one_shot_blank_strings_are_null(ctx):
    client, h, product_id, key = ctx
    res = _one_shot(client, key, product_id, desired_outcome="   ", current_workaround="")
    detail = client.get(f"/ideation/ideas/{res.json()['idea_id']}", headers=h).json()
    assert detail["desiredOutcome"] is None
    assert detail["currentWorkaround"] is None


def test_one_shot_use_cases_must_be_a_list(ctx):
    client, _h, product_id, key = ctx
    res = _one_shot(client, key, product_id, use_cases="not a list")
    assert res.status_code == 422, res.text


# ── AC-20-04 conversational intake ────────────────────────────────────────────
def test_turn_intake_captures_new_fields(ctx):
    client, h, product_id, key = ctx
    _set_delivery(client, h, product_id)
    contact_id = _make_contact(client._factory)
    res = _create_idea(
        client,
        key,
        contact_id,
        product_id,
        fields={
            "problem": "Dealers cannot track order status",
            "desired_outcome": "Self-service status",
            "use_cases": ["Check shipping"],
            "current_workaround": "Call sales",
        },
    )
    assert res.status_code == 200, res.text
    from modules.ideation.models import Idea

    db = client._factory()
    try:
        idea = db.query(Idea).filter(Idea.id == res.json()["draft_id"]).first()
        assert idea.desired_outcome == "Self-service status"
        assert idea.use_cases == ["Check shipping"]
        assert idea.current_workaround == "Call sales"
    finally:
        db.close()


def test_ask_order_unchanged():
    from modules.ideation.services.intake_definitions import OPTIONAL_ASK_ORDER

    assert OPTIONAL_ASK_ORDER == ("proposed_solution", "impact")


# ── AC-20-05 operator create + edit ───────────────────────────────────────────
def test_operator_create_and_patch_new_fields(ctx):
    client, h, product_id, _key = ctx
    res = client.post(
        "/ideation/ideas",
        headers=h,
        json={
            "productId": product_id,
            "problem": "Dealers cannot track order status",
            "desiredOutcome": "Self-service status",
            "useCases": ["Check shipping", ""],
            "currentWorkaround": "Call sales",
        },
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["useCases"] == ["Check shipping"]
    assert body["desiredOutcome"] == "Self-service status"

    res = client.patch(
        f"/ideation/ideas/{body['id']}",
        headers=h,
        json={
            "title": "Order tracking",
            "desiredOutcome": "",
            "useCases": ["A", "B"],
            "currentWorkaround": "Email the desk",
        },
    )
    assert res.status_code == 200, res.text
    out = res.json()
    assert out["title"] == "Order tracking"
    assert out["desiredOutcome"] is None
    assert out["useCases"] == ["A", "B"]
    assert out["currentWorkaround"] == "Email the desk"

    # Omitted keys are left alone (partial update).
    res = client.patch(f"/ideation/ideas/{body['id']}", headers=h, json={"problem": "P2"})
    assert res.json()["useCases"] == ["A", "B"]
    assert res.json()["title"] == "Order tracking"
