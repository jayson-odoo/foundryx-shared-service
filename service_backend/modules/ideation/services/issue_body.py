"""GitHub issue body for the BR "Send to build" hand-off (plan section 6.1).

A pure function over the STAMPED template doc, the BR answers, the linked ideas
and the grill transcript - it never reads a hardcoded field key (the template is
versioned and tenant-editable). All tenant text is neutralised (``clean_text``):
no em/en dash, no live HTML-comment marker, no @mention and no #123 cross
reference. The body stays under GitHub's 65536-char limit: the transcript is cut
first, then the answers, and the two machine markers are always the last lines.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Sequence

from app.form_engine.schemas import FormDocument

# GitHub rejects bodies over 65536 chars; keep headroom.
BODY_LIMIT = 65000
NOT_PROVIDED = "(not provided)"
TRUNCATED_NOTE = "(transcript truncated)"
HEAD_TRUNCATED_NOTE = "(truncated)"
_ZWSP = "​"

_MENTION = re.compile(r"@(?=[A-Za-z0-9_-])")
_XREF = re.compile(r"#(?=\d)")


def clean_text(text: str) -> str:
    """Neutralise tenant text: dashes to ``-``, ``<!--`` defused (no forged
    marker), ``@name`` and ``#123`` / ``owner/repo#12`` broken with a zero-width
    space so GitHub does not notify or cross-link."""
    out = (text or "").replace("\u2014", "-").replace("\u2013", "-")
    out = out.replace("<!", "<!" + _ZWSP)
    # Break the marker words too, so tenant text can neither forge a marker nor
    # match the crash-recovery search for ``br-id: <id>``.
    out = out.replace("br-id:", "br-" + _ZWSP + "id:").replace("br-product:", "br-" + _ZWSP + "product:")
    out = _MENTION.sub("@" + _ZWSP, out)
    return _XREF.sub("#" + _ZWSP, out)


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


def _cap(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return text[: max(cap - len(HEAD_TRUNCATED_NOTE) - 1, 0)].rstrip() + " " + HEAD_TRUNCATED_NOTE


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
    fields = [
        (clean_text(f.label or f.key or ""), clean_text(_answer_text((answers or {}).get(f.key)) if f.key else ""))
        for f in form.input_fields()
    ]

    if ideas:
        idea_lines = [
            "- "
            + " ".join(
                t for t in (clean_text(i.get("number") or ""), clean_text(i.get("title") or "")) if t
            )
            + f" (+{int(i.get('up') or 0)} / -{int(i.get('down') or 0)})"
            for i in ideas
        ]
    else:
        idea_lines = [NOT_PROVIDED]

    tail = (
        f"## Links\n\nBusiness requirement: {br_url}\n\n"
        f"<!-- br-id: {br_id} -->\n<!-- br-product: {product_id} -->\n"
    )
    ideas_section = "## Linked ideas\n\n" + "\n".join(idea_lines)

    def head_for(cap: int) -> str:
        parts = [f"## {label}\n\n{_cap(text, cap) or NOT_PROVIDED}" for label, text in fields]
        return "\n\n".join(parts + [ideas_section])

    budget = BODY_LIMIT - len(tail) - 8
    cap = max(budget, 200)
    head = head_for(cap)
    while len(head) > budget and cap > 50:
        cap = max(int(cap * 0.7), 50)
        head = head_for(cap)
    if len(head) > budget:  # pathological (huge idea list): cut the tail of the head
        head = head[: max(budget - len(HEAD_TRUNCATED_NOTE) - 2, 0)].rstrip() + "\n\n" + HEAD_TRUNCATED_NOTE

    transcript = ""
    if grill_messages:
        turns = [
            f"**{m.get('role', '')}:** {clean_text(m.get('content') or '')}" for m in grill_messages
        ]
        transcript = "## Grill transcript\n\n" + "\n\n".join(turns)
        room = budget - len(head) - 2
        if len(transcript) > room:
            keep = max(room - len(TRUNCATED_NOTE) - 2, 0)
            transcript = (
                transcript[:keep].rstrip() + "\n\n" + TRUNCATED_NOTE if keep > 0 else ""
            )
    sections = [head] + ([transcript] if transcript else []) + [tail]
    return "\n\n".join(s.rstrip("\n") for s in sections) + "\n"
