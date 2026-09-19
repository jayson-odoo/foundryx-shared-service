"""General, operator-configurable cross-endpoint joins on an open-REST HTTP
task (sprint-5/10, AC-10-01/02, owner ruling R9).

``validate_lookups`` is the save-time 422 gate; ``build_index``/
``merge_onto_rows`` are the runtime merge primitives ``HttpApiSource.
fetch_changes`` (and ``/autocount/http/preview``) apply between the page
walk and de-duplication/mapping. One lookup reads one more endpoint on the
SAME connection, joins it to the task's rows on one or more column pairs,
and projects named remote columns onto every source row under an
operator-chosen alias - a miss simply leaves the alias key ABSENT, never
``None`` (``sink_payload()``'s omit-None rule then does the right thing).

One trim rule (AC-10-60): every join key, on both the local and the remote
side, is compared through a TRIMMED view (``str(value).strip()``) regardless
of match mode - ``match: casefold_trim`` additionally casefolds. The trim is
a LOOKUP KEY ONLY; it is never written back onto either row.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..presets import HTTP_PRESETS
from .preview import validate_http_path

# AC-10-01 - "more than MAX_LOOKUPS (5) entries" is a save-time 422.
MAX_LOOKUPS = 5

# `as` (a lookup's own name) and every `fields[].as` (a projected alias):
# letters/numbers/underscores only, starting with a letter, capped at 41
# chars total (`{0,40}` after the first).
_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")

MATCH_EXACT = "exact"
MATCH_CASEFOLD_TRIM = "casefold_trim"
_MATCH_MODES = {MATCH_EXACT, MATCH_CASEFOLD_TRIM}


def _lookup_field_aliases(lookups: Sequence[Dict[str, Any]]) -> set:
    """Every ``fields[].as`` alias across ``lookups`` (defensive against a
    malformed entry - never raises)."""
    aliases: set = set()
    for spec in lookups:
        if not isinstance(spec, dict):
            continue
        for field_spec in spec.get("fields") or []:
            if isinstance(field_spec, dict) and isinstance(field_spec.get("as"), str):
                aliases.add(field_spec["as"])
    return aliases


def validate_lookups(
    lookups: List[Dict[str, Any]],
    source_columns: Optional[Sequence[str]],
    *,
    previously_saved_lookups: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """The save-time 422 gate for a task's ``source_config.lookups``
    (AC-10-01). Empty dict when every entry is clean, else
    ``{"lookups[i].<field>": "<operator-safe message>"}`` - a nested index
    (``lookups[0].on[0].local``, ``lookups[0].fields[1].as``) extends the
    same bracket convention one level for the two list-of-dict sub-fields.

    ``source_columns`` is the task's own RAW previewed columns, or ``None``
    when the task has never been previewed (review round 1 blocker 1a) -
    EVERY structural rule still runs regardless (path, alias regex, the
    5-cap, empty ``on``/``fields``, a duplicate alias, a forward reference);
    only the "local is a known column" and "alias collides with a REAL
    source column" checks are skipped when there is nothing to check them
    against yet, mirroring the ``keyFields`` "accepted un-checked" rule a
    few lines up the caller.

    Two collision rules are genuinely distinct per AC-10-01: a field alias
    colliding with a source column, and a field alias colliding with an
    EARLIER lookup's own alias. The former deliberately excludes a name that
    is (a) produced by one of THIS invocation's own lookups, (b) never ALSO
    used as a join key (``on[].local``/``on[].remote``) anywhere in this
    invocation, AND (c) already EXPLAINED - either by ``previously_saved_
    lookups`` (the task's OWN stored lookups before this save, so a re-save
    of an unchanged lookup can never 422 against the alias its own last
    preview stamped into ``result_columns``, AC-10-05) or by ANY registered
    HTTP preset's own shipped lookup (AC-10-04's ``BaseUOMPrice`` validates
    on a brand-new task with nothing saved yet). (review round 1 blocker 2 -
    the reviewer proved live that a bare "produced by this call" carve-out
    lets a FRESH, unrelated alias (``as: "Description"``) silently shadow a
    genuine raw column of the same name; explaining it only via what is
    ALREADY on record closes that hole while keeping the preset and the
    re-save flows working with zero operator action.) A name doing double
    duty as a join key stays flagged either way - shadowing a column the
    operator is actively joining on is exactly the ambiguity this rule
    exists to catch.

    Never mutates ``lookups``, ``previously_saved_lookups`` or any entry in
    either.
    """
    errors: Dict[str, str] = {}
    if not lookups:
        return errors
    if len(lookups) > MAX_LOOKUPS:
        errors["lookups"] = f"No more than {MAX_LOOKUPS} lookups are allowed on one task."
        return errors

    known_source_columns: Optional[set] = (
        None if source_columns is None else {str(c) for c in source_columns}
    )

    # Precompute, across the WHOLE list, which alias names this call would
    # itself produce and which names are used as a join key anywhere in it.
    all_field_aliases = _lookup_field_aliases(lookups)
    all_join_key_names: set = set()
    for spec in lookups:
        if not isinstance(spec, dict):
            continue
        for pair in spec.get("on") or []:
            if not isinstance(pair, dict):
                continue
            local, remote = pair.get("local"), pair.get("remote")
            if isinstance(local, str):
                all_join_key_names.add(local)
            if isinstance(remote, str):
                all_join_key_names.add(remote)

    # "Explained" aliases (review round 1 blocker 2(iii)): the task's OWN
    # previously-saved lookups, union EVERY registered preset's own shipped
    # lookup aliases - never simply "produced by this call" (see docstring).
    explained_aliases = _lookup_field_aliases(previously_saved_lookups or ())
    for preset in HTTP_PRESETS.values():
        explained_aliases |= _lookup_field_aliases(preset.lookups)

    self_produced_safe = (all_field_aliases & explained_aliases) - all_join_key_names
    column_collision_set: Optional[set] = (
        None if known_source_columns is None else known_source_columns - self_produced_safe
    )

    # `on[].local` validity grows with EARLIER lookups' own aliases only
    # (multi-hop, AC-10-02) - a forward reference (naming a LATER lookup's
    # alias) is therefore a 422, never a cycle the engine resolves, and is
    # detectable with NO source columns at all (it is purely about THIS
    # submission's own ordering).
    known_locals: set = set(known_source_columns) if known_source_columns is not None else set()
    produced_aliases: set = set()

    for i, spec in enumerate(lookups):
        prefix = f"lookups[{i}]"
        if not isinstance(spec, dict):
            errors[prefix] = "Each lookup must be an object."
            continue

        path_error = validate_http_path(str(spec.get("path") or ""))
        if path_error:
            errors[f"{prefix}.path"] = path_error

        as_name = spec.get("as")
        if not isinstance(as_name, str) or not _ALIAS_RE.match(as_name):
            errors[f"{prefix}.as"] = (
                "Give this lookup a short name using letters, numbers and "
                "underscores only."
            )

        on_list = spec.get("on")
        if not isinstance(on_list, list) or not on_list:
            errors[f"{prefix}.on"] = "Add at least one join column pair."
        else:
            for j, pair in enumerate(on_list):
                if not isinstance(pair, dict):
                    errors[f"{prefix}.on[{j}]"] = "Each join pair must be an object."
                    continue
                local = pair.get("local")
                if not isinstance(local, str) or not local:
                    errors[f"{prefix}.on[{j}].local"] = "Pick a local column to join on."
                elif local not in known_locals:
                    if local in all_field_aliases:
                        # Produced somewhere in THIS submission but not yet
                        # known at this point - it can only be a LATER
                        # lookup's alias (a forward reference), regardless
                        # of whether source columns are known at all.
                        errors[f"{prefix}.on[{j}].local"] = (
                            f"'{local}' is a later lookup's own field - lookups "
                            f"run in order, so it is not available yet."
                        )
                    elif known_source_columns is not None:
                        errors[f"{prefix}.on[{j}].local"] = (
                            f"'{local}' is not a source column or an earlier "
                            f"lookup's field."
                        )
                    # else: never previewed - unprovable either way, accepted
                    # un-checked (nothing to check against yet).
                remote = pair.get("remote")
                if not isinstance(remote, str) or not remote:
                    errors[f"{prefix}.on[{j}].remote"] = "Pick a remote column to join on."
                match_mode = pair.get("match", MATCH_EXACT)
                if match_mode not in _MATCH_MODES:
                    errors[f"{prefix}.on[{j}].match"] = (
                        "Choose 'Exact' or 'Ignore case and spaces'."
                    )

        fields_list = spec.get("fields")
        produced_this_lookup: set = set()
        if not isinstance(fields_list, list) or not fields_list:
            errors[f"{prefix}.fields"] = "Add at least one field to bring in."
        else:
            for k, field_spec in enumerate(fields_list):
                if not isinstance(field_spec, dict):
                    errors[f"{prefix}.fields[{k}]"] = "Each field must be an object."
                    continue
                remote_field = field_spec.get("remote")
                if not isinstance(remote_field, str) or not remote_field:
                    errors[f"{prefix}.fields[{k}].remote"] = "Pick a remote column."
                alias = field_spec.get("as")
                field_key = f"{prefix}.fields[{k}].as"
                if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
                    errors[field_key] = (
                        "Give this field a short name using letters, numbers "
                        "and underscores only."
                    )
                elif column_collision_set is not None and alias in column_collision_set:
                    errors[field_key] = f"'{alias}' is already a source column."
                elif alias in produced_aliases:
                    errors[field_key] = f"'{alias}' is already used by an earlier lookup."
                elif alias in produced_this_lookup:
                    errors[field_key] = f"'{alias}' is used twice in this lookup."
                else:
                    produced_this_lookup.add(alias)

        known_locals |= produced_this_lookup
        produced_aliases |= produced_this_lookup

    return errors


def _normalize_key_part(value: Any, match: str) -> str:
    """AC-10-60's "trimmed key view" - ``str(value).strip()`` always,
    additionally casefolded for ``casefold_trim``. Applied to BOTH sides of
    a join pair; never written back onto the row it was read from."""
    text = str(value).strip()
    if match == MATCH_CASEFOLD_TRIM:
        return text.casefold()
    return text


def _key_for(
    row: Dict[str, Any], on: Sequence[Dict[str, Any]], side: str
) -> Optional[Tuple[str, ...]]:
    parts: List[str] = []
    for pair in on:
        value = row.get(pair.get(side))
        if value is None:
            return None
        parts.append(_normalize_key_part(value, pair.get("match", MATCH_EXACT)))
    return tuple(parts)


def build_index(
    rows: Sequence[Dict[str, Any]], on: Sequence[Dict[str, Any]]
) -> Dict[Tuple[str, ...], Dict[str, Any]]:
    """Index the WALKED lookup endpoint's rows on the REMOTE side of ``on``.
    First occurrence wins on a duplicate key (mirrors ``HttpApiSource.
    _dedupe``'s own first-occurrence rule). A row whose join value is
    missing on any pair is simply not indexed - it can never be matched."""
    index: Dict[Tuple[str, ...], Dict[str, Any]] = {}
    for row in rows:
        key = _key_for(row, on, "remote")
        if key is None or key in index:
            continue
        index[key] = row
    return index


class AliasCollisionError(Exception):
    """Raised by ``merge_onto_rows`` (review round 1 blocker 2(ii)) when an
    alias would OVERWRITE a key already present on the row - a REAL raw
    column, or an EARLIER lookup's own alias already merged onto this same
    row. Save-time validation alone cannot always tell a raw column from a
    once-previewed alias (AC-10-05), so this is the run-time backstop: fail
    the whole run loudly (the caller wraps this into a set-level
    ``HttpSourceError``, fail-before-state) rather than silently deliver a
    poisoned value."""

    def __init__(self, alias: str):
        super().__init__(alias)
        self.alias = alias


def merge_onto_rows(
    rows: Sequence[Dict[str, Any]],
    index: Dict[Tuple[str, ...], Dict[str, Any]],
    on: Sequence[Dict[str, Any]],
    fields: Sequence[Dict[str, Any]],
) -> int:
    """Merge ``fields`` from ``index`` onto every row in ``rows`` IN PLACE,
    keyed by the LOCAL side of ``on``. A miss leaves every alias key
    ABSENT, never ``None`` (AC-10-02) - ``sink_payload()``'s omit-None rule
    then treats a miss as "nothing to send", not "clear this field". Raises
    ``AliasCollisionError`` (review round 1 blocker 2(ii)) rather than
    overwrite a key the row already carries. Returns the miss count."""
    misses = 0
    for row in rows:
        key = _key_for(row, on, "local")
        matched = index.get(key) if key is not None else None
        if matched is None:
            misses += 1
            continue
        for field_spec in fields:
            remote = field_spec.get("remote")
            alias = field_spec.get("as")
            if remote in matched:
                if alias in row:
                    raise AliasCollisionError(alias)
                row[alias] = matched[remote]
    return misses
