"""Form block-document schema + publish-time validation (plan sprint-3/01 D6/D7/D8/D9).

The form document is the forever-contract block document — mirror of the frontend
``types/forms.ts``: ``schemaVersion`` at the root, **Page → Section → Field** (D6).
Stored camelCase in ``draft_definition_json`` verbatim (workflow_engine precedent:
the JSON we accept is the JSON we persist), so the Pydantic models use camelCase
field names / aliases and ``model_dump(by_alias=True)`` round-trips the wire exactly.
``extra="forbid"`` everywhere — the doc is a forever-contract, so unknown keys must
422 at save rather than silently rot into the stored payload.

``validate_form_doc`` is the PUBLISH GATE (D9), the server-authoritative twin of
the client mirror ``lib/form-doc.ts validateFormDoc`` — keep PARITY (rule-for-rule;
the prose of each problem string need not match). It returns a list of problem
strings; ``[]`` means publishable.

Field taxonomy (D7) is the full v1 set. Choice options are static-only (D8),
shaped ``{kind:'static', items:[...]}`` so an ``entity`` kind slots in later
without a doc break.

Note on condition validation: a form's visibility conditions reference
``answers.<key>`` facts that are DYNAMIC per-document — there is no registered
``FactSource`` for them (the rule engine's ``validate_tree``/``fact_map`` operate
over the code-side fact registry). So we do NOT call ``rule_engine.schemas.
validate_tree`` here; instead we use ``rule_engine.evaluator.collect_fact_keys``
to extract every referenced fact and enforce the structural rule that each one is
an ``answers.<key>`` of an EARLIER conditionable field (document order). Runtime
stays fail-closed (the submit pipeline's ``evaluate`` handles stale/garbage trees).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Literal, Optional, Set

from pydantic import BaseModel, ConfigDict, Field

from app.form_engine.computed import (
    ComputedExpressionError,
    aggregate_refs,
    field_refs,
    parse_expression,
)
from app.rule_engine.evaluator import collect_fact_keys

FORM_SCHEMA_VERSION = 1

# ---- field taxonomy (D7 — full v1; `payment` deferred BL-086) ----

# Answer-bearing field types.
INPUT_FIELD_TYPES: Set[str] = {
    "text",
    "textarea",
    "email",
    "phone",
    "url",
    "number",
    "integer",
    "select",
    "multiselect",
    "radio",
    "checkboxes",
    "yesno",
    "date",
    "datetime",
    "file",
    "signature",
    "rating",
    "address",
    "repeater",
    "table",
    "computed",
}

# Column types a Table block may carry (line items — scalar + read-only computed
# + a fixed-constant column). `select`/`date` reuse the scalar inputs.
TABLE_COLUMN_TYPES: Set[str] = {"text", "number", "integer", "select", "date", "computed", "fixed"}

# Display-only field types — render, collect nothing (carry no key/required).
DISPLAY_FIELD_TYPES: Set[str] = {"heading", "paragraph", "divider"}

ALL_FIELD_TYPES: Set[str] = INPUT_FIELD_TYPES | DISPLAY_FIELD_TYPES

# Choice fields draw their value(s) from a static option list (D8).
CHOICE_FIELD_TYPES: Set[str] = {"select", "multiselect", "radio", "checkboxes"}

# Field types whose answers feed a computed expression (mirror of frontend).
NUMERIC_FIELD_TYPES: Set[str] = {"number", "integer", "rating", "computed"}

# Sub-field types a repeater row may carry (no composites/uploads/display;
# sub-field conditions = BL-089).
SUB_FIELD_TYPES: Set[str] = {
    "text",
    "textarea",
    "email",
    "phone",
    "url",
    "number",
    "select",
    "radio",
    "yesno",
    "date",
    "rating",
}

# Field types usable as rule-engine condition facts (composites/uploads/display
# excluded v1 — mirror of the frontend CONDITIONABLE_TYPES).
CONDITIONABLE_TYPES: Set[str] = {
    "text",
    "textarea",
    "email",
    "phone",
    "url",
    "number",
    "integer",
    "select",
    "multiselect",
    "radio",
    "checkboxes",
    "yesno",
    "date",
    "datetime",
    "rating",
    "computed",
}

# Answer key grammar — letters/digits/underscores, not starting with a digit.
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Conditions tree (rule-engine group) — shape validated by the rule engine's
# own grammar at evaluate time; here we only walk it for fact keys.
Conditions = Optional[Dict[str, Any]]


# ---- base config ----


class _Base(BaseModel):
    """Strict camelCase-in/camelCase-out base. ``extra="forbid"`` rejects any
    stray key — the stored doc is a forever-contract, garbage must 422 at save."""

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


# ---- choice options (D8 — static-only v1) ----


class FormChoiceItem(_Base):
    value: str
    label: str


class FormStaticOptions(_Base):
    kind: Literal["static"] = "static"
    items: List[FormChoiceItem] = Field(default_factory=list)


# `{kind:'entity', …}` lands additively (BL-087) — for now the union is one arm.
FormChoiceOptions = FormStaticOptions


# ---- per-type validation config bags ----


class FormTextValidation(_Base):
    """Text-family constraints (``text``/``textarea``/``email``/``phone``/``url``)."""

    min_length: Optional[int] = Field(default=None, alias="minLength")
    max_length: Optional[int] = Field(default=None, alias="maxLength")
    # ECMAScript-flavored regex source (no flags) — compiled under Python `re`
    # at the publish gate (re.error → problem).
    pattern: Optional[str] = None
    # Shown when `pattern` rejects — required alongside it (publish-gate enforced).
    pattern_message: Optional[str] = Field(default=None, alias="patternMessage")


class FormNumberValidation(_Base):
    min: Optional[float] = None
    max: Optional[float] = None
    step: Optional[float] = None
    decimals: Optional[int] = None
    integer: Optional[bool] = None


class FormFileValidation(_Base):
    max_size_mb: Optional[float] = Field(default=None, alias="maxSizeMb")
    allowed_mimes: Optional[List[str]] = Field(default=None, alias="allowedMimes")
    max_count: Optional[int] = Field(default=None, alias="maxCount")


class FormRatingConfig(_Base):
    max: int


class FormHeadingConfig(_Base):
    level: Literal[1, 2, 3] = 2


class FormComputedConfig(_Base):
    expression: str = ""


# ---- the document tree (D6) ----


class FormSubField(_Base):
    """A repeater row's sub-field — restricted type set, no conditions (BL-089)."""

    id: str
    type: str
    key: str
    label: str
    required: Optional[bool] = None
    placeholder: Optional[str] = None
    text: Optional[FormTextValidation] = None
    number: Optional[FormNumberValidation] = None
    options: Optional[FormChoiceOptions] = None
    rating: Optional[FormRatingConfig] = None


class FormRepeaterConfig(_Base):
    fields: List[FormSubField] = Field(default_factory=list)
    min_rows: Optional[int] = Field(default=None, alias="minRows")
    max_rows: Optional[int] = Field(default=None, alias="maxRows")


class FormTableColumn(_Base):
    """A Table column (line items). ``computed`` columns are read-only, evaluated
    PER ROW over that row's earlier columns; ``summarize`` adds a column total."""

    id: str
    type: str
    key: str
    label: str
    required: Optional[bool] = None
    placeholder: Optional[str] = None
    options: Optional[FormChoiceOptions] = None
    number: Optional[FormNumberValidation] = None
    computed: Optional[FormComputedConfig] = None
    summarize: Optional[Literal["sum", "avg", "count", "min", "max"]] = None
    decimals: Optional[int] = None
    integer: Optional[bool] = None
    # `fixed` column — the constant stamped into every row (read-only).
    fixed_value: Optional[str] = Field(default=None, alias="fixedValue")


class FormTableConfig(_Base):
    columns: List[FormTableColumn] = Field(default_factory=list)
    show_row_numbers: Optional[bool] = Field(default=None, alias="showRowNumbers")
    min_rows: Optional[int] = Field(default=None, alias="minRows")
    max_rows: Optional[int] = Field(default=None, alias="maxRows")


class FormField(_Base):
    """One leaf of the form. ``key`` is the STABLE answer key — relabel never
    breaks refs (workflow-node-id precedent), unique across the doc. Display
    fields carry no ``key``/``required``. Exactly one type-specific bag applies
    per type — the publish gate enforces which."""

    id: str
    type: str
    key: Optional[str] = None
    label: str
    required: Optional[bool] = None
    placeholder: Optional[str] = None
    help_text: Optional[str] = Field(default=None, alias="helpText")
    # Rule-engine visibility — facts namespace `answers.<fieldKey>`, EARLIER
    # fields only (document order — publish-gate enforced, D14).
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")

    # -- type-specific bags --
    text: Optional[FormTextValidation] = None
    number: Optional[FormNumberValidation] = None
    options: Optional[FormChoiceOptions] = None
    file: Optional[FormFileValidation] = None
    rating: Optional[FormRatingConfig] = None
    heading: Optional[FormHeadingConfig] = None
    repeater: Optional[FormRepeaterConfig] = None
    table: Optional[FormTableConfig] = None
    computed: Optional[FormComputedConfig] = None


class FormSection(_Base):
    """Titled group; optional 2-column layout; conditionally visible."""

    id: str
    title: Optional[str] = None
    description: Optional[str] = None
    two_column: Optional[bool] = Field(default=None, alias="twoColumn")
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")
    fields: List[FormField] = Field(default_factory=list)


class FormPage(_Base):
    """Wizard step — per-page client validation before advancing."""

    id: str
    title: Optional[str] = None
    sections: List[FormSection] = Field(default_factory=list)


class FormDocument(_Base):
    schema_version: int = Field(default=FORM_SCHEMA_VERSION, alias="schemaVersion")
    pages: List[FormPage] = Field(default_factory=list)

    def iter_fields(self):
        """Every field in DOCUMENT ORDER (conditions look backwards only, D14)."""
        for page in self.pages:
            for section in page.sections:
                for field in section.fields:
                    yield page, section, field

    def input_fields(self) -> List[FormField]:
        return [f for _p, _s, f in self.iter_fields() if f.type in INPUT_FIELD_TYPES]


# ---- helpers ----


def _coerce_doc(doc: "FormDocument | Dict[str, Any]") -> FormDocument:
    """Accept either a typed model or the raw camelCase wire dict."""
    if isinstance(doc, FormDocument):
        return doc
    return FormDocument.model_validate(doc)


def _is_display(field: FormField) -> bool:
    return field.type in DISPLAY_FIELD_TYPES


def _is_input(field: FormField) -> bool:
    return field.type in INPUT_FIELD_TYPES


def _condition_fact_keys(tree: Conditions) -> List[str]:
    """Bare answer keys referenced by a conditions tree (LHS + cross-fact RHS),
    with the ``answers.`` namespace stripped. Non-``answers.`` facts pass
    through as-is so they fail the earlier-key check (and surface a problem)."""
    keys: List[str] = []
    for raw in collect_fact_keys(tree):
        keys.append(raw[len("answers.") :] if raw.startswith("answers.") else raw)
    return keys


# ---- publish gate (D9) — server twin of lib/form-doc.ts validateFormDoc ----


def validate_form_doc(doc: "FormDocument | Dict[str, Any]") -> List[str]:
    """Problems blocking publish; empty list = publishable. Parity with the
    client mirror (rules, not message prose)."""
    try:
        form = _coerce_doc(doc)
    except Exception as exc:  # noqa: BLE001 — a malformed doc shape is one problem
        return [f"The form document is malformed: {exc}"]

    problems: List[str] = []

    if not form.pages:
        return ["The form needs at least one page."]

    # Duplicate / missing / malformed keys across the WHOLE doc.
    seen_keys: Set[str] = set()
    for _page, _section, field in form.iter_fields():
        if _is_display(field):
            continue  # display fields need no key
        name = field.label or field.type
        key = (field.key or "").strip()
        if not key:
            problems.append(f'"{name}" is missing an answer key.')
            continue
        if not _KEY_RE.match(key):
            problems.append(
                f'Answer key "{key}" must be letters, digits and underscores.'
            )
        if key in seen_keys:
            problems.append(f'Duplicate answer key "{key}".')
        seen_keys.add(key)

    # No empty page (zero fields across its sections).
    for index, page in enumerate(form.pages):
        field_count = sum(len(section.fields) for section in page.sections)
        if field_count == 0:
            problems.append(f"Page {index + 1} is empty.")

    # Per-field rules + earlier-only condition refs, in document order. A
    # section's conditions see only fields BEFORE it; a field's see all prior.
    # `earlier_keys` = every prior input key (computed-ref + general scope);
    # `earlier_conditionable` = the subset whose type can be a condition fact
    # — the gate forbids conditioning on file/signature/address/repeater/etc.
    earlier_keys: Set[str] = set()
    earlier_conditionable: Set[str] = set()
    # repeaterKey → {subKey: subType} for earlier repeaters (aggregate gate).
    earlier_repeaters: Dict[str, Dict[str, str]] = {}
    for page in form.pages:
        for section in page.sections:
            for bare in _condition_fact_keys(section.conditions_json):
                if bare not in earlier_conditionable:
                    problems.append(
                        f'A section condition references "{bare}", '
                        "which is not an earlier field."
                    )
            for field in section.fields:
                name = field.label or field.key or field.type

                for bare in _condition_fact_keys(field.conditions_json):
                    if bare not in earlier_conditionable:
                        problems.append(
                            f'"{name}" has a condition referencing "{bare}", '
                            "which is not an earlier field."
                        )

                if field.type in CHOICE_FIELD_TYPES:
                    items = field.options.items if field.options else []
                    if not items:
                        problems.append(f'"{name}" needs at least one option.')
                    values = [item.value.strip() for item in items]
                    if any(not v for v in values):
                        problems.append(f'"{name}" has an option without a value.')
                    if len(set(values)) != len(values):
                        problems.append(f'"{name}" has duplicate option values.')

                if field.type == "rating" and (
                    field.rating is None or field.rating.max < 1
                ):
                    problems.append(f'"{name}" needs a rating scale of at least 1.')

                if field.type == "repeater":
                    subs = field.repeater.fields if field.repeater else []
                    if not subs:
                        problems.append(f'"{name}" needs at least one sub-field.')
                    sub_keys = [(s.key or "").strip() for s in subs]
                    if any(not k for k in sub_keys):
                        problems.append(f'"{name}" has a sub-field without a key.')
                    if len(set(sub_keys)) != len(sub_keys):
                        problems.append(f'"{name}" has duplicate sub-field keys.')
                    if field.repeater is not None:
                        lo, hi = field.repeater.min_rows, field.repeater.max_rows
                        if lo is not None and hi is not None and lo > hi:
                            problems.append(
                                f'"{name}" has min rows greater than max rows.'
                            )

                if field.type == "table":
                    _validate_table_columns(field, name, problems)

                if field.type == "computed":
                    expr = (
                        (field.computed.expression or "").strip()
                        if field.computed
                        else ""
                    )
                    if not expr:
                        problems.append(f'"{name}" is missing its expression.')
                    else:
                        try:
                            parse_expression(expr)
                            for ref in field_refs(expr):
                                if ref not in earlier_keys:
                                    problems.append(
                                        f'"{name}" references "{ref}", '
                                        "which is not an earlier field."
                                    )
                                elif ref not in _numeric_keys(form):
                                    problems.append(
                                        f'"{name}" references "{ref}", '
                                        "which is not numeric."
                                    )
                            # Aggregate refs (sum/avg/min/max/count over a
                            # repeater column) — the repeater must be an EARLIER
                            # repeater field; the column must be a numeric
                            # sub-field (count needs only the repeater).
                            for agg in aggregate_refs(expr):
                                cols = earlier_repeaters.get(agg.repeater_key)
                                if cols is None:
                                    problems.append(
                                        f'"{name}" aggregates "{agg.repeater_key}", '
                                        "which is not an earlier repeater field."
                                    )
                                    continue
                                if agg.func == "count":
                                    continue
                                if agg.sub_key not in cols:
                                    problems.append(
                                        f'"{name}" aggregates column "{agg.sub_key}", '
                                        f'which is not a sub-field of "{agg.repeater_key}".'
                                    )
                                elif cols[agg.sub_key] not in NUMERIC_FIELD_TYPES:
                                    problems.append(
                                        f'"{name}" aggregates "{agg.sub_key}", '
                                        "which is not a numeric column."
                                    )
                        except ComputedExpressionError as exc:
                            problems.append(
                                f'"{name}" has an invalid expression: {exc}'
                            )

                if field.text is not None and field.text.pattern:
                    try:
                        re.compile(field.text.pattern)
                    except re.error:
                        problems.append(f'"{name}" has an invalid pattern.')
                    if not (field.text.pattern_message or "").strip():
                        problems.append(f'"{name}" needs a message for its pattern.')

                if field.key and _is_input(field):
                    earlier_keys.add(field.key)
                    if field.type in CONDITIONABLE_TYPES:
                        earlier_conditionable.add(field.key)
                    if field.type == "repeater" and field.repeater:
                        earlier_repeaters[field.key] = {
                            s.key: s.type for s in field.repeater.fields if s.key
                        }
                    if field.type == "table" and field.table:
                        # Table columns are aggregatable too — `sum(table.col)`.
                        earlier_repeaters[field.key] = {
                            c.key: c.type for c in field.table.columns if c.key
                        }

    return problems


def _validate_table_columns(field: "FormField", name: str, problems: List[str]) -> None:
    """Publish-gate rules for a Table block (sprint-3/02): non-empty columns,
    unique keys, computed columns reference EARLIER numeric columns in the same
    table (document order bans cycles + forward refs)."""
    cols = field.table.columns if field.table else []
    if not cols:
        problems.append(f'"{name}" needs at least one column.')
    keys = [(c.key or "").strip() for c in cols]
    if any(not k for k in keys):
        problems.append(f'"{name}" has a column without a key.')
    if len(set(keys)) != len(keys):
        problems.append(f'"{name}" has duplicate column keys.')
    if field.table is not None:
        lo, hi = field.table.min_rows, field.table.max_rows
        if lo is not None and hi is not None and lo > hi:
            problems.append(f'"{name}" has min rows greater than max rows.')

    earlier_numeric: Set[str] = set()
    for col in cols:
        if col.type == "computed":
            expr = (col.computed.expression or "").strip() if col.computed else ""
            if not expr:
                problems.append(f'"{name}" column "{col.key}" is missing its expression.')
            else:
                try:
                    parse_expression(expr)
                    for ref in field_refs(expr):
                        if ref not in earlier_numeric:
                            problems.append(
                                f'"{name}" column "{col.key}" references "{ref}", '
                                "which is not an earlier numeric column."
                            )
                except ComputedExpressionError as exc:
                    problems.append(
                        f'"{name}" column "{col.key}" has an invalid expression: {exc}'
                    )
        # number/computed columns AND a fixed numeric constant are referenceable.
        if col.key and (col.type in NUMERIC_FIELD_TYPES or col.type == "fixed"):
            earlier_numeric.add(col.key)


def _numeric_keys(form: FormDocument) -> Set[str]:
    return {
        f.key
        for f in form.input_fields()
        if f.key and f.type in NUMERIC_FIELD_TYPES
    }
