"""WhatsApp template drafts: a header sample key must be one this channel's
upload route wrote (create, update, submit), on local disk and behind a bucket."""
import pytest

from app.config import settings
from app.models.connection import CONNECTION_STATUS_ERROR, CONNECTION_STATUS_UNVERIFIED
from app.models.tenant import DEFAULT_TENANT_ID, PLATFORM_TENANT_ID
from modules.omnichannel.models import Channel, WhatsappTemplate
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import template_management_service as tms
from tests.test_omni_templates import _DRAFT, _auth, _channel
from tests.test_storage_resolution import _storage_connection, local_media, stub_client  # noqa: F401

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24
MARKER = b"FILE-BODY-MARKER"
TAIL = "sample-abc.png"

# Each template is filled with: cid (this channel), other (another channel id),
# tenant (another tenant id), plat (platform storage connection id).
REFUSED = [
    "documents/x",
    "omni/templates/{other}/" + TAIL,
    "workflows/{tenant}/x",
    "conn:{plat}:documents/x",
    "omni/templates/{cid}x/sample.png",
    "omni/templates/{cid}/",
    "omni/templates/{cid}/../../documents/x",
    "omni\\templates\\{cid}\\..\\..\\documents\\x",
    "omni/templates/{cid}/..\\..\\documents\\x",
    "omni/templates/{cid}/%2e%2e/x",
    "conn:",
    "conn:x",
    "CONN:{plat}:omni/templates/{cid}/a.png",
]


class SpyAdapter:
    def __init__(self):
        self.uploads = []
        self.created = []

    def upload_resumable(self, creds, app_id, data, mime):
        self.uploads.append(data)
        return "handle-1"

    def create_template(self, creds, waba_id, payload):
        self.created.append(payload)
        return {"meta_template_id": "meta-1", "status": "PENDING"}


@pytest.fixture
def spy(monkeypatch):
    s = SpyAdapter()
    monkeypatch.setattr(tms, "get_adapter", lambda *a, **k: s)
    return s


@pytest.fixture(params=["local", "bucket"])
def backend(request, session_factory, local_media, stub_client):  # noqa: F811
    """A platform storage connection always exists (its id feeds the key shapes);
    in 'local' mode it is in ERROR so writes fall back to local disk."""
    db = session_factory()
    status = CONNECTION_STATUS_UNVERIFIED if request.param == "bucket" else CONNECTION_STATUS_ERROR
    conn = _storage_connection(db, PLATFORM_TENANT_ID, status=status)
    plat = conn.id
    db.close()
    return {"mode": request.param, "plat": plat}


def _live(monkeypatch, session_factory, cid):
    """Leave dev mode: an app id plus channel credentials without the dev flag."""
    monkeypatch.setattr(settings, "meta_app_id", "test-app-id")
    db = session_factory()
    ch = db.get(Channel, cid)
    ch.credentials_json = encrypt_credentials({"access_token": "tok"})
    db.commit()
    db.close()


def _doc(name, key=None):
    header = {"format": "IMAGE"}
    if key is not None:
        header["sampleKey"] = key
    return {**_DRAFT, "name": name, "header": header}


def _upload(client, h, cid):
    res = client.post(
        f"/omnichannel/channels/{cid}/templates/upload-sample", headers=h,
        files={"file": ("a.png", PNG, "image/png")},
    )
    assert res.status_code == 200, res.text
    return res.json()["sampleKey"]


def _total(client, h, cid):
    return client.get(f"/omnichannel/channels/{cid}/templates/manage", headers=h).json()["total"]


def _bad(tpl, cid, plat):
    return tpl.format(cid=cid, other="chan-other-0001", tenant="tenant-other-0001", plat=plat)


@pytest.fixture
def ctx(client):
    h = _auth(client)
    cid = _channel(client, h)
    return h, cid, f"/omnichannel/channels/{cid}/templates"


# ── 1. create / update ──────────────────────────────────────────────────────
@pytest.mark.parametrize("tpl", REFUSED)
def test_create_refuses_foreign_sample_key(client, ctx, backend, tpl):
    h, cid, base = ctx
    good = _upload(client, h, cid)
    assert (good.startswith("conn:")) == (backend["mode"] == "bucket")
    assert client.post(base, headers=h, json=_doc("good_one", good)).status_code == 201
    before = _total(client, h, cid)
    res = client.post(base, headers=h, json=_doc("bad_one", _bad(tpl, cid, backend["plat"])))
    assert res.status_code == 422, res.text
    assert _total(client, h, cid) == before


@pytest.mark.parametrize("tpl", REFUSED)
def test_update_refuses_foreign_sample_key(client, ctx, session_factory, backend, tpl):
    h, cid, base = ctx
    good = _upload(client, h, cid)
    tid = client.post(base, headers=h, json=_doc("good_one", good)).json()["id"]
    assert client.patch(f"{base}/{tid}", headers=h, json=_doc("good_one", good)).status_code == 200
    res = client.patch(f"{base}/{tid}", headers=h, json=_doc("good_one", _bad(tpl, cid, backend["plat"])))
    assert res.status_code == 422, res.text
    db = session_factory()
    assert db.get(WhatsappTemplate, tid).media_sample_key == good
    db.close()


def test_create_without_sample_key_works(client, ctx, backend):
    h, cid, base = ctx
    assert client.post(base, headers=h, json=_doc("no_sample")).status_code == 201


# ── 2. submit ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("tpl", REFUSED)
def test_submit_refuses_foreign_sample_key(client, ctx, session_factory, local_media, backend, spy, monkeypatch, tpl):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    (local_media / "documents").mkdir(exist_ok=True)
    (local_media / "documents" / "x").write_bytes(MARKER)

    # control on the same backend: a key the route wrote goes through
    good = _upload(client, h, cid)
    gid = client.post(base, headers=h, json=_doc("good_one", good)).json()["id"]
    assert client.post(f"{base}/{gid}/submit", headers=h).status_code == 200
    assert spy.uploads == [PNG if backend["mode"] == "local" else b""]
    assert len(spy.created) == 1

    tid = client.post(base, headers=h, json=_doc("bad_one")).json()["id"]
    db = session_factory()
    db.get(WhatsappTemplate, tid).media_sample_key = _bad(tpl, cid, backend["plat"])
    db.commit()
    db.close()
    res = client.post(f"{base}/{tid}/submit", headers=h)
    assert res.status_code == 422, res.text
    assert MARKER not in spy.uploads
    assert len(spy.uploads) == 1
    assert len(spy.created) == 1


# ── 4. keep working ─────────────────────────────────────────────────────────
def test_route_upload_create_submit_local_passes_sniffed_bytes(client, ctx, session_factory, local_media, spy, monkeypatch):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    key = _upload(client, h, cid)
    assert not key.startswith("conn:")
    tid = client.post(base, headers=h, json=_doc("local_flow", key)).json()["id"]
    assert client.post(f"{base}/{tid}/submit", headers=h).status_code == 200
    assert spy.uploads == [PNG]
    assert len(spy.created) == 1


def test_bucket_key_accepted_and_submits_as_before(client, ctx, session_factory, local_media, stub_client, spy, monkeypatch):  # noqa: F811
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    db = session_factory()
    plat = _storage_connection(db, PLATFORM_TENANT_ID).id
    db.close()
    key = f"conn:{plat}:omni/templates/{cid}/{TAIL}"
    created = client.post(base, headers=h, json=_doc("bucket_flow", key))
    assert created.status_code == 201, created.text
    tid = created.json()["id"]
    assert client.post(f"{base}/{tid}/submit", headers=h).status_code == 200
    assert spy.uploads == [b""]
    assert len(spy.created) == 1


def test_key_with_migrated_connection_id_is_accepted(client, ctx, local_media, stub_client, session_factory):  # noqa: F811
    h, cid, base = ctx
    db = session_factory()
    plat = _storage_connection(db, PLATFORM_TENANT_ID).id
    own = _storage_connection(db, DEFAULT_TENANT_ID).id
    db.close()
    assert plat != own
    for n, conn in enumerate((plat, own)):
        key = f"conn:{conn}:omni/templates/{cid}/{TAIL}"
        res = client.post(base, headers=h, json=_doc(f"migrated_{n}", key))
        assert res.status_code == 201, res.text


def test_dev_mode_submit_behaves_as_before(client, ctx, local_media, spy):
    h, cid, base = ctx
    assert not settings.meta_app_id
    key = _upload(client, h, cid)
    tid = client.post(base, headers=h, json=_doc("dev_flow", key)).json()["id"]
    assert client.post(f"{base}/{tid}/submit", headers=h).status_code == 200
    assert spy.uploads == [b""]
    assert len(spy.created) == 1


# ── 5. tenant scoping control ───────────────────────────────────────────────
def test_other_tenant_cannot_reach_this_channel(client, ctx, session_factory, local_media, spy):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    h, cid, base = ctx
    key = _upload(client, h, cid)
    tid = client.post(base, headers=h, json=_doc("mine", key)).json()["id"]
    db = session_factory()
    other = TenantService(db).provision(
        name="Other", slug="otherco-key", admin_email="other-key@example.com",
        admin_password="Password123!", admin_name="O",
    )
    db.flush()
    AppStoreService(db).install(other.id, "omnichannel")
    db.commit()
    db.close()
    h2 = _auth(client, email="other-key@example.com", password="Password123!", tenant_slug="otherco-key")
    assert client.post(base, headers=h2, json=_doc("theirs", key)).status_code == 404
    assert client.post(f"{base}/{tid}/submit", headers=h2).status_code == 404
    assert spy.created == []
