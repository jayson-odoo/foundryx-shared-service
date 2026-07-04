"""Connections Resource-list contract (plan sprint-2/06 D6/B4):
GET /integrations/connections grows page/sort/filter/search + /at + /export,
matching every other Resource entity (users is the reference)."""
import json

from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _create(client, headers, provider="smtp", name="Mail", **kwargs):
    payloads = {
        "smtp": {
            "provider": "smtp",
            "name": name,
            "config": {"host": "smtp.acme.com", "port": "587", "security": "starttls",
                       "fromEmail": "a@acme.com"},
            "credentials": {},
        },
        "s3": {
            "provider": "s3",
            "name": name,
            "config": {"bucket": "assets", "region": "auto"},
            "credentials": {"accessKeyId": "ak", "secretAccessKey": "sk"},
        },
    }
    res = client.post("/integrations/connections", json=payloads[provider], headers=headers)
    assert res.status_code == 201, res.text
    return res.json()


def test_list_is_paginated_resource_shape(client):
    h = _login(client)
    _create(client, h, "smtp", "Mail")
    _create(client, h, "s3", "Bucket")
    res = client.get("/integrations/connections?page=0&page_size=1", headers=h)
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 2
    assert body["page"] == 0
    assert len(body["data"]) == 1
    # Credentials never appear anywhere in the page.
    assert "sk" not in res.text


def test_list_search_matches_name_provider_and_error(client):
    h = _login(client)
    _create(client, h, "smtp", "Company mail")
    _create(client, h, "s3", "Bucket")
    res = client.get("/integrations/connections?search=company", headers=h)
    assert [c["name"] for c in res.json()["data"]] == ["Company mail"]
    res = client.get("/integrations/connections?search=s3", headers=h)
    assert [c["name"] for c in res.json()["data"]] == ["Bucket"]


def test_list_sort_and_filter(client):
    h = _login(client)
    _create(client, h, "smtp", "B Mail")
    _create(client, h, "s3", "A Bucket")
    res = client.get(
        "/integrations/connections?sort_by=name&sort_dir=asc", headers=h
    )
    assert [c["name"] for c in res.json()["data"]] == ["A Bucket", "B Mail"]

    flt = json.dumps(
        {"kind": "group", "combinator": "and",
         "rules": [{"kind": "condition", "field": "type", "operator": "eq", "value": "storage"}]}
    )
    res = client.get(f"/integrations/connections?filter={flt}", headers=h)
    assert [c["type"] for c in res.json()["data"]] == ["storage"]


def test_list_rejects_non_whitelisted_filter_field(client):
    h = _login(client)
    flt = json.dumps(
        {"kind": "group", "combinator": "and",
         "rules": [{"kind": "condition", "field": "credentials_json", "operator": "eq", "value": "x"}]}
    )
    assert client.get(f"/integrations/connections?filter={flt}", headers=h).status_code == 422


def test_get_one_connection(client):
    h = _login(client)
    created = _create(client, h, "s3", "Bucket")
    res = client.get(f"/integrations/connections/{created['id']}", headers=h)
    assert res.status_code == 200
    assert res.json()["name"] == "Bucket"
    assert client.get("/integrations/connections/ghost", headers=h).status_code == 404


def test_record_nav_at(client):
    h = _login(client)
    _create(client, h, "smtp", "B Mail")
    _create(client, h, "s3", "A Bucket")
    res = client.get(
        "/integrations/connections/at?index=1&sort_by=name&sort_dir=asc", headers=h
    )
    body = res.json()
    assert body["total"] == 2
    assert body["connection"]["name"] == "B Mail"
    miss = client.get("/integrations/connections/at?index=9", headers=h).json()
    assert miss["connection"] is None


def test_export_csv(client):
    h = _login(client)
    _create(client, h, "s3", "Bucket")
    res = client.get(
        "/integrations/connections/export?columns=name,provider,status", headers=h
    )
    assert res.status_code == 200
    lines = res.text.strip().splitlines()
    assert lines[0] == "Name,Provider,Status"
    assert "Bucket" in lines[1]
    assert "Amazon S3" in lines[1]
    assert "UNVERIFIED" in lines[1]
    # Secrets must never leak into an export.
    assert "sk" not in res.text


def test_export_respects_ids(client):
    h = _login(client)
    a = _create(client, h, "smtp", "Mail")
    _create(client, h, "s3", "Bucket")
    res = client.get(
        f"/integrations/connections/export?columns=name&ids={a['id']}", headers=h
    )
    lines = res.text.strip().splitlines()
    assert len(lines) == 2 and "Mail" in lines[1]


def test_list_requires_read_permission(client):
    assert client.get("/integrations/connections").status_code == 401
