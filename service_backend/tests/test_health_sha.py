"""/health reports the running commit so a test copy can be matched to a PR head."""

from app.api.v1 import health


def test_health_reports_git_sha_from_env(monkeypatch):
    health._git_sha.cache_clear()
    monkeypatch.setenv("GIT_SHA", "abc123")
    try:
        assert health.health() == {"status": "ok", "git_sha": "abc123"}
    finally:
        health._git_sha.cache_clear()


def test_production_hides_the_checkout_sha_unless_opted_in(monkeypatch):
    from app.config import settings

    health._git_sha.cache_clear()
    monkeypatch.delenv("GIT_SHA", raising=False)
    try:
        for env in ("production", "staging", "prod"):
            health._git_sha.cache_clear()
            monkeypatch.setattr(settings, "environment", env)
            assert health.health()["git_sha"] is None, env
    finally:
        health._git_sha.cache_clear()
