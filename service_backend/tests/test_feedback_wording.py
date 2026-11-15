"""SS-FEEDBACK-RENAME (owner ruling 15 Nov): no user-visible "idea".

The stored number / type value / tables stay; what a user reads or opens
(status-page copy, WhatsApp reply text, the item number, the status link,
error messages) says feedback. Test-first: written before the rename.
"""
import re

import pytest

from app.models import DEFAULT_TENANT_ID

IDEA_WORD = re.compile(r"\bideas?\b", re.I)


@pytest.fixture
def db(ideation_session_factory):
    s = ideation_session_factory()
    try:
        yield s
    finally:
        s.close()


def test_display_number_uses_feedback_prefix():
    from modules.ideation.services.numbering import display_idea_number

    assert display_idea_number("IDEA-0016") == "FB-0016"
    assert display_idea_number("IDEA-10000") == "FB-10000"
    assert display_idea_number(None) is None
    assert display_idea_number("") == ""
    # Anything not in the stored shape passes through untouched.
    assert display_idea_number("XYZ-1") == "XYZ-1"


def test_stored_number_is_unchanged():
    from modules.ideation.services import numbering

    assert numbering._NUMBER_RE.match("IDEA-0016")


def test_status_link_points_at_feedback_page(db):
    from app.config import settings
    from modules.ideation.models import Idea
    from modules.ideation.services.sinks import mint_idea_link

    idea = Idea(
        id="i-fb", tenant_id=DEFAULT_TENANT_ID, product_id="p", problem="x", status_token="tok-fb"
    )
    assert mint_idea_link(db, idea) == f"{settings.frontend_url.rstrip('/')}/public/feedback/tok-fb"


def test_public_status_copy_never_says_idea():
    from modules.ideation.services import public_status

    texts = list(public_status.PUBLIC_NEXT_STEP.values()) + [
        public_status._NEXT_STEP_CLOSED,
        public_status._NEXT_STEP_DEFAULT,
    ]
    for t in texts:
        assert not IDEA_WORD.search(t), t


def test_whatsapp_replies_say_feedback_with_fb_number():
    from modules.ideation.services import intake

    done = intake._reply_complete("Faster checkout", "IDEA-0016", "https://x/public/feedback/t", "Feedback")
    assert "FB-0016" in done
    assert "IDEA-" not in done
    assert not IDEA_WORD.search(done)
    voted = intake._reply_voted("IDEA-0016", None)
    assert "FB-0016" in voted and "IDEA-" not in voted
    collecting = intake._reply_collecting(None, {}, ["problem"], "problem")
    assert not IDEA_WORD.search(collecting), collecting
    assert not IDEA_WORD.search(intake._reply_duplicate_candidate("Faster checkout"))


def test_reply_noun_for_idea_type_is_feedback(db):
    from modules.ideation.models import Idea
    from modules.ideation.services.intake import IntakeService

    svc = IntakeService(db)
    assert svc._noun(Idea(type="idea")) == "Feedback"
    assert svc._noun(Idea(type="issue")) == "Problem report"


def test_build_issue_links_feedback_br_page():
    from modules.ideation.services import issue_body

    src = open(issue_body.__file__).read()
    assert "## Linked ideas" not in src


def test_services_catalog_card_says_feedback():
    import json
    import pathlib

    import modules.ideation as mod

    manifest = json.loads((pathlib.Path(mod.__file__).parent / "manifest.json").read_text())
    assert manifest["title"] == "Feedback"
    assert not IDEA_WORD.search(manifest["description"])


def test_permission_labels_and_descriptions_say_feedback():
    import csv
    import pathlib

    import modules.ideation as mod

    rows = list(csv.DictReader(open(pathlib.Path(mod.__file__).parent / "permissions" / "permissions.csv")))
    assert rows
    for r in rows:
        for col in ("resource_label", "action_label", "description"):
            assert not IDEA_WORD.search(r[col] or ""), (r["resource"], col, r[col])
            assert "ideation" not in (r[col] or "").lower()


def test_statuses_entity_label_is_feedback():
    from app.status_engine.registry import get_status_entity
    from modules.ideation.services.statuses import IDEA_ENTITY

    entity = get_status_entity(IDEA_ENTITY)
    assert entity is not None and entity.label == "Feedback"


def test_type_labels_match_the_crm_and_values_stay(db):
    from modules.ideation.services.idea_types import idea_type_label, list_idea_types

    rows = {r.key: r.label for r in list_idea_types(db)}
    assert rows == {"idea": "Feature request", "issue": "Problem report"}
    assert idea_type_label(db, "idea") == "Feature request"


def test_relabel_only_moves_stock_labels(db):
    from modules.ideation.models import IdeaType
    from modules.ideation.services.idea_types import seed_idea_types

    idea = db.get(IdeaType, "idea")
    issue = db.get(IdeaType, "issue")
    idea.label = "Idea"  # stock legacy label -> moves
    issue.label = "Bug"  # a deliberate relabel -> stays
    db.commit()
    seed_idea_types(db)
    assert db.get(IdeaType, "idea").label == "Feature request"
    assert db.get(IdeaType, "issue").label == "Bug"


def test_relabel_migration_sql_is_guarded():
    from modules.ideation.services.idea_types import relabel_idea_types_sql

    stmts = relabel_idea_types_sql("app_ideation")
    assert any("label = 'Idea'" in s and "'Feature request'" in s for s in stmts)
    assert any("label = 'Issue'" in s and "'Problem report'" in s for s in stmts)


def test_problem_report_reply_noun(db):
    from modules.ideation.models import Idea
    from modules.ideation.services.intake import IntakeService

    assert IntakeService(db)._noun(Idea(type="issue")) == "Problem report"
