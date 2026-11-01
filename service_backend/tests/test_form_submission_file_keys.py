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


def _connection(session_factory, tenant_id):
    db = session_factory()
    row = Connection(
        tenant_id=tenant_id,
        provider="s3",
        type="storage",
        name="Bucket",
        config_json={"bucket": "assets", "region": "auto", "cdnBaseUrl": ""},
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


def _entry(key):
    return {"key": key, "name": "n.txt", "size": 1, "mime": "text/plain"}


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
    pytest.param("workflows/{T}/x", id="bare_another_tenants_workflow_prefix"),
    pytest.param("forms/{O}/x", id="bare_another_forms_prefix"),
    pytest.param("forms/{F}x/y", id="lookalike_form_id_plus_chars"),
    pytest.param("forms/{F}", id="lookalike_prefix_without_slash"),
    pytest.param("forms/{F}/", id="lookalike_prefix_alone"),
    pytest.param("Forms/{F}/x", id="lookalike_capitalised"),
    pytest.param("/forms/{F}/x", id="lookalike_leading_slash"),
    pytest.param("forms/{F}/../{O}/x", id="traversal_inside_the_prefix"),
    pytest.param("forms/{F}/..\\{O}\\x", id="traversal_inside_the_prefix_backslashes"),
    pytest.param("conn:{P}:forms/{F}/../{O}/x", id="traversal_inside_the_prefix_on_the_platform_row"),
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

def test_another_tenants_user_gets_not_found_for_the_submission(client, session_factory, stub, media):
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
