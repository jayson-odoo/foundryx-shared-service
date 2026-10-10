"""/health reports the running commit so a test copy can be matched to a PR head."""

from app.api.v1 import health


def test_health_reports_git_sha_from_env(monkeypatch):
    health._git_sha.cache_clear()
    monkeypatch.setenv("GIT_SHA", "abc123")
    try:
        assert health.health() == {"status": "ok", "git_sha": "abc123"}
    finally:
        health._git_sha.cache_clear()
