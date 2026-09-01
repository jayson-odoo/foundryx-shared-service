"""Flat run-context (plan sprint-2/08 D7) - ONE dict the whole run reads.

Keys are dotted strings (``trigger.input.email``, ``nodes.<id>.messageId``) so
they merge-render through the template engine's ``render_tokens`` unchanged
(same flat-key lookup the Template engine uses). String config fields render
against this context; no eval, ever.
"""
from typing import Any, Dict, Optional

from app.template_engine.merge import render_tokens


def build_initial_context(
    *,
    triggered_by: str,
    actor_name: str = "",
    actor_email: str = "",
    actor_id: str = "",
    inputs: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    ctx: Dict[str, Any] = {
        "trigger.triggeredBy": triggered_by,
        "trigger.actor.name": actor_name,
        "trigger.actor.email": actor_email,
        "trigger.actor.id": actor_id,
    }
    for key, value in (inputs or {}).items():
        ctx[f"trigger.input.{key}"] = value
    return ctx


def set_node_output(ctx: Dict[str, Any], node_id: str, output: Dict[str, Any]) -> None:
    """Flatten an action's output under ``nodes.<id>.<key>``."""
    for key, value in (output or {}).items():
        ctx[f"nodes.{node_id}.{key}"] = value


def render_field(value: Any, ctx: Dict[str, Any]) -> str:
    """Merge-render a string config field against the flat context (no escape -
    these are values like email addresses / subjects, not HTML)."""
    if not isinstance(value, str):
        return "" if value is None else str(value)
    facts = {k: ("" if v is None else str(v)) for k, v in ctx.items()}
    return render_tokens(value, facts, mode="send", escape=False)
