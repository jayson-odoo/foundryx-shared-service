"""Frontend ↔ backend form-doc contract parity (sprint-3/01).

The block document is a forever-contract mirrored in ``types/forms.ts``;
``validate_form_doc``/``validate_submission`` branch on the taxonomy sets.
Any drift (a type added on one side only) silently breaks the publish gate
or the renderer - this test pins the two copies together (branding-tokens
precedent, ``test_frontend_defaults_parity``).
"""
import re
from pathlib import Path

from app.form_engine.schemas import (
    CHOICE_FIELD_TYPES,
    DISPLAY_FIELD_TYPES,
    INPUT_FIELD_TYPES,
    NUMERIC_FIELD_TYPES,
    SUB_FIELD_TYPES,
)

TS_PATH = (
    Path(__file__).resolve().parents[2] / "service_frontend" / "types" / "forms.ts"
)


def _union_members(src: str, type_name: str) -> set:
    """Members of `export type X = 'a' | 'b' ...;` (multi- or single-line)."""
    match = re.search(rf"export type {type_name} =([^;]+);", src)
    assert match, f"{type_name} union not found in types/forms.ts"
    return set(re.findall(r"'([a-z]+)'", match.group(1)))


def test_field_taxonomy_parity():
    src = TS_PATH.read_text()
    ts_input = _union_members(src, "FormInputFieldType")
    ts_display = _union_members(src, "FormDisplayFieldType")
    ts_sub = _union_members(src, "FormSubFieldType")

    assert ts_input == set(INPUT_FIELD_TYPES)
    assert ts_display == set(DISPLAY_FIELD_TYPES)
    assert ts_sub == set(SUB_FIELD_TYPES)
    # Derived sets stay subsets of the input taxonomy.
    assert set(CHOICE_FIELD_TYPES) <= set(INPUT_FIELD_TYPES)
    assert set(NUMERIC_FIELD_TYPES) <= set(INPUT_FIELD_TYPES)
