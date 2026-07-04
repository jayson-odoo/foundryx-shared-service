"""Merge-field micro-renderer (plan 07 D5) — ``{{ dotted.path }}`` ONLY.

Substitution, nothing else: no expressions, no filters, no loops, no
partials. Tenant-authored template content NEVER reaches Jinja2 (SSTI → RCE);
this module is the entire templating language. Logic lives structurally —
block-level visibility via the rule engine, not string-spliced conditionals.

ONE renderer system-wide: the status engine's inline notification templates
render through here too (D10).
"""

import html
import re
from typing import Dict, Set
from urllib.parse import urlparse

# Dotted identifier between double braces — same grammar as the frontend
# merge-field-editor (lib/template-doc.ts collectMergeTokens).
TOKEN_RE = re.compile(r"\{\{\s*([\w.]+)\s*\}\}")


def render_tokens(
    value: str,
    facts: Dict[str, str],
    *,
    mode: str = "send",
    escape: bool = True,
) -> str:
    """Substitute ``{{token}}`` occurrences from ``facts``.

    Missing fact: '' in send mode (never leak raw tokens to a recipient);
    a loud ``⟦token?⟧`` marker in preview mode. Values are HTML-escaped by
    default (XSS via attendee-controlled values like names).
    """

    def _sub(match: re.Match) -> str:
        key = match.group(1)
        if key not in facts:
            return f"⟦{key}?⟧" if mode == "preview" else ""
        text = str(facts[key])
        return html.escape(text, quote=True) if escape else text

    return TOKEN_RE.sub(_sub, value)


def render_url(value: str, facts: Dict[str, str], *, mode: str = "send") -> str:
    """Merge + validate an href (D5): only http(s)/mailto survive.

    A merge fact or literal resolving to ``javascript:`` (or any other
    scheme) collapses to '#' — link targets are recipient-facing.
    """
    merged = render_tokens(value, facts, mode=mode, escape=False)
    if not merged:
        return "#"
    try:
        scheme = urlparse(merged).scheme.lower()
    except ValueError:
        return "#"
    if scheme and scheme not in ("http", "https", "mailto"):
        return "#"
    return merged


def collect_tokens(*values: str) -> Set[str]:
    """Every merge token used across the given strings (required-fact gate)."""
    tokens: Set[str] = set()
    for value in values:
        if value:
            tokens.update(TOKEN_RE.findall(value))
    return tokens
