"""AI dashboard builder S1 (SS) red tests: the dashboard store (S-6, S-6b, S-10, S-15, contract 3.2-3.7).

Pure store behaviour: save / get / share / delete / versions / list. None of these may call the LLM
(that guard lives in test_dashboards_builder.py).
"""
from __future__ import annotations

import copy

from tests.dashboards_helpers import dash  # noqa: F401 - pytest fixtures
from tests.dashboards_helpers import (
    BASE,
    OTHER,
    OWNER,
    VIEWER,
    assert_flat_error,
    count_model,
    create_dash,
    delete,
    f1_spec,
    get,
    hdr,
    listing,
    new_idem,
    save,
    share,
    versions,
    versions_items,
)

DASH_KEYS = {"id", "name", "owner_ref", "mine", "shared_with", "spec", "version", "created_at", "updated_at"}


def one_tile_spec(title="Sales overview"):
    spec = f1_spec(title)
    spec["tiles"] = spec["tiles"][:1]
    return spec


# -- create / get ----------------------------------------------------------------------------------

def test_create_returns_get_body_version_1(client, dash):
    res = save(client, dash.sorento, OWNER, "Sales overview", f1_spec())
    assert res.status_code == 200, res.text
    body = res.json()
    assert DASH_KEYS <= set(body)
    assert body["name"] == "Sales overview"
    assert body["owner_ref"] == OWNER and body["mine"] is True
    assert body["version"] == 1 and body["shared_with"] == []
    assert body["spec"] == f1_spec()
    assert body["created_at"].endswith("Z") and body["updated_at"].endswith("Z")
    got = get(client, dash.sorento, OWNER, body["id"])
    assert got.status_code == 200
    assert got.json() == body
    assert not got.json().get("spec_problems")


def test_created_version_row_has_no_changes(client, dash):
    d = create_dash(client, dash.sorento)
    items = versions_items(client, dash.sorento, OWNER, d["id"])
    assert len(items) == 1
    row = items[0]
    assert row["version"] == 1 and row["action"] == "created" and row["actor_ref"] == OWNER
    assert row["changes"] == [] and row["at"].endswith("Z")


def test_save_validation_errors_are_422_spec_invalid_and_store_nothing(client, dash):
    bad = f1_spec()
    bad["tiles"][0]["source"]["spec"]["entity"] = "x; drop table"
    res = save(client, dash.sorento, OWNER, "Bad", bad)
    body = assert_flat_error(res, 422, "spec_invalid")
    assert body["problems"] and all({"path", "reason"} <= set(p) for p in body["problems"])
    extra = f1_spec()
    extra["bogus"] = 1
    assert_flat_error(save(client, dash.sorento, OWNER, "Bad", extra), 422, "spec_invalid")
    assert listing(client, dash.sorento, OWNER).json()["total"] == 0
    assert count_model(dash.sf, "DashDashboard") == 0


def test_save_name_rules(client, dash):
    assert save(client, dash.sorento, OWNER, "", f1_spec()).status_code == 422
    assert save(client, dash.sorento, OWNER, "   ", f1_spec()).status_code == 422
    assert save(client, dash.sorento, OWNER, "n" * 81, f1_spec()).status_code == 422
    assert save(client, dash.sorento, OWNER, "n" * 80, f1_spec()).status_code == 200


# -- update / rename / conflict --------------------------------------------------------------------

def test_update_bumps_version_and_writes_saved_row_with_chart_counts(client, dash):
    d = create_dash(client, dash.sorento)  # 2 tiles
    res = save(client, dash.sorento, OWNER, d["name"], one_tile_spec(d["name"]), dashboard_id=d["id"], base_version=1)
    assert res.status_code == 200, res.text
    assert res.json()["version"] == 2 and res.json()["id"] == d["id"]
    assert len(res.json()["spec"]["tiles"]) == 1
    row = versions_items(client, dash.sorento, OWNER, d["id"])[0]
    assert row["version"] == 2 and row["action"] == "saved"
    assert {"field": "charts", "old": 2, "new": 1} in row["changes"]


def test_name_only_change_is_renamed(client, dash):
    d = create_dash(client, dash.sorento, name="New dashboard")
    res = save(client, dash.sorento, OWNER, "Sales overview", d["spec"], dashboard_id=d["id"], base_version=1)
    assert res.status_code == 200 and res.json()["version"] == 2 and res.json()["name"] == "Sales overview"
    row = versions_items(client, dash.sorento, OWNER, d["id"])[0]
    assert row["action"] == "renamed"
    assert row["changes"] == [{"field": "name", "old": "New dashboard", "new": "Sales overview"}]


def test_save_with_new_name_and_new_spec_lists_both_changes(client, dash):
    d = create_dash(client, dash.sorento, name="Old name")
    res = save(client, dash.sorento, OWNER, "New name", one_tile_spec("New name"), dashboard_id=d["id"], base_version=1)
    assert res.status_code == 200, res.text
    row = versions_items(client, dash.sorento, OWNER, d["id"])[0]
    assert row["action"] == "saved"
    by_field = {c["field"]: c for c in row["changes"]}
    assert by_field["charts"]["old"] == 2 and by_field["charts"]["new"] == 1
    assert by_field["name"]["old"] == "Old name" and by_field["name"]["new"] == "New name"


def test_stale_base_version_is_409_with_current_version(client, dash):
    d = create_dash(client, dash.sorento)
    ok = save(client, dash.sorento, OWNER, d["name"], one_tile_spec(), dashboard_id=d["id"], base_version=1)
    assert ok.status_code == 200
    stale = save(client, dash.sorento, OWNER, d["name"], f1_spec(), dashboard_id=d["id"], base_version=1)
    body = assert_flat_error(stale, 409, "version_conflict")
    assert body["current_version"] == 2
    assert get(client, dash.sorento, OWNER, d["id"]).json()["version"] == 2


# -- F13 idempotency -------------------------------------------------------------------------------

def test_same_idempotency_key_returns_first_response_and_one_version_row(client, dash):
    k = new_idem()
    first = save(client, dash.sorento, OWNER, "Sales overview", f1_spec(), idempotency_key=k)
    second = save(client, dash.sorento, OWNER, "Sales overview", f1_spec(), idempotency_key=k)
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    did = first.json()["id"]
    assert versions(client, dash.sorento, OWNER, did).json()["total"] == 1
    assert listing(client, dash.sorento, OWNER).json()["total"] == 1
    assert count_model(dash.sf, "DashVersion") == 1


def test_idempotent_replay_of_an_update_does_not_conflict_or_double_write(client, dash):
    d = create_dash(client, dash.sorento)
    k = new_idem()
    a = save(client, dash.sorento, OWNER, d["name"], one_tile_spec(), dashboard_id=d["id"], base_version=1, idempotency_key=k)
    b = save(client, dash.sorento, OWNER, d["name"], one_tile_spec(), dashboard_id=d["id"], base_version=1, idempotency_key=k)
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json() and a.json()["version"] == 2
    assert versions(client, dash.sorento, OWNER, d["id"]).json()["total"] == 2


def test_same_idempotency_key_from_another_actor_or_key_is_a_separate_save(client, dash):
    k = new_idem()
    mine = save(client, dash.sorento, OWNER, "Sales overview", f1_spec(), idempotency_key=k)
    theirs = save(client, dash.sorento, OTHER, "Sales overview", f1_spec(), idempotency_key=k)
    other_product = save(client, dash.ecohub, OWNER, "Sales overview", f1_spec(), idempotency_key=k)
    assert mine.status_code == theirs.status_code == other_product.status_code == 200
    ids = {mine.json()["id"], theirs.json()["id"], other_product.json()["id"]}
    assert len(ids) == 3
    assert theirs.json()["owner_ref"] == OTHER and other_product.json()["owner_ref"] == OWNER
    assert count_model(dash.sf, "DashVersion") == 3


# -- share -----------------------------------------------------------------------------------------

def test_share_replaces_the_list_and_writes_a_shared_row(client, dash):
    d = create_dash(client, dash.sorento)
    res = share(client, dash.sorento, OWNER, d["id"], [VIEWER])
    assert res.status_code == 200, res.text
    assert DASH_KEYS <= set(res.json())
    assert res.json()["shared_with"] == [{"user_ref": VIEWER}] and res.json()["version"] == 2
    res = share(client, dash.sorento, OWNER, d["id"], [OTHER])
    assert res.json()["shared_with"] == [{"user_ref": OTHER}]
    assert get(client, dash.sorento, OWNER, d["id"]).json()["shared_with"] == [{"user_ref": OTHER}]
    rows = versions_items(client, dash.sorento, OWNER, d["id"])
    assert [r["version"] for r in rows] == [3, 2, 1]
    assert [r["action"] for r in rows] == ["shared", "shared", "created"]
    assert rows[1]["changes"] == [{"field": "shared_with", "old": [], "new": [VIEWER]}]
    assert rows[0]["changes"] == [{"field": "shared_with", "old": [VIEWER], "new": [OTHER]}]
    assert rows[0]["actor_ref"] == OWNER


def test_share_drops_the_owners_own_ref_and_can_clear(client, dash):
    d = create_dash(client, dash.sorento)
    res = share(client, dash.sorento, OWNER, d["id"], [OWNER, VIEWER])
    assert res.json()["shared_with"] == [{"user_ref": VIEWER}]
    res = share(client, dash.sorento, OWNER, d["id"], [])
    assert res.status_code == 200 and res.json()["shared_with"] == []


def test_share_max_50(client, dash):
    d = create_dash(client, dash.sorento)
    fifty = [f"u-fake-{i}" for i in range(50)]
    assert share(client, dash.sorento, OWNER, d["id"], fifty).status_code == 200
    assert share(client, dash.sorento, OWNER, d["id"], fifty + ["u-fake-50"]).status_code == 422
    assert len(get(client, dash.sorento, OWNER, d["id"]).json()["shared_with"]) == 50


def test_share_duplicates_collapse(client, dash):
    d = create_dash(client, dash.sorento)
    res = share(client, dash.sorento, OWNER, d["id"], [VIEWER, VIEWER])
    assert res.status_code == 200
    assert res.json()["shared_with"] == [{"user_ref": VIEWER}]


# -- recipient and stranger ------------------------------------------------------------------------

def test_recipient_can_read_but_sees_no_share_list_and_is_not_mine(client, dash):
    d = create_dash(client, dash.sorento)
    share(client, dash.sorento, OWNER, d["id"], [VIEWER])
    res = get(client, dash.sorento, VIEWER, d["id"])
    assert res.status_code == 200
    body = res.json()
    assert body["shared_with"] == [] and body["mine"] is False and body["owner_ref"] == OWNER
    assert body["spec"] == f1_spec()
    assert versions(client, dash.sorento, VIEWER, d["id"]).status_code == 200
    ids = [i["id"] for i in listing(client, dash.sorento, VIEWER).json()["items"]]
    assert d["id"] in ids


def test_recipient_cannot_save_share_or_delete(client, dash):
    d = create_dash(client, dash.sorento)
    share(client, dash.sorento, OWNER, d["id"], [VIEWER])
    before = get(client, dash.sorento, OWNER, d["id"]).json()
    r = save(client, dash.sorento, VIEWER, "Hijack", one_tile_spec(), dashboard_id=d["id"], base_version=before["version"])
    assert_flat_error(r, 403, "not_owner")
    assert_flat_error(share(client, dash.sorento, VIEWER, d["id"], [OTHER]), 403, "not_owner")
    assert_flat_error(delete(client, dash.sorento, VIEWER, d["id"]), 403, "not_owner")
    assert get(client, dash.sorento, OWNER, d["id"]).json() == before


def test_stranger_gets_not_found_everywhere(client, dash):
    d = create_dash(client, dash.sorento)
    assert_flat_error(get(client, dash.sorento, OTHER, d["id"]), 404, "not_found")
    assert_flat_error(versions(client, dash.sorento, OTHER, d["id"]), 404, "not_found")
    assert_flat_error(save(client, dash.sorento, OTHER, "x", one_tile_spec(), dashboard_id=d["id"], base_version=1), 404, "not_found")
    assert_flat_error(share(client, dash.sorento, OTHER, d["id"], [VIEWER]), 404, "not_found")
    assert_flat_error(delete(client, dash.sorento, OTHER, d["id"]), 404, "not_found")
    assert listing(client, dash.sorento, OTHER).json()["items"] == []


def test_unknown_id_is_not_found(client, dash):
    assert_flat_error(get(client, dash.sorento, OWNER, "d_does-not-exist"), 404, "not_found")


# -- delete ----------------------------------------------------------------------------------------

def test_delete_hard_deletes_dashboard_and_versions(client, dash):
    d = create_dash(client, dash.sorento)
    share(client, dash.sorento, OWNER, d["id"], [VIEWER])
    res = delete(client, dash.sorento, OWNER, d["id"])
    assert res.status_code == 200 and res.json() == {"deleted": True}
    assert_flat_error(get(client, dash.sorento, OWNER, d["id"]), 404, "not_found")
    assert_flat_error(versions(client, dash.sorento, OWNER, d["id"]), 404, "not_found")
    assert_flat_error(get(client, dash.sorento, VIEWER, d["id"]), 404, "not_found")
    assert listing(client, dash.sorento, OWNER).json()["total"] == 0
    assert count_model(dash.sf, "DashDashboard") == 0
    assert count_model(dash.sf, "DashVersion") == 0
    assert_flat_error(delete(client, dash.sorento, OWNER, d["id"]), 404, "not_found")


# -- versions --------------------------------------------------------------------------------------

def test_versions_newest_first_with_paging(client, dash):
    d = create_dash(client, dash.sorento, name="New dashboard")
    save(client, dash.sorento, OWNER, "Sales overview", d["spec"], dashboard_id=d["id"], base_version=1)
    share(client, dash.sorento, OWNER, d["id"], [VIEWER])
    res = versions(client, dash.sorento, OWNER, d["id"])
    body = res.json()
    assert body["total"] == 3 and body["page"] == 1 and body["limit"] == 50
    assert [(r["version"], r["action"]) for r in body["items"]] == [(3, "shared"), (2, "renamed"), (1, "created")]
    for r in body["items"]:
        assert {"version", "action", "actor_ref", "at", "changes"} <= set(r)
    page2 = versions(client, dash.sorento, OWNER, d["id"], limit=2, page=2).json()
    assert page2["total"] == 3 and page2["page"] == 2 and page2["limit"] == 2
    assert [r["version"] for r in page2["items"]] == [1]


# -- list ------------------------------------------------------------------------------------------

def _seed_list(client, dash):
    """owner: 'Alpha Sales' (shared with viewer), 'beta report'; other: 'Other Private', 'Other Shared' (shared with owner)."""
    a1 = create_dash(client, dash.sorento, OWNER, "Alpha Sales")
    a2 = create_dash(client, dash.sorento, OWNER, "beta report")
    b1 = create_dash(client, dash.sorento, OTHER, "Other Private")
    b2 = create_dash(client, dash.sorento, OTHER, "Other Shared")
    share(client, dash.sorento, OWNER, a1["id"], [VIEWER])
    share(client, dash.sorento, OTHER, b2["id"], [OWNER])
    # touch Alpha last so updated_at order is deterministic: beta older than Alpha
    save(client, dash.sorento, OWNER, "Alpha Sales", one_tile_spec("Alpha Sales"), dashboard_id=a1["id"],
         base_version=get(client, dash.sorento, OWNER, a1["id"]).json()["version"])
    return a1["id"], a2["id"], b1["id"], b2["id"]


def _names(res):
    assert res.status_code == 200, res.text
    return [i["name"] for i in res.json()["items"]]


def test_list_item_shape_and_defaults(client, dash):
    a1, a2, _, _ = _seed_list(client, dash)
    body = listing(client, dash.sorento, OWNER, scope="mine").json()
    assert {"items", "total", "page", "limit"} <= set(body)
    assert body["page"] == 1 and body["limit"] == 25 and body["total"] == 2
    by_id = {i["id"]: i for i in body["items"]}
    item = by_id[a1]
    assert {"id", "name", "owner_ref", "mine", "shared", "shared_count", "updated_at", "version"} <= set(item)
    assert item["mine"] is True and item["shared"] is True and item["shared_count"] == 1
    assert by_id[a2]["shared"] is False and by_id[a2]["shared_count"] == 0


def test_list_scopes(client, dash):
    _seed_list(client, dash)
    assert sorted(_names(listing(client, dash.sorento, OWNER))) == ["Alpha Sales", "Other Shared", "beta report"]
    assert sorted(_names(listing(client, dash.sorento, OWNER, scope="all"))) == ["Alpha Sales", "Other Shared", "beta report"]
    assert sorted(_names(listing(client, dash.sorento, OWNER, scope="mine"))) == ["Alpha Sales", "beta report"]
    assert _names(listing(client, dash.sorento, OWNER, scope="shared")) == ["Other Shared"]
    assert _names(listing(client, dash.sorento, VIEWER)) == ["Alpha Sales"]
    assert _names(listing(client, dash.sorento, VIEWER, scope="mine")) == []
    assert _names(listing(client, dash.sorento, VIEWER, scope="shared")) == ["Alpha Sales"]
    assert _names(listing(client, dash.sorento, "u-stranger-9")) == []
    mine_flags = {i["name"]: i["mine"] for i in listing(client, dash.sorento, OWNER).json()["items"]}
    assert mine_flags == {"Alpha Sales": True, "beta report": True, "Other Shared": False}


def test_list_q_is_case_insensitive_substring(client, dash):
    _seed_list(client, dash)
    assert _names(listing(client, dash.sorento, OWNER, q="SALES")) == ["Alpha Sales"]
    assert _names(listing(client, dash.sorento, OWNER, q="eta rep")) == ["beta report"]
    assert _names(listing(client, dash.sorento, OWNER, q="nothing-matches")) == []
    assert listing(client, dash.sorento, OWNER, q="nothing-matches").json()["total"] == 0


def test_list_sort_name_updated_owner(client, dash):
    _seed_list(client, dash)
    assert _names(listing(client, dash.sorento, OWNER, scope="mine", sort="name", dir="asc")) == ["Alpha Sales", "beta report"]
    assert _names(listing(client, dash.sorento, OWNER, scope="mine", sort="name", dir="desc")) == ["beta report", "Alpha Sales"]
    assert _names(listing(client, dash.sorento, OWNER, scope="mine", sort="updated_at", dir="asc")) == ["beta report", "Alpha Sales"]
    assert _names(listing(client, dash.sorento, OWNER, scope="mine", sort="updated_at", dir="desc")) == ["Alpha Sales", "beta report"]
    asc = [i["owner_ref"] for i in listing(client, dash.sorento, OWNER, sort="owner_ref", dir="asc").json()["items"]]
    desc = [i["owner_ref"] for i in listing(client, dash.sorento, OWNER, sort="owner_ref", dir="desc").json()["items"]]
    assert asc == sorted(asc) and desc == sorted(desc, reverse=True) and asc[0] != asc[-1]


def test_list_paging_and_limits(client, dash):
    _seed_list(client, dash)
    p1 = listing(client, dash.sorento, OWNER, scope="mine", sort="name", dir="asc", limit=1, page=1).json()
    p2 = listing(client, dash.sorento, OWNER, scope="mine", sort="name", dir="asc", limit=1, page=2).json()
    assert [i["name"] for i in p1["items"]] == ["Alpha Sales"] and [i["name"] for i in p2["items"]] == ["beta report"]
    assert p1["total"] == p2["total"] == 2 and p2["page"] == 2 and p2["limit"] == 1
    assert listing(client, dash.sorento, OWNER, limit=100).status_code == 200
    assert listing(client, dash.sorento, OWNER, limit=101).status_code == 422
    assert listing(client, dash.sorento, OWNER, limit=0).status_code == 422
    assert listing(client, dash.sorento, OWNER, page=0).status_code == 422
    assert listing(client, dash.sorento, OWNER, sort="bogus").status_code == 422
    assert listing(client, dash.sorento, OWNER, scope="everything").status_code == 422


def test_list_requires_actor_ref(client, dash):
    res = client.get(BASE, headers=hdr(dash.sorento))
    assert res.status_code == 422, res.text


# -- stored spec that no longer validates ----------------------------------------------------------

def test_get_returns_spec_problems_for_a_stored_spec_that_no_longer_validates(client, dash):
    from modules.dashboards.models import DashDashboard

    d = create_dash(client, dash.sorento)
    db = dash.sf()
    try:
        row = db.get(DashDashboard, d["id"])
        broken = copy.deepcopy(row.spec_json)
        broken["tiles"][0]["source"]["spec"]["entity"] = "x; drop table"
        broken["tiles"][1]["title"] = "a;b"  # v2: pivot is valid, so use a forbidden sequence
        row.spec_json = broken
        db.commit()
    finally:
        db.close()
    res = get(client, dash.sorento, OWNER, d["id"])
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["spec"]["tiles"][0]["source"]["spec"]["entity"] == "x; drop table"
    problems = body["spec_problems"]
    assert problems and all(isinstance(p["path"], str) and isinstance(p["reason"], str) for p in problems)
    assert any(p["path"].startswith("tiles[1]") and p["reason"] == "Only names and values can be used in a chart, not code or links." for p in problems)
