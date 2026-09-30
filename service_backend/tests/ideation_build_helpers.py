"""Shared helpers for the BR "Send to build" red tests (lane BR-TO-CREW).

Not a test module (no ``test_`` prefix). Reuses the fixtures/helpers of
``tests/test_ideation_br.py`` (import, never refactor) and adds: a fake GitHub
``httpx.MockTransport`` handler that RECORDS every request (so tests assert the
call shape and count outside the service's own error handling), a GitHub
connection seeder, product/BR seeders and direct-row seeders for the write-back
tests (which must not depend on the Send endpoint).
"""
from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Dict, List, Optional

import httpx

from app.models import DEFAULT_TENANT_ID
from app.models.connection import Connection
from app.secrets import encrypt_secret
from tests.test_ideation_br import (  # noqa: F401  (re-exported fixtures/helpers)
    _FULL_ANSWERS,
    _auth,
    _idea,
    _make_user,
    _product,
    ideation_client,
)

# Send readiness needs EVERY input field of the stamped template non-empty
# (required or not), so the "sendable" fixture fills all six seeded fields.
ALL_ANSWERS = {
    **_FULL_ANSWERS,
    "stakeholders": "Customer support.",
    "scope": "Order export only.",
    "constraints": "Ship this quarter.",
}
REPO = "acme-org/sorento-crm"
GITHUB_TOKEN = "ghp_test"
OTHER_TENANT_ID = "tenant-x-build"


class FakeGitHub:
    """A recording ``httpx.MockTransport`` handler for api.github.com.

    Knobs: ``label_exists`` (else GET label 404 then POST creates it),
    ``issue_status`` (201 = success, else that status with an error body),
    ``search_items`` (the crash-recovery search result),
    ``connect_error`` (raise httpx.ConnectError on every request).
    """

    def __init__(
        self,
        *,
        label_exists: bool = False,
        issue_status: int = 201,
        issue_number: int = 4242,
        search_items: Optional[List[Dict[str, Any]]] = None,
        connect_error: bool = False,
        repo_private: Optional[bool] = True,
        issue_timeout: bool = False,
        label_lookup_status: Optional[int] = None,
        label_create_status: int = 201,
    ) -> None:
        # R3: ``issue_timeout`` = a transport timeout ONLY on the issue create;
        # ``label_lookup_status`` / ``label_create_status`` fail the label step.
        self.issue_timeout = issue_timeout
        self.label_lookup_status = label_lookup_status
        self.label_create_status = label_create_status
        # ``repo_private`` answers ``GET /repos/{r}`` (SEC F6 visibility check).
        self.repo_private = repo_private
        self.label_exists = label_exists
        self.issue_status = issue_status
        self.issue_number = issue_number
        self.search_items = search_items or []
        self.connect_error = connect_error
        self.calls: List[httpx.Request] = []
        self.unexpected: List[str] = []
        self.label_posts: List[dict] = []
        self.issue_posts: List[dict] = []
        self.comment_posts: List[dict] = []
        self.auth_headers: List[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def paths(self, method: str) -> List[str]:
        return [
            c.url.path for c in self.calls if c.method == method
        ]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if self.connect_error:
            raise httpx.ConnectError("boom", request=request)
        self.auth_headers.append(request.headers.get("authorization", ""))
        path, method = request.url.path, request.method
        repo_prefix = f"/repos/{REPO}"
        if method == "GET" and path == repo_prefix:
            return httpx.Response(
                200, json={"full_name": REPO, "private": self.repo_private}
            )
        if method == "GET" and path == f"{repo_prefix}/labels/crew-intake":
            if self.label_lookup_status is not None:
                return httpx.Response(self.label_lookup_status, json={"message": "x"})
            if self.label_exists:
                return httpx.Response(200, json={"name": "crew-intake"})
            return httpx.Response(404, json={"message": "Not Found"})
        if method == "POST" and path == f"{repo_prefix}/labels":
            payload = json.loads(request.content)
            self.label_posts.append(payload)
            if self.label_create_status != 201:
                return httpx.Response(self.label_create_status, json={"message": "x"})
            self.label_exists = True
            return httpx.Response(201, json={"name": payload.get("name")})
        if method == "POST" and path == f"{repo_prefix}/issues":
            payload = json.loads(request.content)
            self.issue_posts.append(payload)
            if self.issue_timeout:
                raise httpx.ReadTimeout("timed out", request=request)
            if self.issue_status != 201:
                return httpx.Response(
                    self.issue_status, json={"message": "nope"}
                )
            n = self.issue_number
            return httpx.Response(
                201,
                json={
                    "number": n,
                    "html_url": f"https://github.com/{REPO}/issues/{n}",
                    "node_id": f"I_node_{n}",
                },
            )
        if method == "POST" and path.startswith(f"{repo_prefix}/issues/") and path.endswith(
            "/comments"
        ):
            self.comment_posts.append(json.loads(request.content))
            return httpx.Response(201, json={"id": 1})
        if method == "GET" and path == "/search/issues":
            return httpx.Response(
                200,
                json={
                    "total_count": len(self.search_items),
                    "items": self.search_items,
                },
            )
        self.unexpected.append(f"{method} {path}")
        return httpx.Response(599, json={"message": "unexpected"})


def seed_github_connection(
    factory, *, tenant_id: str = DEFAULT_TENANT_ID, active: bool = True
) -> str:
    db = factory()
    try:
        conn = Connection(
            tenant_id=tenant_id,
            provider="github",
            type="scm",
            name="GitHub",
            config_json={},
            credentials_json=encrypt_secret({"token": GITHUB_TOKEN}),
            status="ACTIVE" if active else "ERROR",
            is_active=active,
        )
        db.add(conn)
        db.commit()
        return conn.id
    finally:
        db.close()


def set_build_repo(factory, product_id: str, repo: Optional[str] = REPO) -> None:
    """Direct row write (S2/S3 tests must not depend on the delivery PUT)."""
    from modules.ideation.models import ProductDelivery

    db = factory()
    try:
        row = (
            db.query(ProductDelivery)
            .filter(ProductDelivery.product_id == product_id)
            .first()
        )
        if row is None:
            row = ProductDelivery(tenant_id=DEFAULT_TENANT_ID, product_id=product_id)
            db.add(row)
        row.build_repo = repo
        db.commit()
    finally:
        db.close()


def make_br(client, h, product_id: str, *, title="Order export", answers=None) -> str:
    res = client.post(
        "/ideation/business-requirements",
        headers=h,
        json={
            "productId": product_id,
            "title": title,
            "answers": ALL_ANSWERS if answers is None else answers,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


def sendable_setup(client, *, repo: str = REPO, title: str = "Order export") -> Dict[str, Any]:
    """Admin auth + product with a build repo + ACTIVE github connection + a BR
    whose answers fill EVERY required field of the seeded template."""
    h = _auth(client)
    pid = _product(client, h)
    set_build_repo(client._factory, pid, repo)
    seed_github_connection(client._factory)
    br_id = make_br(client, h, pid, title=title)
    return {"h": h, "pid": pid, "br_id": br_id}


def br_status_key(client, h, br_id: str) -> str:
    res = client.get(f"/ideation/business-requirements/{br_id}", headers=h)
    assert res.status_code == 200, res.text
    return res.json()["status"]


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode("utf-8")).hexdigest()


def insert_key_row(factory, tenant_id: str, *, revoked: bool = False) -> Dict[str, str]:
    """Direct ``br_build_keys`` row for a tenant (sha256 + 8-char prefix after
    the ``fxb_live_`` scheme, exactly the documented storage scheme)."""
    from datetime import datetime, timezone

    from modules.ideation.models import BrBuildKey

    plaintext = "fxb_live_" + secrets.token_urlsafe(32)[:32]
    db = factory()
    try:
        row = BrBuildKey(
            tenant_id=tenant_id,
            name="direct",
            key_prefix=plaintext[9:17],
            key_hash=_hash(plaintext),
            revoked_at=datetime.now(timezone.utc) if revoked else None,
        )
        db.add(row)
        db.commit()
        return {"id": row.id, "plaintext": plaintext}
    finally:
        db.close()


def ensure_other_tenant(factory) -> str:
    from app.models.tenant import Tenant

    db = factory()
    try:
        existing = db.query(Tenant).filter(Tenant.id == OTHER_TENANT_ID).first()
        if existing is not None:
            return OTHER_TENANT_ID
        default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
        db.add(
            Tenant(
                id=OTHER_TENANT_ID,
                name="Other Build Co",
                slug="other-build-co",
                status_id=default_tenant.status_id,
            )
        )
        db.flush()
        # Ideation is ACTIVE for the other tenant too (a key of a tenant without
        # the module is refused 403 service_not_enabled, SEC F1) so the
        # cross-tenant tests keep exercising the 404-not-in-tenant path.
        from app.models.module import Module, TenantModule

        module = db.query(Module).filter(Module.name == "ideation").first()
        mine = (
            db.query(TenantModule)
            .filter(TenantModule.tenant_id == DEFAULT_TENANT_ID, TenantModule.module_id == module.id)
            .first()
        )
        db.add(
            TenantModule(
                tenant_id=OTHER_TENANT_ID,
                module_id=module.id,
                status="ACTIVE",
                installed_version=mine.installed_version,
            )
        )
        db.commit()
        return OTHER_TENANT_ID
    finally:
        db.close()


def insert_sent_br(
    factory,
    *,
    tenant_id: str = DEFAULT_TENANT_ID,
    product_id: str,
    status_key: str = "sent_to_build",
    build_state: str = "sent",
    with_build: bool = True,
) -> str:
    """A BR that already went through Send: BR row at ``sent_to_build`` (or the
    given status), a ``br_builds`` row and the ``sent`` event. Built by direct
    rows so the write-back tests are independent of the Send endpoint."""
    from datetime import datetime, timezone

    from modules.ideation.models import BrBuild, BrBuildEvent, BusinessRequirement
    from modules.ideation.services.statuses import BR_STATUS_IDS

    db = factory()
    try:
        br = BusinessRequirement(
            tenant_id=tenant_id,
            product_id=product_id,
            status_id=BR_STATUS_IDS[status_key],
            template_key="business_requirement",
            template_version=1,
            title="Sent BR",
            answers_json=dict(_FULL_ANSWERS),
        )
        db.add(br)
        db.flush()
        if with_build:
            db.add(
                BrBuild(
                    tenant_id=tenant_id,
                    business_requirement_id=br.id,
                    repo=REPO,
                    state=build_state,
                    issue_number=7,
                    issue_url=f"https://github.com/{REPO}/issues/7",
                    issue_node_id="I_node_7",
                    sent_at=datetime.now(timezone.utc),
                )
            )
            db.add(
                BrBuildEvent(
                    tenant_id=tenant_id,
                    business_requirement_id=br.id,
                    kind="sent",
                    stage="Sent",
                    message="Sent to build",
                    status_moved=True,
                )
            )
        db.commit()
        return br.id
    finally:
        db.close()


def mint_key_via_api(client, h, name: str = "crew") -> Dict[str, Any]:
    res = client.post("/ideation/build-keys", headers=h, json={"name": name})
    assert res.status_code == 201, res.text
    return res.json()


def bearer(plaintext: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {plaintext}"}


def marker_tail(br_id: str, product_id: str) -> str:
    """The exact two machine-marker lines a genuine crew-intake issue body ends with."""
    return f"<!-- br-id: {br_id} -->\n<!-- br-product: {product_id} -->\n"


def search_item(number: int, body: str, *, labels=("crew-intake",)) -> Dict[str, Any]:
    """A ``/search/issues`` item carrying body + labels (SEC F2 adoption checks)."""
    return {
        "number": number,
        "html_url": f"https://github.com/{REPO}/issues/{number}",
        "node_id": f"I_{number}",
        "body": body,
        "labels": [{"name": n} for n in labels],
    }


def insert_creating_row(factory, br_id: str, *, age_seconds: int) -> None:
    """A ``br_builds`` row in state ``creating`` whose ``updated_at`` is
    ``age_seconds`` old (fresh = another request in flight)."""
    from datetime import datetime, timedelta, timezone

    from modules.ideation.models import BrBuild

    stamp = datetime.now(timezone.utc) - timedelta(seconds=age_seconds)
    db = factory()
    try:
        db.add(
            BrBuild(
                tenant_id=DEFAULT_TENANT_ID,
                business_requirement_id=br_id,
                repo=REPO,
                state="creating",
                created_at=stamp,
                updated_at=stamp,
            )
        )
        db.commit()
    finally:
        db.close()
