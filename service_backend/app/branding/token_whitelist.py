"""Branding token whitelist (plan sprint-2/03) — THE canonical source.

Which theme variables a tenant may override, their FoundryX defaults, validation
and CSS generation. Mirrors the Layer-1 ``--foundryx-*`` primitives in the
frontend's ``css/foundryx-tokens.css``; the frontend keeps a display mirror in
``lib/branding-tokens.ts`` — keep both in sync when a primitive is added.

Deliberately EXCLUDED:
- ``-transparent`` variants — derived (base color @ 0.2 alpha), see
  ``derive_transparent``;
- ``--foundryx-white`` / ``--foundryx-black`` — true constants.
"""
import re
from typing import Dict, List, Optional, Tuple

ThemeTokens = Dict[str, str]
TokensDoc = Dict[str, ThemeTokens]  # {"light": {...}, "dark": {...}}

# (key, group) — order drives template key order and CSS emission order.
TOKEN_DEFS: List[Tuple[str, str]] = [
    # Brand
    ("primary", "brand"),
    ("primary-active", "brand"),
    ("primary-accent", "brand"),
    ("primary-soft", "brand"),
    # Status
    ("success", "status"),
    ("success-active", "status"),
    ("success-accent", "status"),
    ("success-soft", "status"),
    ("danger", "status"),
    ("danger-active", "status"),
    ("danger-accent", "status"),
    ("danger-soft", "status"),
    ("info", "status"),
    ("info-active", "status"),
    ("info-accent", "status"),
    ("info-soft", "status"),
    ("warning", "status"),
    ("warning-active", "status"),
    ("warning-accent", "status"),
    ("warning-soft", "status"),
    # Greys (values flip per theme, names stay)
    ("grey-50", "grey"),
    ("grey-100", "grey"),
    ("grey-200", "grey"),
    ("grey-300", "grey"),
    ("grey-400", "grey"),
    ("grey-500", "grey"),
    ("grey-600", "grey"),
    ("grey-700", "grey"),
    ("grey-800", "grey"),
    ("grey-900", "grey"),
    ("grey-950", "grey"),
    # Surfaces
    ("light", "surface"),
    ("light-active", "surface"),
    ("light-soft", "surface"),
    ("dark", "surface"),
    ("dark-active", "surface"),
]

TOKEN_KEYS = {key for key, _ in TOKEN_DEFS}

# Bases whose `-transparent` companion is derived from the picked color.
TRANSPARENT_BASES = {"primary", "success", "danger", "info", "warning"}

# FoundryX defaults — MUST mirror css/foundryx-tokens.css Layer 1 exactly.
FOUNDRYX_DEFAULTS: TokensDoc = {
    "light": {
        "primary": "#ff5a00",
        "primary-active": "#e14b00",
        "primary-accent": "#8f3000",
        "primary-soft": "#fff2e9",
        "success": "#1f9d54",
        "success-active": "#197f44",
        "success-accent": "#115c31",
        "success-soft": "#e3f5e9",
        "danger": "#d93420",
        "danger-active": "#b62a1a",
        "danger-accent": "#8a1f13",
        "danger-soft": "#fce5df",
        "info": "#2c7ff7",
        "info-active": "#1a63d4",
        "info-accent": "#14499c",
        "info-soft": "#e3efff",
        "warning": "#e8a318",
        "warning-active": "#c2860d",
        "warning-accent": "#8f6107",
        "warning-soft": "#fcf0db",
        "grey-50": "#f7f6f4",
        "grey-100": "#ecebe7",
        "grey-200": "#d9d6cf",
        "grey-300": "#bfb8b0",
        "grey-400": "#918a80",
        "grey-500": "#6b6660",
        "grey-600": "#4b4642",
        "grey-700": "#2f2c27",
        "grey-800": "#1e1a17",
        "grey-900": "#0f0f0d",
        "grey-950": "#0a0a0a",
        "light": "#ffffff",
        "light-active": "#f7f6f4",
        "light-soft": "#fbfaf8",
        "dark": "#0a0a0a",
        "dark-active": "#1e1a17",
    },
    "dark": {
        "primary": "#ff5a00",
        "primary-active": "#ff7a1a",
        "primary-accent": "#ff9a5c",
        "primary-soft": "#2e1409",
        "success": "#1f9d54",
        "success-active": "#36b86b",
        "success-accent": "#7fbf98",
        "success-soft": "#0c2613",
        "danger": "#d93420",
        "danger-active": "#f0533f",
        "danger-accent": "#c98a80",
        "danger-soft": "#2e0f0a",
        "info": "#2c7ff7",
        "info-active": "#5a9cf9",
        "info-accent": "#9bbde8",
        "info-soft": "#0c1b33",
        "warning": "#e8a318",
        "warning-active": "#f4bc4a",
        "warning-accent": "#cbb078",
        "warning-soft": "#2a1f08",
        "grey-50": "#141210",
        "grey-100": "#141210",
        "grey-200": "#272420",
        "grey-300": "#3a3631",
        "grey-400": "#4b4642",
        "grey-500": "#6b6660",
        "grey-600": "#918a80",
        "grey-700": "#918a80",
        "grey-800": "#bfb8b0",
        "grey-900": "#d9d6cf",
        "grey-950": "#f7f6f4",
        "light": "#0c0b0a",
        "light-active": "#110f0d",
        "light-soft": "#16140f",
        "dark": "#f7f6f4",
        "dark-active": "#d9d6cf",
    },
}

_COLOR_RE = re.compile(r"^#(?:[0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$", re.IGNORECASE)


def is_valid_color(value: str) -> bool:
    """#RGB, #RRGGBB or #RRGGBBAA — the formats the template/pickers accept."""
    return bool(isinstance(value, str) and _COLOR_RE.match(value.strip()))


def normalize_hex(value: str) -> str:
    """Expand #RGB → #RRGGBB; lowercase — uniform comparisons + storage."""
    v = value.strip().lower()
    if re.fullmatch(r"#[0-9a-f]{3}", v):
        return f"#{v[1]*2}{v[2]*2}{v[3]*2}"
    return v


def derive_transparent(hex_color: str) -> str:
    """Base color @ 0.2 alpha — the `-transparent` companion."""
    v = normalize_hex(hex_color)
    r, g, b = int(v[1:3], 16), int(v[3:5], 16), int(v[5:7], 16)
    return f"rgba({r}, {g}, {b}, 0.2)"


def validate_tokens(doc: object) -> Tuple[Optional[TokensDoc], List[str]]:
    """Validate an arbitrary JSON document into a stored tokens doc.

    Unknown keys / non-color values are reported by NAME (never silently
    dropped). Values equal to the FoundryX default normalize away so the stored
    doc stays a true diff. Returns (tokens|None, errors); tokens is None when
    invalid OR when nothing differs from the defaults.
    """
    errors: List[str] = []
    if not isinstance(doc, dict):
        return None, ['Template must be a JSON object with "light" and "dark" sections.']
    for section in doc:
        if section not in ("light", "dark"):
            errors.append(
                f'Unknown top-level section "{section}" — only "light" and "dark" are allowed.'
            )
    result: TokensDoc = {"light": {}, "dark": {}}
    for theme in ("light", "dark"):
        section = doc.get(theme)
        if section is None:
            continue
        if not isinstance(section, dict):
            errors.append(f'"{theme}" must be an object of token → color pairs.')
            continue
        for key, value in section.items():
            if key not in TOKEN_KEYS:
                errors.append(f'"{theme}.{key}" is not a themeable token.')
                continue
            if not is_valid_color(value):
                errors.append(
                    f'"{theme}.{key}" must be a hex color (#RGB, #RRGGBB or #RRGGBBAA).'
                )
                continue
            normalized = normalize_hex(value)
            if normalized != normalize_hex(FOUNDRYX_DEFAULTS[theme][key]):
                result[theme][key] = normalized
    if errors:
        return None, errors
    if not result["light"] and not result["dark"]:
        return None, []
    return result, []


def build_template(tokens: Optional[TokensDoc]) -> TokensDoc:
    """Downloadable template — every key prefilled with the effective value."""
    out: TokensDoc = {"light": {}, "dark": {}}
    for theme in ("light", "dark"):
        overrides = (tokens or {}).get(theme, {})
        for key, _ in TOKEN_DEFS:
            out[theme][key] = overrides.get(key, FOUNDRYX_DEFAULTS[theme][key])
    return out


def tokens_to_css(tokens: Optional[TokensDoc]) -> str:
    """``:root { … } .dark { … }`` — overridden vars only (+ derived
    transparents). Defaults stay in the frontend's foundryx-tokens.css."""
    if not tokens:
        return ""

    def block(selector: str, theme: str) -> str:
        overrides = tokens.get(theme, {})
        lines: List[str] = []
        for key, _ in TOKEN_DEFS:
            value = overrides.get(key)
            if not value:
                continue
            lines.append(f"  --foundryx-{key}: {normalize_hex(value)};")
            if key in TRANSPARENT_BASES:
                lines.append(f"  --foundryx-{key}-transparent: {derive_transparent(value)};")
        return f"{selector} {{\n" + "\n".join(lines) + "\n}" if lines else ""

    return "\n".join(b for b in (block(":root", "light"), block(".dark", "dark")) if b)
