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
    "conn:omni/templates/{cid}/sample.png",
    "conn::omni/templates/{cid}/sample.png",
    "CONN:{plat}:omni/templates/{cid}/a.png",
]

SMALL = ["documents/x", "omni/templates/{other}/" + TAIL, "omni/templates/{cid}/../../documents/x"]
CASES = [("IMAGE", k) for k in REFUSED] + [(f, k) for f in ("VIDEO", "DOCUMENT") for k in SMALL]


def _field_error(res):
    """The builder reads detail.fieldErrors.<field> as text."""
    detail = res.json()["detail"]
    assert isinstance(detail, dict), detail
    assert isinstance(detail["fieldErrors"]["header"], str) and detail["fieldErrors"]["header"]


class SpyAdapter:
    def __init__(self):
        self.uploads = []
        self.created = []
        self.edits = []

    def upload_resumable(self, creds, app_id, data, mime):
        self.uploads.append(data)
        return "handle-1"

    def edit_template(self, creds, meta_id, payload):
        self.edits.append((meta_id, payload))

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


def _doc(name, key=None, fmt="IMAGE"):
    header = {"format": fmt}
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
@pytest.mark.parametrize("fmt,tpl", CASES)
def test_create_refuses_foreign_sample_key(client, ctx, backend, fmt, tpl):
    h, cid, base = ctx
    good = _upload(client, h, cid)
    assert (good.startswith("conn:")) == (backend["mode"] == "bucket")
    assert client.post(base, headers=h, json=_doc("good_one", good, fmt)).status_code == 201
    before = _total(client, h, cid)
    res = client.post(base, headers=h, json=_doc("bad_one", _bad(tpl, cid, backend["plat"]), fmt))
    assert res.status_code == 422, res.text
    _field_error(res)
    assert _total(client, h, cid) == before


@pytest.mark.parametrize("fmt,tpl", CASES)
def test_update_refuses_foreign_sample_key(client, ctx, session_factory, backend, fmt, tpl):
    h, cid, base = ctx
    good = _upload(client, h, cid)
    tid = client.post(base, headers=h, json=_doc("good_one", good, fmt)).json()["id"]
    assert client.patch(f"{base}/{tid}", headers=h, json=_doc("good_one", good, fmt)).status_code == 200
    res = client.patch(f"{base}/{tid}", headers=h, json=_doc("good_one", _bad(tpl, cid, backend["plat"]), fmt))
    assert res.status_code == 422, res.text
    _field_error(res)
    db = session_factory()
    assert db.get(WhatsappTemplate, tid).media_sample_key == good
    db.close()


def test_create_without_sample_key_works(client, ctx, backend):
    h, cid, base = ctx
    assert client.post(base, headers=h, json=_doc("no_sample")).status_code == 201


# ── 2. submit ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fmt,tpl", CASES)
def test_submit_refuses_foreign_sample_key(client, ctx, session_factory, local_media, backend, spy, monkeypatch, fmt, tpl):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    (local_media / "documents").mkdir(exist_ok=True)
    (local_media / "documents" / "x").write_bytes(MARKER)

    # control on the same backend: a key the route wrote goes through
    good = _upload(client, h, cid)
    gid = client.post(base, headers=h, json=_doc("good_one", good, fmt)).json()["id"]
    assert client.post(f"{base}/{gid}/submit", headers=h).status_code == 200
    assert spy.uploads == [PNG if backend["mode"] == "local" else b""]
    assert len(spy.created) == 1

    tid = client.post(base, headers=h, json=_doc("bad_one", fmt=fmt)).json()["id"]
    db = session_factory()
    db.get(WhatsappTemplate, tid).media_sample_key = _bad(tpl, cid, backend["plat"])
    db.commit()
    db.close()
    res = client.post(f"{base}/{tid}/submit", headers=h)
    assert res.status_code == 422, res.text
    # submit errors reach the builder as a toast of the plain-text detail
    assert isinstance(res.json()["detail"], str) and res.json()["detail"]
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


@pytest.mark.parametrize("fmt", ["VIDEO", "DOCUMENT"])
def test_route_key_accepted_for_other_media_formats(client, ctx, fmt):
    h, cid, base = ctx
    key = _upload(client, h, cid)
    assert client.post(base, headers=h, json=_doc("fmt_flow", key, fmt)).status_code == 201


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


# ── provider handles stored by sync ─────────────────────────────────────────
HANDLE = "https://provider.example/handle"


def _seed(session_factory, cid, handle, status, meta_id):
    db = session_factory()
    row = WhatsappTemplate(
        tenant_id=DEFAULT_TENANT_ID, channel_id=cid, name="synced_one", language="en_US",
        category="UTILITY", status=status, meta_template_id=meta_id,
        components_json=[
            {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [handle]}},
            {"type": "BODY", "text": "Order {{1}} is ready.", "example": {"body_text": [["A1"]]}},
        ],
    )
    db.add(row)
    db.commit()
    rid = row.id
    db.close()
    return rid


def _row_state(session_factory, rid):
    db = session_factory()
    r = db.get(WhatsappTemplate, rid)
    out = (r.media_sample_key, r.components_json, r.status)
    db.close()
    return out


@pytest.fixture
def storage_touched(monkeypatch):
    from app.services.storage import TenantStorage

    calls = []
    real_resolve, real_save = TenantStorage.resolve, TenantStorage.save
    monkeypatch.setattr(TenantStorage, "resolve", lambda self, k: (calls.append(k), real_resolve(self, k))[1])
    monkeypatch.setattr(TenantStorage, "save", lambda self, *a: (calls.append(a), real_save(self, *a))[1])
    return calls


def _same_doc(client, h, base, rid):
    return client.get(f"{base}/manage/{rid}", headers=h).json()["doc"]


def test_unchanged_handle_edit_keeps_it_without_provider_call(client, ctx, session_factory, spy, storage_touched, monkeypatch):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    rid = _seed(session_factory, cid, HANDLE, "APPROVED", None)
    res = client.patch(f"{base}/{rid}", headers=h, json=_same_doc(client, h, base, rid))
    assert res.status_code == 200, res.text
    key, comps, _ = _row_state(session_factory, rid)
    assert key is None
    assert comps[0]["example"]["header_handle"] == [HANDLE]
    assert storage_touched == [] and spy.uploads == [] and spy.edits == []


def test_unchanged_handle_edit_sends_same_handle_to_provider(client, ctx, session_factory, spy, storage_touched, monkeypatch):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    rid = _seed(session_factory, cid, HANDLE, "APPROVED", "meta-9")
    res = client.patch(f"{base}/{rid}", headers=h, json=_same_doc(client, h, base, rid))
    assert res.status_code == 200, res.text
    assert _row_state(session_factory, rid)[0] is None
    assert storage_touched == [] and spy.uploads == []
    assert len(spy.edits) == 1
    meta_id, payload = spy.edits[0]
    assert meta_id == "meta-9"
    header = next(c for c in payload["components"] if c["type"] == "HEADER")
    assert header["example"]["header_handle"] == [HANDLE]


def test_unchanged_old_style_handle_never_reads_its_file(client, ctx, session_factory, local_media, spy, monkeypatch):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    (local_media / "documents").mkdir(exist_ok=True)
    (local_media / "documents" / "x").write_bytes(MARKER)
    rid = _seed(session_factory, cid, "documents/x", "APPROVED", "meta-9")
    res = client.patch(f"{base}/{rid}", headers=h, json=_same_doc(client, h, base, rid))
    assert res.status_code == 200, res.text
    assert MARKER not in spy.uploads
    assert all(MARKER.decode() not in str(e) for e in spy.edits)


@pytest.mark.parametrize("new_value", ["https://provider.example/other", "documents/x"])
def test_changed_handle_is_refused_and_row_unchanged(client, ctx, session_factory, spy, monkeypatch, new_value):
    h, cid, base = ctx
    _live(monkeypatch, session_factory, cid)
    rid = _seed(session_factory, cid, HANDLE, "APPROVED", "meta-9")
    before = _row_state(session_factory, rid)
    doc = _same_doc(client, h, base, rid)
    before = _row_state(session_factory, rid)
    doc["header"]["sampleKey"] = new_value
    res = client.patch(f"{base}/{rid}", headers=h, json=doc)
    assert res.status_code == 422, res.text
    _field_error(res)
    assert _row_state(session_factory, rid) == before


# ── upload route needs this tenant's channel ────────────────────────────────
def _png_post(client, h, cid):
    return client.post(
        f"/omnichannel/channels/{cid}/templates/upload-sample", headers=h,
        files={"file": ("a.png", PNG, "image/png")},
    )


def test_upload_for_other_tenants_channel_is_404_and_stores_nothing(client, ctx, session_factory, local_media, storage_touched):
    from app.services.app_store_service import AppStoreService
    from app.services.tenant_service import TenantService

    h, cid, base = ctx
    db = session_factory()
    other = TenantService(db).provision(
        name="Other", slug="otherco-up", admin_email="other-up@example.com",
        admin_password="Password123!", admin_name="O",
    )
    db.flush()
    AppStoreService(db).install(other.id, "omnichannel")
    db.commit()
    db.close()
    assert _png_post(client, h, cid).status_code == 200  # control: owner succeeds
    storage_touched.clear()
    files_before = sorted(p for p in local_media.rglob("*") if p.is_file())
    h2 = _auth(client, email="other-up@example.com", password="Password123!", tenant_slug="otherco-up")
    assert _png_post(client, h2, cid).status_code == 404
    assert storage_touched == []
    assert sorted(p for p in local_media.rglob("*") if p.is_file()) == files_before


def test_upload_for_missing_channel_is_404(client, ctx, local_media):
    h, cid, base = ctx
    assert _png_post(client, h, cid).status_code == 200
    assert _png_post(client, h, "no-such-channel").status_code == 404


def test_upload_for_own_channel_gives_key_create_accepts(client, ctx, local_media):
    h, cid, base = ctx
    res = _png_post(client, h, cid)
    assert res.status_code == 200
    assert client.post(base, headers=h, json=_doc("own_up", res.json()["sampleKey"])).status_code == 201
