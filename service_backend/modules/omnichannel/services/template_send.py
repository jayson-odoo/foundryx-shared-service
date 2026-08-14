"""Template send-parameter analysis + Meta `components` builder (plan 12 Slice 3,
AC-12-22).

A WhatsApp template send may fill variables in THREE places, not just the body:
  * a TEXT header with a ``{{1}}`` variable,
  * an image/video/document header (media, uploaded-by-id at send time),
  * a URL button with a dynamic ``{{1}}`` suffix (one dynamic var per URL button).

``analyze_template`` reads the stored Meta-shape ``components_json`` and reports
exactly which inputs a send needs (a ``TemplateShape``); ``validate_template_params``
turns a count mismatch into a human message (the composer surfaces it as a 422);
``build_send_components`` assembles the Meta ``components`` array. Pure functions -
no DB/HTTP. The media-header id is injected at send time by ``send_runner`` (the
media rides the SAME upload-by-id pipeline as every other outbound media).
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..template_schemas import MEDIA_HEADER_FORMATS, distinct_var_count

# The Meta button `index` is the button's position (0-based) within the BUTTONS
# component; a dynamic URL button carries one text parameter ({{1}} suffix).
_MEDIA_PARAM_KINDS = {"IMAGE": "image", "VIDEO": "video", "DOCUMENT": "document"}


class TemplateParamError(ValueError):
    """A template-parameter count/media mismatch - carries a human message."""


@dataclass
class TemplateShape:
    """What a send of this template needs to supply."""

    header_format: Optional[str] = None  # None | TEXT | IMAGE | VIDEO | DOCUMENT
    header_text_var_count: int = 0  # distinct {{n}} in a TEXT header (else 0)
    body_var_count: int = 0  # distinct {{n}} in the body
    button_url_var_count: int = 0  # dynamic URL buttons (one {{1}} var each)
    # 0-based indices (in button order) of the dynamic URL buttons - used to
    # build the per-button Meta parameters.
    button_url_indices: List[int] = field(default_factory=list)

    @property
    def has_media_header(self) -> bool:
        return self.header_format in MEDIA_HEADER_FORMATS


def _component(components: Optional[List[Dict[str, Any]]], ctype: str) -> Optional[Dict[str, Any]]:
    for comp in components or []:
        if (comp.get("type") or "").upper() == ctype:
            return comp
    return None


def analyze_template(components: Optional[List[Dict[str, Any]]]) -> TemplateShape:
    """Derive the send-parameter shape from a stored Meta ``components_json``."""
    shape = TemplateShape()

    header = _component(components, "HEADER")
    if header is not None:
        fmt = (header.get("format") or "TEXT").upper()
        shape.header_format = fmt
        if fmt == "TEXT":
            shape.header_text_var_count = distinct_var_count(header.get("text") or "")

    body = _component(components, "BODY")
    if body is not None:
        shape.body_var_count = distinct_var_count(body.get("text") or "")

    buttons_comp = _component(components, "BUTTONS")
    if buttons_comp is not None:
        for idx, btn in enumerate(buttons_comp.get("buttons") or []):
            if (btn.get("type") or "").upper() == "URL" and distinct_var_count(btn.get("url") or "") >= 1:
                shape.button_url_indices.append(idx)
        shape.button_url_var_count = len(shape.button_url_indices)

    return shape


def validate_template_params(
    shape: TemplateShape,
    *,
    header_text_vars: List[str],
    body_vars: List[str],
    button_vars: List[str],
    has_header_media: bool,
) -> None:
    """Raise ``TemplateParamError`` on any header/body/button count or media
    mismatch. Messages are human ("This template's header needs 1 variable; …")."""
    if shape.has_media_header and not has_header_media:
        raise TemplateParamError(
            "This template has a media header - attach an image, video or document."
        )
    if shape.header_format == "TEXT" and len(header_text_vars) != shape.header_text_var_count:
        raise TemplateParamError(
            f"This template's header needs {shape.header_text_var_count} variable(s); "
            f"{len(header_text_vars)} provided."
        )
    if len(body_vars) != shape.body_var_count:
        raise TemplateParamError(
            f"This template's body needs {shape.body_var_count} variable(s); "
            f"{len(body_vars)} provided."
        )
    if len(button_vars) != shape.button_url_var_count:
        raise TemplateParamError(
            f"This template's buttons need {shape.button_url_var_count} variable(s); "
            f"{len(button_vars)} provided."
        )


def build_send_components(
    components: Optional[List[Dict[str, Any]]],
    *,
    header_text_vars: List[str],
    body_vars: List[str],
    button_vars: List[str],
    header_media_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Assemble the Meta ``components`` array for a template send. Empty
    components are omitted. For a media header the parameter carries
    ``{"id": header_media_id}`` (``None`` at build time - ``send_runner`` injects
    the uploaded id before the send)."""
    shape = analyze_template(components)
    out: List[Dict[str, Any]] = []

    # Header
    if shape.header_format == "TEXT" and header_text_vars:
        out.append(
            {
                "type": "header",
                "parameters": [{"type": "text", "text": v} for v in header_text_vars],
            }
        )
    elif shape.has_media_header:
        kind = _MEDIA_PARAM_KINDS[shape.header_format]
        out.append(
            {"type": "header", "parameters": [{"type": kind, kind: {"id": header_media_id}}]}
        )

    # Body
    if body_vars:
        out.append(
            {"type": "body", "parameters": [{"type": "text", "text": v} for v in body_vars]}
        )

    # URL buttons with a dynamic {{1}} suffix - one component each.
    for var, idx in zip(button_vars, shape.button_url_indices):
        out.append(
            {
                "type": "button",
                "sub_type": "url",
                "index": str(idx),
                "parameters": [{"type": "text", "text": var}],
            }
        )

    return out


def inject_header_media_id(template: Dict[str, Any], media_id: str) -> Dict[str, Any]:
    """Set the uploaded media id on the HEADER media parameter of a built
    template payload (in place) - used by ``send_runner`` after upload-by-id."""
    for comp in template.get("components") or []:
        if (comp.get("type") or "").lower() != "header":
            continue
        for param in comp.get("parameters") or []:
            ptype = (param.get("type") or "").lower()
            if ptype in ("image", "video", "document") and isinstance(param.get(ptype), dict):
                param[ptype]["id"] = media_id
    return template
