"""AI dashboard builder S1 (SS) red tests: replay the contract fixtures F1-F13 (S-C, contract section 8).

The CODER ships one JSON file per fixture in ``service_backend/modules/dashboards/contract_fixtures/*.json``
(the CRM lane's stub mirrors the same files). This module defines and replays that format.

Fixture file format (one fixture per file; ``id`` unique across files)::

    {
      "id": "F1",
      "call": "builder/turn",                       # free label: builder/turn | get | list | save | share | delete | any
      "setup": ["owner_dashboard", "share_viewer"], # steps run in order, see below
      "key": "sorento",                             # sorento | ecohub | off | none | bad
      "request": {"method": "POST",
                  "path": "/api/v1/dashboards/{dashboard_id}/share",   # {dashboard_id} is substituted
                  "query": {"actor_ref": "u-viewer-1"},                # optional
                  "body": {"actor_ref": "u-viewer-1", "dashboard_id": "{dashboard_id}"}},   # optional
      "stub_outputs": [{"reply": "...", "operations": [...]}],         # optional: scripted model outputs, in order
      "response": {"status": 200, "body": {...}},   # status + body; ONLY the KEYS (recursively) of body are compared
      "repeat": 2,                                  # optional: send the request N times (F13), responses must be identical
      "cases": [ {"name": "...", "request": {...}, "response": {...}, "key": "...", "setup": [...], "stub_outputs": [...]} ]
    }

``cases`` (optional) replaces the top-level request/response with several variants (F5: no key / bad key; F7: body vs
query product; F9: save / share / delete; F10: four bad specs). A case inherits ``key``, ``setup``, ``stub_outputs``,
``repeat`` from the top level unless it sets its own. Each case runs on a fresh database.

Setup steps (all use the default tenant, sorento key, actor u-owner-1, the F1 tiles as the spec):
    "owner_dashboard"     u-owner-1 saves a dashboard (version 1); its id fills ``{dashboard_id}``
    "owner_dashboard_v2"  as above, then saves again (version 2)
    "share_viewer"        the owner shares it with u-viewer-1
    "module_off"          deactivate the module for the tenant of the "off" key
    "no_llm"              production environment (no LLM connection configured)
Key names: sorento = (default tenant, sorento_crm), ecohub = (default tenant, ecohub), off = a key of a third tenant
(the module is deactivated for it whenever this key is used), none = no X-API-Key header, bad = "bad-key".

Keys compared in a response body: dict -> same key set, recursively; list -> empty iff the fixture's is empty, else every
element has the shape of the fixture element at the same index (the last one repeats); scalars -> same JSON kind
(string / number / boolean / null). Values of ids, timestamps and usage numbers are never compared.

Expected outcome per id (asserted against the fixtures themselves, so a fixture cannot quietly drift):
F1 200, F2 200, F3 200 (question), F4 502 ai_failed, F5 401 invalid_api_key, F6 403 service_not_enabled,
F7 403 product_mismatch (a body case and a query case), F8 404 not_found, F9 403 not_owner (save, share, delete),
F10 422 spec_invalid, F11 409 version_conflict, F12 409 ai_not_configured, F13 200 twice with one version row.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from app.ai.stub import StubResponse, stub_fixtures
from tests.dashboards_helpers import dash  # noqa: F401 - pytest fixtures
from tests.dashboards_helpers import (
    OTHER,
    OWNER,
    TENANT_C,
    TENANT_C_NAME,
    VIEWER,
    count_model,
    create_dash,
    f1_spec,
    hdr,
    issue_key,
    save,
    share,
)
from tests.meetings_helpers import make_admin_user, make_tenant

FIXTURE_DIR = Path(__file__).resolve().parents[1] / "modules" / "dashboards" / "contract_fixtures"
EXPECTED_IDS = [f"F{i}" for i in range(1, 18)]

EXPECT = {
    "F1": (200, None), "F2": (200, None), "F3": (200, None), "F4": (502, "ai_failed"),
    "F5": (401, "invalid_api_key"), "F6": (403, "service_not_enabled"), "F7": (403, "product_mismatch"),
    "F8": (404, "not_found"), "F9": (403, "not_owner"), "F10": (422, "spec_invalid"),
    "F11": (409, "version_conflict"), "F12": (409, "ai_not_configured"), "F13": (200, None),
    "F14": (200, None), "F15": (422, "images_invalid"), "F16": (200, None), "F17": (200, None),
}


# -- loading ---------------------------------------------------------------------------------------

def load_fixtures() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for path in sorted(FIXTURE_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        assert data["id"] not in out, f"duplicate fixture id {data['id']} ({path.name})"
        out[data["id"]] = data
    return out


def expand(fx: Dict[str, Any]) -> List[Dict[str, Any]]:
    """The runnable cases of a fixture with inherited fields merged in."""
    base = {k: fx[k] for k in ("key", "setup", "stub_outputs", "repeat") if k in fx}
    cases = fx.get("cases") or [{"name": "default", "request": fx["request"], "response": fx["response"]}]
    return [{**base, **c, "fixture": fx["id"]} for c in cases]


def build_cases() -> List[Tuple[str, Dict[str, Any]]]:
    fixtures = load_fixtures()
    out = [(f"{fid}-{c.get('name', i)}", c) for fid, fx in fixtures.items() for i, c in enumerate(expand(fx))]
    return out or [("no-fixtures-found", {})]


CASES = build_cases()


# -- structure comparison --------------------------------------------------------------------------

def kind(v: Any) -> str:
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "boolean"
    if isinstance(v, (int, float)):
        return "number"
    if isinstance(v, str):
        return "string"
    return "list" if isinstance(v, list) else "object"


def assert_same_shape(actual: Any, expected: Any, path: str = "$") -> None:
    assert kind(actual) == kind(expected), f"{path}: expected {kind(expected)}, got {kind(actual)} ({actual!r})"
    if isinstance(expected, dict):
        assert set(actual) == set(expected), f"{path}: keys {sorted(actual)} != {sorted(expected)}"
        for k in expected:
            assert_same_shape(actual[k], expected[k], f"{path}.{k}")
    elif isinstance(expected, list):
        if not expected:
            assert actual == [], f"{path}: expected empty list, got {actual!r}"
            return
        assert actual, f"{path}: expected a non-empty list"
        for i, item in enumerate(actual):
            assert_same_shape(item, expected[min(i, len(expected) - 1)], f"{path}[{i}]")


# -- fixture self-checks ---------------------------------------------------------------------------

def test_fixture_files_cover_f1_to_f17():
    fixtures = load_fixtures()
    assert sorted(fixtures, key=lambda s: int(s[1:])) == EXPECTED_IDS, sorted(fixtures)
    assert len(list(FIXTURE_DIR.glob("*.json"))) == len(EXPECTED_IDS), "one file per fixture"


def test_fixtures_follow_the_documented_format_and_expected_outcomes():
    fixtures = load_fixtures()
    assert fixtures, f"no fixtures in {FIXTURE_DIR}"
    for fid, fx in fixtures.items():
        assert isinstance(fx.get("call"), str) and fx["call"], fid
        assert fx.get("key") in {"sorento", "ecohub", "off", "none", "bad"} or all(
            c.get("key") in {"sorento", "ecohub", "off", "none", "bad"} for c in fx.get("cases", [])), fid
        for case in expand(fx):
            assert {"request", "response"} <= set(case), (fid, case)
            assert case["request"]["method"] in {"GET", "POST"} and case["request"]["path"].startswith("/api/v1/dashboards"), fid
            status, code = EXPECT[fid]
            assert case["response"]["status"] == status, (fid, case.get("name"))
            if code:
                assert case["response"]["body"]["error"] == code, (fid, case.get("name"))
                assert isinstance(case["response"]["body"]["message"], str), fid
    cases = lambda fid: expand(fixtures[fid])  # noqa: E731
    assert {c.get("key") for c in cases("F5")} == {"none", "bad"} or len(cases("F5")) >= 2
    assert any("product" in (c["request"].get("body") or {}) for c in cases("F7"))
    assert any("product" in (c["request"].get("query") or {}) for c in cases("F7"))
    assert {c["request"]["path"].rsplit("/", 1)[-1] for c in cases("F9")} >= {"save", "share", "delete"}
    assert len(cases("F10")) >= 4
    assert all(len(c.get("stub_outputs", [])) >= 2 for c in cases("F4"))
    assert all(c.get("repeat", 1) == 2 for c in cases("F13"))
    assert cases("F3")[0]["response"]["body"]["question"]["options"]
    assert cases("F1")[0]["response"]["body"]["changed_tile_ids"] == ["t1", "t2"]
    assert cases("F2")[0]["response"]["body"]["changed_tile_ids"] == ["t1"]
    assert cases("F3")[0]["response"]["body"]["changed_tile_ids"] == []


# -- replay ----------------------------------------------------------------------------------------

def _subst(value: Any, did: str | None) -> Any:
    if isinstance(value, str):
        return value.replace("{dashboard_id}", did or "d_unset")
    if isinstance(value, list):
        return [_subst(v, did) for v in value]
    if isinstance(value, dict):
        return {k: _subst(v, did) for k, v in value.items()}
    return value


@pytest.mark.parametrize("case_id,case", CASES, ids=[c[0] for c in CASES])
def test_fixture_replays_against_the_real_service(client, dash, monkeypatch, case_id, case):
    assert case, f"no fixtures found in {FIXTURE_DIR}"
    from app.services.app_store_service import AppStoreService

    # the third tenant for the "off" key (module installed; deactivated by the module_off step / by use)
    db = dash.sf()
    try:
        make_tenant(db, TENANT_C, TENANT_C_NAME)
        make_admin_user(db, TENANT_C, "admin@dash-c.example")
        AppStoreService(db).install(TENANT_C, "dashboards")
        db.commit()
        _, off_key = issue_key(db, TENANT_C, "sorento_crm")
    finally:
        db.close()
    keys = {"sorento": dash.sorento, "ecohub": dash.ecohub, "off": off_key, "none": None, "bad": "bad-key"}

    did = None
    key_name = case.get("key", "sorento")
    for step in case.get("setup", []):
        if step in ("owner_dashboard", "owner_dashboard_v2"):
            d = create_dash(client, dash.sorento, OWNER, "Sales overview", f1_spec())
            did = d["id"]
            if step.endswith("_v2"):
                res = save(client, dash.sorento, OWNER, "Sales overview", f1_spec(), dashboard_id=did, base_version=1)
                assert res.status_code == 200, res.text
        elif step == "share_viewer":
            assert share(client, dash.sorento, OWNER, did, [VIEWER]).status_code == 200
        elif step == "module_off":
            pass  # handled below, after any other setup that needs the module
        elif step == "no_llm":
            from app.config import settings

            monkeypatch.setattr(settings, "environment", "production")
        else:
            pytest.fail(f"unknown setup step {step!r}")
    if key_name == "off" or "module_off" in case.get("setup", []):
        db = dash.sf()
        try:
            AppStoreService(db).deactivate(TENANT_C, "dashboards")
            db.commit()
        except Exception:  # already inactive
            db.rollback()
        finally:
            db.close()

    req = case["request"]
    path = _subst(req["path"], did)
    query = _subst(req.get("query"), did)
    body = _subst(req.get("body"), did)
    outputs = [StubResponse(structured=copy.deepcopy(o)) for o in case.get("stub_outputs", [])]
    responses = []
    with stub_fixtures(*outputs):
        for _ in range(case.get("repeat", 1)):
            responses.append(client.request(req["method"], path, params=query or None, json=body,
                                            headers=hdr(keys[key_name])))

    expected = case["response"]
    for res in responses:
        assert res.status_code == expected["status"], res.text
        payload = res.json()
        if "error" in expected["body"]:
            assert payload["error"] == expected["body"]["error"], payload
        assert_same_shape(payload, expected["body"])
    for res in responses[1:]:
        assert res.json() == responses[0].json(), "repeated request must return the first response"
    if case["fixture"] == "F13":
        assert count_model(dash.sf, "DashVersion") == 1
