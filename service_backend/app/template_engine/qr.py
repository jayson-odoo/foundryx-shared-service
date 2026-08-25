"""Server-side QR generation (segno) - shared by every render surface.

The canvas (badge) + document compilers embed a vector inline SVG (crisp at any
print size); the email/MJML compiler embeds a PNG data-URI (email clients render
inline SVG inconsistently). segno is pure-Python (no Node) - matches the
no-Chromium stance.
"""

import re

import segno


def qr_svg(data: str, ec_level: str) -> str:
    """Inline SVG that fills its container. segno emits ``<svg width="N" ...>``
    with NO viewBox, so a plain ``width:100%`` leaves the modules at their
    intrinsic N-unit size - inject a viewBox so the QR scales to fill."""
    payload = data.strip() or "-"
    qr = segno.make(payload, error=ec_level.lower())
    svg = qr.svg_inline(border=2)
    m = re.match(r'<svg width="(\d+)" height="(\d+)"', svg)
    if m:
        w, h = m.group(1), m.group(2)
        svg = svg.replace(
            f'<svg width="{w}" height="{h}"',
            f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="xMidYMid meet" '
            'style="width:100%;height:100%;display:block"',
            1,
        )
    return svg


def qr_png_data_uri(data: str, ec_level: str, scale: int = 4) -> str:
    """A ``data:image/png;base64,…`` QR - for the email surface (mj-image src)."""
    payload = data.strip() or "-"
    qr = segno.make(payload, error=ec_level.lower())
    return qr.png_data_uri(scale=scale, border=2)
