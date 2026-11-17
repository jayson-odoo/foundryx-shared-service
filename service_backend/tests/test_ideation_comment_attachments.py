"""FEEDBACK-ATTACH-IMAGE - staff + embed side of comment attachments (AC-A-08/09/10), RED first."""
from pathlib import Path

import pytest

from tests.test_ideation_attachments_upload import (  # noqa: F401
    PNG,
    ctx,
    ideation_client,
    media_root,
)
from tests.test_ideation_br import _make_user, _product
from tests.test_ideation_embed_writes import (
    _auth,
    _bearer,
    _insert_idea,
    _mint,
    _seed_connection,
)


def _up(c, h, idea_id, comment_id=None, prefix="/ideation", name="a.png"):
    return c.post(
        f"{prefix}/ideas/{idea_id}/attachments",
        headers=h,
        files={"file": (name, PNG, "application/octet-stream")},
        data={"commentId": comment_id} if comment_id else None,
    )


def _staff_comment(ctx, body="note"):
    res = ctx["c"].post(f"/ideation/ideas/{ctx['idea_id']}/comments", headers=ctx["h"], json={"body": body})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def test_ac_a_09_author_attaches_to_own_comment(ctx):
    cid = _staff_comment(ctx)
    res = _up(ctx["c"], ctx["h"], ctx["idea_id"], cid)
    assert res.status_code == 201, res.text
    rows = ctx["c"].get(f"/ideation/ideas/{ctx['idea_id']}/comments", headers=ctx["h"]).json()
    mine = [r for r in rows if r["id"] == cid][0]
    assert [a["id"] for a in mine["attachments"]] == [res.json()["id"]]


def test_ac_a_09_non_author_cannot_attach(ctx):
    cid = _staff_comment(ctx)
    keys = ["ideation.ideas.view", "ideation.ideas.comment", "ideation.triage.manage"]
    _make_user(ctx["c"]._factory, "second@x.com", "second1234", keys)
    h2 = _auth(ctx["c"], email="second@x.com", password="second1234")
    assert _up(ctx["c"], h2, ctx["idea_id"]).status_code == 201  # control: may upload report-level
    assert _up(ctx["c"], h2, ctx["idea_id"], cid).status_code in (403, 404)


def test_ac_a_09_unknown_comment_is_404(ctx):
    assert _up(ctx["c"], ctx["h"], ctx["idea_id"]).status_code == 201  # control
    assert _up(ctx["c"], ctx["h"], ctx["idea_id"], "no-such").status_code == 404


def test_ac_a_09_idea_out_excludes_comment_files(ctx):
    cid = _staff_comment(ctx)
    report = _up(ctx["c"], ctx["h"], ctx["idea_id"]).json()["id"]
    comment_file = _up(ctx["c"], ctx["h"], ctx["idea_id"], cid).json()["id"]
    d = ctx["c"].get(f"/ideation/ideas/{ctx['idea_id']}", headers=ctx["h"]).json()
    ids = [a["id"] for a in d["attachments"]]
    assert report in ids and comment_file not in ids


def test_ac_a_09_embed_upload_with_comment_id(ideation_client):
    c = ideation_client
    h = _auth(c)
    pid = _product(c, h)
    _seed_connection(c._factory, product_id=pid)
    idea_id = _insert_idea(c._factory, pid)
    eh = _bearer(_mint(c))
    made = c.post(f"/embed/ideas/{idea_id}/comments", headers=eh, json={"body": "hi"})
    assert made.status_code == 201, made.text
    res = _up(c, eh, idea_id, made.json()["id"], prefix="/embed")
    assert res.status_code == 201, res.text
    rows = c.get(f"/embed/ideas/{idea_id}/comments", headers=eh).json()
    assert [a["id"] for a in rows[0]["attachments"]] == [res.json()["id"]]


def test_ac_a_08_staff_empty_body_needs_flag(ctx):
    base = f"/ideation/ideas/{ctx['idea_id']}/comments"
    assert ctx["c"].post(base, headers=ctx["h"], json={"body": "x"}).status_code == 201  # control
    assert ctx["c"].post(base, headers=ctx["h"], json={"body": ""}).status_code == 422
    ok = ctx["c"].post(base, headers=ctx["h"], json={"body": "", "hasAttachments": True})
    assert ok.status_code == 201, ok.text


def test_ac_a_10_migration_file():
    versions = Path(__file__).resolve().parent.parent / "modules/ideation/alembic/versions"
    f = versions / "0025_ideation_comment_attachments.py"
    assert f.exists()
    text = f.read_text()
    assert "ADD COLUMN IF NOT EXISTS comment_id" in text
    import re

    rev = re.search(r"""^revision\s*(?::\s*str)?\s*=\s*['"]([^'"]+)['"]""", text, re.M)
    assert rev and len(rev.group(1)) <= 32
