"""FEEDBACK-ATTACH-IMAGE - board attachments on reports + comments, RED first.

Contract: ``documentation/plans/sprint-5/feedback-attach-image-acceptance-criteria.md``
(AC-A-01..08, AC-A-11). Board routes are ``/portal/ideas/*`` (manifest prefix).
"""
import pytest

from app.config import settings
from app.models import DEFAULT_TENANT_ID
from tests.test_ideation_feedback_link import _contact, _contact_session  # noqa: F401
from tests.test_ideation_portal import _crm_session, _idea, _staff_session  # noqa: F401
from tests.test_ideation_public_status import _auth, ideation_client, setup  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n" + b"0" * 64
HTML = b"<html><script>alert(1)</script></html>"
EXE = b"MZ" + b"\x90\x00" * 32
CAP = 25 * 1024 * 1024
ITEM_LIMIT_MSG = "This feedback has reached its attachment limit."
COMMENT_LIMIT_MSG = "This comment has reached its attachment limit."


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


def _up(s, h, idea_id, content=PNG, name="shot.png", comment_id=None):
    data = {"commentId": comment_id} if comment_id else None
    return s["client"].post(
        f"/portal/ideas/{idea_id}/attachments",
        headers=h,
        files={"file": (name, content, "application/octet-stream")},
        data=data,
    )


def _comment(s, h, idea_id, body="hello", **extra):
    res = s["client"].post(f"/portal/ideas/{idea_id}/comments", headers=h, json={"body": body, **extra})
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _owner(s, n, sub="crm-owner"):
    h = _crm_session(s, sub=sub, ideas_manage=False)
    return _idea(s, n, crm_user=sub), h


# ── AC-A-01 / AC-A-02: report-level upload ───────────────────────────────────
def test_ac_a_01_owner_uploads_report_file(setup):
    iid, h = _owner(setup, 1000)
    res = _up(setup, h, iid)
    assert res.status_code == 201, res.text
    b = res.json()
    assert b["kind"] == "image" and b["name"] == "shot.png" and b["sizeBytes"] == len(PNG)
    assert b["contentPath"] == f"/portal/ideas/{iid}/attachments/{b['id']}/content"


def test_ac_a_01_bytes_are_in_tenant_storage(setup):
    from modules.ideation.models import IdeaAttachment

    iid, h = _owner(setup, 1001)
    aid = _up(setup, h, iid).json()["id"]
    db = setup["factory"]()
    try:
        row = db.query(IdeaAttachment).filter(IdeaAttachment.id == aid).one()
        assert row.storage_key and row.tenant_id == DEFAULT_TENANT_ID and row.idea_id == iid
    finally:
        db.close()


def test_ac_a_02_other_user_cannot_upload_report_level(setup):
    s = setup
    iid, owner = _owner(s, 1002)
    assert _up(s, owner, iid).status_code == 201  # control
    other = _crm_session(s, sub="crm-other", ideas_manage=False)
    assert _up(s, other, iid).status_code == 403


def test_ac_a_02_manager_can_upload_report_level(setup):
    s = setup
    iid, _ = _owner(s, 1003)
    mgr = _crm_session(s, sub="crm-mgr", ideas_manage=True)
    assert _up(s, mgr, iid).status_code == 201


# ── AC-A-03: comment-level upload ────────────────────────────────────────────
def test_ac_a_03_comment_author_attaches_to_own_comment(setup):
    s = setup
    iid, _ = _owner(s, 1010)
    a = _crm_session(s, sub="crm-a", ideas_manage=False)
    cid = _comment(s, a, iid)
    res = _up(s, a, iid, comment_id=cid)
    assert res.status_code == 201, res.text
    rows = s["client"].get(f"/portal/ideas/{iid}/comments", headers=a).json()
    mine = [r for r in rows if r["id"] == cid][0]
    assert [x["id"] for x in mine["attachments"]] == [res.json()["id"]]


def test_ac_a_03_other_user_cannot_attach_to_comment(setup):
    from modules.ideation.models import IdeaAttachment

    s = setup
    iid, _ = _owner(s, 1011)
    a = _crm_session(s, sub="crm-a", ideas_manage=False)
    b = _crm_session(s, sub="crm-b", ideas_manage=False)
    cid = _comment(s, a, iid)
    assert _up(s, a, iid, comment_id=cid).status_code == 201  # control
    assert _up(s, b, iid, comment_id=cid).status_code in (403, 404)
    db = s["factory"]()
    try:
        assert db.query(IdeaAttachment).filter(IdeaAttachment.idea_id == iid).count() == 1
    finally:
        db.close()


def test_ac_a_03_comment_of_another_item_is_404(setup):
    s = setup
    one, _ = _owner(s, 1012, sub="crm-a")
    two = _idea(s, 1013, crm_user="crm-a")
    a = _crm_session(s, sub="crm-a", ideas_manage=False)
    cid = _comment(s, a, one)
    assert _up(s, a, one, comment_id=cid).status_code == 201  # control
    assert _up(s, a, two, comment_id=cid).status_code == 404


def test_ac_a_03_deleted_comment_is_404(setup):
    s = setup
    iid, _ = _owner(s, 1014)
    a = _crm_session(s, sub="crm-a", ideas_manage=False)
    cid = _comment(s, a, iid)
    assert _up(s, a, iid, comment_id=cid).status_code == 201  # control
    assert s["client"].delete(f"/portal/ideas/{iid}/comments/{cid}", headers=a).status_code == 204
    assert _up(s, a, iid, comment_id=cid).status_code == 404


def test_ac_a_03_unknown_comment_is_404(setup):
    s = setup
    iid, h = _owner(s, 1015)
    assert _up(s, h, iid).status_code == 201  # control
    assert _up(s, h, iid, comment_id="no-such-comment").status_code == 404


# ── AC-A-04: limits ──────────────────────────────────────────────────────────
def test_ac_a_04_oversize_is_413(setup):
    iid, h = _owner(setup, 1020)
    assert _up(setup, h, iid).status_code == 201  # control
    assert _up(setup, h, iid, PNG + b"\x00" * CAP).status_code == 413


@pytest.mark.parametrize("content,name", [(HTML, "x.png"), (EXE, "x.pdf")], ids=["html", "exe"])
def test_ac_a_04_unverifiable_is_415(setup, content, name):
    iid, h = _owner(setup, 1021)
    assert _up(setup, h, iid).status_code == 201  # control
    assert _up(setup, h, iid, content, name).status_code == 415


def test_ac_a_04_comment_cap_422(setup, monkeypatch):
    import modules.ideation.services.attachments as att

    monkeypatch.setattr(att, "MAX_ATTACHMENTS_PER_COMMENT", 2, raising=False)
    s = setup
    iid, _ = _owner(s, 1022)
    a = _crm_session(s, sub="crm-a", ideas_manage=False)
    cid = _comment(s, a, iid)
    for i in range(2):
        assert _up(s, a, iid, name=f"{i}.png", comment_id=cid).status_code == 201
    res = _up(s, a, iid, name="3.png", comment_id=cid)
    assert res.status_code == 422, res.text
    assert COMMENT_LIMIT_MSG in res.text


def test_ac_a_04_item_cap_counts_report_and_comments(setup, monkeypatch):
    import modules.ideation.services.attachments as att

    monkeypatch.setattr(att, "MAX_ATTACHMENTS_PER_IDEA", 2)
    s = setup
    iid, owner = _owner(s, 1023, sub="crm-a")
    cid = _comment(s, owner, iid)
    assert _up(s, owner, iid).status_code == 201
    assert _up(s, owner, iid, comment_id=cid).status_code == 201
    res = _up(s, owner, iid)
    assert res.status_code == 422, res.text
    assert ITEM_LIMIT_MSG in res.text


def test_ac_a_04_item_limit_is_fifty():
    import modules.ideation.services.attachments as att

    assert att.MAX_ATTACHMENTS_PER_IDEA == 50
    assert att.MAX_ATTACHMENTS_PER_COMMENT == 10


# ── AC-A-05: detail carries report-level files only ──────────────────────────
def test_ac_a_05_detail_lists_report_level_only(setup):
    s = setup
    iid, owner = _owner(s, 1030)
    rid = _up(s, owner, iid, name="report.png").json()["id"]
    cid = _comment(s, owner, iid)
    fid = _up(s, owner, iid, name="comment.png", comment_id=cid).json()["id"]
    d = s["client"].get(f"/portal/ideas/{iid}", headers=owner).json()
    ids = [a["id"] for a in d["attachments"]]
    assert rid in ids and fid not in ids


def test_ac_a_05_detail_omits_attachments_when_text_withheld(setup):
    s = setup
    iid, owner = _owner(s, 1031)
    assert _up(s, owner, iid).status_code == 201
    dealer = _contact_session(s, _contact(s))
    res = s["client"].get(f"/portal/ideas/{iid}", headers=dealer)
    assert res.status_code == 200, res.text
    assert "problem" not in res.json()  # control: this viewer is withheld
    assert "attachments" not in res.json()
    # Control: the owner still sees them.
    assert s["client"].get(f"/portal/ideas/{iid}", headers=owner).json()["attachments"]


def test_ac_a_05_withheld_keys_include_attachments():
    from modules.ideation.services.portal import WITHHELD_DETAIL_KEYS

    assert "attachments" in WITHHELD_DETAIL_KEYS


# ── AC-A-06: comments carry their attachments ────────────────────────────────
def test_ac_a_06_comments_list_has_per_comment_attachments(setup):
    s = setup
    iid, owner = _owner(s, 1040)
    c1 = _comment(s, owner, iid, "one")
    c2 = _comment(s, owner, iid, "two")
    aid = _up(s, owner, iid, comment_id=c1).json()["id"]
    rows = {r["id"]: r for r in s["client"].get(f"/portal/ideas/{iid}/comments", headers=owner).json()}
    assert [a["id"] for a in rows[c1]["attachments"]] == [aid]
    assert rows[c2]["attachments"] == []


def test_ac_a_06_deleted_comment_placeholder_has_no_attachments(setup):
    s = setup
    iid, owner = _owner(s, 1041)
    cid = _comment(s, owner, iid)
    assert _up(s, owner, iid, comment_id=cid).status_code == 201
    assert s["client"].delete(f"/portal/ideas/{iid}/comments/{cid}", headers=owner).status_code == 204
    rows = s["client"].get(f"/portal/ideas/{iid}/comments", headers=owner).json()
    placeholder = [r for r in rows if r["id"] == cid]
    assert placeholder and placeholder[0]["attachments"] == []


# ── AC-A-07: content route ───────────────────────────────────────────────────
def test_ac_a_07_content_served_sandboxed(setup):
    s = setup
    iid, owner = _owner(s, 1050)
    path = _up(s, owner, iid).json()["contentPath"]
    res = s["client"].get(path, headers=owner)
    assert res.status_code == 200, res.text
    assert res.content == PNG
    assert res.headers["content-security-policy"] == "default-src 'none'; sandbox"
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "private" in res.headers["cache-control"]


def test_ac_a_07_other_tenant_attachment_is_404(setup):
    from modules.ideation.models import IdeaAttachment
    from tests.test_ideation_public_status import _make_captured_idea

    s = setup
    iid, owner = _owner(s, 1051)
    own_path = _up(s, owner, iid).json()["contentPath"]
    assert s["client"].get(own_path, headers=owner).status_code == 200  # control
    foreign_idea = _make_captured_idea(
        s["factory"], s["product_id"], idea_number="IDEA-1052", tenant_id="tenant-x"
    )
    db = s["factory"]()
    try:
        row = IdeaAttachment(
            tenant_id="tenant-x", idea_id=foreign_idea, source_msg_id="upload:foreign",
            kind="image", url="", filename="f.png", storage_key="missing", mime="image/png",
            size_bytes=len(PNG),
        )
        db.add(row)
        db.commit()
        foreign_aid = row.id
    finally:
        db.close()
    for i in (iid, foreign_idea):
        res = s["client"].get(f"/portal/ideas/{i}/attachments/{foreign_aid}/content", headers=owner)
        assert res.status_code == 404, res.text


def test_ac_a_07_attachment_of_another_item_is_404(setup):
    s = setup
    iid, owner = _owner(s, 1053, sub="crm-a")
    other = _idea(s, 1054, crm_user="crm-a")
    path = _up(s, owner, iid).json()["contentPath"]
    assert s["client"].get(path, headers=owner).status_code == 200  # control
    aid = path.split("/attachments/")[1].split("/")[0]
    assert s["client"].get(f"/portal/ideas/{other}/attachments/{aid}/content", headers=owner).status_code == 404


def test_ac_a_07_withheld_report_file_is_404_for_dealer(setup):
    s = setup
    iid, owner = _owner(s, 1055)
    path = _up(s, owner, iid).json()["contentPath"]
    assert s["client"].get(path, headers=owner).status_code == 200  # control
    dealer = _contact_session(s, _contact(s))
    assert s["client"].get(path, headers=dealer).status_code == 404


def test_ac_a_07_deleted_comment_file_is_404(setup):
    s = setup
    iid, owner = _owner(s, 1056)
    cid = _comment(s, owner, iid)
    path = _up(s, owner, iid, comment_id=cid).json()["contentPath"]
    assert s["client"].get(path, headers=owner).status_code == 200  # control
    assert s["client"].delete(f"/portal/ideas/{iid}/comments/{cid}", headers=owner).status_code == 204
    assert s["client"].get(path, headers=owner).status_code == 404


# ── AC-A-08: empty body with files ───────────────────────────────────────────
def test_ac_a_08_empty_body_with_has_attachments_is_201(setup):
    s = setup
    iid, owner = _owner(s, 1060)
    res = s["client"].post(
        f"/portal/ideas/{iid}/comments", headers=owner, json={"body": "", "hasAttachments": True}
    )
    assert res.status_code == 201, res.text


def test_ac_a_08_empty_body_without_flag_is_422(setup):
    s = setup
    iid, owner = _owner(s, 1061)
    ok = s["client"].post(f"/portal/ideas/{iid}/comments", headers=owner, json={"body": "x"})
    assert ok.status_code == 201  # control
    res = s["client"].post(f"/portal/ideas/{iid}/comments", headers=owner, json={"body": ""})
    assert res.status_code == 422


# ── AC-A-11: throttle ────────────────────────────────────────────────────────
def test_ac_a_11_upload_throttle_429(setup, monkeypatch):
    monkeypatch.setattr(settings, "throttle_idea_portal_upload_max", 2, raising=False)
    s = setup
    iid, owner = _owner(s, 1070)
    codes = [_up(s, owner, iid, name=f"{i}.png").status_code for i in range(3)]
    assert codes == [201, 201, 429]
