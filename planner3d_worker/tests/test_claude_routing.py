"""claude-procedural red tests: routing (plan planner3d-claude-procedural-engine.md, D4)."""
import json

import pytest

from planner3d_worker.claude.routing import Profile, Routing

PRICES = {
    "claude-sonnet-5-5": {"input": 2.0, "output": 10.0, "cacheRead": 0.10},
    "claude-opus-5-5": {"input": 4.0, "output": 20.0, "cacheRead": 0.20},
}


def _file(tmp_path, **over):
    data = {
        "spendCapUsd": 700,
        "prices": PRICES,
        "default": {"model": "claude-sonnet-5-5", "approach": "primitives", "maxVersions": 2, "effort": "medium"},
        "categories": {
            "SRTWC": {"model": "claude-opus-5-5", "approach": "sdf", "maxVersions": 3, "effort": "high"},
        },
    }
    data.update(over)
    path = tmp_path / "routing.json"
    path.write_text(json.dumps(data))
    return path


def test_category_code_picks_its_profile(tmp_path):
    r = Routing.load(_file(tmp_path))
    p = r.profile_for({"code": "SRTWC", "name": "Water closets"})
    assert p == Profile(model="claude-opus-5-5", approach="sdf", max_versions=3, effort="high")


@pytest.mark.parametrize("category", [None, {}, {"code": "UNKNOWN", "name": "x"}, {"name": "no code"}])
def test_unknown_or_missing_category_falls_back_to_default(tmp_path, category):
    p = Routing.load(_file(tmp_path)).profile_for(category)
    assert (p.model, p.approach, p.max_versions) == ("claude-sonnet-5-5", "primitives", 2)


def test_profile_is_frozen(tmp_path):
    p = Routing.load(_file(tmp_path)).profile_for(None)
    with pytest.raises(Exception):
        p.model = "other"


@pytest.mark.parametrize("raw,want", [(1, 2), (2, 2), (3, 3), (9, 3)])
def test_max_versions_clamped_to_2_to_3(tmp_path, raw, want):
    default = {"model": "claude-sonnet-5-5", "approach": "primitives", "maxVersions": raw, "effort": "low"}
    assert Routing.load(_file(tmp_path, default=default)).profile_for(None).max_versions == want


def test_prices_and_cap(tmp_path):
    r = Routing.load(_file(tmp_path))
    assert r.prices("claude-opus-5-5") == PRICES["claude-opus-5-5"]
    assert r.spend_cap_usd == 700.0


def test_shipped_default_file_is_sonnet_primitives_with_no_categories():
    from pathlib import Path

    import planner3d_worker.claude.routing as mod

    path = Path(mod.__file__).with_name("routing.default.json")
    raw = json.loads(path.read_text())
    assert raw["categories"] == {}
    r = Routing.load(path)
    p = r.profile_for(None)
    assert p.approach == "primitives" and "sonnet" in p.model
    assert r.spend_cap_usd == 700.0
    assert r.prices(p.model)["input"] == 2.0
