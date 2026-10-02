"""Sprint-5/10 S1 - AC-10-01 (general operator-configurable lookups, R9):
the save-time validator for a task's ``source_config.lookups`` list.

RED before the coder: ``modules.autocount.http_source.lookups`` does not
exist at all yet (verified 2026-09-20 - the module directory only has
``__init__.py``/``client.py``/``envelope.py``/``errors.py``/``preview.py``/
``source.py``). Every test here imports
``modules.autocount.http_source.lookups.validate_lookups`` (plain top-level
import, no try/except, per the sprint-5/08 test-file precedent in
``test_autocount_http_source.py``) and is expected to fail COLLECTION with
``ImportError``/``ModuleNotFoundError`` until S1 lands.

Assumed signature (the plan names the module and says it "owns
``validate_lookups(specs, source_columns)``" - the exact return shape is
NOT given, so this file pins one): a pure function
``validate_lookups(lookups: list[dict], source_columns: Sequence[str]) ->
dict[str, str]`` - empty dict when every entry is clean, else a
``{"lookups[i].<field>": "<operator-safe message>"}`` map, mirroring the
``Dict[str, str]`` field-error shape every other save-gate in this module
already returns (``EtlService._validate_http_config``'s own ``errors``
dict). A nested index (``lookups[0].fields[1].as``, ``lookups[0].on[0].
local``) extends that SAME bracket convention one level for the two list-
of-dict sub-fields (``on``/``fields``) - not explicitly spelled out by the
AC beyond "naming ``lookups[i].<field>``", called out here as an ASSUMPTION
the coder should confirm rather than silently reshape.

``MAX_LOOKUPS`` (AC-10-01: "more than MAX_LOOKUPS (5) entries") is assumed
to be an importable module constant so a cap test never hardcodes a number
that could drift from the real one.
"""
from __future__ import annotations

import copy
from typing import Any, Dict, List

import pytest

from modules.autocount.http_source.lookups import MAX_LOOKUPS, validate_lookups
from modules.autocount.http_source.preview import validate_http_path

SOURCE_COLUMNS = [
    "ItemCode", "Description", "Desc2", "BaseUOM", "ItemGroup",
    "ItemBrand", "IsActive", "Discontinued", "LastModified",
]


def _valid_lookup(**overrides: Any) -> Dict[str, Any]:
    """The AC-10-04 pre-filled ItemUOM lookup - the KNOWN-GOOD baseline
    every negative test mutates one field of."""
    spec: Dict[str, Any] = {
        "path": "/itemuombypage",
        "as": "uom",
        "on": [
            {"local": "ItemCode", "remote": "ItemCode"},
            {"local": "BaseUOM", "remote": "UOM", "match": "casefold_trim"},
        ],
        "fields": [{"remote": "Price", "as": "BaseUOMPrice"}],
    }
    spec.update(overrides)
    return spec


# ── the happy path (a control - proves the fixture itself is well-formed) ────


def test_valid_single_lookup_has_no_errors():
    errors = validate_lookups([_valid_lookup()], SOURCE_COLUMNS)
    assert errors == {}


# ── AC-10-01: `as` / `fields[].as` regex ─────────────────────────────────────


def test_lookup_as_must_match_identifier_regex():
    errors = validate_lookups([_valid_lookup(**{"as": "uom price"})], SOURCE_COLUMNS)
    assert "lookups[0].as" in errors, errors


def test_field_alias_must_match_identifier_regex():
    spec = _valid_lookup(fields=[{"remote": "Price", "as": "Base UOM Price"}])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].fields[0].as" in errors, errors


def test_field_alias_over_length_cap_rejected():
    """The regex caps an alias at 41 chars (`{0,40}` after the first)."""
    too_long = "a" * 42
    spec = _valid_lookup(fields=[{"remote": "Price", "as": too_long}])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].fields[0].as" in errors, errors


# ── AC-10-01: duplicate / colliding aliases ──────────────────────────────────


def test_duplicate_field_alias_within_one_lookup_rejected():
    spec = _valid_lookup(
        fields=[
            {"remote": "Price", "as": "X"},
            {"remote": "Rate", "as": "X"},
        ]
    )
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].fields[1].as" in errors, errors


def test_field_alias_colliding_with_a_source_column_rejected():
    spec = _valid_lookup(fields=[{"remote": "Price", "as": "ItemCode"}])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].fields[0].as" in errors, errors


def test_second_lookup_alias_colliding_with_first_lookups_alias_rejected():
    first = _valid_lookup(fields=[{"remote": "Price", "as": "BaseUOMPrice"}])
    second = _valid_lookup(
        path="/itembypage", **{"as": "item2"},
        on=[{"local": "ItemCode", "remote": "ItemCode"}],
        fields=[{"remote": "Description", "as": "BaseUOMPrice"}],
    )
    errors = validate_lookups([first, second], SOURCE_COLUMNS)
    assert "lookups[1].fields[0].as" in errors, errors


# ── AC-10-01: empty `on` / empty `fields` ────────────────────────────────────


def test_empty_on_rejected():
    spec = _valid_lookup(on=[])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].on" in errors, errors


def test_empty_fields_rejected():
    spec = _valid_lookup(fields=[])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].fields" in errors, errors


# ── AC-10-01: forward reference / multi-hop ──────────────────────────────────


def test_local_column_unknown_to_this_point_is_a_forward_reference_422():
    spec = _valid_lookup(on=[{"local": "NotAColumn", "remote": "ItemCode"}])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].on[0].local" in errors, errors


def test_multi_hop_local_referencing_an_earlier_lookups_alias_is_valid():
    """AC-10-02's own example: lookup 2 may join on an alias lookup 1
    produced - never a save-time error."""
    first = _valid_lookup(
        path="/itembypage", **{"as": "item"},
        on=[{"local": "ItemCode", "remote": "ItemCode"}],
        fields=[{"remote": "BaseUOM", "as": "ItemBaseUOM"}],
    )
    second = _valid_lookup(
        path="/itemuombypage", **{"as": "uom"},
        on=[
            {"local": "ItemCode", "remote": "ItemCode"},
            {"local": "ItemBaseUOM", "remote": "UOM", "match": "casefold_trim"},
        ],
        fields=[{"remote": "Rate", "as": "UomRate"}],
    )
    errors = validate_lookups([first, second], SOURCE_COLUMNS)
    assert errors == {}, errors


def test_same_local_reference_as_a_forward_lookup_is_rejected():
    """The MIRROR of the valid multi-hop case above: lookup 1 (evaluated
    FIRST) may not reference lookup 2's alias - order IS evaluation order,
    so this is a forward reference, not a cycle the engine resolves."""
    first = _valid_lookup(
        path="/itembypage", **{"as": "item"},
        on=[{"local": "ItemCode", "remote": "ItemCode"}, {"local": "UomRate", "remote": "Whatever"}],
        fields=[{"remote": "BaseUOM", "as": "ItemBaseUOM"}],
    )
    second = _valid_lookup(
        path="/itemuombypage", **{"as": "uom"},
        on=[{"local": "ItemCode", "remote": "ItemCode"}],
        fields=[{"remote": "Rate", "as": "UomRate"}],
    )
    errors = validate_lookups([first, second], SOURCE_COLUMNS)
    assert "lookups[0].on[1].local" in errors, errors


# ── AC-10-01: the MAX_LOOKUPS cap ─────────────────────────────────────────────


def test_max_lookups_constant_is_five():
    assert MAX_LOOKUPS == 5


def test_over_max_lookups_rejected():
    specs: List[Dict[str, Any]] = []
    for i in range(MAX_LOOKUPS + 1):
        specs.append(
            _valid_lookup(
                path="/itembypage", **{"as": f"l{i}"},
                on=[{"local": "ItemCode", "remote": "ItemCode"}],
                fields=[{"remote": "Description", "as": f"alias{i}"}],
            )
        )
    errors = validate_lookups(specs, SOURCE_COLUMNS)
    assert "lookups" in errors, errors
    assert str(MAX_LOOKUPS) in errors["lookups"], errors["lookups"]


def test_exactly_max_lookups_is_accepted():
    specs = [
        _valid_lookup(
            path="/itembypage", **{"as": f"l{i}"},
            on=[{"local": "ItemCode", "remote": "ItemCode"}],
            fields=[{"remote": "Description", "as": f"alias{i}"}],
        )
        for i in range(MAX_LOOKUPS)
    ]
    errors = validate_lookups(specs, SOURCE_COLUMNS)
    assert errors == {}, errors


# ── AC-10-01: path reuses `validate_http_path` verbatim ──────────────────────


def test_lookup_path_reuses_validate_http_path_rule():
    bad_path = "/itemuombypage/../secret"
    spec = _valid_lookup(path=bad_path)
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].path" in errors, errors
    # Same message the main path's own validator would produce for the
    # identical string - the lookup editor can never reach an endpoint the
    # main path could not, and must fail with the SAME words.
    assert errors["lookups[0].path"] == validate_http_path(bad_path)


def test_lookup_path_must_start_with_slash():
    spec = _valid_lookup(path="itemuombypage")
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].path" in errors, errors


# ── match mode ────────────────────────────────────────────────────────────────


def test_invalid_match_mode_rejected():
    spec = _valid_lookup(
        on=[
            {"local": "ItemCode", "remote": "ItemCode"},
            {"local": "BaseUOM", "remote": "UOM", "match": "fuzzy"},
        ]
    )
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert "lookups[0].on[1].match" in errors, errors


def test_default_match_mode_is_exact_and_accepted():
    spec = _valid_lookup(on=[{"local": "ItemCode", "remote": "ItemCode"}])
    errors = validate_lookups([spec], SOURCE_COLUMNS)
    assert errors == {}, errors


# ── deep-copy hygiene: validate_lookups must never mutate its input ─────────


def test_validate_lookups_never_mutates_the_input_list():
    specs = [_valid_lookup()]
    before = copy.deepcopy(specs)
    validate_lookups(specs, SOURCE_COLUMNS)
    assert specs == before


# KILL TEST (for the reviewer): comment out the "alias colliding with a
# source column" branch in the coder's implementation (whatever line raises
# for `fields[].as in source_columns`) - exactly
# ``test_field_alias_colliding_with_a_source_column_rejected`` must flip
# green-to-red (and no other test in this file should move), since it is the
# only test whose fixture has NO OTHER violation to be caught by.
