"""IntakeDefinition registry — the generic Conversational-Intake engine (D18,
AC-A-13..16).

An ``IntakeDefinition`` binds a stable ``key`` to a form_engine ``target_schema``
(the captured/missing surface), a ``completion_rule`` (captured/missing over that
schema), an ``on_complete_sink`` (the ONLY promotion path), and an ``agent_role``.
**Ideation is exactly one definition** (``key="ideation"``); a future "form over
WhatsApp" flow is a NEW registry entry — no new conversation code (D18).

Everything here is DETERMINISTIC (no LLM, D20): field-extraction already happened
in sorento's brain and arrives as structured ``fields``; this module only merges
against the schema, computes completion, and echoes templated text.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Tuple

from app.form_engine.schemas import FormDocument

# completion_rule(captured_json) -> (captured, missing)
CompletionRule = Callable[[Dict[str, object]], Tuple[Dict[str, object], List[str]]]
# on_complete_sink(db, idea, tenant_id) -> link (str | None); idempotent.
OnCompleteSink = Callable[..., Optional[str]]


@dataclass(frozen=True)
class IntakeDefinition:
    key: str
    target_schema: FormDocument
    completion_rule: CompletionRule
    on_complete_sink: OnCompleteSink
    agent_role: str


_REGISTRY: Dict[str, IntakeDefinition] = {}


def register_intake_definition(definition: IntakeDefinition) -> None:
    """Register (idempotently) an intake definition by key. Re-registration with
    the same key overwrites — boot hooks run more than once."""
    _REGISTRY[definition.key] = definition


def get_intake_definition(key: str) -> Optional[IntakeDefinition]:
    return _REGISTRY.get(key)


# ── the ideation intake definition ────────────────────────────────────────────

IDEATION_INTAKE_KEY = "ideation"

# Human-readable labels for each captured field — used verbatim in the
# deterministic reply_text templates (no LLM). Kept in sync with the schema below.
IDEATION_FIELD_LABELS: Dict[str, str] = {
    "problem": "Problem statement",
    "proposed_solution": "Proposed solution",
    "impact": "Impact",
    "department": "Department",
}


def _ideation_target_schema() -> FormDocument:
    """The Idea-capture form document (Page -> Section -> Field), a valid
    ``validate_form_doc`` document (AC-A-14). All fields are required — they
    are the intake's captured/missing surface. NB: no ``module`` (business
    submitters don't know modules) and no ``who`` (the submitter identity already
    answers that); the required set is problem / proposed_solution / impact /
    department."""
    return FormDocument.model_validate(
        {
            "schemaVersion": 1,
            "pages": [
                {
                    "id": "page-capture",
                    "title": "Capture",
                    "sections": [
                        {
                            "id": "sec-idea",
                            "title": "Idea",
                            "fields": [
                                {
                                    "id": "f-problem",
                                    "type": "textarea",
                                    "key": "problem",
                                    "label": IDEATION_FIELD_LABELS["problem"],
                                    "required": True,
                                },
                                {
                                    "id": "f-proposed-solution",
                                    "type": "textarea",
                                    "key": "proposed_solution",
                                    "label": IDEATION_FIELD_LABELS["proposed_solution"],
                                    "required": True,
                                },
                                {
                                    "id": "f-impact",
                                    "type": "textarea",
                                    "key": "impact",
                                    "label": IDEATION_FIELD_LABELS["impact"],
                                    "required": True,
                                },
                                {
                                    "id": "f-department",
                                    "type": "text",
                                    "key": "department",
                                    "label": IDEATION_FIELD_LABELS["department"],
                                    "required": True,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )


def _is_answered(value: object) -> bool:
    """A key is answered when it has a non-empty, non-whitespace value."""
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, dict)):
        return len(value) > 0
    return True


def make_completion_rule(schema: FormDocument) -> CompletionRule:
    """A completion rule over ``schema``: ``captured`` = answered input keys
    (schema order), ``missing`` = required input keys not yet answered (schema
    order). Deterministic; ``missing == []`` means the intake is complete."""
    input_fields = schema.input_fields()
    ordered_keys = [f.key for f in input_fields if f.key]
    required_keys = [f.key for f in input_fields if f.key and f.required]

    def rule(captured_json: Dict[str, object]) -> Tuple[Dict[str, object], List[str]]:
        answers = captured_json or {}
        captured = {
            k: answers[k]
            for k in ordered_keys
            if k in answers and _is_answered(answers[k])
        }
        missing = [k for k in required_keys if k not in captured]
        return captured, missing

    return rule


def register_ideation_intake() -> None:
    """Register the single ``ideation`` intake definition (idempotent). Called at
    module boot from ``register_engine_entities``."""
    from .sinks import ideation_on_complete_sink

    schema = _ideation_target_schema()
    register_intake_definition(
        IntakeDefinition(
            key=IDEATION_INTAKE_KEY,
            target_schema=schema,
            completion_rule=make_completion_rule(schema),
            on_complete_sink=ideation_on_complete_sink,
            agent_role="ideation_intake",
        )
    )
