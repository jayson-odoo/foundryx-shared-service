"""Bundled font registry (plan sprint-3/03 - F2 font expansion).

A code-side registry of the fonts available to the render surfaces. All faces
are bundled TTFs in ``app/assets/fonts`` (deterministic PDFs, offline - never a
render-time network fetch). Adding a family = drop the TTF in + one row here.

The WeasyPrint url_fetcher resolves ``FONT_BASE_URL/<file>`` to the local bytes;
the browser preview loads the same families from Google Fonts via a ``<link>``.
"""

from dataclasses import dataclass, field
from typing import List, Tuple

# Sentinel host the url_fetcher intercepts → bundled font bytes (D8).
FONT_BASE_URL = "https://fonts.foundryx.internal"


@dataclass(frozen=True)
class FontFamily:
    name: str  # CSS family name (e.g. "Roboto")
    # (css-font-weight, ttf-filename) pairs. A variable font uses ONE face with
    # a weight RANGE (e.g. "100 900"); static fonts list one face per weight.
    faces: Tuple[Tuple[str, str], ...] = field(default_factory=tuple)
    # Google Fonts weights for the browser-preview <link> (woff2).
    preview_weights: Tuple[int, ...] = (400, 700)


# Curated set - sans / serif / display / mono. Inter + Poppins are the house
# defaults (already bundled); the rest were added for the canvas surface.
FONTS: List[FontFamily] = [
    FontFamily("Inter", (("100 900", "Inter.ttf"),), (400, 500, 600, 700)),
    FontFamily(
        "Poppins",
        (("400", "Poppins-Regular.ttf"), ("600", "Poppins-SemiBold.ttf"), ("700", "Poppins-Bold.ttf")),
        (400, 600, 700),
    ),
    FontFamily("Roboto", (("400", "Roboto-400.ttf"), ("700", "Roboto-700.ttf"))),
    FontFamily("Montserrat", (("400", "Montserrat-400.ttf"), ("700", "Montserrat-700.ttf"))),
    FontFamily("Lato", (("400", "Lato-400.ttf"), ("700", "Lato-700.ttf"))),
    FontFamily("Open Sans", (("400", "OpenSans-400.ttf"), ("700", "OpenSans-700.ttf"))),
    FontFamily("Merriweather", (("400", "Merriweather-400.ttf"), ("700", "Merriweather-700.ttf"))),
    FontFamily("Playfair Display", (("400", "PlayfairDisplay-400.ttf"), ("700", "PlayfairDisplay-700.ttf"))),
    FontFamily("Oswald", (("400", "Oswald-400.ttf"), ("700", "Oswald-700.ttf"))),
    FontFamily("Roboto Mono", (("400", "RobotoMono-400.ttf"), ("700", "RobotoMono-700.ttf"))),
]

FONT_NAMES: List[str] = [f.name for f in FONTS]


def font_face_css() -> str:
    """`@font-face` rules for every bundled family (resolved by the url_fetcher)."""
    parts: List[str] = []
    for fam in FONTS:
        for weight, fname in fam.faces:
            parts.append(
                f'@font-face{{font-family:"{fam.name}";'
                f'src:url("{FONT_BASE_URL}/{fname}") format("truetype");'
                f"font-weight:{weight};font-style:normal;}}"
            )
    return "".join(parts)


def google_fonts_link() -> str:
    """A Google-Fonts <link> covering every family - for the browser preview
    (the iframe can't reach the bundled TTFs)."""
    families = "&".join(
        "family=" + fam.name.replace(" ", "+") + ":wght@" + ";".join(str(w) for w in fam.preview_weights)
        for fam in FONTS
    )
    return (
        '<link rel="preconnect" href="https://fonts.googleapis.com" />'
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />'
        f'<link href="https://fonts.googleapis.com/css2?{families}&display=swap" rel="stylesheet" />'
    )
