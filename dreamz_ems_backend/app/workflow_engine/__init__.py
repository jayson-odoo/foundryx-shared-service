"""Workflow engine (plan sprint-2/08) — the last core platform engine.

PLATFORM CORE, never an App Store module: lives in core ``public`` tables, perms
in the core CSV, present for every tenant. Modules EXTEND it by registering
``TriggerDef``/``ActionDef`` at install (slice 09+).
"""
from app.workflow_engine.registry import (
    ActionDef,
    NodeField,
    NodeOutput,
    TriggerDef,
    get_action,
    get_trigger,
    list_actions,
    list_triggers,
    register_action,
    register_trigger,
)
from app.workflow_engine.schemas import (
    WorkflowDefinitionModel,
    WorkflowValidationError,
    definition_issues,
    parse_definition,
    topo_order,
    validate_definition,
)

# Importing entity_events registers the after-commit drain on the Session class
# (the CRUD event bus → workflow matcher, slice 09). Side-effect import.
from app.workflow_engine import entity_events  # noqa: E402,F401
from app.workflow_engine.entity_events import emit_entity_event  # noqa: E402

__all__ = [
    "ActionDef",
    "TriggerDef",
    "NodeField",
    "NodeOutput",
    "get_action",
    "get_trigger",
    "list_actions",
    "list_triggers",
    "register_action",
    "register_trigger",
    "WorkflowDefinitionModel",
    "WorkflowValidationError",
    "definition_issues",
    "parse_definition",
    "topo_order",
    "validate_definition",
    "emit_entity_event",
]
