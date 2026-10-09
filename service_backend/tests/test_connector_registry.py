"""Connector product registry (plan sprint-4/19, AC-19-10 + AC-19-12 static guard)."""

import re
from pathlib import Path

import pytest

from tests.connector_support import make_env


@pytest.fixture(autouse=True)
def _reset_env():
    from modules.connector import registry

    yield
    registry.set_env_for_tests(None)


def test_load_products_builds_product_with_defaults():
    from modules.connector import registry

    got = registry.load_products(make_env())
    assert set(got) == {"acme", "beta"}
    p = got["acme"].product
    assert got["acme"].status != "misconfigured"
    assert p.key == "acme" and p.tenant_slug == "default" and p.connection_id == "conn-acme"
    assert p.consent_url == "https://acme.test/connect/claude"
    assert p.api_base_url == "https://acme.test"
    assert p.ss_to_product_secret == "acme-ss-to-product-secret"
    assert p.product_to_ss_secret == "acme-product-to-ss-secret"
    # defaults: display name = key, issuer = key, audiences = <key>-connector-consent / -api
    assert p.display_name == "acme" and p.issuer == "acme"
    assert p.consent_audience == "acme-connector-consent"
    assert p.call_audience == "acme-connector-api"


def test_optional_overrides_respected():
    from modules.connector import registry

    env = make_env({
        "CONNECTOR_ACME_DISPLAY_NAME": "Acme CRM",
        "CONNECTOR_ACME_ISSUER": "acme-iss",
        "CONNECTOR_ACME_CONSENT_AUDIENCE": "acme-consent-aud",
        "CONNECTOR_ACME_CALL_AUDIENCE": "acme-call-aud",
    })
    p = registry.load_products(env)["acme"].product
    assert (p.display_name, p.issuer, p.consent_audience, p.call_audience) == (
        "Acme CRM", "acme-iss", "acme-consent-aud", "acme-call-aud")


@pytest.mark.parametrize("missing", [
    "CONNECTOR_ACME_SS_TO_PRODUCT_SECRET", "CONNECTOR_ACME_PRODUCT_TO_SS_SECRET",
    "CONNECTOR_ACME_CONSENT_URL", "CONNECTOR_ACME_API_BASE_URL",
    "CONNECTOR_ACME_TENANT_SLUG", "CONNECTOR_ACME_CONNECTION_ID",
])
def test_missing_required_value_marks_misconfigured_and_hides(missing):
    from modules.connector import registry

    env = make_env()
    del env[missing]
    registry.set_env_for_tests(env)
    got = registry.load_products(env)
    assert got["acme"].status == "misconfigured"
    assert registry.get_product("acme") is None
    assert registry.get_product("beta") is not None  # siblings unaffected


def test_blank_value_counts_as_missing():
    from modules.connector import registry

    env = make_env({"CONNECTOR_ACME_PRODUCT_TO_SS_SECRET": "   "})
    registry.set_env_for_tests(env)
    assert registry.get_product("acme") is None


def test_unknown_product_is_none_and_empty_env_has_no_products():
    from modules.connector import registry

    registry.set_env_for_tests({})
    assert registry.get_product("acme") is None
    assert registry.load_products({}) == {}


@pytest.mark.parametrize("path", ["/mcp/acme", "/mcp/acme/oauth/authorize", "/mcp/acme/oauth/register",
                                  "/.well-known/oauth-protected-resource/mcp/acme",
                                  "/.well-known/oauth-authorization-server/mcp/acme"])
def test_misconfigured_product_answers_404_everywhere_without_leaking(connector_client, path):
    from modules.connector import registry

    env = make_env()
    del env["CONNECTOR_ACME_PRODUCT_TO_SS_SECRET"]
    registry.set_env_for_tests(env)
    for method in ("get", "post"):
        res = getattr(connector_client, method)(path)
        assert res.status_code == 404, (method, path, res.status_code)
        low = res.text.lower()
        assert "secret" not in low and "connector_acme" not in low and "misconfigured" not in low


def test_unknown_product_404(connector_client):
    assert connector_client.post("/mcp/nope", json={}).status_code == 404
    assert connector_client.get("/.well-known/oauth-protected-resource/mcp/nope").status_code == 404


# --- AC-19-12 static guard on the module migration ----------------------------

TABLES = ["oauth_clients", "pending_requests", "auth_codes", "tokens", "grants",
          "assertion_jti", "call_log", "grant_events", "manifest_cache"]


def test_migration_revision_ids_fit_alembic_and_cover_every_table():
    versions = Path(__file__).resolve().parents[1] / "modules" / "connector" / "alembic" / "versions"
    files = list(versions.glob("*.py"))
    assert files, "connector module needs an alembic migration"
    src = "\n".join(f.read_text() for f in files)
    for rev in re.findall(r"""^\s*(?:down_)?revision\s*(?::\s*[^=]+)?=\s*['"]([^'"]+)['"]""", src, re.M):
        assert len(rev) <= 32, rev
    for t in TABLES:
        assert f'"{t}"' in src or f"'{t}'" in src, t
    assert "app_connector" in src


def test_identical_directional_secrets_mark_product_misconfigured():
    from modules.connector import registry

    env = make_env({"CONNECTOR_ACME_PRODUCT_TO_SS_SECRET": "same-secret",
                    "CONNECTOR_ACME_SS_TO_PRODUCT_SECRET": "same-secret"})
    registry.set_env_for_tests(env)
    assert registry.load_products(env)["acme"].status == "misconfigured"
    assert registry.get_product("acme") is None
    assert registry.get_product("beta") is not None
