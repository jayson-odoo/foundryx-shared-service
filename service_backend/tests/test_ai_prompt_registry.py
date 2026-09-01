"""AI prompt registry tests (Meetings S4 P2a, AC-S4-9/AC-S4-10).

Covers: append-only version numbering, label repoint + immediate cache bust,
hardcoded fallback on an empty registry, immutability (no update/delete
surface for a version anywhere), route gating (platform admin 200 / tenant
user 403 / unauthenticated 401), and the migration seed's template staying
in sync with the runtime fallback.
"""
import re
from pathlib import Path

import pytest

from app.services import ai_prompt_registry as registry
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    res = client.post("/auth/login", json=payload)
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _platform_headers(client):
    return _login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform")


def _tenant_headers(client):
    return _login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD)


# --------------------------------------------------------------------------- #
# Service-level: resolver + registry semantics                                 #
# --------------------------------------------------------------------------- #


def test_get_prompt_falls_back_when_registry_is_empty(session_factory):
    """AC-S4-9 - an empty registry never blocks a caller; it serves the
    hardcoded fallback with version=None."""
    db = session_factory()
    try:
        rendered = registry.get_prompt(db, "meetings_minutes")
        assert rendered.version is None
        assert rendered.text == registry._meetings_minutes_fallback()
        assert "{{transcript}}" in rendered.text
    finally:
        db.close()


def test_get_prompt_unknown_name_falls_back_to_empty_text(session_factory):
    db = session_factory()
    try:
        rendered = registry.get_prompt(db, "not_a_real_prompt")
        assert rendered.version is None
        assert rendered.text == ""
    finally:
        db.close()


def test_save_version_is_append_only_and_increments_per_name(session_factory):
    db = session_factory()
    try:
        v1 = registry.save_version(
            db, "meetings_minutes", template="v1 {{title}}", commit_message="first", user_id=None
        )
        v2 = registry.save_version(
            db, "meetings_minutes", template="v2 {{title}}", commit_message="second", user_id=None
        )
        assert v1["version"] == 1
        assert v2["version"] == 2
        assert v1["id"] != v2["id"]

        detail = registry.get_prompt_detail(db, "meetings_minutes")
        # Newest first; the prior version's content is UNCHANGED by the append.
        assert [v["version"] for v in detail["versions"]] == [2, 1]
        prior = next(v for v in detail["versions"] if v["version"] == 1)
        assert prior["template"] == "v1 {{title}}"
    finally:
        db.close()


def test_save_version_unknown_token_rejected(session_factory):
    db = session_factory()
    try:
        with pytest.raises(registry.PromptValidationError) as exc:
            registry.save_version(
                db,
                "meetings_minutes",
                template="{{title}} {{bogus_token}}",
                commit_message="bad",
                user_id=None,
            )
        assert "bogus_token" in exc.value.unknown_tokens
    finally:
        db.close()


def test_save_version_blank_commit_message_rejected(session_factory):
    db = session_factory()
    try:
        with pytest.raises(registry.PromptValidationError):
            registry.save_version(
                db, "meetings_minutes", template="{{title}}", commit_message="   ", user_id=None
            )
    finally:
        db.close()


def test_save_version_unknown_prompt_name_raises_not_found(session_factory):
    db = session_factory()
    try:
        with pytest.raises(registry.PromptNotFound):
            registry.save_version(
                db, "not_a_real_prompt", template="x", commit_message="c", user_id=None
            )
    finally:
        db.close()


def test_set_label_repoints_and_busts_cache_immediately(session_factory):
    """AC-S4-9 - publish takes effect on the very next `get_prompt`, no TTL wait."""
    db = session_factory()
    try:
        v1 = registry.save_version(
            db, "meetings_minutes", template="v1 body", commit_message="v1", user_id=None
        )
        registry.set_label(db, "meetings_minutes", label="production", version_id=v1["id"], user_id=None)
        resolved = registry.get_prompt(db, "meetings_minutes")
        assert resolved.text == "v1 body"
        assert resolved.version == 1

        v2 = registry.save_version(
            db, "meetings_minutes", template="v2 body", commit_message="v2", user_id=None
        )
        # Without a bust this would still read the TTL-cached v1 text.
        registry.set_label(db, "meetings_minutes", label="production", version_id=v2["id"], user_id=None)
        resolved_again = registry.get_prompt(db, "meetings_minutes")
        assert resolved_again.text == "v2 body"
        assert resolved_again.version == 2
    finally:
        db.close()


def test_set_label_unknown_label_raises(session_factory):
    db = session_factory()
    try:
        v1 = registry.save_version(
            db, "meetings_minutes", template="v1", commit_message="v1", user_id=None
        )
        with pytest.raises(registry.InvalidLabel):
            registry.set_label(
                db, "meetings_minutes", label="canary", version_id=v1["id"], user_id=None
            )
    finally:
        db.close()


def test_set_label_missing_version_raises(session_factory):
    db = session_factory()
    try:
        with pytest.raises(registry.PromptVersionNotFound):
            registry.set_label(
                db, "meetings_minutes", label="production", version_id="does-not-exist", user_id=None
            )
    finally:
        db.close()


def test_list_prompts_and_detail_shape(session_factory):
    db = session_factory()
    try:
        summaries = registry.list_prompts(db)
        assert [s["name"] for s in summaries] == ["meetings_minutes"]
        assert summaries[0]["production_version"] is None
        assert summaries[0]["latest_version"] is None

        v1 = registry.save_version(
            db, "meetings_minutes", template="v1", commit_message="v1", user_id=None
        )
        registry.set_label(db, "meetings_minutes", label="production", version_id=v1["id"], user_id=None)

        summaries = registry.list_prompts(db)
        assert summaries[0]["production_version"] == 1
        assert summaries[0]["latest_version"] == 1

        detail = registry.get_prompt_detail(db, "meetings_minutes")
        assert detail["variables"] == ["title", "participants", "language", "transcript"]
        assert detail["labels"] == {"production": 1, "staging": None}
        assert detail["versions"][0]["labels"] == ["production"]
    finally:
        db.close()


def test_registry_module_exposes_no_update_or_delete_of_a_version():
    """AC-S4-9 immutability - no update/delete surface anywhere in the module."""
    forbidden = {"update_version", "delete_version", "edit_version", "remove_version"}
    exposed = {name for name in dir(registry) if not name.startswith("_")}
    assert not (forbidden & exposed)


# --------------------------------------------------------------------------- #
# Route-level: gating + the four FE-facing endpoints                           #
# --------------------------------------------------------------------------- #


def test_platform_admin_full_crud_flow(client):
    headers = _platform_headers(client)

    listed = client.get("/ai-prompts", headers=headers)
    assert listed.status_code == 200, listed.text
    assert [p["name"] for p in listed.json()] == ["meetings_minutes"]

    detail = client.get("/ai-prompts/meetings_minutes", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["variables"] == ["title", "participants", "language", "transcript"]
    assert body["versions"] == []

    created = client.post(
        "/ai-prompts/meetings_minutes/versions",
        json={"template": "Hi {{title}}", "commitMessage": "tweak"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    version = created.json()
    assert version["version"] == 1
    assert version["labels"] == []

    published = client.post(
        "/ai-prompts/meetings_minutes/publish",
        json={"versionId": version["id"], "label": "production"},
        headers=headers,
    )
    assert published.status_code == 200, published.text
    pub_body = published.json()
    assert pub_body["labels"]["production"] == 1
    assert pub_body["versions"][0]["labels"] == ["production"]

    # List reflects the publish.
    listed_after = client.get("/ai-prompts", headers=headers).json()
    assert listed_after[0]["productionVersion"] == 1


def test_tenant_admin_forbidden(client):
    headers = _tenant_headers(client)
    res = client.get("/ai-prompts", headers=headers)
    assert res.status_code == 403, res.text


def test_unauthenticated_rejected(client):
    assert client.get("/ai-prompts").status_code == 401
    assert client.get("/ai-prompts/meetings_minutes").status_code == 401
    assert (
        client.post(
            "/ai-prompts/meetings_minutes/versions",
            json={"template": "x", "commitMessage": "c"},
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/ai-prompts/meetings_minutes/publish", json={"versionId": "x", "label": "production"}
        ).status_code
        == 401
    )


def test_unknown_prompt_name_404(client):
    headers = _platform_headers(client)
    assert client.get("/ai-prompts/not_a_real_prompt", headers=headers).status_code == 404


def test_create_version_unknown_token_returns_422(client):
    headers = _platform_headers(client)
    res = client.post(
        "/ai-prompts/meetings_minutes/versions",
        json={"template": "{{bogus_token}}", "commitMessage": "bad"},
        headers=headers,
    )
    assert res.status_code == 422, res.text


def test_publish_unknown_label_returns_422(client):
    headers = _platform_headers(client)
    created = client.post(
        "/ai-prompts/meetings_minutes/versions",
        json={"template": "v1", "commitMessage": "v1"},
        headers=headers,
    ).json()
    res = client.post(
        "/ai-prompts/meetings_minutes/publish",
        json={"versionId": created["id"], "label": "canary"},
        headers=headers,
    )
    assert res.status_code == 422, res.text


def test_no_route_updates_or_deletes_a_version(client):
    """AC-S4-9 - the router exposes GET (list/detail), POST (create/publish)
    only; no PUT/PATCH/DELETE surface exists for a version anywhere."""
    headers = _platform_headers(client)
    created = client.post(
        "/ai-prompts/meetings_minutes/versions",
        json={"template": "v1", "commitMessage": "v1"},
        headers=headers,
    ).json()
    for verb in ("put", "patch", "delete"):
        res = getattr(client, verb)(
            f"/ai-prompts/meetings_minutes/versions/{created['id']}", headers=headers
        )
        assert res.status_code in (404, 405), (verb, res.status_code)


# --------------------------------------------------------------------------- #
# Migration seed <-> runtime fallback drift guard                              #
# --------------------------------------------------------------------------- #


def test_migration_seed_template_matches_runtime_fallback():
    """The seed migration copies the fallback verbatim as v1 (module docstring
    promise) - a regression guard against the two drifting apart."""
    migration_path = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions" / "ai_prompt_s4_registry.py"
    )
    text = migration_path.read_text()
    match = re.search(r'_MEETINGS_MINUTES_V1 = \((.*?)\n\)\n', text, re.S)
    assert match, "could not locate _MEETINGS_MINUTES_V1 in the migration"
    # Wrap back in parens - the regex captured only the inner concatenated
    # string literals, which need the enclosing parens to eval as a single
    # expression across multiple physical lines.
    seeded_template = eval("(" + match.group(1) + ")")  # noqa: S307 - trusted repo file, string literals only
    assert seeded_template == registry._meetings_minutes_fallback()


def test_migration_revision_id_fits_alembic_version_column():
    migration_path = (
        Path(__file__).resolve().parent.parent / "alembic" / "versions" / "ai_prompt_s4_registry.py"
    )
    text = migration_path.read_text()
    match = re.search(r"""^revision(?:\s*:\s*str)?\s*=\s*['"]([^'"]+)['"]""", text, re.M)
    assert match
    assert len(match.group(1)) <= 32
