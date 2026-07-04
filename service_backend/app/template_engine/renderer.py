"""render_email — ONE renderer for every product mail (plan 07 D9/D10).

Full pipeline per send: resolve brand values for the RECIPIENT's tenant →
prune blocks whose visibility conditions fail for THIS recipient (rule
engine, fail closed) → compile MJML via mrml → merge-substitute facts →
{subject, html, text}. The preview endpoint runs this same function — the
preview IS the production renderer, no drift.

This is the contract the Workflow engine's SendEmail action consumes next.
"""

import ipaddress
import logging
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.config import settings
from app.models.template import Template
from app.models.tenant import Tenant
from app.models.tenant_branding import TenantBranding
from app.rule_engine.evaluator import collect_fact_keys, evaluate
from app.rule_engine.registry import resolve_facts
from app.template_engine.compiler import BrandValues, compile_document, document_text
from app.template_engine.contexts import ensure_core_contexts
from app.template_engine.expand import expand_iterators
from app.template_engine.merge import render_tokens
from app.template_engine.schemas import TemplateDocumentModel

logger = logging.getLogger(__name__)


@dataclass
class RenderedEmail:
    subject: str
    html: str
    text: str


def brand_values_for_tenant(db: Session, tenant_id) -> BrandValues:
    """Tenant brand snapshot — resolved at RENDER time (D4 live-follow)."""
    if tenant_id is None:
        # Platform scope (operator maintaining defaults) — stock values.
        return BrandValues()
    tenant = db.get(Tenant, tenant_id)
    row: Optional[TenantBranding] = (
        db.query(TenantBranding).filter(TenantBranding.tenant_id == tenant_id).first()
    )
    values = BrandValues(tenant_name=tenant.name if tenant else "Your workspace")
    if row is None:
        return values

    if row.logo_key and tenant is not None:
        values.logo_url = (
            f"{settings.public_base_url}/public/branding/{tenant.slug}/asset/logo?v={row.version}"
        )
    tokens = row.tokens_json or {}
    primary = (tokens.get("light") or {}).get("primary")
    if primary:
        values.primary_color = primary

    footer = row.footer_json or {}
    footer_bits = [footer.get("companyName"), footer.get("addressLine"), footer.get("tagline")]
    values.footer_text = " · ".join(bit for bit in footer_bits if bit)

    socials = row.socials_json or {}
    values.socials = [
        {"platform": platform, "href": href}
        for platform, href in socials.items()
        if href
    ]
    return values


def _prune(doc: TemplateDocumentModel, rule_facts: Dict[str, Any]) -> TemplateDocumentModel:
    """Drop sections/blocks whose visibility conditions fail (fail closed)."""
    sections = []
    for section in doc.sections:
        if section.conditions_json is not None and not evaluate(section.conditions_json, rule_facts):
            continue
        columns = []
        for column in section.columns:
            kept = [
                block
                for block in column.blocks
                if block.conditions_json is None or evaluate(block.conditions_json, rule_facts)
            ]
            columns.append(column.model_copy(update={"blocks": kept}))
        sections.append(section.model_copy(update={"columns": columns}))
    return doc.model_copy(update={"sections": sections})


def _conditioned(doc: TemplateDocumentModel) -> bool:
    if any(s.conditions_json is not None for s in doc.sections):
        return True
    return any(b.conditions_json is not None for _s, _c, b in doc.iter_blocks())


def render_email(
    db: Session,
    template: Template,
    tenant_id: str,
    facts: Dict[str, str],
    *,
    rule_objects: Optional[Dict[str, Any]] = None,
    mode: str = "send",
) -> RenderedEmail:
    """Render ``template`` for a recipient in ``tenant_id``.

    ``facts`` = merge-field values (context vocabulary). ``rule_objects`` =
    rule-engine source objects for visibility conditions (e.g.
    ``{"recipient": user}``); absent objects fail conditioned blocks CLOSED
    by design. ``mode="preview"`` renders unresolved tokens loudly and skips
    pruning (the editor shows every block; real pruning needs a real
    recipient).
    """
    ensure_core_contexts()
    doc = TemplateDocumentModel.model_validate(template.doc_json)

    if mode != "preview" and _conditioned(doc):
        needed: set = set()
        for section in doc.sections:
            needed |= collect_fact_keys(section.conditions_json)
        for _s, _c, block in doc.iter_blocks():
            needed |= collect_fact_keys(block.conditions_json)
        rule_facts = resolve_facts(db, rule_objects or {}, only_keys=needed)
        doc = _prune(doc, rule_facts)

    # Expand table/repeater blocks into concrete structure BEFORE compile
    # (shared with the PDF seam — invoice line-item tables work in email too).
    # No-op for docs without iterators (every legacy template unchanged).
    doc, facts = expand_iterators(doc, facts, mode=mode)

    brand = brand_values_for_tenant(db, tenant_id)
    subject = render_tokens(template.subject, facts, mode=mode, escape=False)
    try:
        html = compile_document(doc, brand, facts, title=subject, mode=mode)
    except ValueError:
        logger.exception("template %s failed to compile", template.key)
        raise
    text = document_text(doc, brand, facts)
    return RenderedEmail(subject=subject, html=html, text=text)


def render_email_doc(
    db: Session,
    *,
    doc_json: Dict[str, Any],
    subject: str,
    context: str,
    tenant_id: str,
    facts: Dict[str, str],
    rule_objects: Optional[Dict[str, Any]] = None,
    mode: str = "send",
) -> RenderedEmail:
    """Render a PER-USE block document (a copy of a template, edited inline) —
    same pipeline as ``render_email`` but over a raw doc + subject rather than a
    persisted ``Template`` row. Used by notification specs / workflow email
    actions that store their own edited copy of a template."""
    transient = Template(doc_json=doc_json, subject=subject, context=context, key="adhoc")
    return render_email(db, transient, tenant_id, facts, rule_objects=rule_objects, mode=mode)


# --- F2 document surface: block doc → PDF bytes ----------------------------

_FONTS_DIR = Path(__file__).resolve().parent.parent / "assets" / "fonts"


def _font_mime(name: str) -> str:
    if name.endswith(".woff2"):
        return "font/woff2"
    if name.endswith(".woff"):
        return "font/woff"
    return "font/ttf"


def make_url_fetcher(db: Session, tenant_id):
    """A WeasyPrint url_fetcher that resolves OUR urls to bytes in-process (D8).

    - bundled font urls (``FONT_BASE_URL/...``) → ``app/assets/fonts`` bytes
      (deterministic PDFs, no host fontconfig dependency).
    - branding / storage-backed urls (anything under ``public_base_url`` or a
      ``conn:`` storage key) → bytes via ``storage_for_tenant`` / the branding
      asset, killing the localhost-logo round-trip (the email-logo gotcha).
    - everything else (external ``https://`` images) → WeasyPrint's default.
    """
    from weasyprint import default_url_fetcher

    from app.template_engine.compiler_pdf import FONT_BASE_URL

    def fetch(url: str):
        if url.startswith(FONT_BASE_URL):
            name = url.rsplit("/", 1)[-1]
            path = _FONTS_DIR / name
            if path.is_file():
                return {"string": path.read_bytes(), "mime_type": _font_mime(name)}
            # Missing bundled font — fall through to WeasyPrint's font fallback.
            raise FileNotFoundError(name)

        resolved = _resolve_internal_asset(db, tenant_id, url)
        if resolved is not None:
            data, mime = resolved
            return {"string": data, "mime_type": mime}
        # SSRF guard: the render is the first place the SERVER fetches a
        # tenant-authored url (WeasyPrint resolves <img src> server-side). A
        # `templates.read` user must not be able to make us hit internal hosts
        # (169.254.169.254 metadata, localhost services, RFC1918). Block
        # non-http(s) schemes + any host resolving to a private/loopback IP.
        if _is_blocked_fetch_url(url):
            raise ValueError(f"blocked non-public url: {url}")
        return default_url_fetcher(url, timeout=10)

    return fetch


def _is_blocked_fetch_url(url: str) -> bool:
    """True ⇒ refuse to fetch (SSRF protection). ``data:`` is inline (allowed);
    only ``http(s)`` external hosts are fetched, and only if they resolve to a
    public address. (DNS-rebinding TOCTOU is a known residual — acceptable for
    a low-frequency render path; revisit if it becomes a vector.)"""
    try:
        parsed = urlparse(url)
    except ValueError:
        return True
    if parsed.scheme == "data":
        return False  # inline base64 — no network fetch
    if parsed.scheme not in ("http", "https"):
        return True  # file:, ftp:, etc.
    host = parsed.hostname
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return True
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or ip.is_multicast
            or ip.is_unspecified
        ):
            return True
    return False


def _resolve_internal_asset(db: Session, tenant_id, url: str):
    """Resolve a branding/storage URL to (bytes, mime) IN-PROCESS, or None to
    let WeasyPrint fetch it normally. Never raises — a missing asset just
    falls through to the default fetcher (best-effort, like the email logo)."""
    from app.services.storage import storage_for_tenant

    base = settings.public_base_url
    if not url.startswith(base):
        return None
    try:
        path_part = url[len(base):].split("?", 1)[0]
        storage = storage_for_tenant(db, tenant_id)
        # Branding asset route: /public/branding/{slug}/asset/{kind}
        if "/public/branding/" in path_part and "/asset/" in path_part:
            return _resolve_branding_asset(db, storage, path_part)
        return None
    except Exception:  # defense-in-depth: an asset hiccup must not 500 a render
        logger.warning("url_fetcher could not resolve internal asset %s", url, exc_info=True)
        return None


def _resolve_branding_asset(db: Session, storage, path_part: str):
    """Branding asset path → (bytes, mime) via the tenant's stored key."""
    from app.models.tenant import Tenant
    from app.models.tenant_branding import TenantBranding

    # /public/branding/<slug>/asset/<kind>
    parts = [p for p in path_part.split("/") if p]
    slug = parts[parts.index("branding") + 1]
    kind = parts[-1]
    tenant = db.query(Tenant).filter(Tenant.slug == slug).first()
    if tenant is None:
        return None
    row = db.query(TenantBranding).filter(TenantBranding.tenant_id == tenant.id).first()
    if row is None:
        return None
    key = {"logo": row.logo_key, "favicon": row.favicon_key, "illustration": row.illustration_key}.get(kind)
    mime = {"logo": row.logo_mime, "favicon": row.favicon_mime, "illustration": row.illustration_mime}.get(kind)
    if not key:
        return None
    kind_, value = storage.resolve(key)
    if kind_ == "path":
        from pathlib import Path as _Path

        data = _Path(value).read_bytes()
        return data, mime or "application/octet-stream"
    # Remote (url/presigned) — let WeasyPrint fetch it (already a real URL).
    return None


def _prepare_document(
    db: Session,
    template: Template,
    tenant_id,
    facts: Dict[str, Any],
    rule_objects: Optional[Dict[str, Any]],
    mode: str,
):
    """Shared front half: validate → prune-by-conditions → expand-iterators →
    resolve brand. Used by both the PDF and the browser-preview HTML renders."""
    ensure_core_contexts()
    doc = TemplateDocumentModel.model_validate(template.doc_json)

    if mode != "preview" and _conditioned(doc):
        needed: set = set()
        for section in doc.sections:
            needed |= collect_fact_keys(section.conditions_json)
        for _s, _c, block in doc.iter_blocks():
            needed |= collect_fact_keys(block.conditions_json)
        rule_facts = resolve_facts(db, rule_objects or {}, only_keys=needed)
        doc = _prune(doc, rule_facts)

    doc, facts = expand_iterators(doc, facts, mode=mode)
    brand = brand_values_for_tenant(db, tenant_id)
    return doc, facts, brand


def render_document(
    db: Session,
    template: Template,
    tenant_id,
    facts: Dict[str, Any],
    *,
    rule_objects: Optional[Dict[str, Any]] = None,
    mode: str = "send",
) -> bytes:
    """Render ``template``'s block doc to PDF bytes (plan sprint-3/03 D2).

    Pipeline mirrors ``render_email``: brand-resolve → prune-by-conditions →
    expand-iterators → compile_pdf (HTML+CSS) → WeasyPrint write_pdf. The
    download/output path. WeasyPrint is CPU-bound + sync — the router offloads
    this to a threadpool.
    """
    from weasyprint import HTML

    from app.template_engine.compiler_pdf import compile_pdf_html

    doc, facts, brand = _prepare_document(db, template, tenant_id, facts, rule_objects, mode)
    html = compile_pdf_html(doc, brand, facts, mode=mode)

    return HTML(
        string=html,
        base_url=settings.public_base_url,
        url_fetcher=make_url_fetcher(db, tenant_id),
    ).write_pdf()


def render_document_html(
    db: Session,
    template: Template,
    tenant_id,
    facts: Dict[str, Any],
    *,
    rule_objects: Optional[Dict[str, Any]] = None,
    mode: str = "send",
) -> str:
    """Render the block doc to an in-app PREVIEW HTML sheet (no WeasyPrint, no
    browser PDF-viewer chrome). Same compiler/merge/brand as the PDF — the
    editor shows this; Download produces the WeasyPrint PDF."""
    from app.template_engine.compiler_pdf import compile_pdf_html

    doc, facts, brand = _prepare_document(db, template, tenant_id, facts, rule_objects, mode)
    return compile_pdf_html(doc, brand, facts, mode=mode, for_browser=True)


# --- F2 slice 2: fixed-canvas surface (badge/ticket/cert) → PDF -------------


def _prune_canvas(doc, rule_facts: Dict[str, Any]):
    """Drop elements whose visibility conditions fail (fail closed)."""
    from app.rule_engine.evaluator import evaluate

    sides = []
    for side in doc.sides:
        kept = [
            el
            for el in side.elements
            if el.conditions_json is None or evaluate(el.conditions_json, rule_facts)
        ]
        sides.append(side.model_copy(update={"elements": kept}))
    return doc.model_copy(update={"sides": sides})


def _prepare_canvas(
    db: Session,
    template: Template,
    tenant_id,
    facts: Dict[str, Any],
    rule_objects: Optional[Dict[str, Any]],
    mode: str,
):
    """Validate → prune-elements-by-conditions → resolve brand. Mirrors
    ``_prepare_document`` for the canvas doc shape."""
    from app.template_engine.schemas import CanvasDocumentModel

    ensure_core_contexts()
    doc = CanvasDocumentModel.model_validate(template.doc_json)

    conditioned = any(
        el.conditions_json is not None for _side, el in doc.iter_elements()
    )
    if mode != "preview" and conditioned:
        needed: set = set()
        for _side, el in doc.iter_elements():
            needed |= collect_fact_keys(el.conditions_json)
        rule_facts = resolve_facts(db, rule_objects or {}, only_keys=needed)
        doc = _prune_canvas(doc, rule_facts)

    brand = brand_values_for_tenant(db, tenant_id)
    return doc, facts, brand


def render_canvas(
    db: Session,
    template: Template,
    tenant_id,
    facts: Dict[str, Any],
    *,
    rule_objects: Optional[Dict[str, Any]] = None,
    mode: str = "send",
) -> bytes:
    """Render a canvas (badge) doc to PDF bytes (plan sprint-3/03 D13).

    Each side → one page sized to the canvas (no margin). Same WeasyPrint
    backend + bundled fonts + url_fetcher as the flowing-doc surface. CPU-bound
    + sync — the router offloads to a threadpool; batch wraps this N times (D16).
    """
    from weasyprint import HTML

    from app.template_engine.compiler_canvas import compile_canvas_html

    doc, facts, brand = _prepare_canvas(db, template, tenant_id, facts, rule_objects, mode)
    html = compile_canvas_html(doc, brand, facts, mode=mode)
    return HTML(
        string=html,
        base_url=settings.public_base_url,
        url_fetcher=make_url_fetcher(db, tenant_id),
    ).write_pdf()


def render_canvas_html(
    db: Session,
    template: Template,
    tenant_id,
    facts: Dict[str, Any],
    *,
    rule_objects: Optional[Dict[str, Any]] = None,
    mode: str = "send",
) -> str:
    """In-app PREVIEW HTML (stacked centred sheets, no WeasyPrint) — same
    compiler/merge/brand as the canvas PDF."""
    from app.template_engine.compiler_canvas import compile_canvas_html

    doc, facts, brand = _prepare_canvas(db, template, tenant_id, facts, rule_objects, mode)
    return compile_canvas_html(doc, brand, facts, mode=mode, for_browser=True)


def render_canvas_batch(
    db: Session,
    template: Template,
    tenant_id,
    facts_list: "list[Dict[str, Any]]",
    *,
    rule_objects_list: "Optional[list[Optional[Dict[str, Any]]]]" = None,
) -> bytes:
    """Batch seam (D16): render ONE artifact per facts dict → a single
    multi-page PDF (one artifact per page-set). Wraps ``compile_canvas_html`` N
    times and concatenates the side-HTML so WeasyPrint paginates once. The real
    trigger ("print all badges for Event X" → attendee query) lands with Cluster
    H; exercised here with synthetic sample-fact dicts. Celery-queued for large
    N — the unit is the seam, zero rework.
    """
    from weasyprint import HTML

    from app.template_engine.compiler_canvas import compile_canvas_html

    rule_objects_list = rule_objects_list or [None] * len(facts_list)
    bodies: list[str] = []
    css_head = ""
    for facts, rule_objects in zip(facts_list, rule_objects_list):
        doc, f, brand = _prepare_canvas(db, template, tenant_id, dict(facts), rule_objects, "send")
        full = compile_canvas_html(doc, brand, f, mode="send")
        # Pull the <head>…</head> once (identical per artifact — same template);
        # concatenate every artifact's <body> sides so all paginate as one PDF.
        head, _, rest = full.partition("</head>")
        if not css_head:
            css_head = head + "</head>"
        body = rest.partition("<body>")[2].partition("</body>")[0]
        bodies.append(body)

    html = css_head + "<body>" + "".join(bodies) + "</body></html>"
    return HTML(
        string=html,
        base_url=settings.public_base_url,
        url_fetcher=make_url_fetcher(db, tenant_id),
    ).write_pdf()
