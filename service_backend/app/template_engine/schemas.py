"""Block-document schema + save-time validation (plan 07 D2/D3).

Mirrors the frontend forever-contract in ``types/templates.ts`` -
camelCase wire, ``schemaVersion`` at the root, discriminated block union.
``validate_doc`` is the 422 gate: unknown block shapes fail Pydantic;
conditions validate through the rule engine; custom/rich HTML is sanitized
IN PLACE (nh3) so stored docs are clean, not just checked.
"""

from typing import Annotated, Any, Dict, List, Literal, Optional, Sequence, Union

import nh3
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.rule_engine.schemas import validate_tree
from app.template_engine.merge import collect_tokens

SCHEMA_VERSION = 1

SECTION_LAYOUT_COLUMNS: Dict[str, List[float]] = {
    "100": [100],
    "50/50": [50, 50],
    "33/33/33": [33.33, 33.33, 33.34],
    "67/33": [67, 33],
}

# Rich-lite vocabulary for Text blocks (D3) - formatting only, no containers.
TEXT_ALLOWED_TAGS = {"b", "strong", "i", "em", "u", "a", "ul", "ol", "li", "br", "span", "p"}
TEXT_ALLOWED_ATTRS = {"a": {"href", "target"}, "span": set()}
# Custom-HTML escape hatch - block elements allowed, scripts/handlers never.
CUSTOM_ALLOWED_TAGS = TEXT_ALLOWED_TAGS | {
    "table", "thead", "tbody", "tr", "td", "th", "div", "img",
    "h1", "h2", "h3", "h4", "hr", "blockquote", "center",
}
CUSTOM_ALLOWED_ATTRS = {
    "a": {"href", "target"},
    "img": {"src", "alt", "width", "height", "style"},
    "table": {"role", "width", "cellpadding", "cellspacing", "style"},
    "td": {"style", "width", "align", "valign", "colspan"},
    "th": {"style", "width", "align"},
    "tr": {"style"},
    "div": {"style", "align"},
    "span": {"style"},
    "p": {"style"},
    "h1": {"style"}, "h2": {"style"}, "h3": {"style"}, "h4": {"style"},
}


def sanitize_text_html(value: str) -> str:
    return nh3.clean(value, tags=TEXT_ALLOWED_TAGS, attributes=TEXT_ALLOWED_ATTRS)


def sanitize_custom_html(value: str) -> str:
    return nh3.clean(value, tags=CUSTOM_ALLOWED_TAGS, attributes=CUSTOM_ALLOWED_ATTRS)


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class Padding(_Base):
    top: int = Field(ge=0, le=200)
    bottom: int = Field(ge=0, le=200)
    left: int = Field(ge=0, le=200)
    right: int = Field(ge=0, le=200)


Align = Literal["left", "center", "right"]
# Visibility trees are validated against the context's fact sources by
# validate_doc, not by shape here (rule engine owns the grammar).
Conditions = Optional[Dict[str, Any]]


class HeadingBlock(_Base):
    id: str
    type: Literal["heading"]
    text: str = ""
    level: Literal[1, 2, 3] = 2
    align: Align = "left"
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class TextBlock(_Base):
    id: str
    type: Literal["text"]
    html: str = ""
    align: Align = "left"
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class ImageBlock(_Base):
    id: str
    type: Literal["image"]
    storage_key: Optional[str] = Field(default=None, alias="storageKey")
    src: Optional[str] = None
    alt: str = ""
    width: Optional[int] = Field(default=None, ge=8, le=600)
    align: Align = "center"
    href: Optional[str] = None
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class ButtonBlock(_Base):
    id: str
    type: Literal["button"]
    label: str = ""
    href: str = ""
    align: Align = "left"
    background_color: Optional[str] = Field(default=None, alias="backgroundColor")
    text_color: Optional[str] = Field(default=None, alias="textColor")
    border_radius: int = Field(default=6, ge=0, le=32, alias="borderRadius")
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class DividerBlock(_Base):
    id: str
    type: Literal["divider"]
    color: str = "#E4E4E7"
    thickness: int = Field(default=1, ge=1, le=8)
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class SpacerBlock(_Base):
    id: str
    type: Literal["spacer"]
    height: int = Field(default=24, ge=4, le=160)
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class SocialLink(_Base):
    platform: Literal["facebook", "instagram", "x", "linkedin", "youtube", "tiktok", "website"]
    href: str


class SocialLinksBlock(_Base):
    id: str
    type: Literal["socialLinks"]
    # None = render the tenant's branding socials at send time (D4).
    links: Optional[List[SocialLink]] = None
    align: Align = "center"
    icon_size: int = Field(default=24, ge=16, le=48, alias="iconSize")
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class BrandHeaderOverrides(_Base):
    logo_src: Optional[str] = Field(default=None, alias="logoSrc")
    background_color: Optional[str] = Field(default=None, alias="backgroundColor")


class BrandHeaderBlock(_Base):
    id: str
    type: Literal["brandHeader"]
    overrides: Optional[BrandHeaderOverrides] = None
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class BrandFooterOverrides(_Base):
    footer_text: Optional[str] = Field(default=None, alias="footerText")
    background_color: Optional[str] = Field(default=None, alias="backgroundColor")
    show_socials: Optional[bool] = Field(default=None, alias="showSocials")


class BrandFooterBlock(_Base):
    id: str
    type: Literal["brandFooter"]
    overrides: Optional[BrandFooterOverrides] = None
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class CustomHtmlBlock(_Base):
    id: str
    type: Literal["customHtml"]
    html: str = ""
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class QrBlock(_Base):
    """QR block for the flowing (email/document) surface - a centred QR image of
    a fixed pixel size. ``data`` is merge-enabled (e.g. {{ticketLink}})."""

    id: str
    type: Literal["qr"]
    data: str = ""
    ec_level: Literal["L", "M", "Q", "H"] = Field(default="M", alias="ecLevel")
    size: int = Field(default=120, ge=32, le=600)  # px
    align: Align = "center"
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


# --- F2 document-surface blocks (table / repeater) -------------------------
# Iterate a LIST fact. Repetition is STRUCTURAL (expand-before-compile); the
# merge renderer stays substitution-only. Body refs use the `row.<key>` scope.

class TableColumn(_Base):
    key: str  # binds row.<key>
    header: str = ""
    align: Align = "left"
    width: Optional[int] = Field(default=None, ge=1, le=100)  # percent


class TableFooterCell(_Base):
    text: str = ""  # scalar merge tokens only (domain-owned totals)
    align: Align = "right"
    span: int = Field(default=1, ge=1, le=24)


class TableFooterRow(_Base):
    cells: List[TableFooterCell] = Field(default_factory=list)


class TableBlock(_Base):
    id: str
    type: Literal["table"]
    source: str  # list-fact key
    columns: List[TableColumn] = Field(default_factory=list)
    footer: Optional[List[TableFooterRow]] = None
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


# Leaf blocks legal inside a repeater body - single level (no table/repeater
# nesting v1), no brand/social (those resolve tenant-globals, not row scope).
LeafBlockModel = Annotated[
    Union[
        HeadingBlock,
        TextBlock,
        ImageBlock,
        ButtonBlock,
        DividerBlock,
        SpacerBlock,
        QrBlock,
    ],
    Field(discriminator="type"),
]


class RepeaterBlock(_Base):
    id: str
    type: Literal["repeater"]
    source: str  # list-fact key
    body: List[LeafBlockModel] = Field(default_factory=list)
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


TemplateBlockModel = Annotated[
    Union[
        HeadingBlock,
        TextBlock,
        ImageBlock,
        ButtonBlock,
        DividerBlock,
        SpacerBlock,
        SocialLinksBlock,
        BrandHeaderBlock,
        BrandFooterBlock,
        CustomHtmlBlock,
        QrBlock,
        TableBlock,
        RepeaterBlock,
    ],
    Field(discriminator="type"),
]


class TemplateColumnModel(_Base):
    id: str
    blocks: List[TemplateBlockModel] = Field(default_factory=list)


class TemplateSectionModel(_Base):
    id: str
    layout: Literal["100", "50/50", "33/33/33", "67/33"] = "100"
    background: Optional[str] = None
    padding: Padding
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")
    columns: List[TemplateColumnModel]


class PageMargins(_Base):
    top: int = Field(default=15, ge=0, le=100)  # mm
    bottom: int = Field(default=15, ge=0, le=100)
    left: int = Field(default=15, ge=0, le=100)
    right: int = Field(default=15, ge=0, le=100)


class PageSetup(_Base):
    size: Literal["A4", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins: PageMargins = Field(default_factory=PageMargins)


class TemplateDocumentModel(_Base):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    # Document-surface only (PDF render); email docs omit it.
    page_setup: Optional[PageSetup] = Field(default=None, alias="pageSetup")
    sections: List[TemplateSectionModel] = Field(default_factory=list)

    def iter_blocks(self):
        """Top-level blocks (post-expansion render path)."""
        for section in self.sections:
            for column in section.columns:
                for block in column.blocks:
                    yield section, column, block

    def iter_all_blocks(self):
        """Every block incl. repeater-body children - token/condition scans."""
        for section in self.sections:
            for column in section.columns:
                for block in column.blocks:
                    yield section, column, block
                    if isinstance(block, RepeaterBlock):
                        for child in block.body:
                            yield section, column, child


def _block_token_values(block: TemplateBlockModel) -> List[str]:
    if isinstance(block, HeadingBlock):
        return [block.text]
    if isinstance(block, TextBlock):
        return [block.html]
    if isinstance(block, ButtonBlock):
        return [block.label, block.href]
    if isinstance(block, ImageBlock) and block.href:
        return [block.href]
    if isinstance(block, CustomHtmlBlock):
        return [block.html]
    if isinstance(block, QrBlock):
        return [block.data]
    if isinstance(block, TableBlock):
        # Footer cells bind scalar facts; column headers are static.
        cells = [cell.text for row in (block.footer or []) for cell in row.cells]
        return cells
    return []


def _doc_tokens(doc: TemplateDocumentModel, subject: str) -> set:
    """Context-scalar tokens only - row.* (repeater/table scope) excluded so a
    required context fact is never 'satisfied' by an iterator-local ref."""
    values: List[str] = [subject]
    for _s, _c, block in doc.iter_blocks():
        values.extend(_block_token_values(block))
        # repeater body refs are row-scoped → not context facts; skip for the
        # required-fact gate (validated separately against the source).
    return {tok for tok in collect_tokens(*values) if not tok.startswith("row.")}


def _iterator_problems(
    doc: TemplateDocumentModel,
    list_facts: "Sequence[Any]",
    scalar_facts: Sequence[str],
) -> List[str]:
    """Document-surface checks for table/repeater blocks (plan sprint-3/03 D10).

    ``list_facts`` are the context's ``ListFact`` rows (key + item_facts);
    ``scalar_facts`` are the context's scalar fact keys. Branches on the
    presence of iterators, so email docs without table/repeater are unaffected.
    """
    problems: List[str] = []
    by_key = {lf.key: lf for lf in list_facts}

    # row.* tokens are legal ONLY inside a table/repeater body. Collect the
    # blocks that ARE iterator bodies (table cells / repeater children) first.
    iterator_block_ids: set = set()
    for _s, _c, block in doc.iter_blocks():
        if isinstance(block, RepeaterBlock):
            for child in block.body:
                iterator_block_ids.add(id(child))

    for _section, _column, block in doc.iter_all_blocks():
        if isinstance(block, TableBlock):
            source = by_key.get(block.source)
            if source is None:
                problems.append(
                    f"Table {block.id}: source '{block.source}' is not a list field of this context."
                )
            if not block.columns:
                problems.append(f"Table {block.id}: add at least one column.")
            else:
                item_keys = {f.key for f in source.item_facts} if source else set()
                for col in block.columns:
                    if source is not None and col.key not in item_keys:
                        problems.append(
                            f"Table {block.id}: column '{col.key}' is not a row field of '{block.source}'."
                        )
            # Footer cells bind SCALAR context facts.
            for frow in block.footer or []:
                for cell in frow.cells:
                    for tok in collect_tokens(cell.text):
                        if tok.startswith("row."):
                            problems.append(
                                f"Table {block.id}: footer cell uses row.* - footer binds totals (scalar facts) only."
                            )
                        elif scalar_facts and tok not in scalar_facts:
                            problems.append(
                                f"Table {block.id}: footer references unknown field '{tok}'."
                            )

        elif isinstance(block, RepeaterBlock):
            source = by_key.get(block.source)
            if source is None:
                problems.append(
                    f"Repeater {block.id}: source '{block.source}' is not a list field of this context."
                )
            if not block.body:
                problems.append(f"Repeater {block.id}: add at least one block to the body.")
            item_keys = {f.key for f in source.item_facts} if source else set()
            for child in block.body:
                for value in _block_token_values(child):
                    for tok in collect_tokens(value):
                        if tok.startswith("row."):
                            sub = tok[len("row."):]
                            if source is not None and sub not in item_keys:
                                problems.append(
                                    f"Repeater {block.id}: row field '{sub}' is not a field of '{block.source}'."
                                )

    # row.* used OUTSIDE any iterator body = scope leak.
    for _s, _c, block in doc.iter_all_blocks():
        if id(block) in iterator_block_ids or isinstance(block, (TableBlock, RepeaterBlock)):
            continue
        for value in _block_token_values(block):
            for tok in collect_tokens(value):
                if tok.startswith("row."):
                    problems.append(
                        f"Block {block.id}: row.* fields only work inside a table or repeater."
                    )
    return problems


# --- F2 slice 2: fixed-canvas document (badge / ticket / certificate) -------
# A SECOND doc shape, polymorphic by template ``type`` (canvas-doc when badge).
# Absolute-positioned elements over a fixed physical page (plan sprint-3/03
# D14). Geometry stored in mm (print-authoritative); ``canvas.unit`` is the
# editor's display unit only. ``z`` = array order (no explicit field). Mirrors
# ``types/templates.ts`` (parity-pinned by tests/test_template_parity.py).

CanvasUnit = Literal["mm", "in", "px"]


class _CanvasElementBase(_Base):
    id: str
    x: float
    y: float
    w: float = Field(gt=0)
    h: float = Field(gt=0)
    rotation: float = 0.0
    conditions_json: Conditions = Field(default=None, alias="conditionsJson")


class CanvasTextElement(_CanvasElementBase):
    type: Literal["text"]
    content: str = ""
    # Any bundled family name (app/template_engine/fonts.py FONT_NAMES). Free
    # string - an unknown family falls back at render, never a 422.
    font_family: str = Field(default="Inter", alias="fontFamily")
    font_size: float = Field(default=12.0, gt=0, le=400, alias="fontSize")
    weight: Literal[400, 600, 700] = 400
    align: Align = "left"
    color: str = "#18181B"
    line_height: float = Field(default=1.3, gt=0, le=4, alias="lineHeight")


class CanvasImageElement(_CanvasElementBase):
    type: Literal["image"]
    storage_key: Optional[str] = Field(default=None, alias="storageKey")
    src: Optional[str] = None
    fit: Literal["contain", "cover"] = "contain"


class CanvasShapeElement(_CanvasElementBase):
    type: Literal["shape"]
    kind: Literal["rect", "ellipse", "line"] = "rect"
    fill: Optional[str] = "#FF5A00"
    stroke: Optional[str] = None
    stroke_width: float = Field(default=0.0, ge=0, le=50, alias="strokeWidth")
    radius: float = Field(default=0.0, ge=0, le=200)


class CanvasQrElement(_CanvasElementBase):
    type: Literal["qr"]
    data: str = ""
    ec_level: Literal["L", "M", "Q", "H"] = Field(default="M", alias="ecLevel")


# Cross-surface parity (user request): divider / socialLinks / customHtml - the
# flowing-block elements that also make sense positioned on a fixed card.
class CanvasDividerElement(_CanvasElementBase):
    type: Literal["divider"]
    color: str = "#E4E4E7"
    thickness: float = Field(default=0.4, gt=0, le=20)  # mm


class CanvasSocialElement(_CanvasElementBase):
    type: Literal["socialLinks"]
    # None = render the tenant's branding socials at render time.
    links: Optional[List[SocialLink]] = None
    align: Align = "center"
    icon_size: int = Field(default=18, ge=8, le=64, alias="iconSize")


class CanvasHtmlElement(_CanvasElementBase):
    type: Literal["customHtml"]
    html: str = ""  # sanitized in place by validate_canvas_doc


class CanvasBrandHeaderElement(_CanvasElementBase):
    type: Literal["brandHeader"]
    overrides: Optional[BrandHeaderOverrides] = None


class CanvasBrandFooterElement(_CanvasElementBase):
    type: Literal["brandFooter"]
    overrides: Optional[BrandFooterOverrides] = None


# Discriminated on `type` so a malformed element reports its OWN error (e.g.
# "w: greater than 0"), not a misleading "should be 'text'" from the first arm.
CanvasElementModel = Annotated[
    Union[
        CanvasTextElement,
        CanvasImageElement,
        CanvasShapeElement,
        CanvasQrElement,
        CanvasDividerElement,
        CanvasSocialElement,
        CanvasHtmlElement,
        CanvasBrandHeaderElement,
        CanvasBrandFooterElement,
    ],
    Field(discriminator="type"),
]


class CanvasSide(_Base):
    name: str = "front"
    elements: List[CanvasElementModel] = Field(default_factory=list)


class CanvasSize(_Base):
    width: float = Field(gt=0, le=2000)  # mm
    height: float = Field(gt=0, le=2000)
    unit: CanvasUnit = "mm"
    orientation: Literal["portrait", "landscape"] = "portrait"
    bleed: float = Field(default=3.0, ge=0, le=50)


class CanvasDocumentModel(_Base):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    canvas: CanvasSize
    sides: List[CanvasSide] = Field(default_factory=list)

    def iter_elements(self):
        for side in self.sides:
            for el in side.elements:
                yield side, el


def _element_token_values(el: CanvasElementModel) -> List[str]:
    if isinstance(el, CanvasTextElement):
        return [el.content]
    if isinstance(el, CanvasImageElement):
        return [el.src or ""]
    if isinstance(el, CanvasQrElement):
        return [el.data]
    if isinstance(el, CanvasHtmlElement):
        return [el.html]
    return []


def validate_canvas_doc(
    raw_doc: Dict[str, Any],
    *,
    fact_sources: Sequence[str],
    required_facts: Sequence[str] = (),
    scalar_facts: Sequence[str] = (),
) -> "tuple[CanvasDocumentModel, List[str]]":
    """Parse + validate a canvas document (plan sprint-3/03 D18).

    Checks: positive dims + known unit (Pydantic), ≥1 side + each side named,
    element ids unique WITHIN a side, merge tokens reference known context
    facts (unknown-ref), QR non-empty data, image src scheme-valid, conditions
    via the rule engine, required facts present. NO hard out-of-bounds fail
    (bleed = intentional overflow). Returns (model, problems).
    """
    from app.template_engine.contexts import ensure_core_contexts

    ensure_core_contexts()

    problems: List[str] = []
    try:
        doc = CanvasDocumentModel.model_validate(raw_doc)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return (
            CanvasDocumentModel(schemaVersion=1, canvas={"width": 86, "height": 54}, sides=[]),
            [f"Invalid badge document at {loc}: {first['msg']}"],
        )

    if not doc.sides:
        problems.append("A badge needs at least one side.")
    for i, side in enumerate(doc.sides):
        if not side.name.strip():
            problems.append(f"Side {i + 1} needs a name.")
        seen: set = set()
        for el in side.elements:
            if el.id in seen:
                problems.append(f"Side '{side.name}': duplicate element id '{el.id}'.")
            seen.add(el.id)

    scalar = set(scalar_facts)
    used: set = set()
    for _side, el in doc.iter_elements():
        if el.conditions_json is not None:
            for issue in validate_tree(el.conditions_json, fact_sources):
                problems.append(f"Element {el.id} visibility: {issue}")
        # Sanitize custom-HTML elements in place (the model is what's persisted).
        if isinstance(el, CanvasHtmlElement):
            el.html = sanitize_custom_html(el.html)
        if isinstance(el, CanvasQrElement) and not el.data.strip():
            problems.append(f"QR element {el.id}: add the data field (e.g. {{{{ticketCode}}}}).")
        if isinstance(el, CanvasImageElement) and el.src:
            scheme = el.src.split(":", 1)[0].lower() if ":" in el.src.split("/", 1)[0] else "https"
            # A {{token}} src is a merge placeholder - scheme-checked post-merge.
            if "{{" not in el.src and scheme not in ("http", "https", "data"):
                problems.append(f"Image element {el.id}: unsupported image URL scheme.")
        for value in _element_token_values(el):
            for tok in collect_tokens(value):
                used.add(tok)
                if scalar and tok not in scalar:
                    problems.append(f"Element {el.id}: unknown merge field '{{{{{tok}}}}}'.")

    missing = [fact for fact in required_facts if fact not in used]
    if missing:
        tokens = ", ".join("{{%s}}" % m for m in missing)
        problems.append(f"Required merge field{'s' if len(missing) > 1 else ''} missing: {tokens}.")

    return doc, problems


def validate_doc(
    raw_doc: Dict[str, Any],
    subject: str,
    *,
    fact_sources: Sequence[str],
    required_facts: Sequence[str],
    list_facts: "Sequence[Any] | None" = None,
    scalar_facts: Sequence[str] = (),
) -> "tuple[TemplateDocumentModel, List[str]]":
    """Parse + sanitize + validate a document. Returns (model, problems).

    Problems non-empty ⇒ the caller raises a named 422. The returned model
    has rich/custom HTML already SANITIZED - persist the model's dump, never
    the raw input.

    ``list_facts`` / ``scalar_facts`` drive the document-surface checks
    (table/repeater source + row-key + scope, plan sprint-3/03 D10). Omitted
    (email path) → those checks are skipped; row.* outside an iterator still
    fails as a scope leak regardless.
    """
    # The 'recipient' fact source registers with the core contexts - make
    # sure it exists before validating visibility trees against it.
    from app.template_engine.contexts import ensure_core_contexts

    ensure_core_contexts()

    problems: List[str] = []
    try:
        doc = TemplateDocumentModel.model_validate(raw_doc)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(p) for p in first["loc"])
        return TemplateDocumentModel(schemaVersion=1, sections=[]), [
            f"Invalid document at {loc}: {first['msg']}"
        ]

    for section in doc.sections:
        expected = len(SECTION_LAYOUT_COLUMNS[section.layout])
        if len(section.columns) != expected:
            problems.append(
                f"Section {section.id}: layout {section.layout} needs {expected} columns, has {len(section.columns)}."
            )
        if section.conditions_json is not None:
            for issue in validate_tree(section.conditions_json, fact_sources):
                problems.append(f"Section {section.id} visibility: {issue}")

    for _section, _column, block in doc.iter_all_blocks():
        if block.conditions_json is not None:
            for issue in validate_tree(block.conditions_json, fact_sources):
                problems.append(f"Block {block.id} visibility: {issue}")
        # Sanitize stored HTML in place (the model is what gets persisted).
        if isinstance(block, TextBlock):
            block.html = sanitize_text_html(block.html)
        elif isinstance(block, CustomHtmlBlock):
            block.html = sanitize_custom_html(block.html)

    # Document-surface iterator checks (table/repeater) + row-scope leak. The
    # scope-leak check runs even on the email path (list_facts None ⇒ empty),
    # so a stray row.* in an email template is still caught.
    problems.extend(_iterator_problems(doc, list_facts or (), scalar_facts))

    used = _doc_tokens(doc, subject)
    missing = [fact for fact in required_facts if fact not in used]
    if missing:
        tokens = ", ".join("{{%s}}" % m for m in missing)
        problems.append(
            f"Required merge field{'s' if len(missing) > 1 else ''} missing: {tokens}. "
            "Add them to the design or subject before saving."
        )

    return doc, problems
