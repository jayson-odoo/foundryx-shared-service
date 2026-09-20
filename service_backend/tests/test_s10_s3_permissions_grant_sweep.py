"""Sprint-5/10 S3 - the DoD "new permission -> grant sweep" gate (AC-10-36).

``autocount.pull.read``/``autocount.pull.manage`` are new CSV rows (module
0.11.0). Mirrors ``test_omnichannel_broadcasts.py::test_grant_sweep_on_update``
byte for byte: an already-provisioned tenant's Admin role must gain the new
keys through ``AppStoreService.update()`` alone (the manifest version bump is
what makes that call fire - ``update()`` refuses once ``installed_version``
already matches), never a manual step.
"""
from __future__ import annotations

from typing import Dict

from app.models import DEFAULT_TENANT_ID


def _auth(client, email="demo@example.com", password="demo1234") -> Dict[str, str]:
    response = client.post("/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_pull_permissions_are_in_the_catalog(session_factory):
    from app.repositories.permission_repository import PermissionRepository

    # Read straight off the seeded catalog (module ``install()`` runs at
    # bootstrap) rather than re-syncing here.
    db = session_factory()
    try:
        keys = {p.key for p in PermissionRepository(db).list_all()}
    finally:
        db.close()
    assert "autocount.pull.read" in keys
    assert "autocount.pull.manage" in keys


def test_grant_sweep_delivers_the_new_pull_permissions_on_update(client, session_factory):
    from app.services.app_store_service import AppStoreService

    db = session_factory()
    state = AppStoreService(db)._installed_state(DEFAULT_TENANT_ID, "autocount")[1]
    state.installed_version = "0.10.0"
    db.commit()
    db.close()

    db2 = session_factory()
    module, new_state = AppStoreService(db2).update(DEFAULT_TENANT_ID, "autocount")
    assert module.version == "0.11.0"
    assert new_state.installed_version == "0.11.0"
    db2.close()

    headers = _auth(client)
    perms = set(client.get("/auth/me", headers=headers).json()["permissions"])
    assert {"autocount.pull.read", "autocount.pull.manage"} <= perms
