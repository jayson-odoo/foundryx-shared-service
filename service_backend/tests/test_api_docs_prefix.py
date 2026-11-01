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


def test_docs_behind_prefix_point_at_prefixed_spec(client, monkeypatch):
    monkeypatch.setattr(main, "_DOCS_PREFIX", "/be")
    for path in ("/docs", "/redoc"):
        res = client.get(path)
        assert res.status_code == 200
        assert "/be/openapi.json" in res.text
    # The spec itself is still served at the (stripped) root path.
    assert client.get("/openapi.json").status_code == 200
