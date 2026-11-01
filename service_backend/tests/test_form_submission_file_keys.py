"""The form submission file route serves only keys this form wrote.

`GET /submissions/{id}/files/{field_key}/{index}` answers only for a stored key
under `forms/<the submission's form id>/` with something after the prefix, bare
or behind a well-formed `conn:<id>:<raw>`. Anything else is the one 404
"File not found." and the storage layer is not reached.
"""
import base64
import json
import uuid

import pytest

from app.integrations.s3_provider import S3CompatibleAdapter
from app.models.connection import CONNECTION_STATUS_UNVERIFIED, Connection
from app.models.form import FormSubmission
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID
from app.secrets import encrypt_secret
from app.services import storage as storage_module
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD
from tests.test_storage_providers import StubS3Client

_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=="
)
SECRET = b"file-bytes-that-must-not-be-served"


# ---- fixtures ----------------------------------------------------------------

@pytest.fixture
def stub(monkeypatch):
    stub_client = StubS3Client()
    monkeypatch.setattr(S3CompatibleAdapter, "_build_client", lambda self: stub_client)
    storage_module.clear_adapter_cache()
    yield stub_client
    storage_module.clear_adapter_cache()


@pytest.fixture
def media(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "media_root", str(tmp_path))
    return tmp_path


def _connection(session_factory, tenant_id, cdn=""):
    db = session_factory()
    row = Connection(
        tenant_id=tenant_id,
        provider="s3",
        type="storage",
        name="Bucket",
        config_json={"bucket": "assets", "region": "auto", "cdnBaseUrl": cdn},
        credentials_json=encrypt_secret({"accessKeyId": "ak", "secretAccessKey": "sk"}),
        status=CONNECTION_STATUS_UNVERIFIED,
    )
    db.add(row)
    db.commit()
    conn_id = row.id
    db.close()
    return conn_id


def _headers(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _doc(*fields):
    return {
        "schemaVersion": 1,
        "pages": [{"id": "p1", "title": "P", "sections": [{"id": "s1", "fields": list(fields)}]}],
    }


FILE_FIELD = {"id": "f1", "type": "file", "key": "resume", "label": "Resume"}
SIGN_FIELD = {"id": "f2", "type": "signature", "key": "sign", "label": "Sign"}
NAME_FIELD = {"id": "f3", "type": "text", "key": "name", "label": "Name"}


def _form(client, headers, *fields, revisions=False):
    res = client.post("/forms", json={"name": f"F {uuid.uuid4().hex[:6]}", "access": "internal"}, headers=headers)
    form = res.json()
    assert client.patch(f"/forms/{form['id']}", json={"draftDefinition": _doc(*fields)}, headers=headers).status_code == 200
    if revisions:
        client.patch(f"/forms/{form['id']}", json={"allowRevisions": True}, headers=headers)
    assert client.post(f"/forms/{form['id']}/publish", headers=headers).status_code == 200
    return form


def _plain_submission(client, headers, form_id):
    res = client.post(f"/forms/{form_id}/submissions", json={"answers": {"name": "x"}}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def _set_answer(session_factory, submission_id, field, value):
    db = session_factory()
    row = db.get(FormSubmission, submission_id)
    row.answers_json = {**(row.answers_json or {}), field: value}
    db.commit()
    db.close()


def _entry(key, mime="text/plain", name="n.txt"):
    return {"key": key, "name": name, "size": 1, "mime": mime}


def _file(media, rel, content=SECRET):
    path = media / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _serve(client, headers, submission_id, field):
    return client.get(f"/submissions/{submission_id}/files/{field}/0", headers=headers, follow_redirects=False)


SHAPES = ["list", "string"]


def _store(session_factory, submission_id, shape, key):
    if shape == "list":
        _set_answer(session_factory, submission_id, "resume", [_entry(key)])
        return "resume"
    _set_answer(session_factory, submission_id, "sign", key)
    return "sign"


class World:
    def __init__(self, client, headers, session_factory, media, stub, platform, own=False):
        self.client, self.headers, self.sf, self.media, self.stub = client, headers, session_factory, media, stub
        self.platform = _connection(session_factory, PLATFORM_TENANT_ID) if platform else None
        self.own = _connection(session_factory, DEFAULT_TENANT_ID) if own else None
        self.form = _form(client, headers, FILE_FIELD, SIGN_FIELD, NAME_FIELD)["id"]
        self.other_form = _form(client, headers, FILE_FIELD, SIGN_FIELD, NAME_FIELD)["id"]
        self.sub = _plain_submission(client, headers, self.form)
        self.other_tenant = str(uuid.uuid4())

    def fmt(self, template):
        return template.format(
            F=self.form, O=self.other_form, T=self.other_tenant, S=self.sub,
            P=self.platform or "no-platform", OWN=self.own or "no-own",
        )

    def serve(self, shape, key):
        field = _store(self.sf, self.sub, shape, key)
        return _serve(self.client, self.headers, self.sub, field)


@pytest.fixture
def local_world(client, session_factory, stub, media):
    return World(client, _headers(client), session_factory, media, stub, platform=False)


@pytest.fixture
def platform_world(client, session_factory, stub, media):
    return World(client, _headers(client), session_factory, media, stub, platform=True)


@pytest.fixture
def own_world(client, session_factory, stub, media):
    return World(client, _headers(client), session_factory, media, stub, platform=True, own=True)


def _assert_refused(res, stub):
    assert res.status_code == 404, (res.status_code, res.text[:200])
    assert res.json() == {"detail": "File not found."}
    assert SECRET not in res.content
    assert stub.presigned == []


# ---- requirement 1 and 2: refused keys -------------------------------------------

# Each template is stored as the answer; real files are created for the bare ones
# so a refusal is proven by the route and not by a missing file.
REFUSED = [
    pytest.param("conn:{P}:documents/x", id="platform_row_outside_the_form_prefix"),
    pytest.param("conn:{P}:forms/{O}/x", id="platform_row_another_forms_prefix"),
    pytest.param("conn:{P}:x", id="platform_row_bare_raw"),
    pytest.param("documents/x", id="bare_outside_the_form_prefix"),
    pytest.param("workflows/{T}/x", id="bare_workflow_prefix_of_a_different_id"),
    pytest.param("forms/{O}/x", id="bare_another_forms_prefix"),
    pytest.param("forms/{F}x/y", id="lookalike_form_id_plus_chars"),
    pytest.param("forms/{F}", id="lookalike_prefix_without_slash"),
    pytest.param("forms/{F}/", id="lookalike_prefix_alone"),
    pytest.param("Forms/{F}/x", id="lookalike_capitalised"),
    pytest.param("/forms/{F}/x", id="lookalike_leading_slash"),
    pytest.param("forms/{F}/../{O}/x", id="dotdot_segments_inside_the_prefix"),
    pytest.param("forms/{F}/..\\{O}\\x", id="dotdot_segments_inside_the_prefix_backslashes"),
    pytest.param("conn:{P}:forms/{F}/../{O}/x", id="dotdot_segments_inside_the_prefix_on_the_platform_row"),
    pytest.param("conn:{P}:forms/{F}/..\\{O}\\x", id="dotdot_segments_backslashes_on_the_platform_row"),
    pytest.param("conn:{P}:forms/{F}/%2e%2e/%2e%2e/documents/x", id="percent_encoded_dots_on_the_platform_row"),
    pytest.param("conn:{P}:forms/{F}/.%2e/x", id="dot_then_percent_encoded_dot_on_the_platform_row"),
    pytest.param("conn:{P}:forms/{F}/%2E./x", id="percent_encoded_dot_then_dot_on_the_platform_row"),
    pytest.param("conn:{P}:forms/{F}/a b", id="space_on_the_platform_row"),
    pytest.param("forms/{F}/a?b", id="question_mark_in_a_bare_key"),
    pytest.param("conn:", id="malformed_empty"),
    pytest.param("conn:x", id="malformed_two_parts_made_up_id"),
    pytest.param("conn:{P}:", id="malformed_empty_raw"),
    pytest.param("CONN:{P}:forms/{F}/x", id="uppercase_conn_prefix_is_a_bare_key"),
    pytest.param("hello", id="plain_text_that_is_not_a_key"),
]


def _make_real_files(world):
    for rel in [
        "documents/x",
        f"workflows/{world.other_tenant}/x",
        f"forms/{world.other_form}/x",
        f"forms/{world.form}x/y",
        f"Forms/{world.form}/x",
        "hello",
        f"CONN:{world.platform}:forms/{world.form}/x",
        f"forms/{world.form}/x",
        f"forms/{world.form}/a?b",
    ]:
        _file(world.media, rel)
    (world.media / "x").write_bytes(SECRET)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("template", REFUSED)
def test_a_stored_key_outside_the_forms_own_prefix_is_not_found(platform_world, shape, template):
    w = platform_world
    _make_real_files(w)
    key = w.fmt(template)
    if key.startswith(f"forms/{w.form}/..") or "/.." in key:
        _file(w.media, f"forms/{w.other_form}/x")
    _assert_refused(w.serve(shape, key), w.stub)


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("template", ["documents/x", f"workflows/{{T}}/x", "forms/{O}/x", "hello"])
def test_on_local_disk_a_stored_key_outside_the_forms_own_prefix_is_not_found(local_world, shape, template):
    w = local_world
    _make_real_files(w)
    _assert_refused(w.serve(shape, w.fmt(template)), w.stub)


@pytest.mark.parametrize("key", [5, [1], {"a": 1}])
def test_a_list_entry_whose_key_is_not_a_string_is_not_found(platform_world, key):
    w = platform_world
    _set_answer(w.sf, w.sub, "resume", [{"key": key, "name": "n", "size": 1, "mime": "text/plain"}])
    _assert_refused(_serve(w.client, w.headers, w.sub, "resume"), w.stub)


def test_the_refusal_is_the_same_response_whatever_the_reason(platform_world):
    w = platform_world
    _make_real_files(w)
    seen = set()
    for template in ["conn:{P}:documents/x", "documents/x", "conn:x", "hello", "forms/{F}/"]:
        res = w.serve("list", w.fmt(template))
        seen.add((res.status_code, res.text))
    assert len(seen) == 1
    assert next(iter(seen))[0] == 404


# ---- controls: allowed keys on the same backends ------------------------------------

@pytest.mark.parametrize("shape", SHAPES)
def test_control_a_bare_key_under_the_forms_prefix_is_served_from_local_disk(local_world, shape):
    w = local_world
    rel = f"forms/{w.form}/{w.sub}/resume/0-x.txt"
    _file(w.media, rel)
    res = w.serve(shape, rel)
    assert res.status_code == 200, res.text
    assert res.content == SECRET


@pytest.mark.parametrize("shape", SHAPES)
def test_control_a_platform_row_key_under_the_forms_prefix_reaches_the_storage_client(platform_world, shape):
    w = platform_world
    raw = f"forms/{w.form}/{w.sub}/resume/0-x.txt"
    res = w.serve(shape, f"conn:{w.platform}:{raw}")
    assert res.status_code in (302, 307), res.text
    assert res.headers["location"].startswith("https://signed.example/")
    assert w.stub.presigned == [raw]


# ---- requirement 3: keys the route must keep serving ---------------------------------

def _upload(client, headers, form_id):
    res = client.post(
        f"/forms/{form_id}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:resume", ("cv.png", _PNG, "image/png"))],
        headers=headers,
    )
    assert res.status_code == 201, res.text
    return res.json()


def test_an_upload_from_the_submit_path_is_served_from_local_disk(client, session_factory, stub, media):
    headers = _headers(client)
    form = _form(client, headers, FILE_FIELD)
    sub = _upload(client, headers, form["id"])
    assert sub["answers"]["resume"][0]["key"].startswith(f"forms/{form['id']}/")
    res = _serve(client, headers, sub["id"], "resume")
    assert res.status_code == 200
    assert res.content == _PNG


def test_an_upload_from_the_submit_path_is_served_from_the_platform_connection(client, session_factory, stub, media):
    platform = _connection(session_factory, PLATFORM_TENANT_ID)
    headers = _headers(client)
    form = _form(client, headers, FILE_FIELD)
    sub = _upload(client, headers, form["id"])
    key = sub["answers"]["resume"][0]["key"]
    assert key.startswith(f"conn:{platform}:forms/{form['id']}/")
    stub.presigned.clear()
    res = _serve(client, headers, sub["id"], "resume")
    assert res.status_code in (302, 307)
    assert stub.presigned == [key.split(":", 2)[2]]


def _sign(client, headers, form_id):
    data_url = "data:image/png;base64," + base64.b64encode(_PNG).decode()
    res = client.post(f"/forms/{form_id}/submissions", json={"answers": {"sign": data_url}}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_a_signature_from_the_submit_path_is_served_from_local_disk(client, session_factory, stub, media):
    headers = _headers(client)
    form = _form(client, headers, SIGN_FIELD)
    sub = _sign(client, headers, form["id"])
    res = _serve(client, headers, sub["id"], "sign")
    assert res.status_code == 200
    assert res.content == _PNG


def test_a_signature_from_the_submit_path_is_served_from_the_platform_connection(client, session_factory, stub, media):
    platform = _connection(session_factory, PLATFORM_TENANT_ID)
    headers = _headers(client)
    form = _form(client, headers, SIGN_FIELD)
    sub = _sign(client, headers, form["id"])
    assert sub["answers"]["sign"].startswith(f"conn:{platform}:forms/{form['id']}/")
    stub.presigned.clear()
    res = _serve(client, headers, sub["id"], "sign")
    assert res.status_code in (302, 307)
    assert len(stub.presigned) == 1


def test_a_revision_serves_a_file_carried_by_reference_from_the_old_submission(client, session_factory, stub, media):
    headers = _headers(client)
    form = _form(client, headers, FILE_FIELD, revisions=True)
    original = _upload(client, headers, form["id"])
    revise = client.post(f"/submissions/{original['id']}/revise", headers=headers)
    assert revise.status_code == 200, revise.text
    revision = revise.json()
    key = revision["answers"]["resume"][0]["key"]
    assert revision["id"] != original["id"]
    assert key.startswith(f"forms/{form['id']}/{original['id']}/")
    res = _serve(client, headers, revision["id"], "resume")
    assert res.status_code == 200
    assert res.content == _PNG


def test_a_key_on_the_tenants_own_storage_connection_is_served(own_world):
    w = own_world
    raw = f"forms/{w.form}/{w.sub}/resume/0-x.txt"
    res = w.serve("list", f"conn:{w.own}:{raw}")
    assert res.status_code in (302, 307)
    assert w.stub.presigned == [raw]


@pytest.mark.parametrize("shape", SHAPES)
def test_a_key_written_before_a_storage_migration_on_the_platform_row_is_served(own_world, shape):
    w = own_world
    raw = f"forms/{w.form}/old-{uuid.uuid4().hex[:6]}/resume/0-x.txt"
    res = w.serve(shape, f"conn:{w.platform}:{raw}")
    assert res.status_code in (302, 307)
    assert w.stub.presigned == [raw]


# ---- requirement 4: tenant isolation ------------------------------------------------

def test_a_user_of_a_different_tenant_gets_not_found_for_the_submission(client, session_factory, stub, media):
    headers = _headers(client)
    form = _form(client, headers, FILE_FIELD)
    sub = _upload(client, headers, form["id"])
    platform_login = client.post(
        "/auth/login", json={"email": PLATFORM_EMAIL, "password": PLATFORM_PASSWORD, "tenantSlug": "platform"}
    )
    platform_headers = {"Authorization": f"Bearer {platform_login.json()['access_token']}"}
    slug = f"fk-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/platform/tenants",
        json={"name": slug, "slug": slug, "adminName": "Kay", "adminEmail": f"kay@{slug}.com", "adminPassword": "ChangeMe1!"},
        headers=platform_headers,
    )
    assert created.status_code == 201, created.text
    other = client.post(
        "/auth/login", json={"email": f"kay@{slug}.com", "password": "ChangeMe1!", "tenantSlug": slug}
    )
    assert other.status_code == 200, other.text
    other_headers = {"Authorization": f"Bearer {other.json()['access_token']}"}
    res = _serve(client, other_headers, sub["id"], "resume")
    assert res.status_code == 404
    assert _serve(client, headers, sub["id"], "resume").status_code == 200


# ---- more refused shapes on a connection that has a CDN ------------------------------

@pytest.mark.parametrize("template", ["conn:{P}:forms/{F}/a b", "conn:{P}:x", "conn:{P}:other/x", "conn:{P}:forms/{F}/%2e%2e/x"])
def test_on_a_connection_with_a_cdn_a_stored_key_the_form_did_not_write_is_not_found(
    client, session_factory, stub, media, template
):
    w = World(client, _headers(client), session_factory, media, stub, platform=False)
    w.platform = _connection(session_factory, PLATFORM_TENANT_ID, cdn="https://cdn.example")
    res = w.serve("list", w.fmt(template))
    assert res.status_code == 404, (res.status_code, res.headers.get("location"))
    assert res.json() == {"detail": "File not found."}


def test_control_on_a_connection_with_a_cdn_a_key_under_the_forms_prefix_redirects_to_the_cdn(
    client, session_factory, stub, media
):
    w = World(client, _headers(client), session_factory, media, stub, platform=False)
    w.platform = _connection(session_factory, PLATFORM_TENANT_ID, cdn="https://cdn.example")
    res = w.serve("list", f"conn:{w.platform}:forms/{w.form}/{w.sub}/resume/0-x.txt")
    assert res.status_code in (302, 307)
    assert res.headers["location"].startswith("https://cdn.example/")


# ---- the content type is not taken from the answer -----------------------------------

def _serve_entry_on_local_disk(w, mime, name="n.txt"):
    rel = f"forms/{w.form}/{w.sub}/resume/0-x.bin"
    _file(w.media, rel, b"hello")
    _set_answer(w.sf, w.sub, "resume", [_entry(rel, mime=mime, name=name)])
    return _serve(w.client, w.headers, w.sub, "resume")


@pytest.mark.parametrize(
    "mime",
    ["text/html", "image/svg+xml", "application/xhtml+xml", "text/xml", "text/html; charset=utf-8"],
)
def test_an_entry_declaring_a_markup_type_is_served_as_an_opaque_download(local_world, mime):
    res = _serve_entry_on_local_disk(local_world, mime)
    assert res.status_code == 200
    assert res.headers["content-type"].split(";")[0] == "application/octet-stream"


@pytest.mark.parametrize(
    "mime",
    ["image/png", "image/jpeg", "image/gif", "image/webp", "application/pdf", "text/plain"],
)
def test_control_an_entry_declaring_a_plain_content_type_keeps_it(local_world, mime):
    res = _serve_entry_on_local_disk(local_world, mime)
    assert res.status_code == 200
    assert res.headers["content-type"].split(";")[0] == mime


def test_a_signature_string_is_served_as_png(local_world):
    w = local_world
    rel = f"forms/{w.form}/{w.sub}/sign/0-x.png"
    _file(w.media, rel, _PNG)
    res = w.serve("string", rel)
    assert res.status_code == 200
    assert res.headers["content-type"].split(";")[0] == "image/png"


# ---- the file name header is well formed ---------------------------------------------

def test_a_name_with_a_quote_gives_a_well_formed_header(local_world):
    from urllib.parse import quote

    name = 'a"b.png'
    res = _serve_entry_on_local_disk(local_world, "image/png", name=name)
    assert res.status_code == 200
    header = res.headers["content-disposition"]
    assert header.count('"') == 2, header
    assert f"filename*=UTF-8''{quote(name, safe='')}" in header


def test_a_non_ascii_name_gives_a_header_carrying_the_real_name(local_world):
    from urllib.parse import quote

    name = "\u7b80\u5386.png"
    res = _serve_entry_on_local_disk(local_world, "image/png", name=name)
    assert res.status_code == 200
    assert f"filename*=UTF-8''{quote(name, safe='')}" in res.headers["content-disposition"]


def test_an_upload_named_with_non_ascii_characters_opens(client, session_factory, stub, media):
    headers = _headers(client)
    form = _form(client, headers, FILE_FIELD)
    res = client.post(
        f"/forms/{form['id']}/submissions",
        data={"payload": json.dumps({"answers": {}})},
        files=[("file:resume", ("\u7b80\u5386.png", _PNG, "image/png"))],
        headers=headers,
    )
    assert res.status_code == 201, res.text
    served = _serve(client, headers, res.json()["id"], "resume")
    assert served.status_code == 200
    assert served.content == _PNG


# ---- a key under the prefix whose file is not there ----------------------------------

def test_a_key_under_the_prefix_whose_local_file_is_missing_is_not_found(local_world):
    w = local_world
    res = w.serve("list", f"forms/{w.form}/{w.sub}/resume/missing.txt")
    assert res.status_code == 404
    assert res.json() == {"detail": "File not found."}


def test_a_key_under_the_prefix_that_is_a_directory_is_not_found(local_world):
    w = local_world
    (w.media / "forms" / w.form / "dirx").mkdir(parents=True)
    res = w.serve("list", f"forms/{w.form}/dirx")
    assert res.status_code == 404
    assert res.json() == {"detail": "File not found."}


# ---- the file name header is well formed for any stored name --------------------------

CONTROL_NAMES = ["a\x00b.png", "a\x01b.png", "a\x0bb.png", "a\x0cb.png", "a\x1bb.png", "a\x7fb.png"]


def _ascii_part(header: str) -> str:
    import re

    match = re.search(r'filename="(.*?)"; filename\*=', header)
    assert match, header
    return match.group(1)


def _assert_plain_ascii_name(part: str):
    assert all(0x20 <= ord(c) < 0x7F for c in part), repr(part)
    assert '"' not in part and "\\" not in part, repr(part)


@pytest.mark.parametrize("name", CONTROL_NAMES, ids=lambda n: f"byte_{ord(n[1]):02x}")
def test_a_stored_name_with_control_bytes_gives_a_clean_header(local_world, name):
    res = _serve_entry_on_local_disk(local_world, "image/png", name=name)
    assert res.status_code == 200
    _assert_plain_ascii_name(_ascii_part(res.headers["content-disposition"]))


def test_a_stored_name_with_a_lone_surrogate_gives_a_pure_ascii_header(local_world):
    res = _serve_entry_on_local_disk(local_world, "image/png", name="a\ud800b.png")
    assert res.status_code == 200
    raw = dict(res.headers.raw)[b"content-disposition"]
    assert raw.isascii()


def test_control_a_non_ascii_name_keeps_its_real_name_and_a_plain_name_is_unchanged(local_world):
    from urllib.parse import quote

    res = _serve_entry_on_local_disk(local_world, "image/png", name="简历.png")
    assert f"filename*=UTF-8''{quote(chr(0x7b80) + chr(0x5386) + '.png', safe='')}" in res.headers["content-disposition"]
    res = _serve_entry_on_local_disk(local_world, "application/pdf", name="report.pdf")
    assert res.headers["content-disposition"].startswith('inline; filename="report.pdf"')


@pytest.mark.parametrize("name", CONTROL_NAMES, ids=lambda n: f"byte_{ord(n[1]):02x}")
def test_content_disposition_helper_strips_control_bytes(name):
    from app.api.v1.documents import _content_disposition

    _assert_plain_ascii_name(_ascii_part(_content_disposition("inline", name)))


def test_content_disposition_helper_accepts_a_lone_surrogate():
    from app.api.v1.documents import _content_disposition

    assert _content_disposition("inline", "a\ud800b.png").isascii()


def test_control_content_disposition_helper_keeps_plain_and_real_names():
    from urllib.parse import quote

    from app.api.v1.documents import _content_disposition

    assert _content_disposition("inline", "report.pdf").startswith('inline; filename="report.pdf"')
    real = "简历.png"
    assert f"filename*=UTF-8''{quote(real, safe='')}" in _content_disposition("inline", real)


# ---- every type a real upload can have keeps its type at the route ----------------------

_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
_ZIP_BYTES = b"PK\x03\x04" + b"\x00" * 24

# (sample bytes, filename, the type detect_upload_mime must report)
SNIFFED_SAMPLES = [
    pytest.param(_PNG, "a.png", "image/png", id="png"),
    pytest.param(b"\xff\xd8\xff\xe0" + b"\x00" * 16, "a.jpg", "image/jpeg", id="jpeg"),
    pytest.param(b"GIF89a" + b"\x00" * 16, "a.gif", "image/gif", id="gif"),
    pytest.param(b"RIFF\x00\x00\x00\x00WEBPVP8 ", "a.webp", "image/webp", id="webp"),
    pytest.param(b"\x00\x00\x01\x00" + b"\x00" * 16, "a.ico", "image/x-icon", id="icon"),
    pytest.param(b"%PDF-1.4\n", "a.pdf", "application/pdf", id="pdf"),
    pytest.param(_ZIP_BYTES, "a.zip", "application/zip", id="zip"),
    pytest.param(_ZIP_BYTES, "a.docx", _DOCX, id="docx"),
    pytest.param(_ZIP_BYTES, "a.xlsx", _XLSX, id="xlsx"),
    pytest.param(_ZIP_BYTES, "a.pptx", _PPTX, id="pptx"),
    pytest.param("plain text, café".encode("utf-8"), "a.txt", "text/plain", id="text"),
]


@pytest.mark.parametrize("content,filename,expected", SNIFFED_SAMPLES)
def test_a_sniffed_upload_type_is_served_with_the_same_type(local_world, content, filename, expected):
    from app.uploads import detect_upload_mime

    w = local_world
    sniffed = detect_upload_mime(content, filename)
    assert sniffed == expected  # guard: the sample really sniffs to this type
    rel = f"forms/{w.form}/{w.sub}/resume/0-x.bin"
    _file(w.media, rel, content)
    _set_answer(w.sf, w.sub, "resume", [_entry(rel, mime=sniffed, name=filename)])
    res = _serve(w.client, w.headers, w.sub, "resume")
    assert res.status_code == 200
    assert res.headers["content-type"].split(";")[0] == expected


@pytest.mark.parametrize(
    "content,filename",
    [
        pytest.param(b"<svg xmlns='http://www.w3.org/2000/svg'></svg>", "a.svg", id="svg"),
        pytest.param(b"<!doctype html><p>x</p>", "a.html", id="html"),
    ],
)
def test_markup_is_not_a_sniffed_type_and_stays_an_opaque_download(local_world, content, filename):
    from app.uploads import detect_upload_mime

    w = local_world
    assert detect_upload_mime(content, filename) is None
    res = _serve_entry_on_local_disk(w, "text/html", name=filename)
    assert res.headers["content-type"].split(";")[0] == "application/octet-stream"
