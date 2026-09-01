"""Forever-contract parity: types/templates.ts ↔ app/template_engine/schemas.py.

The block document is editor-agnostic and outlives any editor. A block (or a
field on table/repeater/pageSetup) added on ONE side but not the other silently
breaks round-tripping - this test fails loudly when the two drift. Lightweight
by design: it parses the TS source as text (no TS toolchain in the pytest env).
"""

import re
from pathlib import Path
from typing import get_args

import pytest

from app.template_engine.schemas import CanvasElementModel, TemplateBlockModel

_TS_PATH = (
    Path(__file__).resolve().parents[2]
    / "service_frontend"
    / "types"
    / "templates.ts"
)
# Parity needs the frontend mirror checked out next to the backend. In a
# backend-only context (e.g. the CI Docker image) it's absent - skip at
# collection rather than erroring.
if not _TS_PATH.exists():
    pytest.skip(
        "frontend mirror (service_frontend) not present", allow_module_level=True
    )
_TS = _TS_PATH.read_text()


def _python_types(union) -> set[str]:
    # Unwrap Annotated[Union[...], Field(discriminator=...)].
    if hasattr(union, "__metadata__"):
        union = union.__origin__
    types: set[str] = set()
    for model in get_args(union):
        field = model.model_fields["type"]
        types |= set(get_args(field.annotation))
    return types


def _ts_discriminant_types() -> set[str]:
    # Every interface (block OR canvas element) declares `type: 'xxx';`.
    return set(re.findall(r"\n\s+type:\s*'([a-zA-Z]+)';", _TS))


def test_block_discriminants_match() -> None:
    # The TS file declares both block discriminants AND canvas-element ones
    # (F2 slice 2) - compare against the UNION of the two python unions.
    py = _python_types(TemplateBlockModel) | _python_types(CanvasElementModel)
    ts = _ts_discriminant_types()
    assert py == ts, f"discriminant drift - py-only={py - ts}, ts-only={ts - py}"
    # The F2 document blocks must be present on both sides.
    assert {"table", "repeater"} <= _python_types(TemplateBlockModel)


def test_canvas_element_discriminants_match() -> None:
    py = _python_types(CanvasElementModel)
    assert py == {
        "text",
        "image",
        "shape",
        "qr",
        "divider",
        "socialLinks",
        "customHtml",
        "brandHeader",
        "brandFooter",
    }, f"canvas drift: {py}"
    # Each canvas element interface mirrored on the TS side.
    for token in (
        "interface CanvasTextElement",
        "interface CanvasImageElement",
        "interface CanvasShapeElement",
        "interface CanvasQrElement",
        "interface CanvasDividerElement",
        "interface CanvasSocialElement",
        "interface CanvasHtmlElement",
        "interface CanvasBrandHeaderElement",
        "interface CanvasBrandFooterElement",
        "interface CanvasDocument",
        "interface CanvasSide",
        "interface CanvasSize",
    ):
        assert token in _TS, f"{token} missing from types/templates.ts"


def test_qr_block_mirrored() -> None:
    # QR is both a flowing-doc BLOCK and a canvas element (cross-surface parity).
    assert "interface QrBlock" in _TS
    assert "qr" in _python_types(TemplateBlockModel)


def test_table_block_fields_mirrored() -> None:
    for token in ("interface TableBlock", "interface TableColumn", "interface TableFooterCell"):
        assert token in _TS, f"{token} missing from types/templates.ts"
    # TableColumn key/header/align/width parity (the binding surface).
    for field in ("key", "header", "align", "width"):
        assert re.search(rf"\n\s+{field}:", _TS)


def test_repeater_and_pagesetup_mirrored() -> None:
    assert "interface RepeaterBlock" in _TS
    assert "interface PageSetup" in _TS
    assert "pageSetup?" in _TS  # optional on TemplateDocument (document surface only)
    # List-fact vocabulary that backs table/repeater binding.
    assert "interface TemplateListFact" in _TS
    assert "listFacts?" in _TS


def test_template_type_includes_document_and_badge() -> None:
    assert re.search(
        r"TemplateType\s*=\s*'email'\s*\|\s*'document'\s*\|\s*'badge'", _TS
    )
