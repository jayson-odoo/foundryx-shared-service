"""Block document → MJML → email-safe HTML (plan 07 D9).

The compiler runs the FULL pipeline at render time, per send - no compiled
caches (per-recipient conditional pruning makes a single cached HTML wrong
by construction, and brand values must live-follow a rebrand). MJML compiles
via ``mrml`` (Rust port, no Node) - validated by the Phase-0 spike.

Merge tokens are substituted AFTER compilation? No - values are substituted
into the MJML source per element with proper escaping (html.escape via
merge.render_tokens), because hrefs need URL validation BEFORE they hit the
attribute. mrml never sees un-merged ``{{`` braces in attributes it might
mangle; text content keeps tokens only in preview mode's loud markers.
"""

import html as html_mod
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import mrml

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
    QrBlock,
    SocialLinksBlock,
    SpacerBlock,
    TemplateBlockModel,
    TemplateDocumentModel,
    TextBlock,
)
from app.template_engine.qr import qr_png_data_uri


@dataclass
class BrandValues:
    """Tenant brand snapshot resolved at render time (D4 live-follow)."""

    tenant_name: str = "Your workspace"
    logo_url: Optional[str] = None
    primary_color: str = "#FF5A00"
    footer_text: str = ""
    socials: List[Dict[str, str]] = field(default_factory=list)  # [{platform, href}]


# mj-social-element icon names (mrml ships the standard set; tiktok has no
# stock icon - fall back to the generic 'web' glyph, href still correct).
_SOCIAL_ICON = {
    "facebook": "facebook",
    "instagram": "instagram",
    "x": "x",
    "linkedin": "linkedin",
    "youtube": "youtube",
    "tiktok": "web",
    "website": "web",
}

_HEADING_SIZES = {1: 28, 2: 24, 3: 18}


def _attr(value: str) -> str:
    return html_mod.escape(str(value), quote=True)


def _social_elements(links: List[Dict[str, str]], icon_size: int) -> str:
    parts = []
    for link in links:
        icon = _SOCIAL_ICON.get(link.get("platform", "website"), "web")
        href = render_url(link.get("href", ""), {})
        parts.append(
            f'<mj-social-element name="{icon}" href="{_attr(href)}" icon-size="{icon_size}px" />'
        )
    return "".join(parts)


def _block_mjml(
    block: TemplateBlockModel,
    brand: BrandValues,
    facts: Dict[str, str],
    mode: str,
) -> str:
    if isinstance(block, HeadingBlock):
        text = render_tokens(block.text, facts, mode=mode)
        size = _HEADING_SIZES[block.level]
        return (
            f'<mj-text align="{block.align}" font-size="{size}px" font-weight="700" '
            f'font-family="Poppins, Inter, Arial, sans-serif" padding="4px 0">{text}</mj-text>'
        )

    if isinstance(block, TextBlock):
        # Rich-lite html was sanitized at save; only tokens substitute now.
        body = render_tokens(block.html, facts, mode=mode)
        return (
            f'<mj-text align="{block.align}" font-size="14px" line-height="1.6" '
            f'padding="4px 0">{body}</mj-text>'
        )

    if isinstance(block, ImageBlock):
        src = block.src or ""
        if not src:
            return ""
        # Scheme-validate the src like hrefs (consistency + defense-in-depth);
        # only http(s)/data-image survive, else the image is dropped.
        scheme = src.split(":", 1)[0].lower() if ":" in src.split("/", 1)[0] else "https"
        if scheme not in ("http", "https", "data"):
            return ""
        width = f' width="{block.width}px"' if block.width else ""
        href = f' href="{_attr(render_url(block.href, facts, mode=mode))}"' if block.href else ""
        return (
            f'<mj-image src="{_attr(src)}" alt="{_attr(block.alt)}"{width}{href} '
            f'align="{block.align}" padding="4px 0" />'
        )

    if isinstance(block, ButtonBlock):
        bg = block.background_color or brand.primary_color
        color = block.text_color or "#FFFFFF"
        label = render_tokens(block.label, facts, mode=mode)
        href = render_url(block.href, facts, mode=mode)
        return (
            f'<mj-button href="{_attr(href)}" background-color="{_attr(bg)}" color="{_attr(color)}" '
            f'border-radius="{block.border_radius}px" align="{block.align}" font-weight="600" '
            f'padding="8px 0">{label}</mj-button>'
        )

    if isinstance(block, QrBlock):
        # PNG data-uri (email clients render inline SVG inconsistently). Data is
        # merge-enabled; rendered server-side, never a remote fetch.
        data = render_tokens(block.data, facts, mode=mode, escape=False)
        uri = qr_png_data_uri(data, block.ec_level)
        return (
            f'<mj-image src="{uri}" alt="QR code" width="{block.size}px" '
            f'align="{block.align}" padding="4px 0" />'
        )

    if isinstance(block, DividerBlock):
        return (
            f'<mj-divider border-color="{_attr(block.color)}" border-width="{block.thickness}px" '
            f'padding="8px 0" />'
        )

    if isinstance(block, SpacerBlock):
        return f'<mj-spacer height="{block.height}px" />'

    if isinstance(block, SocialLinksBlock):
        links = (
            [link.model_dump() for link in block.links]
            if block.links is not None
            else brand.socials
        )
        if not links:
            return ""
        return (
            f'<mj-social mode="horizontal" align="{block.align}" padding="8px 0">'
            f"{_social_elements(links, block.icon_size)}</mj-social>"
        )

    if isinstance(block, BrandHeaderBlock):
        bg = (block.overrides.background_color if block.overrides else None) or brand.primary_color
        logo = (block.overrides.logo_src if block.overrides else None) or brand.logo_url
        if logo:
            # width-capped - mj-image with only a height stretches the image
            # to the full column width (squashed wordmark, UX iteration).
            return (
                f'<mj-image src="{_attr(logo)}" alt="{_attr(brand.tenant_name)}" width="160px" '
                f'align="left" container-background-color="{_attr(bg)}" padding="16px 24px" />'
            )
        return (
            f'<mj-text container-background-color="{_attr(bg)}" padding="16px 24px" '
            f'font-family="Poppins, Inter, Arial, sans-serif" font-size="18px" font-weight="700" '
            f'color="#FFFFFF">{html_mod.escape(brand.tenant_name)}</mj-text>'
        )

    if isinstance(block, BrandFooterBlock):
        bg = (block.overrides.background_color if block.overrides else None) or "#18181B"
        text = (block.overrides.footer_text if block.overrides else None) or brand.footer_text
        show_socials = block.overrides.show_socials if block.overrides and block.overrides.show_socials is not None else True
        parts = [
            f'<mj-text container-background-color="{_attr(bg)}" align="center" color="#A1A1AA" '
            f'font-size="12px" padding="20px 24px 8px">{html_mod.escape(text or "")}</mj-text>'
        ]
        if show_socials and brand.socials:
            parts.append(
                f'<mj-social mode="horizontal" align="center" container-background-color="{_attr(bg)}" '
                f'padding="0 24px 20px">{_social_elements(brand.socials, 20)}</mj-social>'
            )
        return "".join(parts)

    if isinstance(block, CustomHtmlBlock):
        # Sanitized at save; tokens substitute, markup passes through raw.
        return f"<mj-raw>{render_tokens(block.html, facts, mode=mode, escape=True)}</mj-raw>"

    return ""


def document_mjml(
    doc: TemplateDocumentModel,
    brand: BrandValues,
    facts: Dict[str, str],
    *,
    title: str = "",
    mode: str = "send",
) -> str:
    sections: List[str] = []
    for section in doc.sections:
        ratios = SECTION_LAYOUT_COLUMNS[section.layout]
        columns: List[str] = []
        for i, column in enumerate(section.columns):
            blocks = "".join(_block_mjml(b, brand, facts, mode) for b in column.blocks)
            columns.append(f'<mj-column width="{ratios[i]}%">{blocks}</mj-column>')
        bg = f' background-color="{_attr(section.background)}"' if section.background else ""
        pad = section.padding
        sections.append(
            f'<mj-section{bg} padding="{pad.top}px {pad.right}px {pad.bottom}px {pad.left}px">'
            f'{"".join(columns)}</mj-section>'
        )

    title_tag = f"<mj-title>{html_mod.escape(title)}</mj-title>" if title else ""
    return (
        "<mjml><mj-head>"
        f"{title_tag}"
        '<mj-attributes><mj-all font-family="Inter, Arial, sans-serif" />'
        f'<mj-button background-color="{_attr(brand.primary_color)}" /></mj-attributes>'
        "</mj-head>"
        '<mj-body background-color="#F4F4F5">'
        f'{"".join(sections)}'
        "</mj-body></mjml>"
    )


def compile_document(
    doc: TemplateDocumentModel,
    brand: BrandValues,
    facts: Dict[str, str],
    *,
    title: str = "",
    mode: str = "send",
) -> str:
    """Doc → email-safe HTML (mrml). Raises ValueError on compile failure."""
    source = document_mjml(doc, brand, facts, title=title, mode=mode)
    try:
        result = mrml.to_html(source)
    except Exception as exc:  # mrml raises its own error types
        raise ValueError(f"MJML compile failed: {exc}") from exc
    return result.content if hasattr(result, "content") else str(result)


_TAG_RE = re.compile(r"<[^>]+>")


def document_text(doc: TemplateDocumentModel, brand: BrandValues, facts: Dict[str, str]) -> str:
    """Plain-text sibling, derived from the block tree (never authored)."""
    lines: List[str] = []
    for _section, _column, block in doc.iter_blocks():
        if isinstance(block, HeadingBlock):
            lines.append(render_tokens(block.text, facts, escape=False))
        elif isinstance(block, TextBlock):
            stripped = _TAG_RE.sub(" ", block.html)
            lines.append(
                re.sub(r"\s+", " ", render_tokens(stripped, facts, escape=False)).strip()
            )
        elif isinstance(block, ButtonBlock):
            label = render_tokens(block.label, facts, escape=False)
            lines.append(f"{label}: {render_url(block.href, facts)}")
        elif isinstance(block, BrandFooterBlock):
            text = (block.overrides.footer_text if block.overrides else None) or brand.footer_text
            if text:
                lines.append(text)
    return "\n\n".join(line for line in lines if line)
