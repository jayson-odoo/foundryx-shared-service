"""BR Send to build - S1: GitHub provider (AC-STB-04, AC-STB-05) + GitHubClient
unit tests over ``httpx.MockTransport``. RED until
``modules/ideation/github_provider.py`` / ``github_client.py`` exist and the
provider is registered by the ideation bootstrap.
"""
import json

import httpx
import pytest

from tests.ideation_build_helpers import (  # noqa: F401
    GITHUB_TOKEN,
    REPO,
    FakeGitHub,
    _auth,
    ideation_client,
)

TOKEN = "ghp_supersecrettoken123"


def _provider(handler):
    from modules.ideation.github_provider import GitHubProvider

    return GitHubProvider(transport=httpx.MockTransport(handler))


# ── AC-STB-04 registry ────────────────────────────────────────────────────────


def test_ac_stb_04_provider_registered_in_core_registry(ideation_client):
    from app.integrations import get_provider

    provider = get_provider("github")
    assert provider is not None
    assert provider.provider == "github"
    assert provider.type == "scm"
    assert provider.test_target is None


def test_ac_stb_04_provider_has_one_secret_password_token_field():
    from modules.ideation.github_provider import GitHubProvider

    fields = GitHubProvider().fields()
    assert len(fields) == 1
    row = fields[0]
    assert row["key"] == "token"
    assert row["type"] == "password"
    assert row["secret"] is True
    assert row["required"] is True


def test_ac_stb_04_providers_endpoint_lists_github(ideation_client):
    h = _auth(ideation_client)
    res = ideation_client.get("/integrations/providers", headers=h)
    assert res.status_code == 200, res.text
    by_key = {p["provider"]: p for p in res.json()}
    assert "github" in by_key
    assert by_key["github"]["type"] == "scm"


# ── AC-STB-05 test() names the failing step ───────────────────────────────────


def test_ac_stb_05_200_is_ok_with_login_and_calls_get_user():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["method"], seen["url"] = request.method, str(request.url)
        seen["auth"] = request.headers.get("authorization")
        return httpx.Response(200, json={"login": "octocat"})

    result = _provider(handler).test({}, {"token": TOKEN})
    assert result.ok is True
    assert "octocat" in result.message
    assert seen["method"] == "GET"
    assert seen["url"] == "https://api.github.com/user"
    assert seen["auth"] == f"Bearer {TOKEN}"
    assert TOKEN not in result.message


@pytest.mark.parametrize("status", [401, 403])
def test_ac_stb_05_rejected_token(status):
    result = _provider(lambda r: httpx.Response(status, json={"message": "Bad credentials"})).test(
        {}, {"token": TOKEN}
    )
    assert result.ok is False
    assert result.message == "GitHub rejected the token"
    assert TOKEN not in result.message


def test_ac_stb_05_unreachable():
    def handler(request):
        raise httpx.ConnectError("dns failure for " + TOKEN, request=request)

    result = _provider(handler).test({}, {"token": TOKEN})
    assert result.ok is False
    assert "unreachable" in result.message
    assert TOKEN not in result.message
    assert "Traceback" not in result.message


def test_ac_stb_05_missing_token_is_a_plain_failure_without_a_call():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={"login": "x"})

    result = _provider(handler).test({}, {})
    assert result.ok is False
    assert calls == []


# ── GitHubClient unit tests ──────────────────────────────────────────────────


def _client(handler):
    from modules.ideation.github_client import GitHubClient

    return GitHubClient(TOKEN, transport=httpx.MockTransport(handler))


def test_ac_stb_09_client_ensure_label_creates_when_404():
    gh = FakeGitHub(label_exists=False)
    _client(gh).ensure_label(REPO, "crew-intake", "ff5a00")
    assert gh.paths("GET") == [f"/repos/{REPO}/labels/crew-intake"]
    assert gh.label_posts == [{"name": "crew-intake", "color": "ff5a00"}]
    assert gh.auth_headers[0] == f"Bearer {TOKEN}"
    assert gh.unexpected == []


def test_ac_stb_09_client_ensure_label_noop_when_present():
    gh = FakeGitHub(label_exists=True)
    _client(gh).ensure_label(REPO, "crew-intake", "ff5a00")
    assert gh.label_posts == []


def test_ac_stb_09_client_create_issue_returns_number_url_node():
    gh = FakeGitHub(issue_number=77)
    out = _client(gh).create_issue(REPO, "Title", "Body", ["crew-intake"])
    assert out == {
        "number": 77,
        "html_url": f"https://github.com/{REPO}/issues/77",
        "node_id": "I_node_77",
    }
    assert gh.issue_posts == [{"title": "Title", "body": "Body", "labels": ["crew-intake"]}]


def test_ac_stb_11_client_create_comment_posts_body():
    gh = FakeGitHub()
    _client(gh).create_comment(REPO, 5, "Re-sent to build")
    assert gh.comment_posts == [{"body": "Re-sent to build"}]
    assert gh.paths("POST") == [f"/repos/{REPO}/issues/5/comments"]


def test_ac_stb_11_client_search_by_marker_hit_and_miss():
    hit = FakeGitHub(
        search_items=[
            {"number": 9, "html_url": f"https://github.com/{REPO}/issues/9", "node_id": "I_9"}
        ]
    )
    found = _client(hit).search_issue_by_marker(REPO, "br-id: abc")
    assert found is not None and found["number"] == 9
    q = hit.calls[0].url.params["q"]
    assert '"br-id: abc" in:body' in q and f"repo:{REPO}" in q

    assert _client(FakeGitHub(search_items=[])).search_issue_by_marker(REPO, "br-id: zzz") is None


@pytest.mark.parametrize("status", [401, 404, 422])
def test_ac_stb_12_client_raises_github_error_with_step_and_status(status):
    from modules.ideation.github_client import GitHubError

    gh = FakeGitHub(issue_status=status)
    with pytest.raises(GitHubError) as exc:
        _client(gh).create_issue(REPO, "T", "B", ["crew-intake"])
    assert exc.value.status_code == status
    assert exc.value.step
    assert TOKEN not in str(exc.value)


def test_ac_stb_12_client_transport_error_is_not_swallowed_as_success():
    def handler(request):
        raise httpx.ConnectError("boom", request=request)

    from modules.ideation.github_client import GitHubError

    client = _client(handler)
    with pytest.raises((GitHubError, httpx.HTTPError)) as exc:
        client.create_issue(REPO, "T", "B", ["crew-intake"])
    assert TOKEN not in str(exc.value)


# ── SEC F3 / F7 ──────────────────────────────────────────────────────────────


def test_sec_f3_ac_stb_09_request_path_is_exactly_the_repo_issues_path():
    seen = []

    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(201, json={"number": 1, "html_url": "https://x/1", "node_id": "n"})

    from modules.ideation.github_client import GitHubClient

    GitHubClient(TOKEN, transport=httpx.MockTransport(handler)).create_issue(
        "owner/repo", "T", "B", ["crew-intake"]
    )
    assert seen == ["/repos/owner/repo/issues"]


def test_sec_f7_ac_stb_09_timeout_constant_is_10_seconds():
    from modules.ideation.github_client import GITHUB_TIMEOUT_SECONDS

    assert GITHUB_TIMEOUT_SECONDS == 10


def test_sec_f7_ac_stb_09_httpx_client_is_built_with_the_10s_timeout(monkeypatch):
    captured = []
    real_client = httpx.Client

    class Spy(real_client):
        def __init__(self, *args, **kwargs):
            captured.append(kwargs.get("timeout"))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "Client", Spy)
    from modules.ideation.github_client import GitHubClient

    GitHubClient(
        TOKEN,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(201, json={"number": 1, "html_url": "u", "node_id": "n"})
        ),
    ).create_issue("owner/repo", "T", "B", ["crew-intake"])
    assert captured, "no httpx.Client constructed"
    for t in captured:
        seconds = t.read if isinstance(t, httpx.Timeout) else t
        assert float(seconds) == 10.0
