"""FEEDBACK-IMAGE-PREVIEW - attachment previews on the public share page.

Owner (prod): every image on the shared feedback item page opened as
"Preview unavailable.". Two causes:

1. the share serializers pointed ``contentPath`` at the portal route, which
   needs a portal Bearer token the share page never has (401);
2. the content routes 307-redirected to a presigned bucket URL on R2/S3, which
   the browser's fetch is CORS-blocked on.

Contract: a share token reads its own item's files (no Authorization), wrong
item / revoked token = uniform 404, and every ideation content route streams
the bytes same-origin (never a redirect).
"""
import pytest

from app.config import settings
from tests.test_ideation_feedback_link import _contact, _set  # noqa: F401
from tests.test_ideation_portal import _idea, _staff_session  # noqa: F401
from tests.test_ideation_public_status import (  # noqa: F401
    _auth,
    ideation_client,
    setup,
)

def _real_png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


PNG = _real_png()


@pytest.fixture(autouse=True)
def media_root(tmp_path):
    from app.services.storage import clear_adapter_cache

    prev = settings.media_root
    settings.media_root = str(tmp_path)
    clear_adapter_cache()
    try:
        yield tmp_path
    finally:
        settings.media_root = prev
        clear_adapter_cache()


def _share_token(s, iid) -> str:
    res = s["client"].post(f"/ideation/ideas/{iid}/share-link", headers=s["h"])
    assert res.status_code == 200, res.text
    return res.json()["url"].rsplit("/", 1)[1]


def _upload_report(s, iid, name="shot.png") -> str:
    res = s["client"].post(
        f"/ideation/ideas/{iid}/attachments",
        headers=s["h"],
        files={"file": (name, PNG, "application/octet-stream")},
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _comment_with_file(s, iid) -> str:
    h = _staff_session(s)
    res = s["client"].post(f"/portal/ideas/{iid}/comments", headers=h, json={"body": "see screenshot"})
    assert res.status_code == 201, res.text
    cid = res.json()["id"]
    up = s["client"].post(
        f"/portal/ideas/{iid}/attachments",
        headers=h,
        files={"file": ("c.png", PNG, "application/octet-stream")},
        data={"commentId": cid},
    )
    assert up.status_code == 201, up.text
    return up.json()["id"]


def _shared_item(s, n):
    iid = _idea(s, n, submitter_contact_id=_contact(s))
    aid = _upload_report(s, iid)
    return iid, aid, _share_token(s, iid)


# ── share route ────────────────────────────────────────────────────────────────


def test_share_view_keeps_report_files_withheld(setup):
    """Owner ruling (b): the share view never shows the report's own files -
    not in the detail, and not through the new share content route either."""
    s = setup
    iid, aid, token = _shared_item(s, 701)
    body = s["client"].get(f"/portal/ideas/shared/{token}").json()
    assert "attachments" not in body
    assert s["client"].get(f"/portal/ideas/shared/{token}/{iid}/attachments/{aid}/content").status_code == 404


def test_share_image_serves_bytes_without_authorization(setup):
    s = setup
    iid, _aid, token = _shared_item(s, 702)
    caid = _comment_with_file(s, iid)
    path = f"/portal/ideas/shared/{token}/{iid}/attachments/{caid}/content"
    res = s["client"].get(path)
    assert res.status_code == 200, res.text
    assert res.content == PNG
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in res.headers["content-security-policy"]
    assert res.headers["cache-control"] == "private, no-cache"
    thumb = s["client"].get(f"{path}?variant=thumb")
    assert thumb.status_code == 200, thumb.text


def test_share_comment_file_serves_from_the_share_route(setup):
    s = setup
    iid, _aid, token = _shared_item(s, 703)
    caid = _comment_with_file(s, iid)
    comments = s["client"].get(f"/portal/ideas/shared/{token}/comments").json()
    files = [f for c in comments for f in (c.get("attachments") or [])]
    assert [f["id"] for f in files] == [caid]
    path = files[0]["contentPath"]
    assert path == f"/portal/ideas/shared/{token}/{iid}/attachments/{caid}/content"
    res = s["client"].get(path)
    assert res.status_code == 200, res.text
    assert res.content == PNG


def test_share_token_cannot_read_another_items_file(setup):
    s = setup
    _iid, _aid, token = _shared_item(s, 704)
    other_iid, _x, _other_token = _shared_item(s, 705)
    other_aid = _comment_with_file(s, other_iid)
    # The other item's file through THIS item's token, with either idea id.
    c = s["client"]
    assert c.get(f"/portal/ideas/shared/{token}/{other_iid}/attachments/{other_aid}/content").status_code == 404
    assert c.get(f"/portal/ideas/shared/{token}/{_iid}/attachments/{other_aid}/content").status_code == 404


def test_share_revoked_token_404(setup):
    s = setup
    iid, _aid, token = _shared_item(s, 706)
    aid = _comment_with_file(s, iid)
    assert s["client"].delete(f"/ideation/ideas/{iid}/share-link", headers=s["h"]).status_code == 204
    res = s["client"].get(f"/portal/ideas/shared/{token}/{iid}/attachments/{aid}/content")
    assert res.status_code == 404


def test_share_hidden_item_404(setup):
    s = setup
    iid, _aid, token = _shared_item(s, 707)
    aid = _comment_with_file(s, iid)
    _set(s, iid, portal_hidden=True)
    assert s["client"].get(f"/portal/ideas/shared/{token}/{iid}/attachments/{aid}/content").status_code == 404


def test_share_bad_token_404(setup):
    s = setup
    iid, aid, _token = _shared_item(s, 708)
    assert s["client"].get(f"/portal/ideas/shared/{'x' * 43}/{iid}/attachments/{aid}/content").status_code == 404


def test_share_deleted_comment_file_404(setup):
    s = setup
    iid, _aid, token = _shared_item(s, 709)
    caid = _comment_with_file(s, iid)
    from modules.ideation.models import IdeaAttachment, IdeaComment

    db = s["factory"]()
    try:
        cid = db.query(IdeaAttachment.comment_id).filter(IdeaAttachment.id == caid).scalar()
        from datetime import datetime, timezone

        db.query(IdeaComment).filter(IdeaComment.id == cid).update({"deleted_at": datetime.now(timezone.utc)})
        db.commit()
    finally:
        db.close()
    assert s["client"].get(f"/portal/ideas/shared/{token}/{iid}/attachments/{caid}/content").status_code == 404


# ── stream, never redirect (R2/S3 presigned) ───────────────────────────────────


class _PresigningStorage:
    """A remote store: ``resolve`` would hand back an expiring bucket URL."""

    def __init__(self, real):
        self.real = real

    def resolve(self, key):
        return "presigned", "https://bucket.example.test/obj?X-Amz-Signature=abc"

    def fetch(self, key):
        return self.real.fetch(key)

    def __getattr__(self, name):
        return getattr(self.real, name)


@pytest.fixture
def presigning(monkeypatch):
    from app.services import storage

    real = storage.storage_for_tenant

    def fake(db, tenant_id):
        return _PresigningStorage(real(db, tenant_id))

    monkeypatch.setattr(storage, "storage_for_tenant", fake)


def _assert_streamed(res):
    assert res.status_code == 200, (res.status_code, res.headers.get("location"))
    assert res.content == PNG
    assert "location" not in res.headers


def test_share_route_streams_not_redirects(setup, presigning):
    s = setup
    iid, _aid, token = _shared_item(s, 710)
    aid = _comment_with_file(s, iid)
    res = s["client"].get(f"/portal/ideas/shared/{token}/{iid}/attachments/{aid}/content", follow_redirects=False)
    _assert_streamed(res)


def test_portal_route_streams_not_redirects(setup, presigning):
    s = setup
    iid, aid, _token = _shared_item(s, 711)
    res = s["client"].get(
        f"/portal/ideas/{iid}/attachments/{aid}/content", headers=_staff_session(s), follow_redirects=False
    )
    _assert_streamed(res)


def test_staff_route_streams_not_redirects(setup, presigning):
    s = setup
    iid, aid, _token = _shared_item(s, 712)
    res = s["client"].get(f"/ideation/ideas/{iid}/attachments/{aid}/content", headers=s["h"], follow_redirects=False)
    _assert_streamed(res)


def test_share_file_reads_are_throttled_per_ip(setup, monkeypatch):
    s = setup
    iid, _aid, token = _shared_item(s, 714)
    aid = _comment_with_file(s, iid)
    monkeypatch.setattr(settings, "throttle_idea_share_file_max", 2)
    path = f"/portal/ideas/shared/{token}/{iid}/attachments/{aid}/content"
    assert s["client"].get(path).status_code == 200
    assert s["client"].get(path).status_code == 200
    res = s["client"].get(path)
    assert res.status_code == 429
    assert int(res.headers["retry-after"]) > 0


def test_missing_blob_404_not_500(setup, monkeypatch):
    from app.services import storage

    s = setup
    iid, _aid, token = _shared_item(s, 713)
    aid = _comment_with_file(s, iid)
    real = storage.storage_for_tenant

    class _Gone(_PresigningStorage):
        def fetch(self, key):
            raise FileNotFoundError(key)

    monkeypatch.setattr(storage, "storage_for_tenant", lambda db, t: _Gone(real(db, t)))
    assert s["client"].get(f"/portal/ideas/shared/{token}/{iid}/attachments/{aid}/content").status_code == 404
