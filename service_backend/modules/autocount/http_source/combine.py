"""General, entity-agnostic row-combining step for an open-REST HTTP task
(sprint-5/10, AC-10-76..81, owner ruling R11).

``validate_combine`` is the save-time 422 gate (mirrors ``lookups.
validate_lookups`` exactly - same bracket-index error-key convention,
same "unchecked when never previewed" contract); ``apply_combine`` is the
runtime reducer ``HttpApiSource.fetch_changes`` (and the preview route)
call AFTER every lookup has merged onto the rows and BEFORE de-duplication,
hashing and mapping (AC-10-80: identity and the row hash both run on the
COMBINED rows).

This is NOT a rules engine: one step per task, no joins (that is
Lookups), no nested grouping. Stage order, pinned literally (AC-10-77/78/
79):

    computed (list order) -> require (list order, first falsy excludes)
    -> group by ``groupBy`` (first-appearance order) -> measures + carry
    -> round -> drop (list order, first match wins)

Every formula (``computed``/``require``/``drop``) runs through the
EXISTING, hand-written ``modules.autocount.formula.parse_formula`` /
``evaluate_formula`` - never eval/Jinja, the house anti-SSTI line applied
to one more surface. ``evaluate_formula(formula, None, facts=row)`` is the
SAME calling shape a document header formula already uses: a raw dict of
EXACT-cased column names as ``facts``. Since ``evaluate_formula`` derives
its own ``known_variables`` from ``facts.keys()`` on every call, a row
whose referenced column is genuinely ABSENT (a lookup miss - AC-10-02
never writes ``None``, it omits the key) fails to even PARSE for that one
row, which is exactly the desired "this formula could not run for this
row" signal - caught the same way as a genuine runtime fault.

Generic metadata (AC-10-81), the SAME four keys for ANY entity - the
agreed Sorento stock header names are produced from this by a separate
declarative map on the entity profile (S5b), never baked in here:

    {excludedRows, excludedCount, dropped: {<rule>: {count, rows?}},
     roundedCount}
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple

from ..formula import FormulaError, FormulaParseError, evaluate_formula, parse_formula, to_bool_strict
from ..mapping import TransformError, t_decimal

# AC-10-76's own caps.
MAX_COMBINE_COMPUTED = 10
MAX_COMBINE_REQUIRE = 10
MAX_COMBINE_GROUP_BY = 5
MAX_COMBINE_MEASURES = 10
MAX_COMBINE_DROP = 10
MAX_COMBINE_CARRY = 20

# AC-10-79 - the dropped-rows LIST is capped; the "count" stays the full total.
DROPPED_ROWS_CAP = 50

# review round 3 (AC-10-76) - the SAMPLE-based require/drop boolean-type
# check below is bounded to the first N previewed rows regardless of how
# many the caller hands in, so a formula authored against a large preview
# sample never turns Test into an O(sample x formulas) crawl.
SAMPLE_TYPE_CHECK_ROWS = 50

MEASURE_OPS = frozenset({"sum", "min", "max", "count", "first", "last"})
_NUMERIC_MEASURE_OPS = frozenset({"sum", "min", "max"})
ROUND_MODES = frozenset({"none", "half_up"})

# A computed/measure alias: letters/numbers/underscores only, starting with a
# letter, capped at 41 chars total - the same shape ``lookups._ALIAS_RE``
# already established for a lookup's own aliases.
_ALIAS_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,40}$")

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def _as_str_list(value: Any) -> List[str]:
    return [str(c) for c in value] if isinstance(value, list) else []


def _formula_known_variables(
    known_source: Optional[FrozenSet[str]],
    extra_known: Sequence[str],
    formula_text: str,
) -> FrozenSet[str]:
    """The ``known_variables`` set for ONE formula parse.

    When ``known_source`` is ``None`` (the task has never been previewed -
    the SAME "accepted un-checked" contract ``validate_lookups`` already
    applies), there is nothing real to check a name against - every
    identifier token the formula itself uses is accepted, which makes the
    "unknown name" check a structural no-op for this one case rather than
    a false 422 against a column that may well turn out to exist.
    """
    if known_source is None:
        return frozenset(_IDENT_RE.findall(formula_text))
    return known_source | frozenset(extra_known)


def combine_output_columns(combine: Optional[Dict[str, Any]]) -> List[str]:
    """The COMBINED, POST-GROUP column schema a ``combine`` step's own
    output rows carry (review round 3, B1): ``groupBy + carry +
    measures[].alias``, de-duplicated, in that declared order - the SAME
    projection ``preview_http`` already builds inline for the response
    grid and ``_metadata_row_projection`` builds (narrower - no ``carry``)
    for a dropped/listed row.

    This is the effective result-column set for a combine-carrying task
    from de-dup / ``compared_columns_for`` / the row hash onward: a
    combined row never carries its PRE-combine raw or lookup-alias columns
    (a ``groupBy``/``measures[].source`` name is consumed, not projected),
    so hashing against ``effective_result_columns`` (the raw+lookup set)
    would compare columns that simply do not exist on the row it is
    hashing - AC-10-80's "de-duplication, source_ref minting and row_hash
    all run on the COMBINED rows" only holds when the compared-column set
    itself is drawn from the SAME combined shape.

    ``None`` / not a dict / an empty ``groupBy`` -> ``[]`` (no combine step
    configured, or not yet valid enough to derive a schema from - the
    caller falls back to the pre-combine effective columns in that case).
    """
    if not isinstance(combine, dict):
        return []
    group_by = [str(c) for c in (combine.get("groupBy") or []) if str(c)]
    if not group_by:
        return []
    carry = [str(c) for c in (combine.get("carry") or []) if str(c)]
    measure_aliases = [
        str(spec.get("alias"))
        for spec in (combine.get("measures") or [])
        if isinstance(spec, dict) and spec.get("alias")
    ]
    seen: List[str] = []
    for col in (*group_by, *carry, *measure_aliases):
        if col not in seen:
            seen.append(col)
    return seen


class CombineDropError(FormulaError):
    """A ``drop`` rule's formula raised, or evaluated to something other
    than true/false, at RUNTIME (AC-10-79 - "a drop formula that raises is
    a named task error, not a silent keep", review round 3 B2). Carries
    the rule's list INDEX and NAME so any caller (the preview route, a
    real run) can name the failing rule without re-walking ``combine``
    itself to find it.

    review round 4 - ``rule_name`` used to be dead: ``str(exc)`` was only
    the underlying formula error's own message, so a caller that logged
    ``str(exc)`` (the push run) never actually named the rule. The message
    itself now carries it too, so every consumer of ``str(exc)`` gets the
    rule name, not only the ones that reach into ``.rule_name``."""

    def __init__(self, index: int, name: str, message: str):
        super().__init__(f"Drop rule '{name}': {message}")
        self.index = index
        self.rule_name = name


class CombineMeasureError(TransformError):
    """A numeric measure op (``sum``/``min``/``max``, AC-10-76) hit a
    non-numeric value at RUNTIME - the SAMPLE-based save-time check
    (``_sample_numeric_errors``) could not have caught it (the sample was
    clean, the task was never previewed, or the offending row simply was
    not in the sample). AC-10-76's own text: "a runtime non-numeric still
    raises the normal named ``TransformError`` - stated, not pretended
    away". Carries the measure's list INDEX and its ``source`` column name
    so a caller (``preview_http``) can key the 422 to
    ``combine.measures[i].source`` without re-walking ``combine`` itself,
    mirroring ``CombineDropError`` exactly (review round 4, SF-1)."""

    def __init__(self, index: int, source_name: str, message: str):
        super().__init__(message)
        self.index = index
        self.source_name = source_name


def _sample_boolean_errors(
    combine: Dict[str, Any], sample: Sequence[Dict[str, Any]]
) -> Dict[str, str]:
    """AC-10-76's own save-time rule: "a require or drop formula whose
    inferred type is not boolean" is a 422. ``formula.py`` has no static
    return-type inference (confirmed - it is a hand-written recursive-
    descent evaluator with no type pass), so this is the documented
    fallback: evaluate each ``require``/``drop`` formula against the
    PREVIEWED SAMPLE and 422 the ones that ever produce a value that is
    not a genuine ``bool``. A formula that RAISES on a given sample row is
    a DIFFERENT problem (a per-row data fault, e.g. a lookup miss on that
    one sample row) - not itself a type-inference signal, so that row is
    skipped for THIS check (it may still be a perfectly boolean-typed
    formula) and left to surface at run time under its own existing
    fail-closed rule (``require_error`` exclusion / ``CombineDropError``).

    Bounded to the first ``SAMPLE_TYPE_CHECK_ROWS`` rows and to require/
    drop formulas that already parsed clean (a formula with its own
    structural error is not re-evaluated here - that error already names
    the field).
    """
    errors: Dict[str, str] = {}
    if not sample:
        return errors
    rows = list(sample)[:SAMPLE_TYPE_CHECK_ROWS]
    computed_specs = _as_list(combine.get("computed"))
    require_specs = _as_list(combine.get("require"))

    # ── require: evaluated against the SAMPLE'S computed-enriched facts,
    # exactly the facts a require formula sees at run time (AC-10-77 stage
    # order: computed THEN require) ──────────────────────────────────────
    for row in rows:
        facts: Dict[str, Any] = dict(row)
        try:
            for spec in computed_specs:
                if not isinstance(spec, dict):
                    continue
                alias = spec.get("alias")
                formula_text = spec.get("formula")
                if not isinstance(alias, str) or not isinstance(formula_text, str):
                    continue
                facts[alias] = evaluate_formula(formula_text, None, facts=facts)
        except FormulaError:
            continue
        # NIT (ii, review round 4) - honours the SAME "first falsy/raising
        # rule excludes the row" short-circuit `apply_combine` enforces at
        # runtime (AC-10-77): a raising or falsy require rule is itself an
        # exclusion, so a LATER rule never actually sees this row - the
        # sample walk must stop at the same point, never pass a type
        # verdict on a rule that could never even run against this row.
        for i, spec in enumerate(require_specs):
            if not isinstance(spec, dict):
                continue
            formula_text = spec.get("formula")
            if not isinstance(formula_text, str) or not formula_text.strip():
                continue
            key = f"combine.require[{i}].formula"
            try:
                result = evaluate_formula(formula_text, None, facts=facts)
            except FormulaError:
                break
            if not isinstance(result, bool):
                errors[key] = (
                    "This formula must produce true or false, not a number or "
                    "piece of text."
                )
                break
            if not result:
                break

    # ── drop: evaluated against the GROUPED sample (computed, require and
    # grouping already applied - drop is a POST-GROUP stage). Reuses
    # ``apply_combine`` itself with ``drop`` emptied out to get there,
    # rather than duplicating the computed/require/group/measure/round
    # pipeline a second time ─────────────────────────────────────────────
    drop_specs = _as_list(combine.get("drop"))
    if drop_specs:
        try:
            grouped = apply_combine(rows, {**combine, "drop": []}).rows
        except (FormulaError, TransformError):
            # NIT (i, review round 4) - this used to look like it could
            # silently skip the drop check ("not checked" reading as
            # "clean"), but neither branch is actually reachable with
            # anything left unreported: a ``FormulaError`` from the
            # computed/require stages is caught INSIDE `apply_combine`'s
            # own per-row loop as a `computed_error`/`require_error`
            # exclusion (never propagates here - `drop` is emptied, so no
            # `CombineDropError` is possible either), and a numeric-measure
            # `TransformError` is now independently caught and named by
            # `_sample_numeric_errors` below, in the SAME validation pass.
            # `grouped = []` therefore only means "nothing to check the
            # drop formulas AGAINST", never "the problem went unreported".
            grouped = []
        for out_row in grouped:
            for i, spec in enumerate(drop_specs):
                key = f"combine.drop[{i}].formula"
                if key in errors or not isinstance(spec, dict):
                    continue
                formula_text = spec.get("formula")
                if not isinstance(formula_text, str) or not formula_text.strip():
                    continue
                try:
                    result = evaluate_formula(formula_text, None, facts=out_row)
                except FormulaError:
                    continue
                if not isinstance(result, bool):
                    errors[key] = (
                        "This formula must produce true or false, not a number "
                        "or piece of text."
                    )

    return errors


def _sample_numeric_errors(
    combine: Dict[str, Any], sample: Sequence[Dict[str, Any]]
) -> Dict[str, str]:
    """AC-10-76's own save-time rule (review round 4, SF-2): "a numeric op
    (``sum``/``min``/``max``) over a column whose previewed sample values
    are non-numeric with no computed cast" is a 422 named
    ``combine.measures[i].source``. Evaluated against the SAME
    computed-enriched sample facts a measure's ``source`` sees at run time
    (AC-10-77 stage order: computed runs BEFORE grouping/measures), so a
    computed cast (``number(x)``) that turns a text column numeric clears
    the measure that reads it. ``None``/blank sample values are skipped
    (absent is not non-numeric - the SAME rule ``t_decimal`` itself
    already applies); a ``number()``-coercible string counts as numeric
    (``t_decimal``'s own dialect, reused so this check speaks the exact
    numeric dialect the runtime reducer does).

    A RUNTIME non-numeric that this sample never caught still raises the
    normal named ``TransformError`` (``CombineMeasureError`` - stated in
    AC-10-76's own text, not pretended away by this check).

    Bounded to the first ``SAMPLE_TYPE_CHECK_ROWS`` rows, mirroring
    ``_sample_boolean_errors`` exactly.
    """
    errors: Dict[str, str] = {}
    if not sample:
        return errors
    measures_raw = _as_list(combine.get("measures"))
    numeric_measures = [
        (i, spec.get("source"))
        for i, spec in enumerate(measures_raw)
        if isinstance(spec, dict)
        and spec.get("op") in _NUMERIC_MEASURE_OPS
        and isinstance(spec.get("source"), str)
        and spec.get("source")
    ]
    if not numeric_measures:
        return errors

    rows = list(sample)[:SAMPLE_TYPE_CHECK_ROWS]
    computed_specs = _as_list(combine.get("computed"))

    # ── one enriched fact set per sample row (computed columns applied),
    # shared across every measure below - never re-derived per measure ────
    enriched_rows: List[Dict[str, Any]] = []
    for row in rows:
        facts: Dict[str, Any] = dict(row)
        try:
            for spec in computed_specs:
                if not isinstance(spec, dict):
                    continue
                alias = spec.get("alias")
                formula_text = spec.get("formula")
                if not isinstance(alias, str) or not isinstance(formula_text, str):
                    continue
                facts[alias] = evaluate_formula(formula_text, None, facts=facts)
        except FormulaError:
            # Same "skip, never a type-inference signal" treatment
            # `_sample_boolean_errors` gives a per-row computed fault.
            continue
        enriched_rows.append(facts)

    for i, source in numeric_measures:
        key = f"combine.measures[{i}].source"
        for facts in enriched_rows:
            value = facts.get(source)
            if value is None or (isinstance(value, str) and not value.strip()):
                continue
            try:
                t_decimal(value)
            except TransformError:
                errors[key] = (
                    f"'{source}' is not a number in the previewed sample - "
                    f"sum, min and max need a numeric column (add a computed "
                    f"cast if it needs converting)."
                )
                break

    return errors


def validate_combine(
    combine: Optional[Dict[str, Any]],
    source_columns: Optional[Sequence[str]],
    lookup_aliases: Optional[Sequence[str]] = None,
    sample: Optional[Sequence[Dict[str, Any]]] = None,
) -> Dict[str, str]:
    """The save-time 422 gate for a task's ``source_config.combine``
    (AC-10-76). Empty dict when clean (or when ``combine`` is ``None`` - no
    combine step configured at all), else ``{"combine.<part>[i].<field>":
    "<message>"}``. Never mutates ``combine`` or any entry in it.
    """
    errors: Dict[str, str] = {}
    if combine is None:
        return errors
    if not isinstance(combine, dict):
        errors["combine"] = "The combine step must be an object."
        return errors

    known_source: Optional[FrozenSet[str]] = (
        None if source_columns is None else frozenset(str(c) for c in source_columns)
    )
    known_lookup = frozenset(str(a) for a in (lookup_aliases or ()))

    computed_raw = _as_list(combine.get("computed"))
    require_raw = _as_list(combine.get("require"))
    group_by = _as_str_list(combine.get("groupBy"))
    measures_raw = _as_list(combine.get("measures"))
    carry = _as_str_list(combine.get("carry"))
    round_raw = _as_list(combine.get("round"))
    drop_raw = _as_list(combine.get("drop"))
    measure_col = combine.get("measure")

    if len(computed_raw) > MAX_COMBINE_COMPUTED:
        errors["combine.computed"] = (
            f"No more than {MAX_COMBINE_COMPUTED} computed columns are allowed."
        )
    if len(require_raw) > MAX_COMBINE_REQUIRE:
        errors["combine.require"] = (
            f"No more than {MAX_COMBINE_REQUIRE} require rules are allowed."
        )
    if len(group_by) > MAX_COMBINE_GROUP_BY:
        errors["combine.groupBy"] = (
            f"No more than {MAX_COMBINE_GROUP_BY} group-by columns are allowed."
        )
    elif not group_by:
        errors["combine.groupBy"] = "Add at least one group-by column."
    if len(measures_raw) > MAX_COMBINE_MEASURES:
        errors["combine.measures"] = (
            f"No more than {MAX_COMBINE_MEASURES} measures are allowed."
        )
    if len(carry) > MAX_COMBINE_CARRY:
        errors["combine.carry"] = (
            f"No more than {MAX_COMBINE_CARRY} carried columns are allowed."
        )
    if len(drop_raw) > MAX_COMBINE_DROP:
        errors["combine.drop"] = f"No more than {MAX_COMBINE_DROP} drop rules are allowed."

    # ── computed (ordered; a formula may name any EARLIER computed alias) ──
    computed_alias_set: set = set()
    for i, spec in enumerate(computed_raw):
        prefix = f"combine.computed[{i}]"
        if not isinstance(spec, dict):
            errors[prefix] = "Each computed column must be an object."
            continue
        alias = spec.get("alias")
        alias_key = f"{prefix}.alias"
        valid_alias = isinstance(alias, str) and bool(_ALIAS_RE.match(alias))
        if not valid_alias:
            errors[alias_key] = (
                "Give this computed column a short name using letters, numbers "
                "and underscores only."
            )
        elif known_source is not None and alias in known_source:
            errors[alias_key] = f"'{alias}' is already a source column."
        elif alias in known_lookup:
            errors[alias_key] = f"'{alias}' is already used by a lookup."
        elif alias in computed_alias_set:
            errors[alias_key] = f"'{alias}' is already used by an earlier computed column."

        formula_text = spec.get("formula")
        formula_key = f"{prefix}.formula"
        if not isinstance(formula_text, str) or not formula_text.strip():
            errors[formula_key] = "Enter a formula."
        else:
            known = _formula_known_variables(
                None if known_source is None else known_source | known_lookup,
                computed_alias_set,
                formula_text,
            )
            try:
                parse_formula(formula_text, known)
            except FormulaParseError as exc:
                errors[formula_key] = str(exc)

        if valid_alias and alias_key not in errors:
            computed_alias_set.add(alias)

    pre_group_known: Optional[FrozenSet[str]] = (
        None if known_source is None else known_source | known_lookup | frozenset(computed_alias_set)
    )

    # ── require (ordered; first falsy excludes) ─────────────────────────────
    for i, spec in enumerate(require_raw):
        prefix = f"combine.require[{i}]"
        if not isinstance(spec, dict):
            errors[prefix] = "Each require rule must be an object."
            continue
        name = spec.get("name")
        if not isinstance(name, str) or not name.strip():
            errors[f"{prefix}.name"] = "Give this require rule a name."
        reason = spec.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            errors[f"{prefix}.reason"] = "Give this require rule a reason code."
        formula_text = spec.get("formula")
        formula_key = f"{prefix}.formula"
        if not isinstance(formula_text, str) or not formula_text.strip():
            errors[formula_key] = "Enter a formula."
        else:
            known = _formula_known_variables(pre_group_known, (), formula_text)
            try:
                parse_formula(formula_text, known)
            except FormulaParseError as exc:
                errors[formula_key] = str(exc)

    # ── the designated `measure` - a PRE-GROUP column (R11 ruling 2), never
    # a `measures[].alias` ────────────────────────────────────────────────
    if measure_col is not None:
        if not isinstance(measure_col, str) or not measure_col:
            errors["combine.measure"] = "Choose the designated measure column."
        elif pre_group_known is not None and measure_col not in pre_group_known:
            errors["combine.measure"] = f"'{measure_col}' is not a known column."

    # ── groupBy (each column picked, becomes the task's key fields) ───────
    for i, col in enumerate(group_by):
        if not col:
            errors[f"combine.groupBy[{i}]"] = "Choose a column to group by."
        elif pre_group_known is not None and col not in pre_group_known:
            errors[f"combine.groupBy[{i}]"] = f"'{col}' is not a known column."
    group_by_set = set(group_by)

    # ── measures ─────────────────────────────────────────────────────────
    measure_alias_set: set = set()
    for i, spec in enumerate(measures_raw):
        prefix = f"combine.measures[{i}]"
        if not isinstance(spec, dict):
            errors[prefix] = "Each measure must be an object."
            continue
        source = spec.get("source")
        if not isinstance(source, str) or not source:
            errors[f"{prefix}.source"] = "Choose a source column."
        elif pre_group_known is not None and source not in pre_group_known:
            errors[f"{prefix}.source"] = f"'{source}' is not a known column."
        op = spec.get("op")
        if op not in MEASURE_OPS:
            errors[f"{prefix}.op"] = "Choose sum, min, max, count, first or last."
        alias = spec.get("alias")
        alias_key = f"{prefix}.alias"
        if not isinstance(alias, str) or not _ALIAS_RE.match(alias):
            errors[alias_key] = (
                "Give this measure a short name using letters, numbers and "
                "underscores only."
            )
        elif alias in group_by_set:
            errors[alias_key] = f"'{alias}' is already a group-by column."
        elif alias in measure_alias_set:
            errors[alias_key] = f"'{alias}' is already used by an earlier measure."
        else:
            measure_alias_set.add(alias)

    # ── carry (existing pre-group columns, first value in the group wins) ──
    for i, col in enumerate(carry):
        if not col:
            errors[f"combine.carry[{i}]"] = "Choose a column to carry."
        elif pre_group_known is not None and col not in pre_group_known:
            errors[f"combine.carry[{i}]"] = f"'{col}' is not a known column."

    # ── the POST-GROUP schema (groupBy + carry + measure aliases) - always
    # fully known regardless of preview state, since it is entirely derived
    # from THIS combine config, never from the raw source ────────────────
    post_group_known = group_by_set | measure_alias_set | set(carry)

    # ── round (a measure alias, after grouping) ─────────────────────────
    round_measures_seen: set = set()
    for i, spec in enumerate(round_raw):
        prefix = f"combine.round[{i}]"
        if not isinstance(spec, dict):
            errors[prefix] = "Each rounding rule must be an object."
            continue
        round_measure = spec.get("measure")
        if not isinstance(round_measure, str) or round_measure not in measure_alias_set:
            errors[f"{prefix}.measure"] = f"'{round_measure}' is not a declared measure."
        # N2 (review round 3) - a SECOND rounding rule for the same measure
        # is never meaningful (the first application already changed the
        # value the second one would read) and would silently double-round
        # whichever one runs last - a save-time 422, not a runtime surprise.
        elif round_measure in round_measures_seen:
            errors[f"{prefix}.measure"] = (
                f"'{round_measure}' already has an earlier rounding rule."
            )
        else:
            round_measures_seen.add(round_measure)
        mode = spec.get("mode")
        if mode not in ROUND_MODES:
            errors[f"{prefix}.mode"] = "Choose 'None' or 'Half up'."
        dp = spec.get("dp")
        if isinstance(dp, bool) or not isinstance(dp, int) or dp < 0:
            errors[f"{prefix}.dp"] = "Decimal places must be zero or a positive whole number."

    # ── drop (ordered; first match wins) ────────────────────────────────
    drop_names_seen: set = set()
    for i, spec in enumerate(drop_raw):
        prefix = f"combine.drop[{i}]"
        if not isinstance(spec, dict):
            errors[prefix] = "Each drop rule must be an object."
            continue
        name = spec.get("name")
        name_key = f"{prefix}.name"
        if not isinstance(name, str) or not name.strip():
            errors[name_key] = "Give this drop rule a name."
        elif name in drop_names_seen:
            errors[name_key] = f"'{name}' is already used by an earlier drop rule."
        else:
            drop_names_seen.add(name)
        formula_text = spec.get("formula")
        formula_key = f"{prefix}.formula"
        if not isinstance(formula_text, str) or not formula_text.strip():
            errors[formula_key] = "Enter a formula."
        else:
            try:
                parse_formula(formula_text, frozenset(post_group_known))
            except FormulaParseError as exc:
                errors[formula_key] = str(exc)

    # ── AC-10-76's own SAMPLE-based rules - the require/drop boolean-type
    # check (review round 3, B2) and the sum/min/max numeric-op check
    # (review round 4, SF-2) - only attempted once every STRUCTURAL check
    # above is already clean, so a malformed spec (an unknown column, a
    # bad alias, ...) is never masked by a confusing second error from
    # evaluating a formula that could not even be trusted to mean what it
    # says yet. The two checks are independent of EACH OTHER (different
    # keys - `combine.require`/`combine.drop` vs `combine.measures`), so
    # both always run together rather than one gating the other ─────────
    if sample and not errors:
        errors.update(_sample_boolean_errors(combine, sample))
        errors.update(_sample_numeric_errors(combine, sample))

    return errors


# ── runtime ──────────────────────────────────────────────────────────────────


@dataclass
class CombineResult:
    rows: List[Dict[str, Any]]
    metadata: Dict[str, Any]


def _coerce_measure_number(value: Any, source_name: str) -> Decimal:
    """AC-10-76's own text: a RUNTIME non-numeric on a numeric op is a named
    ``TransformError`` - reuses the mapping engine's own ``t_decimal``
    coercion so this measure engine speaks the exact same numeric dialect
    the rest of the mapper does."""
    coerced = t_decimal(value)
    if coerced is None:
        raise TransformError(
            f"'{source_name}' is required for a numeric measure but is blank."
        )
    return coerced


def _apply_measure_op(op: str, values: List[Any], source_name: str) -> Any:
    if op == "count":
        return len(values)
    if op == "first":
        return values[0] if values else None
    if op == "last":
        return values[-1] if values else None
    numeric = [_coerce_measure_number(v, source_name) for v in values]
    if op == "sum":
        total = Decimal(0)
        for n in numeric:
            total += n
        return total
    if op == "min":
        return min(numeric)
    if op == "max":
        return max(numeric)
    raise ValueError(f"Unknown measure op {op!r}.")  # unreachable: validated at save time


def _metadata_row_projection(
    row: Dict[str, Any], group_by: Sequence[str], measure_aliases: Sequence[str]
) -> Dict[str, Any]:
    """A dropped/listed row is the GROUPED OUTPUT shape - groupBy columns
    plus measure aliases ONLY (never a carried column), matching AC-10-42's
    own ``{item_code, location_code, qty}`` example."""
    projected: Dict[str, Any] = {}
    for col in group_by:
        projected[col] = row.get(col)
    for alias in measure_aliases:
        projected[alias] = row.get(alias)
    return projected


def apply_combine(rows: Sequence[Dict[str, Any]], combine: Dict[str, Any]) -> CombineResult:
    """Reduce ``rows`` per ``combine`` (already validated at save time -
    trusted as-is here, mirroring ``lookups.merge_onto_rows``/``build_index``
    trusting a saved ``lookups`` config). Never mutates ``rows`` or any row
    in it - every stage works on a fresh copy.
    """
    computed_specs = combine.get("computed") or []
    require_specs = combine.get("require") or []
    measure_col = combine.get("measure")
    group_by = [str(c) for c in (combine.get("groupBy") or [])]
    measures_specs = combine.get("measures") or []
    carry_cols = [str(c) for c in (combine.get("carry") or [])]
    round_specs = combine.get("round") or []
    drop_specs = combine.get("drop") or []

    excluded_rows: List[Dict[str, Any]] = []
    survivors: List[Dict[str, Any]] = []

    for raw_row in rows:
        row: Dict[str, Any] = dict(raw_row)
        excluded = False
        reason: Optional[str] = None

        # ── computed (AC-10-77 stage 1) ─────────────────────────────────
        for spec in computed_specs:
            alias = spec.get("alias")
            formula = spec.get("formula")
            try:
                value = evaluate_formula(formula, None, facts=row)
            except FormulaError:
                # R11 ruling 1 - a computed formula that raises EXCLUDES the
                # row, by symmetry with a raising `require` rule (AC-10-77) -
                # a per-record failure never fails the whole set (R6).
                excluded = True
                reason = "computed_error"
                break
            row[alias] = value

        # ── require (AC-10-77 stage 2, first falsy excludes) ────────────
        # review round 3 (B2) - the result goes through the SAME strict
        # boolean coercion `not`/`and`/`or`/`if` already use
        # (``formula.to_bool_strict``), never a permissive second dialect:
        # a non-boolean result (a raw string/number column with no
        # comparison) is fail-closed exactly like a raising formula -
        # "require_error" - never silently treated as truthy (which would
        # exclude NOTHING, the exact opposite of a require gate's job).
        if not excluded:
            for spec in require_specs:
                formula = spec.get("formula")
                try:
                    result = evaluate_formula(formula, None, facts=row)
                    passed = to_bool_strict(result)
                except FormulaError:
                    excluded = True
                    reason = "require_error"
                    break
                if not passed:
                    excluded = True
                    reason = spec.get("reason")
                    break

        if excluded:
            entry: Dict[str, Any] = {}
            for col in group_by:
                if col in row:
                    entry[col] = row[col]
            # R11 ruling 4 - a computed-stage failure never resolved the
            # designated measure column, so it reports as absent (``None``),
            # even when an EARLIER computed step happened to set it.
            entry["measure"] = (
                None if reason == "computed_error"
                else (row.get(measure_col) if measure_col else None)
            )
            entry["reason"] = reason
            excluded_rows.append(entry)
            continue

        survivors.append(row)

    # ── group (AC-10-78, first-appearance order) ────────────────────────
    group_order: List[Tuple[Any, ...]] = []
    group_members: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for row in survivors:
        key = tuple(row.get(col) for col in group_by)
        if key not in group_members:
            group_order.append(key)
            group_members[key] = []
        group_members[key].append(row)

    grouped_rows: List[Dict[str, Any]] = []
    for key in group_order:
        members = group_members[key]
        out_row: Dict[str, Any] = {}
        for col, value in zip(group_by, key):
            out_row[col] = value
        for carry_col in carry_cols:
            out_row[carry_col] = members[0].get(carry_col)
        for measure_index, spec in enumerate(measures_specs):
            source = spec.get("source")
            op = spec.get("op")
            alias = spec.get("alias")
            values = [member.get(source) for member in members]
            try:
                out_row[alias] = _apply_measure_op(op, values, source)
            except TransformError as exc:
                # review round 4 (SF-1) - a RUNTIME non-numeric on a
                # sum/min/max measure (AC-10-76's own "a runtime non-numeric
                # still raises the normal named TransformError" text): wrap
                # with the measure's own list INDEX so a caller
                # (``preview_http``) can key the 422 to
                # ``combine.measures[i].source`` without re-walking
                # ``combine`` itself, mirroring ``CombineDropError`` exactly.
                raise CombineMeasureError(measure_index, str(source), str(exc)) from exc
        grouped_rows.append(out_row)

    # ── round (AC-10-79) ─────────────────────────────────────────────────
    rounded_count = 0
    for spec in round_specs:
        measure_alias = spec.get("measure")
        mode = spec.get("mode")
        dp = spec.get("dp") or 0
        if mode != "half_up":
            continue
        quant = Decimal(1).scaleb(-dp)
        for out_row in grouped_rows:
            if measure_alias not in out_row:
                continue
            current = out_row[measure_alias]
            try:
                current_decimal = (
                    current if isinstance(current, Decimal) else Decimal(str(current))
                )
            except (InvalidOperation, TypeError):
                continue
            rounded = current_decimal.quantize(quant, rounding=ROUND_HALF_UP)
            if rounded != current_decimal:
                rounded_count += 1
            out_row[measure_alias] = rounded

    # ── drop (AC-10-79, ordered, first match wins) ──────────────────────
    measure_aliases = [spec.get("alias") for spec in measures_specs]
    dropped: Dict[str, Dict[str, Any]] = {}
    output_rows: List[Dict[str, Any]] = []
    for out_row in grouped_rows:
        matched_spec: Optional[Dict[str, Any]] = None
        for drop_index, spec in enumerate(drop_specs):
            formula = spec.get("formula")
            # A drop formula that raises - OR evaluates to something other
            # than a genuine boolean, through the SAME strict coercion the
            # require stage now uses (review round 3, B2: the previous
            # permissive dialect treated any non-empty string as truthy,
            # which DROPPED EVERY GROUP for a formula that merely named a
            # string column) - is a named task error, never a silent keep
            # (AC-10-79): propagates as ``CombineDropError``, carrying the
            # rule's index/name so a caller need not re-walk ``combine``.
            try:
                result = evaluate_formula(formula, None, facts=out_row)
                matched = to_bool_strict(result)
            except FormulaError as exc:
                raise CombineDropError(
                    drop_index, str(spec.get("name")), str(exc)
                ) from exc
            if matched:
                matched_spec = spec
                break
        if matched_spec is None:
            output_rows.append(out_row)
            continue
        name = str(matched_spec.get("name"))
        bucket = dropped.setdefault(name, {"count": 0})
        bucket["count"] += 1
        if matched_spec.get("listRows"):
            rows_list = bucket.setdefault("rows", [])
            if len(rows_list) < DROPPED_ROWS_CAP:
                rows_list.append(
                    _metadata_row_projection(out_row, group_by, measure_aliases)
                )

    metadata = {
        "excludedRows": excluded_rows,
        "excludedCount": len(excluded_rows),
        "dropped": dropped,
        "roundedCount": rounded_count,
    }
    return CombineResult(rows=output_rows, metadata=metadata)


def _json_safe(value: Any) -> Any:
    """A ``Decimal`` (a rounded measure, AC-10-43) is not JSON-serializable
    as-is; every quantity this map ever projects is already a WHOLE number
    by the time it reaches here (the stock preset's own ``round`` rule), so
    a lossless ``Decimal`` -> ``int`` cast is always safe. Falls back to
    ``float`` for the (currently unreached, defence-in-depth) case of a
    genuinely fractional value, rather than raising deep inside a snapshot
    build."""
    if isinstance(value, Decimal):
        as_int = int(value)
        return as_int if Decimal(as_int) == value else float(value)
    return value


def _json_safe_row(row: Dict[str, Any]) -> Dict[str, Any]:
    return {key: _json_safe(value) for key, value in row.items()}


def apply_pull_metadata_map(
    combine_metadata: Dict[str, Any], metadata_map: Dict[str, Any]
) -> Dict[str, Any]:
    """sprint-5/10 S5b (AC-10-81, R11) - the ONE declarative map from this
    module's own generic ``{excludedRows, excludedCount, dropped,
    roundedCount}`` shape onto an entity's agreed per-entity wire names
    (e.g. stock's ``zeroPairs``/``negativePairs``/``negativePairList``/
    ``fractionalPairs``/``excludedNonzeroCount``). ``metadata_map`` lives on
    the entity's own ``EntityProfile.pull_metadata_map`` (``mapping.py``);
    this is the ONE place that reads it, so RENAMING a drop rule 422s at
    save time (the map itself would need editing to match) instead of
    silently changing what a consumer reads off the snapshot header.

    ``metadata_map`` shape::

        {"dropCounts": {<rule>: <wireKey>}, "dropRows": {<rule>: <wireKey>},
         "roundedCountAs": <wireKey>, "excludedNonzeroCountAs": <wireKey>}

    Every part is optional - an entity's map may use any subset. Rows under
    ``dropRows`` are JSON-sanitised (``Decimal`` -> ``int``, AC-10-43) since
    they land straight in a JSON column, unlike ``excludedRows``' own
    ``measure`` (already a plain ``float``/``None`` from ``number()``).

    ``excludedNonzeroCountAs`` counts every ``excludedRows`` entry whose
    ``measure`` is not exactly ``0`` - a MISSING/``None`` measure (a
    ``computed_error``, AC-10-77 ruling 4) counts as non-zero, fail-closed:
    an unresolved quantity is never provably safe to treat as zero.
    """
    dropped = combine_metadata.get("dropped") or {}
    excluded_rows = combine_metadata.get("excludedRows") or []
    out: Dict[str, Any] = {}
    for rule_name, wire_key in (metadata_map.get("dropCounts") or {}).items():
        out[wire_key] = (dropped.get(rule_name) or {}).get("count", 0)
    for rule_name, wire_key in (metadata_map.get("dropRows") or {}).items():
        rows = (dropped.get(rule_name) or {}).get("rows") or []
        out[wire_key] = [_json_safe_row(row) for row in rows]
    rounded_as = metadata_map.get("roundedCountAs")
    if rounded_as:
        out[rounded_as] = combine_metadata.get("roundedCount", 0)
    nonzero_as = metadata_map.get("excludedNonzeroCountAs")
    if nonzero_as:
        out[nonzero_as] = sum(1 for row in excluded_rows if row.get("measure") != 0)
    return out
