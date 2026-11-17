"""FEEDBACK-ATTACH-IMAGE fix round 1 - delete with files, comment-upload gates, thumbnails."""
import io

import pytest
from jose import jwt
from sqlalchemy import text

from app.config import settings
from tests.test_ideation_attachments_upload import PDF, PNG, ctx, ideation_client, media_root  # noqa: F401
from tests.test_ideation_br import _make_user
from tests.test_ideation_embed_writes import (
    _assertion,
    CONNECTION_ID,
    SIGNING_SECRET,
    _auth,
    _bearer,
    _insert_idea,
    _seed_connection,
)
from tests.test_ideation_br import _product
from tests.test_ideation_feedback_link import _contact, _contact_session  # noqa: F401
from tests.test_ideation_portal import _crm_session, _idea  # noqa: F401
from tests.test_ideation_public_status import setup  # noqa: F401


def _real_png(size=(800, 600), mode="RGB") -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 255) if mode == "RGBA" else (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _up(c, h, idea_id, content=PNG, name="a.png", comment_id=None, prefix="/ideation"):
    return c.post(
        f"{prefix}/ideas/{idea_id}/attachments",
        headers=h,
        files={"file": (name, content, "application/octet-stream")},
        data={"commentId": comment_id} if comment_id else None,
    )


def _comment(ctx, body="note"):
    res = ctx["c"].post(f"/ideation/ideas/{ctx['idea_id']}/comments", headers=ctx["h"], json={"body": body})
    assert res.status_code == 201, res.text
    return res.json()["id"]


# ── 1: deleting an item that carries files (FK enforced like Postgres) ────────
def test_delete_item_with_report_and_comment_files(ctx, media_root):
    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    db = c._factory()
    db.execute(text("PRAGMA foreign_keys=ON"))
    db.commit()
    db.close()
    cid = _comment(ctx)
    assert _up(c, h, iid, _real_png()).status_code == 201
    assert _up(c, h, iid, _real_png(), comment_id=cid).status_code == 201
    assert not [p for p in media_root.rglob("*") if p.is_file()] == []  # control: blobs exist
    res = c.delete(f"/ideation/ideas/{iid}", headers=h)
    assert res.status_code == 204, res.text
    assert [p for p in media_root.rglob("*") if p.is_file()] == []  # blobs removed after commit


# ── 2: embed comment upload does not need manage rights ───────────────────────
def _embed_token_no_manage(client, sub="user-9"):
    claims = jwt.get_unverified_claims(_assertion(sub=sub))
    claims["ideas_manage"] = False
    a = jwt.encode(claims, SIGNING_SECRET, algorithm=settings.jwt_algorithm)
    res = client.post("/embed/session", json={"connection_id": CONNECTION_ID, "assertion": a})
    assert res.status_code == 200, res.text
    return _bearer(res.json()["token"])


def test_embed_non_manager_attaches_to_own_comment_on_others_item(ideation_client):
    c = ideation_client
    pid = _product(c, _auth(c))
    _seed_connection(c._factory, product_id=pid)
    idea_id = _insert_idea(c._factory, pid)
    eh = _embed_token_no_manage(c)
    made = c.post(f"/embed/ideas/{idea_id}/comments", headers=eh, json={"body": "hi"})
    assert made.status_code == 201, made.text
    assert _up(c, eh, idea_id, PNG, prefix="/embed").status_code == 403  # control: report-level still owned-only
    assert _up(c, eh, idea_id, PNG, comment_id=made.json()["id"], prefix="/embed").status_code == 201


# ── 3: staff comment uploads gate on the comment permission ───────────────────
def test_staff_comment_upload_gates(ctx):
    c, iid = ctx["c"], ctx["idea_id"]
    cid_admin = _comment(ctx)
    _make_user(c._factory, "commenter@x.com", "commenter1234", ["ideation.ideas.view", "ideation.ideas.comment"])
    _make_user(c._factory, "triager@x.com", "triager1234", ["ideation.ideas.view", "ideation.triage.manage"])
    ch = _auth(c, email="commenter@x.com", password="commenter1234")
    th = _auth(c, email="triager@x.com", password="triager1234")
    own = c.post(f"/ideation/ideas/{iid}/comments", headers=ch, json={"body": "mine"}).json()["id"]
    assert _up(c, ch, iid, PNG, comment_id=own).status_code == 201
    assert _up(c, ch, iid, PNG).status_code == 403  # report-level needs triage.manage
    assert _up(c, ch, iid, PNG, comment_id=cid_admin).status_code in (403, 404)  # not the author
    assert _up(c, th, iid, PNG).status_code == 201  # control: triage keeps report-level
    assert _up(c, th, iid, PNG, comment_id=cid_admin).status_code == 403  # no comment permission


# ── 5: thumbnails ────────────────────────────────────────────────────────────
def _thumb(c, h, path):
    return c.get(f"{path}?variant=thumb", headers=h)


def _row(c, att_id):
    from modules.ideation.models import IdeaAttachment

    db = c._factory()
    try:
        r = db.query(IdeaAttachment).filter(IdeaAttachment.id == att_id).one()
        return r.thumb_key, r.storage_key
    finally:
        db.close()


def test_staff_thumb_generated_then_stored(ctx, monkeypatch):
    from PIL import Image

    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    up = _up(c, h, iid, _real_png((1600, 1200))).json()
    assert _row(c, up["id"])[0] is None
    res = _thumb(c, h, up["contentPath"])
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("image/jpeg")
    img = Image.open(io.BytesIO(res.content))
    assert max(img.size) <= 320 and len(res.content) < len(_real_png((1600, 1200)))
    key1, storage_key = _row(c, up["id"])
    assert key1 and key1 != storage_key
    # Second call serves the stored thumb: generating again would blow up.
    monkeypatch.setattr("PIL.Image.open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("regenerated")))
    again = _thumb(c, h, up["contentPath"])
    assert again.status_code == 200 and again.content == res.content
    assert _row(c, up["id"])[0] == key1
    # The original is still the full image.
    assert c.get(up["contentPath"], headers=h).content == _real_png((1600, 1200))


def test_staff_thumb_keeps_alpha_as_png(ctx):
    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    up = _up(c, h, iid, _real_png((500, 500), "RGBA")).json()
    res = _thumb(c, h, up["contentPath"])
    assert res.status_code == 200 and res.headers["content-type"].startswith("image/png")


def test_thumb_of_non_image_and_corrupt_image_is_404(ctx):
    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    pdf = _up(c, h, iid, PDF, "s.pdf").json()
    assert _thumb(c, h, pdf["contentPath"]).status_code == 404
    bad = _up(c, h, iid, PNG, "bad.png").json()  # PNG magic, no real image
    assert c.get(bad["contentPath"], headers=h).status_code == 200  # control
    assert _thumb(c, h, bad["contentPath"]).status_code == 404
    assert _row(c, bad["id"])[0] == ""  # remembered as "no preview"


def test_embed_thumb(ideation_client):
    c = ideation_client
    pid = _product(c, _auth(c))
    _seed_connection(c._factory, product_id=pid)
    idea_id = _insert_idea(c._factory, pid)
    eh = _bearer(__import__("tests.test_ideation_embed_writes", fromlist=["_mint"])._mint(c))
    up = _up(c, eh, idea_id, _real_png(), prefix="/embed")
    assert up.status_code == 201, up.text
    res = _thumb(c, eh, up.json()["contentPath"])
    assert res.status_code == 200 and res.headers["content-type"].startswith("image/jpeg")


def test_board_thumb(setup):
    s = setup
    h = _crm_session(s, sub="crm-owner", ideas_manage=False)
    iid = _idea(s, 2000, crm_user="crm-owner")
    up = s["client"].post(
        f"/portal/ideas/{iid}/attachments", headers=h,
        files={"file": ("p.png", _real_png(), "application/octet-stream")},
    )
    assert up.status_code == 201, up.text
    res = s["client"].get(up.json()["contentPath"] + "?variant=thumb", headers=h)
    assert res.status_code == 200 and res.headers["content-type"].startswith("image/jpeg")
    assert "private" in res.headers["cache-control"]


# ── round 2: thumbnail memory guard, refused viewers, alpha PNG bytes ─────────
def _huge_dim_png(w=13000, h=13000) -> bytes:
    import struct
    import zlib

    def chunk(tag: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(tag + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0)
    idat = zlib.compress(b"\x00" * 16)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def test_huge_dimension_image_is_refused_before_decoding(ctx, monkeypatch):
    from PIL import Image

    import app.services.storage as storage_mod

    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    up = _up(c, h, iid, _huge_dim_png(), "big.png")
    assert up.status_code == 201, up.text  # never rejected at upload
    decoded = []
    for name in ("load", "thumbnail"):
        orig = getattr(Image.Image, name)
        monkeypatch.setattr(
            Image.Image, name, lambda self, *a, _o=orig, _n=name, **k: (decoded.append(_n), _o(self, *a, **k))[1]
        )
    assert _thumb(c, h, up.json()["contentPath"]).status_code == 404
    assert decoded == []
    assert _row(c, up.json()["id"])[0] == ""  # "no preview" sentinel
    reads = []
    real = storage_mod.read_object
    monkeypatch.setattr(storage_mod, "read_object", lambda *a, **k: (reads.append(1), real(*a, **k))[1])
    assert _thumb(c, h, up.json()["contentPath"]).status_code == 404
    assert reads == []  # remembered: storage is not touched again
    assert c.get(up.json()["contentPath"], headers=h).status_code == 200  # the original is untouched


def test_alpha_thumb_bytes_are_png(ctx):
    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    up = _up(c, h, iid, _real_png((500, 500), "RGBA")).json()
    res = _thumb(c, h, up["contentPath"])
    assert res.content.startswith(b"\x89PNG") and res.headers["content-type"].startswith("image/png")


def test_refused_board_viewer_triggers_no_thumbnail_work(setup):
    s = setup
    owner = _crm_session(s, sub="crm-owner", ideas_manage=False)
    iid = _idea(s, 2100, crm_user="crm-owner")
    up = s["client"].post(
        f"/portal/ideas/{iid}/attachments", headers=owner,
        files={"file": ("p.png", _real_png(), "application/octet-stream")},
    ).json()
    dealer = _contact_session(s, _contact(s))
    res = s["client"].get(up["contentPath"] + "?variant=thumb", headers=dealer)
    assert res.status_code == 404
    from modules.ideation.models import IdeaAttachment

    db = s["factory"]()
    try:
        assert db.query(IdeaAttachment).filter(IdeaAttachment.id == up["id"]).one().thumb_key is None
    finally:
        db.close()


def test_delete_item_also_removes_generated_thumbnail(ctx, media_root):
    c, h, iid = ctx["c"], ctx["h"], ctx["idea_id"]
    up = _up(c, h, iid, _real_png()).json()
    assert _thumb(c, h, up["contentPath"]).status_code == 200
    assert len([p for p in media_root.rglob("*") if p.is_file()]) == 2  # original + thumb
    assert c.delete(f"/ideation/ideas/{iid}", headers=h).status_code == 204
    assert [p for p in media_root.rglob("*") if p.is_file()] == []
