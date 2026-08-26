"""Form upload pipeline tests (plan sprint-3/02, slice 2 §TDD, D12).

Covers: multipart submit stores a sniff-gated file under a quarantine key and
the answer carries the storage key (not the placeholder) · the authed serve
route returns it CSP-sandboxed · a bad-magic file (text renamed .png) → 422
fieldErrors, nothing stored · a signature data-URL is decoded + stored · public
multipart submit works anonymously · the JSON path is unaffected.
"""
import base64
import json
import uuid

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

# A real 1x1 PNG (valid magic bytes → passes detect_upload_mime).
_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)


def _admin(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _doc(*fields):
    return {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "title": "P", "sections": [{"id": "s1", "fields": list(fields)}]}],
    }


def _publish(client, headers, doc, access="internal"):
    res = client.post("/forms", json={"name": f"F {uuid.uuid4().hex[:6]}", "access": access}, headers=headers)
    form = res.json()
    assert client.patch(f"/forms/{form['id']}", json={"draftDefinition": doc}, headers=headers).status_code == 200
    assert client.post(f"/forms/{form['id']}/publish", headers=headers).status_code == 200
    return form


def test_internal_file_upload_stores_and_serves(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {"id": "f1", "type": "file", "key": "resume", "label": "Resume", "required": True},
    ))
    res = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:resume", ("cv.png", _PNG, "image/png"))],
        headers=headers,
    )
    assert res.status_code == 201, res.text
    sub = res.json()
    resume = sub["answers"]["resume"]
    assert isinstance(resume, list) and len(resume) == 1
    # The stored answer carries a real storage key, NOT the local: placeholder.
    assert not resume[0]["key"].startswith("local:")
    assert not resume[0]["key"].startswith("pending")

    served = client.get(f"/submissions/{sub['id']}/files/resume/0", headers=headers)
    assert served.status_code == 200, served.text
    assert "sandbox" in served.headers.get("content-security-policy", "")
    assert served.headers.get("x-content-type-options") == "nosniff"


def test_file_upload_bad_magic_is_rejected(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {"id": "f1", "type": "file", "key": "resume", "label": "Resume", "required": True},
    ))
    res = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:resume", ("evil.png", b"<html>not an image</html>", "image/png"))],
        headers=headers,
    )
    assert res.status_code == 422
    assert "resume" in res.json()["detail"]["fieldErrors"]


def test_file_upload_disallowed_mime_rejected(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {
            "id": "f1", "type": "file", "key": "doc", "label": "Doc", "required": True,
            "file": {"allowedMimes": ["application/pdf"]},
        },
    ))
    # A valid PNG, but the field only allows PDF.
    res = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:doc", ("x.png", _PNG, "image/png"))],
        headers=headers,
    )
    assert res.status_code == 422
    assert "doc" in res.json()["detail"]["fieldErrors"]


def test_signature_data_url_stored(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {"id": "f1", "type": "signature", "key": "sign", "label": "Sign", "required": True},
    ))
    data_url = "data:image/png;base64," + base64.b64encode(_PNG).decode()
    res = client.post(
        f"/forms/{form['id']}/submissions",
        json={"answers": {"sign": data_url}},
        headers=headers,
    )
    assert res.status_code == 201, res.text
    sub = res.json()
    assert isinstance(sub["answers"]["sign"], str)
    assert not sub["answers"]["sign"].startswith("data:")  # replaced by a storage key
    served = client.get(f"/submissions/{sub['id']}/files/sign/0", headers=headers)
    assert served.status_code == 200


# A zip container (PK magic) - docx/xlsx/pptx are zips; the gate reads the magic
# only, the office sub-type is refined from the filename (BL-093).
_ZIP = b"PK\x03\x04" + b"\x00" * 24
_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def test_detect_upload_mime_office_and_floor():
    from app.uploads import detect_upload_mime

    # Zip family widened in; extension refines the office sub-type.
    assert detect_upload_mime(_ZIP, "report.xlsx") == _XLSX_MIME
    assert detect_upload_mime(_ZIP, "archive.zip") == "application/zip"
    assert detect_upload_mime(_ZIP, None) == "application/zip"
    # Hard floor preserved - no config can open these.
    assert detect_upload_mime(b"MZ\x90\x00", "evil.xlsx") is None  # PE exe
    assert detect_upload_mime(b"<svg onload=x>", "a.svg") is None
    assert detect_upload_mime(b"<!doctype html>", "a.xlsx") is None


def test_xlsx_upload_accepted_any_type(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {"id": "f1", "type": "file", "key": "sheet", "label": "Sheet", "required": True},
    ))
    res = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:sheet", ("data.xlsx", _ZIP, _XLSX_MIME))],
        headers=headers,
    )
    assert res.status_code == 201, res.text
    assert res.json()["answers"]["sheet"][0]["mime"] == _XLSX_MIME


def test_xlsx_upload_matches_configured_allow_list(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {
            "id": "f1", "type": "file", "key": "sheet", "label": "Sheet", "required": True,
            "file": {"allowedMimes": [_XLSX_MIME]},
        },
    ))
    # Configured to xlsx, uploading xlsx → passes (the extension-refined mime
    # matches the whitelist).
    ok = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:sheet", ("data.xlsx", _ZIP, _XLSX_MIME))],
        headers=headers,
    )
    assert ok.status_code == 201, ok.text
    # A plain zip (no office extension) → application/zip ≠ whitelist → rejected.
    bad = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:sheet", ("x.zip", _ZIP, "application/zip"))],
        headers=headers,
    )
    assert bad.status_code == 422
    assert "sheet" in bad.json()["detail"]["fieldErrors"]


def test_public_multipart_submit_anonymous(client):
    headers = _admin(client)
    form = _publish(client, headers, _doc(
        {"id": "f1", "type": "file", "key": "photo", "label": "Photo", "required": True},
    ), access="public")
    res = client.post(
        f"/public/forms/default/{form['slug']}/submissions",
        data={"payload": json.dumps({"answers": {}, "honeypot": ""})},
        files=[("file:photo", ("p.png", _PNG, "image/png"))],
    )
    assert res.status_code == 204, res.text
    rows = client.get(f"/forms/{form['id']}/submissions", headers=headers).json()
    assert rows["total"] == 1
    assert rows["data"][0]["userId"] is None
