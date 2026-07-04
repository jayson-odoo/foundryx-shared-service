"""Block document → semantic HTML + print CSS (plan sprint-3/03 D2).

The SECOND compiler — parallel to ``compiler.py`` (MJML/email). Documents
render to paper, so the email-table-safe MJML output is wrong; this emits
semantic HTML + ``@page``/print CSS that WeasyPrint turns into a PDF.

Shares the engine seams (merge / conditions-prune / brand-resolve / expand)
with email; forks ONLY this emit step. Merge tokens substitute through the
SAME ``render_tokens`` / ``render_url`` (substitution-only, anti-SSTI).

Fonts are bundled (Poppins headings + Inter body) and resolved by the
WeasyPrint ``url_fetcher`` from ``app/assets/fonts`` so PDFs are deterministic
across hosts (system-fontconfig fallback would make dev ≠ prod).
"""

import html as html_mod
from typing import Dict, List, Optional

from app.template_engine.compiler import BrandValues
from app.template_engine.merge import render_tokens, render_url
from app.template_engine.schemas import (
    SECTION_LAYOUT_COLUMNS,
    BrandFooterBlock,
    BrandHeaderBlock,
    ButtonBlock,
    CustomHtmlBlock,
    DividerBlock,
    HeadingBlock,
    ImageBlock,
    PageSetup,
    QrBlock,
    SocialLinksBlock,
    SpacerBlock,
    TemplateBlockModel,
    TemplateDocumentModel,
    TextBlock,
)
from app.template_engine.qr import qr_svg

# Font registry lives in fonts.py (bundled-TTF set). Re-export FONT_BASE_URL so
# the renderer's url_fetcher import keeps working.
from app.template_engine.fonts import (  # noqa: E402
    FONT_BASE_URL,
    font_face_css,
    google_fonts_link,
)

_PAGE_SIZE = {"A4": "A4", "Letter": "letter"}
# Physical page dimensions (mm) — for the browser preview "paper sheet".
_PAGE_DIMS = {"A4": (210, 297), "Letter": (216, 279)}
_HEADING_SIZES = {1: "26px", 2: "20px", 3: "16px"}

# Browser-preview fonts: the real PDF resolves bundled TTFs via the url_fetcher,
# but a browser iframe can't reach those — load every bundled family from Google
# Fonts (computed once from the registry).
_GOOGLE_FONTS_LINK = google_fonts_link()


def _attr(value: str) -> str:
    return html_mod.escape(str(value), quote=True)


def _page_dims(setup: PageSetup) -> "tuple[int, int]":
    w, h = _PAGE_DIMS.get(setup.size, _PAGE_DIMS["A4"])
    return (h, w) if setup.orientation == "landscape" else (w, h)


def _page_css(setup: Optional[PageSetup]) -> str:
    """`@page` rule from the doc's pageSetup (default A4 portrait 15mm)."""
    setup = setup or PageSetup()
    size = _PAGE_SIZE.get(setup.size, "A4")
    m = setup.margins
    return (
        f"@page {{ size: {size} {setup.orientation}; "
        f"margin: {m.top}mm {m.right}mm {m.bottom}mm {m.left}mm; }}"
    )


def _paper_css(setup: Optional[PageSetup]) -> str:
    """Browser preview: a flex-CENTRED white 'paper sheet' the size of the page,
    margins simulated as padding (the @page rule only applies when printing)."""
    setup = setup or PageSetup()
    w, _h = _page_dims(setup)
    m = setup.margins
    return (
        "html { margin:0; }"
        "body { margin:0; background:#F4F4F5; display:flex; justify-content:center; "
        "padding:16px; }"
        f".tpl-sheet {{ background:#FFFFFF; width:{w}mm; max-width:100%; flex:0 0 auto; "
        f"padding:{m.top}mm {m.right}mm {m.bottom}mm {m.left}mm; "
        "box-shadow:0 1px 6px rgba(0,0,0,0.12); }"
    )


def _font_face_css() -> str:
    """Bundled @font-face for every registered family (Inter/Poppins + the
    curated canvas set). The url_fetcher resolves these to local TTF bytes
    (deterministic, offline)."""
    return font_face_css()


def _base_css(brand: BrandValues, setup: Optional[PageSetup], *, for_browser: bool = False) -> str:
    primary = _attr(brand.primary_color)
    # Browser preview loads fonts via a <link> + sheet layout; the PDF uses the
    # bundled @font-face (url_fetcher) + the @page rule.
    fonts_and_page = _paper_css(setup) if for_browser else (_font_face_css() + _page_css(setup))
    return (
        "<style>"
        + fonts_and_page
        + (
            "* { box-sizing: border-box; }"
            'body { margin:0; font-family:"Inter", Arial, sans-serif; font-size:11pt; '
            "color:#18181B; line-height:1.5; }"
            'h1,h2,h3 { font-family:"Poppins","Inter",Arial,sans-serif; font-weight:700; '
            "margin:0 0 6px; }"
            ".tpl-section { display:flex; gap:16px; page-break-inside:avoid; padding:4px 0; }"
            ".tpl-col { flex:1; min-width:0; }"
            ".tpl-block { margin:0 0 8px; }"
            # Repeat <thead> across page breaks (D4).
            "table.tpl-table { width:100%; border-collapse:collapse; }"
            "table.tpl-table thead { display:table-header-group; }"
            "table.tpl-table th, table.tpl-table td { padding:6px 8px; "
            "border-bottom:1px solid #E4E4E7; }"
            "table.tpl-table thead th { border-bottom:2px solid #18181B; "
            "text-align:left; font-weight:600; }"
            "table.tpl-table tfoot td { border-bottom:none; font-weight:600; }"
            "img { max-width:100%; }"
            f".tpl-button {{ display:inline-block; background:{primary}; color:#FFFFFF; "
            "text-decoration:none; padding:8px 16px; font-weight:600; }}"
            f".tpl-brand-header {{ background:{primary}; color:#FFFFFF; padding:16px 20px; }}"
            ".tpl-brand-footer { background:#18181B; color:#A1A1AA; padding:16px 20px; "
            "text-align:center; font-size:9pt; }"
        )
        + "</style>"
    )


def _block_html(
    block: TemplateBlockModel,
    brand: BrandValues,
    facts: Dict[str, str],
    mode: str,
) -> str:
    if isinstance(block, HeadingBlock):
        text = render_tokens(block.text, facts, mode=mode)
        size = _HEADING_SIZES[block.level]
        tag = f"h{block.level}"
        return (
            f'<{tag} class="tpl-block" style="text-align:{block.align};font-size:{size}">'
            f"{text}</{tag}>"
        )

    if isinstance(block, TextBlock):
        # Rich-lite html sanitized at save; only tokens substitute now.
        body = render_tokens(block.html, facts, mode=mode)
        return f'<div class="tpl-block" style="text-align:{block.align}">{body}</div>'

    if isinstance(block, ImageBlock):
        src = block.src or ""
        if not src:
            return ""
        scheme = src.split(":", 1)[0].lower() if ":" in src.split("/", 1)[0] else "https"
        if scheme not in ("http", "https", "data"):
            return ""
        width = f"width:{block.width}px;" if block.width else ""
        justify = {"left": "flex-start", "center": "center", "right": "flex-end"}[block.align]
        img = f'<img src="{_attr(src)}" alt="{_attr(block.alt)}" style="{width}" />'
        if block.href:
            img = f'<a href="{_attr(render_url(block.href, facts, mode=mode))}">{img}</a>'
        return (
            f'<div class="tpl-block" style="display:flex;justify-content:{justify}">'
            f"{img}</div>"
        )

    if isinstance(block, ButtonBlock):
        bg = block.background_color or brand.primary_color
        color = block.text_color or "#FFFFFF"
        label = render_tokens(block.label, facts, mode=mode)
        href = render_url(block.href, facts, mode=mode)
        return (
            f'<div class="tpl-block" style="text-align:{block.align}">'
            f'<a class="tpl-button" href="{_attr(href)}" '
            f'style="background:{_attr(bg)};color:{_attr(color)};'
            f'border-radius:{block.border_radius}px">{label}</a></div>'
        )

    if isinstance(block, QrBlock):
        # Vector inline SVG sized to `size` px, aligned within the column.
        data = render_tokens(block.data, facts, mode=mode, escape=False)
        justify = {"left": "flex-start", "center": "center", "right": "flex-end"}[block.align]
        return (
            f'<div class="tpl-block" style="display:flex;justify-content:{justify}">'
            f'<div style="width:{block.size}px;height:{block.size}px">{qr_svg(data, block.ec_level)}</div>'
            f"</div>"
        )

    if isinstance(block, DividerBlock):
        return (
            f'<hr class="tpl-block" style="border:none;'
            f'border-top:{block.thickness}px solid {_attr(block.color)}" />'
        )

    if isinstance(block, SpacerBlock):
        return f'<div class="tpl-block" style="height:{block.height}px"></div>'

    if isinstance(block, BrandHeaderBlock):
        bg = (block.overrides.background_color if block.overrides else None) or brand.primary_color
        logo = (block.overrides.logo_src if block.overrides else None) or brand.logo_url
        inner = (
            f'<img src="{_attr(logo)}" alt="{_attr(brand.tenant_name)}" '
            f'style="width:160px;max-height:48px;object-fit:contain" />'
            if logo
            else f'<span style="font-family:Poppins;font-weight:700;font-size:16pt">'
            f"{html_mod.escape(brand.tenant_name)}</span>"
        )
        return (
            f'<div class="tpl-block tpl-brand-header" style="background:{_attr(bg)}">'
            f"{inner}</div>"
        )

    if isinstance(block, BrandFooterBlock):
        bg = (block.overrides.background_color if block.overrides else None) or "#18181B"
        text = (block.overrides.footer_text if block.overrides else None) or brand.footer_text
        return (
            f'<div class="tpl-block tpl-brand-footer" style="background:{_attr(bg)}">'
            f"{html_mod.escape(text or '')}</div>"
        )

    if isinstance(block, SocialLinksBlock):
        # Print docs don't render social-icon glyphs; emit plain text links so
        # the doc never breaks (icons = an email-surface concern).
        links = (
            [link.model_dump() for link in block.links]
            if block.links is not None
            else brand.socials
        )
        if not links:
            return ""
        parts = [
            f'<a href="{_attr(render_url(link.get("href", ""), {}))}" '
            f'style="margin:0 6px">{html_mod.escape(link.get("platform", ""))}</a>'
            for link in links
        ]
        return (
            f'<div class="tpl-block" style="text-align:{block.align};font-size:9pt">'
            f'{"".join(parts)}</div>'
        )

    if isinstance(block, CustomHtmlBlock):
        # Sanitized at save (and the expand pass emits trusted table markup);
        # tokens substitute, markup passes through. escape=False keeps the
        # table tags intact — cell VALUES were escaped where they were placed.
        return render_tokens(block.html, facts, mode=mode, escape=False)

    return ""


def compile_pdf_html(
    doc: TemplateDocumentModel,
    brand: BrandValues,
    facts: Dict[str, str],
    *,
    mode: str = "send",
    for_browser: bool = False,
) -> str:
    """Block doc → a full standalone HTML string.

    ``for_browser=False`` (default) → the WeasyPrint input (bundled @font-face +
    @page rule). ``for_browser=True`` → an in-app preview sheet (Google-Fonts
    link + a centred paper body) so the editor can show the document WITHOUT the
    browser's native PDF-viewer chrome. Same compiler, same merge/brand output.

    Exposed for the deterministic intermediate goldens (never byte-golden the
    PDF — font hinting/timestamps make that flaky).
    """
    sections: List[str] = []
    for section in doc.sections:
        ratios = SECTION_LAYOUT_COLUMNS[section.layout]
        cols: List[str] = []
        for i, column in enumerate(section.columns):
            blocks = "".join(_block_html(b, brand, facts, mode) for b in column.blocks)
            cols.append(
                f'<div class="tpl-col" style="flex:{ratios[i]}">{blocks}</div>'
            )
        bg = f"background:{_attr(section.background)};" if section.background else ""
        pad = section.padding
        style = (
            f"{bg}padding:{pad.top}px {pad.right}px {pad.bottom}px {pad.left}px"
        )
        sections.append(
            f'<div class="tpl-section" style="{style}">{"".join(cols)}</div>'
        )

    body = "".join(sections)
    # Browser preview wraps the content in a centred paper sheet; the PDF lets
    # @page own the page box.
    inner = f'<div class="tpl-sheet">{body}</div>' if for_browser else body
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\" />"
        + (_GOOGLE_FONTS_LINK if for_browser else "")
        + _base_css(brand, doc.page_setup, for_browser=for_browser)
        + "</head><body>"
        + inner
        + "</body></html>"
    )
