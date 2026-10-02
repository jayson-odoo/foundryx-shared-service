"""SS-PUBLIC-LINK-BASE - per-tenant ``public_link_base_url`` for public idea links.

Public idea tracking links must be mintable on a tenant-chosen origin (the Sorento
CRM customer portal) instead of the shared-service domain. The tenant setting is
nullable: NULL keeps today's behaviour (``{frontend_url}/public/ideas/{token}``), so
nothing changes for a tenant until it is filled in. Links already sent stay valid
because the old route is untouched - only NEW links pick up the setting.

Test-first: written before the implementation exists.
"""
import pytest
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID
from app.models.tenant_settings import TenantSettings
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD

PRODUCT_ID = "prod-link-base"
IDEA_ID = "idea-123"
TOKEN = "tok-abc"


@pytest.fixture
def db(ideation_session_factory):
    s = ideation_session_factory()
    try:
        yield s
    finally:
        s.close()


@pytest.fixture
def ideation_client(ideation_session_factory):
    def override_get_db():
        s = ideation_session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _auth(client) -> dict:
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _idea(tenant_id=DEFAULT_TENANT_ID, token=TOKEN):
    from modules.ideation.models import Idea

    return Idea(
        id=IDEA_ID, tenant_id=tenant_id, product_id=PRODUCT_ID, problem="x", status_token=token
    )


def _set_link_base(db, base, tenant_id=DEFAULT_TENANT_ID):
    row = db.get(TenantSettings, tenant_id)
    if row is None:
        row = TenantSettings(tenant_id=tenant_id)
        db.add(row)
    row.public_link_base_url = base
    db.commit()


def _ss_base() -> str:
    from app.config import settings

    return settings.frontend_url.rstrip("/")


# ── mint_idea_link ────────────────────────────────────────────────────────────


def test_null_setting_keeps_shared_service_link(db):
    """NULL = today's shared-service status page, unchanged."""
    from modules.ideation.services.sinks import mint_idea_link

    assert mint_idea_link(db, _idea()) == f"{_ss_base()}/public/ideas/{TOKEN}"


def test_no_status_token_is_none_even_with_tenant_base(db):
    from modules.ideation.services.sinks import mint_idea_link

    _set_link_base(db, "https://crm.sorento.my/portal/ideas/{token}")
    assert mint_idea_link(db, _idea(token=None)) is None


def test_tenant_base_as_origin_replaces_shared_service_domain(db):
    from modules.ideation.services.sinks import mint_idea_link

    _set_link_base(db, "https://crm.sorento.my/")
    assert mint_idea_link(db, _idea()) == f"https://crm.sorento.my/public/ideas/{TOKEN}"


def test_tenant_base_crm_portal_token_template(db):
    """The Sorento value (IDEATION-IN-CRM, sorento #1438): the CRM portal path
    carries the status token, substituted in place, nothing appended."""
    from modules.ideation.services.sinks import mint_idea_link

    _set_link_base(db, "https://crm.sorento.my/portal/ideas/{token}")
    assert mint_idea_link(db, _idea()) == f"https://crm.sorento.my/portal/ideas/{TOKEN}"


def test_tenant_base_idea_id_placeholder(db):
    from modules.ideation.services.sinks import mint_idea_link

    _set_link_base(db, "https://crm.sorento.my/t/{token}?idea={ideaId}")
    assert (
        mint_idea_link(db, _idea())
        == f"https://crm.sorento.my/t/{TOKEN}?idea={IDEA_ID}"
    )


def test_tenant_base_is_tenant_scoped(db):
    """Another tenant's setting never leaks into this tenant's links."""
    from modules.ideation.services.sinks import mint_idea_link

    _set_link_base(db, "https://crm.other.my/portal/ideas/{token}", tenant_id="other-tenant")
    assert mint_idea_link(db, _idea()) == f"{_ss_base()}/public/ideas/{TOKEN}"


# ── settings API (/settings/general) ─────────────────────────────────────────


def test_general_settings_default_link_base_is_null(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get("/settings/general", headers=h)
    assert res.status_code == 200, res.text
    assert res.json()["publicLinkBaseUrl"] is None


def test_general_settings_set_and_clear_link_base(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.put(
        "/settings/general", headers=h, json={"publicLinkBaseUrl": "https://crm.sorento.my/portal/"}
    )
    assert res.status_code == 200, res.text
    assert res.json()["publicLinkBaseUrl"] == "https://crm.sorento.my/portal"
    # Unrelated fields untouched by the patch.
    assert res.json()["defaultCurrency"]

    res = ideation_client.put("/settings/general", headers=h, json={"publicLinkBaseUrl": ""})
    assert res.status_code == 200, res.text
    assert res.json()["publicLinkBaseUrl"] is None

    res = ideation_client.put(
        "/settings/general", headers=h, json={"publicLinkBaseUrl": "https://a.my"}
    )
    res = ideation_client.put("/settings/general", headers=h, json={"publicLinkBaseUrl": None})
    assert res.json()["publicLinkBaseUrl"] is None


def test_general_settings_accepts_crm_portal_template(ideation_client):
    h = _auth(ideation_client)
    value = "https://crm.sorento.my/portal/ideas/{token}"
    res = ideation_client.put("/settings/general", headers=h, json={"publicLinkBaseUrl": value})
    assert res.status_code == 200, res.text
    assert res.json()["publicLinkBaseUrl"] == value


@pytest.mark.parametrize(
    "bad",
    [
        "crm.sorento.my",
        "ftp://crm.sorento.my",
        "javascript:alert(1)",
        "https://",
        "https://crm.sorento.my/#frag",
        "https://user:pw@crm.sorento.my",
        "https://crm.sorento.my/portal?src=wa",
    ],
)
def test_general_settings_rejects_bad_link_base(ideation_client, bad):
    h = _auth(ideation_client)
    res = ideation_client.put("/settings/general", headers=h, json={"publicLinkBaseUrl": bad})
    assert res.status_code == 422, res.text
