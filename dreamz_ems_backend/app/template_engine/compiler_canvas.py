"""Canvas document → absolute-positioned HTML + print CSS (plan sprint-3/03 D13).

The THIRD emit step (after compiler.py/MJML-email and compiler_pdf.py/flowing
PDF). A badge/ticket/cert is a FIXED single-page design: each side becomes a
``position:relative`` page box at the exact mm size, with every element
``position:absolute`` at its mm coordinates. WeasyPrint turns each side into one
PDF page (N sides → N pages).

Revised away from a separate SVG emitter (D13): SVG ``<text>`` has no auto-wrap.
HTML abs-pos gives native CSS text wrapping + the SAME bundled ``@font-face`` +
the SAME ``url_fetcher`` + the SAME WeasyPrint backend as the flowing-doc surface
— one render stack, not two. mm positioning is exact in WeasyPrint; output is
vector-crisp. The client Konva editor NEVER renders the artifact — this server
HTML is authoritative (Konva = interactive editor only).

QR codes are generated server-side (segno → inline SVG); data comes from a
merge ``{{fact}}``.
"""

import html as html_mod
import re
from typing import Dict, List, Optional

from app.template_engine.compiler import BrandValues
from app.template_engine.compiler_pdf import (
    _GOOGLE_FONTS_LINK,
    _font_face_css,
)
from app.template_engine.fonts import FONT_NAMES
from app.template_engine.qr import qr_svg
from app.template_engine.merge import render_tokens, render_url
from app.template_engine.schemas import (
    CanvasBrandFooterElement,
    CanvasBrandHeaderElement,
    CanvasDividerElement,
    CanvasDocumentModel,
    CanvasHtmlElement,
    CanvasImageElement,
    CanvasQrElement,
    CanvasShapeElement,
    CanvasSocialElement,
    CanvasTextElement,
)


def _attr(value: str) -> str:
    return html_mod.escape(str(value), quote=True)


# Element colours are tenant-authored free text (the inspector colour field) and
# land in a `style="…"` attribute. HTML-escaping alone leaves `;`/`:` intact, so
# a value like "red;background:url(...)" would inject extra CSS declarations.
# Whitelist real colour syntaxes; anything else falls back to a safe default.
_COLOR_RE = re.compile(
    r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]+|rgba?\([0-9.,%\s]+\)|hsla?\([0-9.,%\s]+\))$"
)


def _css_color(value: Optional[str], fallback: str = "#000000") -> str:
    if value and _COLOR_RE.match(value.strip()):
        return value.strip()
    return fallback


def _font_family(name: str) -> str:
    """Only emit a KNOWN bundled family (else fall back) — the name lands in a
    CSS `font-family` and must not be arbitrary tenant text."""
    return name if name in FONT_NAMES else "Inter"


def _num(value: float) -> str:
    """Format a number for CSS — drop a trailing ``.0`` (5.0 → ``5``)."""
    if value == int(value):
        return str(int(value))
    return f"{value:g}"




def _element_box_style(el) -> str:
    """Absolute mm box + rotation around the element's TOP-LEFT (matches Konva's
    default node rotation pivot at x,y — keeps editor↔render parity)."""
    base = (
        f"position:absolute;left:{_num(el.x)}mm;top:{_num(el.y)}mm;"
        f"width:{_num(el.w)}mm;height:{_num(el.h)}mm;"
    )
    if el.rotation:
        base += f"transform:rotate({_num(el.rotation)}deg);transform-origin:left top;"
    return base


def _element_html(el, brand: BrandValues, facts: Dict[str, str], mode: str) -> str:
    box = _element_box_style(el)

    if isinstance(el, CanvasTextElement):
        content = render_tokens(el.content, facts, mode=mode)
        style = (
            f"{box}font-family:'{_font_family(el.font_family)}',Arial,sans-serif;"
            f"font-size:{_num(el.font_size)}pt;font-weight:{el.weight};"
            f"text-align:{el.align};color:{_css_color(el.color)};"
            f"line-height:{_num(el.line_height)};overflow:hidden;white-space:pre-wrap;"
            "word-break:break-word;"
        )
        return f'<div style="{style}">{content}</div>'

    if isinstance(el, CanvasImageElement):
        src = render_url(el.src or "", facts, mode=mode) if el.src else ""
        if not src or src == "#":
            return ""
        scheme = src.split(":", 1)[0].lower() if ":" in src.split("/", 1)[0] else "https"
        if scheme not in ("http", "https", "data"):
            return ""
        img = (
            f'<img src="{_attr(src)}" alt="" '
            f'style="width:100%;height:100%;object-fit:{el.fit};display:block" />'
        )
        return f'<div style="{box}overflow:hidden">{img}</div>'

    if isinstance(el, CanvasShapeElement):
        fill = f"background:{_css_color(el.fill, '#FF5A00')};" if el.fill else ""
        stroke = (
            f"border:{_num(el.stroke_width)}mm solid {_css_color(el.stroke)};"
            if el.stroke and el.stroke_width
            else ""
        )
        if el.kind == "ellipse":
            return f'<div style="{box}{fill}{stroke}border-radius:50%"></div>'
        if el.kind == "line":
            # A line = a thin filled bar across the box width (height = stroke).
            color = el.stroke or el.fill or "#18181B"
            sw = el.stroke_width or 0.4
            line_box = (
                f"position:absolute;left:{_num(el.x)}mm;top:{_num(el.y)}mm;width:{_num(el.w)}mm;"
                f"height:{_num(sw)}mm;background:{_css_color(color, '#18181B')};"
            )
            if el.rotation:
                line_box += f"transform:rotate({_num(el.rotation)}deg);transform-origin:left center;"
            return f'<div style="{line_box}"></div>'
        radius = f"border-radius:{_num(el.radius)}mm;" if el.radius else ""
        return f'<div style="{box}{fill}{stroke}{radius}"></div>'

    if isinstance(el, CanvasQrElement):
        data = render_tokens(el.data, facts, mode=mode, escape=False)
        return f'<div style="{box}">{qr_svg(data, el.ec_level)}</div>'

    if isinstance(el, CanvasDividerElement):
        # A horizontal rule centred vertically in the box, spanning its width.
        return (
            f'<div style="{box}display:flex;align-items:center">'
            f'<div style="width:100%;border-top:{_num(el.thickness)}mm solid '
            f'{_css_color(el.color, "#E4E4E7")}"></div></div>'
        )

    if isinstance(el, CanvasSocialElement):
        links = (
            [link.model_dump() for link in el.links]
            if el.links is not None
            else brand.socials
        )
        if not links:
            return ""
        parts = [
            f'<a href="{_attr(render_url(link.get("href", ""), {}))}" '
            f'style="margin:0 4px;text-decoration:none;color:inherit">'
            f'{html_mod.escape(link.get("platform", ""))}</a>'
            for link in links
        ]
        return (
            f'<div style="{box}display:flex;align-items:center;justify-content:'
            f'{ {"left": "flex-start", "center": "center", "right": "flex-end"}[el.align] };'
            f'font-size:{el.icon_size}px">{"".join(parts)}</div>'
        )

    if isinstance(el, CanvasHtmlElement):
        # Sanitized at save; tokens substitute, markup passes through.
        body = render_tokens(el.html, facts, mode=mode, escape=False)
        return f'<div style="{box}overflow:hidden">{body}</div>'

    if isinstance(el, CanvasBrandHeaderElement):
        ov = el.overrides
        bg = (ov.background_color if ov else None) or brand.primary_color
        logo = (ov.logo_src if ov else None) or brand.logo_url
        inner = (
            f'<img src="{_attr(logo)}" alt="{_attr(brand.tenant_name)}" '
            f'style="max-width:100%;max-height:100%;object-fit:contain" />'
            if logo
            else f'<span style="color:#FFFFFF;font-family:Poppins,sans-serif;font-weight:700">'
            f"{html_mod.escape(brand.tenant_name)}</span>"
        )
        return (
            f'<div style="{box}background:{_css_color(bg, brand.primary_color)};'
            f'display:flex;align-items:center;justify-content:center;overflow:hidden">{inner}</div>'
        )

    if isinstance(el, CanvasBrandFooterElement):
        ov = el.overrides
        bg = (ov.background_color if ov else None) or "#18181B"
        text = (ov.footer_text if ov else None) or brand.footer_text
        show_socials = True if (ov is None or ov.show_socials is None) else ov.show_socials
        socials = ""
        if show_socials and brand.socials:
            socials = "".join(
                f'<span style="margin:0 3px">{html_mod.escape(s.get("platform", ""))}</span>'
                for s in brand.socials
            )
        return (
            f'<div style="{box}background:{_css_color(bg, "#18181B")};color:#A1A1AA;'
            f"display:flex;flex-direction:column;align-items:center;justify-content:center;"
            f'text-align:center;font-size:8pt;overflow:hidden">'
            f"<span>{html_mod.escape(text or '')}</span><span>{socials}</span></div>"
        )

    return ""


def _side_dims(doc: CanvasDocumentModel) -> "tuple[float, float]":
    # width/height are the authoritative physical page dimensions (the editor
    # positions elements against them directly). `orientation` is metadata only
    # — never swap here, or the render disagrees with where elements were placed
    # whenever the chosen orientation contradicts the authored aspect ratio.
    return doc.canvas.width, doc.canvas.height


def compile_canvas_html(
    doc: CanvasDocumentModel,
    brand: BrandValues,
    facts: Dict[str, str],
    *,
    mode: str = "send",
    for_browser: bool = False,
) -> str:
    """Canvas doc → a full standalone HTML string.

    ``for_browser=False`` (default) → WeasyPrint input: ``@page`` sized to the
    canvas (no margin) so each side is exactly one trimmed page; bundled
    ``@font-face``. ``for_browser=True`` → an in-app preview: each side a centred
    white sheet (Google-Fonts link), stacked. Same compiler/merge/brand output
    — never byte-golden the PDF; golden THIS HTML.
    """
    w, h = _side_dims(doc)

    sides_html: List[str] = []
    for i, side in enumerate(doc.sides):
        els = "".join(_element_html(el, brand, facts, mode) for el in side.elements)
        break_css = "" if (for_browser or i == len(doc.sides) - 1) else "page-break-after:always;"
        sides_html.append(
            f'<div class="badge-side" style="{break_css}">{els}</div>'
        )

    wmm, hmm = _num(w), _num(h)
    if for_browser:
        page_css = (
            "html{margin:0}"
            "body{margin:0;background:#F4F4F5;display:flex;flex-direction:column;"
            "align-items:center;gap:16px;padding:16px}"
            f".badge-side{{position:relative;width:{wmm}mm;height:{hmm}mm;background:#FFFFFF;"
            "box-shadow:0 1px 6px rgba(0,0,0,0.18);overflow:hidden;flex:0 0 auto}"
        )
        fonts = _GOOGLE_FONTS_LINK
    else:
        page_css = (
            f"@page{{size:{wmm}mm {hmm}mm;margin:0}}"
            "html,body{margin:0;padding:0}"
            f".badge-side{{position:relative;width:{wmm}mm;height:{hmm}mm;overflow:hidden}}"
            + _font_face_css()
        )
        fonts = ""

    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8" />'
        + fonts
        + f"<style>*{{box-sizing:border-box}}{page_css}</style>"
        + "</head><body>"
        + "".join(sides_html)
        + "</body></html>"
    )
