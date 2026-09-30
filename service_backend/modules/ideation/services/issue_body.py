"""GitHub issue body for the BR "Send to build" hand-off (plan section 6.1).

A pure function over the STAMPED template doc, the BR answers, the linked ideas
and the grill transcript - it never reads a hardcoded field key (the template is
versioned and tenant-editable). Output carries no em/en dash and stays under
GitHub's 65536-char limit by truncating the transcript first.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence

from app.form_engine.schemas import FormDocument

# GitHub rejects bodies over 65536 chars; keep headroom.
BODY_LIMIT = 65000
NOT_PROVIDED = "(not provided)"
TRUNCATED_NOTE = "(transcript truncated)"


def _clean(text: str) -> str:
    return (text or "").replace("—", "-").replace("–", "-")


def _answer_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if isinstance(value, (list, tuple)):
        return ", ".join(_answer_text(v) for v in value if _answer_text(v))
    if isinstance(value, dict):
        return ", ".join(
            f"{k}: {_answer_text(v)}" for k, v in value.items() if _answer_text(v)
        )
    return str(value)


def render_issue_body(
    doc: Dict[str, Any],
    answers: Dict[str, Any],
    ideas: Sequence[Dict[str, Any]],
    grill_messages: Sequence[Dict[str, str]],
    br_url: str,
    br_id: str,
    product_id: str,
) -> str:
    """``ideas`` items: ``{number, title, up, down}``; ``grill_messages`` items:
    ``{role, content}``."""
    form = FormDocument.model_validate(doc)
    parts: List[str] = []
    for field in form.input_fields():
        text = _answer_text((answers or {}).get(field.key)) if field.key else ""
        parts.append(f"## {_clean(field.label or field.key or '')}\n\n{_clean(text) or NOT_PROVIDED}")

    if ideas:
        lines = [
            "- "
            + " ".join(
                t for t in (_clean(i.get("number") or ""), _clean(i.get("title") or "")) if t
            )
            + f" (+{int(i.get('up') or 0)} / -{int(i.get('down') or 0)})"
            for i in ideas
        ]
    else:
        lines = [NOT_PROVIDED]
    parts.append("## Linked ideas\n\n" + "\n".join(lines))

    tail = (
        f"## Links\n\nBusiness requirement: {br_url}\n\n"
        f"<!-- br-id: {br_id} -->\n<!-- br-product: {product_id} -->\n"
    )

    head = "\n\n".join(parts)
    transcript = ""
    if grill_messages:
        turns = [f"**{m.get('role', '')}:** {_clean(m.get('content') or '')}" for m in grill_messages]
        transcript = "## Grill transcript\n\n" + "\n\n".join(turns)
        budget = BODY_LIMIT - len(head) - len(tail) - 8
        if len(transcript) > budget:
            keep = max(budget - len(TRUNCATED_NOTE) - 2, 0)
            transcript = transcript[:keep].rstrip() + "\n\n" + TRUNCATED_NOTE
    sections = [head] + ([transcript] if transcript else []) + [tail]
    return "\n\n".join(s.rstrip("\n") for s in sections) + "\n"
