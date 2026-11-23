"""Swagger/ReDoc behind the Caddy-stripped backend prefix (`/be`).

Caddy strips the prefix before proxying, so the app routes on root paths, but
the browser must fetch the spec at <prefix>/openapi.json.
"""
import app.main as main


def test_docs_without_prefix_point_at_root_spec(client, monkeypatch):
    monkeypatch.setattr(main, "_DOCS_PREFIX", "")
    for path in ("/docs", "/redoc"):
        res = client.get(path)
        assert res.status_code == 200
        assert "'/openapi.json'" in res.text or '"/openapi.json"' in res.text
        assert "/be/openapi.json" not in res.text


def test_docs_behind_prefix_point_at_prefixed_spec(client, monkeypatch):
    monkeypatch.setattr(main, "_DOCS_PREFIX", "/be")
    for path in ("/docs", "/redoc"):
        res = client.get(path)
        assert res.status_code == 200
        assert "/be/openapi.json" in res.text
    # The spec itself is still served at the (stripped) root path.
    assert client.get("/openapi.json").status_code == 200


def test_prefix_and_servers_derive_from_public_base_url():
    """`_DOCS_PREFIX` / `servers` are fixed at import, so check in a fresh process."""
    import json
    import os
    import subprocess
    import sys

    code = (
        "import json, app.main as m;"
        "print(json.dumps([m._DOCS_PREFIX, m.app.servers]))"
    )

    def run(base_url):
        env = {**os.environ, "PUBLIC_BASE_URL": base_url}
        out = subprocess.run(
            [sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True
        )
        return json.loads(out.stdout.strip().splitlines()[-1])

    assert run("https://app.example.com/be") == ["/be", [{"url": "/be"}]]
    assert run("https://app.example.com/be/") == ["/be", [{"url": "/be"}]]
    assert run("http://localhost:8001") == ["", []]
