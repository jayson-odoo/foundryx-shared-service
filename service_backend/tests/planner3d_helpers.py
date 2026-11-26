"""Shared builders for the planner3d suite (plan planner3d-s3-gpu-worker).

Fixture bytes are tiny and built in memory: real PNG/JPEG/WebP via Pillow and a
hand-built minimal GLB (trimesh is not in the venv). Every test seeds its own
tenants and users through these helpers.
"""
from __future__ import annotations

import hashlib
import io
import json
import struct
from datetime import datetime, timedelta, timezone

from PIL import Image

from app.models import Role, User, UserStatus
from app.models.permission import Permission
from app.security import hash_password

WORKER_TOKEN = "p3-worker-token-for-tests-0123456789"
WORKER = "mac-mini-1"
OTHER_WORKER = "mac-mini-2"
TENANT_B = "tenant-p3-b"
TENANT_B_SLUG = "planner-b"
PW = "demo1234"
VIEW_EMAIL = "p3-view@example.com"
NONE_EMAIL = "p3-none@example.com"
B_EMAIL = "admin@planner-b.example"

DIMS = {"lengthMm": "1200", "widthMm": "600", "heightMm": "800"}
SIX = ["model.glb", "model.gltf", "model.obj", "model.mtl", "model.fbx", "model.stl"]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# ── fixture bytes ───────────────────────────────────────────────────────────

def _img(fmt: str, size=(4, 4), colour=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, colour).save(buf, fmt)
    return buf.getvalue()


def png_bytes(colour=(200, 30, 30)) -> bytes:
    return _img("PNG", colour=colour)


def jpeg_bytes() -> bytes:
    return _img("JPEG")


def webp_bytes() -> bytes:
    return _img("WEBP")


def array_png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def glb_bytes(tag: str = "a") -> bytes:
    """Minimal valid GLB: 12-byte header + one padded JSON chunk."""
    doc = json.dumps({"asset": {"version": "2.0", "generator": tag}}).encode()
    doc += b" " * (-len(doc) % 4)
    total = 12 + 8 + len(doc)
    return struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<I4s", len(doc), b"JSON") + doc


def gltf_bytes() -> bytes:
    return json.dumps({"asset": {"version": "2.0"}, "scenes": []}).encode()


def obj_bytes() -> bytes:
    return b"# obj\nmtllib model.mtl\nv 0 0 0\nv 1 0 0\nv 0 1 0\nf 1 2 3\n"


def mtl_bytes() -> bytes:
    return b"newmtl mat\nKd 0.8 0.8 0.8\n"


def stl_bytes() -> bytes:
    return b"solid m\nfacet normal 0 0 1\nouter loop\nvertex 0 0 0\nvertex 1 0 0\nvertex 0 1 0\nendloop\nendfacet\nendsolid m\n"


def fbx_bytes() -> bytes:
    return b"Kaydara FBX Binary  \x00\x1a\x00" + struct.pack("<I", 7400) + b"\x00" * 64


EXPORTS = {
    "model.glb": glb_bytes("convert"),
    "model.gltf": gltf_bytes(),
    "model.obj": obj_bytes(),
    "model.mtl": mtl_bytes(),
    "model.fbx": fbx_bytes(),
    "model.stl": stl_bytes(),
}


def scene_mask_arrays(size=8):
    """A grey scene and a mask whose LEFT half is product (red > 0)."""
    scene = Image.new("RGB", (size, size), (120, 120, 120))
    mask = Image.new("RGB", (size, size), (0, 0, 0))
    mask.paste((255, 0, 0), (0, 0, size // 2, size))
    return scene, mask


# ── worker + staff request helpers ──────────────────────────────────────────

def worker_headers(name: str = WORKER, token: str = WORKER_TOKEN) -> dict:
    return {"Authorization": f"Bearer {token}", "X-Planner3d-Worker": name}


def login(client, email: str, password: str = PW, slug: str | None = None) -> dict:
    body = {"email": email, "password": password}
    if slug:
        body["tenantSlug"] = slug
    res = client.post("/auth/login", json=body)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def err_code(res) -> str | None:
    """The error code wherever the app's error envelope puts it."""
    body = res.json()
    if not isinstance(body, dict):
        return None
    if "code" in body:
        return body["code"]
    for key in ("detail", "error"):
        inner = body.get(key)
        if isinstance(inner, dict) and "code" in inner:
            return inner["code"]
    return None


def submit_model(client, headers, photos=None, data=None):
    photos = photos if photos is not None else [("photo.png", png_bytes(), "image/png")]
    files = [("photos", (n, b, m)) for n, b, m in photos]
    return client.post("/planner3d/jobs/models", files=files, data=data or DIMS, headers=headers)


def submit_render(client, headers, *, scene=None, mask=None, depth=None, prompt="a sunny room", seed=None):
    arr_scene, arr_mask = scene_mask_arrays()
    files = {
        "scene": ("scene.png", scene or array_png(arr_scene), "image/png"),
        "mask": ("mask.png", mask or array_png(arr_mask), "image/png"),
        "depth": ("depth.png", depth or array_png(arr_scene), "image/png"),
    }
    data = {"prompt": prompt}
    if seed is not None:
        data["seed"] = str(seed)
    return client.post("/planner3d/jobs/renders", files=files, data=data, headers=headers)


def claim(client, kinds=("model", "render", "convert"), name: str = WORKER):
    return client.post("/planner3d/worker/claim", json={"kinds": list(kinds)}, headers=worker_headers(name))


def put_output(client, job_id, name, data: bytes, role: str | None = None, worker: str = WORKER):
    return client.put(
        f"/planner3d/worker/jobs/{job_id}/outputs/{name}",
        params={"role": role or name},
        content=data,
        headers=worker_headers(worker),
    )


def finish(client, job_id, status="succeeded", worker: str = WORKER, **extra):
    body = {"status": status, "gpuSeconds": 12.5, "peakRssMb": 4096, **extra}
    return client.post(f"/planner3d/worker/jobs/{job_id}/finish", json=body, headers=worker_headers(worker))


def finished_model_job(client, staff, n_candidates: int = 3) -> tuple[str, dict]:
    """Submit a model job, run it through the worker, return (job id, {name: bytes})."""
    job_id = submit_model(client, staff).json()["id"]
    got = claim(client, ["model"])
    assert got.status_code == 200 and got.json()["jobId"] == job_id, got.text
    cands = {}
    for i in range(1, n_candidates + 1):
        name = f"candidate-{i}.glb"
        cands[name] = glb_bytes(f"cand{i}")
        res = put_output(client, job_id, name, cands[name], role="candidate")
        assert res.status_code == 201, res.text
    res = finish(client, job_id)
    assert res.status_code == 200 and res.json()["status"] == "succeeded", res.text
    return job_id, cands


# ── DB seeding ──────────────────────────────────────────────────────────────

def make_user_with(db, tenant_id: str, email: str, keys: list[str], role_name: str) -> User:
    role = Role(tenant_id=tenant_id, name=role_name, description="p3 test role", is_system=False)
    role.permissions = db.query(Permission).filter(Permission.key.in_(keys)).all() if keys else []
    db.add(role)
    db.flush()
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password(PW),
        name=role_name,
        status=UserStatus.ACTIVE.value,
        email_verified_at=datetime.now(timezone.utc),
    )
    user.roles = [role]
    db.add(user)
    db.flush()
    return user


def age_job(session_factory, job_id: str, *, heartbeat_minutes_ago: int | None = None,
            attempts: int | None = None, created_at: datetime | None = None):
    from modules.planner3d.models import P3Job

    db = session_factory()
    try:
        job = db.get(P3Job, job_id)
        if heartbeat_minutes_ago is not None:
            ts = datetime.now(timezone.utc) - timedelta(minutes=heartbeat_minutes_ago)
            job.heartbeat_at = ts
            job.claimed_at = ts
        if attempts is not None:
            job.attempts = attempts
        if created_at is not None:
            job.created_at = created_at
        db.commit()
    finally:
        db.close()


def file_count(session_factory, job_id: str | None = None) -> int:
    from modules.planner3d.models import P3JobFile

    db = session_factory()
    try:
        q = db.query(P3JobFile)
        if job_id:
            q = q.filter(P3JobFile.job_id == job_id)
        return q.count()
    finally:
        db.close()


def job_count(session_factory) -> int:
    from modules.planner3d.models import P3Job

    db = session_factory()
    try:
        return db.query(P3Job).count()
    finally:
        db.close()


# ── fixtures (import into a test module with `# noqa: F401`) ─────────────────
import pytest  # noqa: E402

from app.config import settings  # noqa: E402
from app.models import DEFAULT_TENANT_ID  # noqa: E402
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD  # noqa: E402
from tests.meetings_helpers import make_admin_user, make_tenant  # noqa: E402


@pytest.fixture
def worker_token(monkeypatch):
    """SS holds only the sha256 of the worker token (AC-S3-03)."""
    monkeypatch.setattr(settings, "planner3d_worker_token_sha256", sha(WORKER_TOKEN.encode()), raising=False)
    return WORKER_TOKEN


@pytest.fixture
def p3(session_factory, monkeypatch, worker_token):
    """planner3d installed for the default tenant and for tenant B, plus a
    view-only and a no-permission user in the default tenant."""
    import app.database as database
    from app.services.app_store_service import AppStoreService

    monkeypatch.setattr(database, "SessionLocal", session_factory)
    db = session_factory()
    try:
        AppStoreService(db).install(DEFAULT_TENANT_ID, "planner3d")
        make_tenant(db, TENANT_B, "Planner B")
        make_admin_user(db, TENANT_B, B_EMAIL)
        AppStoreService(db).install(TENANT_B, "planner3d")
        make_user_with(db, DEFAULT_TENANT_ID, VIEW_EMAIL, ["planner3d.jobs.read"], "P3 Viewer")
        make_user_with(db, DEFAULT_TENANT_ID, NONE_EMAIL, [], "P3 Nothing")
        db.commit()
    finally:
        db.close()
    return session_factory


@pytest.fixture
def staff(client, p3):
    return login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)


@pytest.fixture
def staff_b(client, p3):
    return login(client, B_EMAIL, PW, slug=TENANT_B_SLUG)
