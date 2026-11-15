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
    assert svc._noun(Idea(type="issue")) == "Issue"


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
