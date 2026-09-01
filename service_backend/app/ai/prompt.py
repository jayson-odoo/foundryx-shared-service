"""Prompt composition - SUBSTITUTION ONLY (AC-BI-08, Bi-D6).

Skill bodies are editable tenant config, so the standing anti-SSTI house rule
applies to them exactly as it does to email templates: composition goes through
`template_engine.render_tokens`, which does `{{ dotted.path }}` replacement and
nothing else. A body containing Jinja (`{% for %}`), an f-string, `${}` or any
eval-shaped construct is NEVER evaluated - it is inert text.

`escape=False` is deliberate and correct here: the output is a prompt for a
model, not HTML for a browser, so HTML-escaping would corrupt legitimate
characters (`<`, `&`, quotes) in the composed instructions. The XSS boundary
that `escape=True` protects does not exist on this path.
"""
from typing import Any, Dict, List

from app.template_engine.merge import render_tokens


def compose(body: str, variables: Dict[str, Any]) -> str:
    """Render a skill body against its variables.

    Missing token → '' (send-mode semantics): a half-composed prompt with a raw
    `{{ target_fields }}` visible would confuse the model far more than an
    empty slot.
    """
    facts = {k: _stringify(v) for k, v in (variables or {}).items()}
    return render_tokens(body, facts, mode="send", escape=False)


def _stringify(value: Any) -> str:
    """Flatten a variable to prompt text. Lists become bullet lines - the shape
    a field list or artifact list wants when injected into a prompt."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple)):
        return "\n".join(f"- {_stringify(item)}" for item in value)
    if isinstance(value, dict):
        return "\n".join(f"- {k}: {_stringify(v)}" for k, v in value.items())
    return str(value)


def field_schema(fields: List[Dict[str, str]], *, required: bool = False) -> Dict[str, Any]:
    """A JSON Schema object shaped by a target template's field list.

    Every field is a plain string. ``required`` controls schema pressure:

    - ``required=False`` (the TURN default) marks nothing required - coverage is
      incremental and a field the transcript hasn't reached yet is simply absent.
    - ``required=True`` (the EXTRACTION contract, AC-BI-24c) marks EVERY key
      required so the model returns a value for each field - including one it must
      synthesize across turns, or a negative answer like "no constraints". Without
      this pressure a shallow (thinking-off) pass silently omits synthesized
      fields (the live bug). This is NOT invention: the paired directive tells the
      model to emit an EMPTY string for a genuinely-ungrounded field, and our
      ``validate_submission(..., enforce_required=False)`` accepts those blanks -
      partial emit stays success (AC-BI-26). ``required`` here is only schema
      pressure toward completeness, never the promote-gate completeness check.
    """
    keys = [f["key"] for f in fields if f.get("key")]
    schema: Dict[str, Any] = {
        "type": "object",
        "properties": {
            f["key"]: {
                "type": "string",
                "description": f.get("label") or f["key"],
            }
            for f in fields
            if f.get("key")
        },
    }
    if required and keys:
        schema["required"] = keys
    return schema
