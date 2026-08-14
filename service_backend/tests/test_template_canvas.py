"""F2 slice 2 - fixed-canvas (badge) tests: validate_canvas_doc matrix, the
compile_canvas HTML intermediate (never byte-golden a PDF), QR generation,
render smoke (valid PDF, N sides = N pages), the batch seam, and the API
preview/create surface.
"""

from app.models.template import TEMPLATE_TYPE_BADGE, Template
from app.template_engine.compiler import BrandValues
from app.template_engine.compiler_canvas import compile_canvas_html
from app.template_engine.contexts import get_context
from app.template_engine.renderer import render_canvas, render_canvas_batch
from app.template_engine.schemas import CanvasDocumentModel, validate_canvas_doc
from app.template_engine.seed_templates import _badge_doc
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ---- helpers --------------------------------------------------------------

def _canvas_doc(elements, *, sides=None, width=86, height=54):
    if sides is None:
        sides = [{"name": "front", "elements": elements}]
    return {
        "schemaVersion": 1,
        "canvas": {"width": width, "height": height, "unit": "mm",
                   "orientation": "landscape", "bleed": 3},
        "sides": sides,
    }


def _text_el(id="t1", content="{{attendeeName}}"):
    return {"id": id, "type": "text", "x": 5, "y": 5, "w": 40, "h": 10, "rotation": 0,
            "content": content, "fontFamily": "Poppins", "fontSize": 14, "weight": 700,
            "align": "left", "color": "#000", "lineHeight": 1.2}


def _qr_el(id="q1", data="{{ticketCode}}"):
    return {"id": id, "type": "qr", "x": 60, "y": 10, "w": 20, "h": 20,
            "rotation": 0, "data": data, "ecLevel": "M"}


_FACTS = ("attendeeName", "role", "company", "ticketCode")
_SAMPLE = {"attendeeName": "Alex Tan", "role": "Speaker", "company": "Acme", "ticketCode": "TKT-1"}


def _login(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


# ---- validate_canvas_doc matrix (D18) -------------------------------------

class TestValidateCanvas:
    def test_valid(self):
        doc, problems = validate_canvas_doc(
            _canvas_doc([_text_el(), _qr_el()]),
            fact_sources=(), scalar_facts=_FACTS, required_facts=("attendeeName",),
        )
        assert problems == []
        assert len(doc.sides[0].elements) == 2

    def test_duplicate_element_id(self):
        _doc, problems = validate_canvas_doc(
            _canvas_doc([_text_el(id="x"), _qr_el(id="x")]),
            fact_sources=(), scalar_facts=_FACTS,
        )
        assert any("duplicate element id" in p for p in problems)

    def test_unknown_merge_field(self):
        _doc, problems = validate_canvas_doc(
            _canvas_doc([_text_el(content="{{nope}}")]),
            fact_sources=(), scalar_facts=_FACTS,
        )
        assert any("unknown merge field" in p for p in problems)

    def test_empty_qr_data(self):
        _doc, problems = validate_canvas_doc(
            _canvas_doc([_qr_el(data="")]),
            fact_sources=(), scalar_facts=_FACTS,
        )
        assert any("QR element" in p for p in problems)

    def test_bad_image_scheme(self):
        img = {"id": "i1", "type": "image", "x": 0, "y": 0, "w": 10, "h": 10,
               "rotation": 0, "src": "file:///etc/passwd", "fit": "contain"}
        _doc, problems = validate_canvas_doc(_canvas_doc([img]), fact_sources=(), scalar_facts=_FACTS)
        assert any("scheme" in p for p in problems)

    def test_token_image_src_allowed(self):
        img = {"id": "i1", "type": "image", "x": 0, "y": 0, "w": 10, "h": 10,
               "rotation": 0, "src": "{{logoUrl}}", "fit": "contain"}
        # {{token}} src is a merge placeholder - scheme-checked post-merge, never
        # at save; only the unknown-field check applies.
        _doc, problems = validate_canvas_doc(_canvas_doc([img]), fact_sources=(), scalar_facts=("logoUrl",))
        assert problems == []

    def test_no_sides(self):
        _doc, problems = validate_canvas_doc(_canvas_doc([], sides=[]), fact_sources=())
        assert any("at least one side" in p for p in problems)

    def test_required_fact_missing(self):
        _doc, problems = validate_canvas_doc(
            _canvas_doc([_qr_el()]),
            fact_sources=(), scalar_facts=_FACTS, required_facts=("attendeeName",),
        )
        assert any("Required merge field" in p for p in problems)

    def test_negative_dims_rejected(self):
        _doc, problems = validate_canvas_doc(_canvas_doc([_text_el()], width=0), fact_sources=())
        assert problems  # Pydantic gt=0 rejects width 0


# ---- compile_canvas_html (HTML intermediate golden) ------------------------

class TestCompileCanvas:
    def test_mm_positioning_and_merge(self):
        doc = CanvasDocumentModel.model_validate(_canvas_doc([_text_el()]))
        html = compile_canvas_html(doc, BrandValues(), _SAMPLE, mode="send")
        assert "left:5mm" in html and "top:5mm" in html
        assert "width:40mm" in html and "height:10mm" in html
        assert "Alex Tan" in html
        assert "@page{size:86mm 54mm;margin:0}" in html

    def test_qr_inline_svg(self):
        doc = CanvasDocumentModel.model_validate(_canvas_doc([_qr_el()]))
        html = compile_canvas_html(doc, BrandValues(), _SAMPLE, mode="send")
        assert "<svg" in html  # segno inline SVG, server-side

    def test_two_sides_page_break(self):
        doc = CanvasDocumentModel.model_validate(
            _canvas_doc([], sides=[
                {"name": "front", "elements": [_text_el()]},
                {"name": "back", "elements": [_qr_el()]},
            ])
        )
        html = compile_canvas_html(doc, BrandValues(), _SAMPLE, mode="send")
        assert "page-break-after:always" in html

    def test_browser_preview_uses_sheets(self):
        doc = CanvasDocumentModel.model_validate(_canvas_doc([_text_el()]))
        html = compile_canvas_html(doc, BrandValues(), _SAMPLE, mode="preview", for_browser=True)
        assert "badge-side" in html and "box-shadow" in html
        assert "@page" not in html  # browser preview has no @page rule

    def test_preview_marks_unresolved(self):
        doc = CanvasDocumentModel.model_validate(_canvas_doc([_text_el(content="{{missing}}")]))
        html = compile_canvas_html(doc, BrandValues(), {}, mode="preview")
        assert "missing" in html  # loud ⟦missing?⟧ marker

    def test_css_injection_in_color_dropped(self):
        # A colour field carrying extra CSS declarations must not break out of
        # the style property.
        el = _text_el()
        el["color"] = "red;position:absolute;width:9999mm"
        doc = CanvasDocumentModel.model_validate(_canvas_doc([el]))
        html = compile_canvas_html(doc, BrandValues(), _SAMPLE, mode="send")
        assert "9999mm" not in html
        assert "color:#000000" in html  # fell back to the safe default

    def test_orientation_does_not_swap_dims(self):
        # width/height are authoritative; a portrait orientation on a wide canvas
        # must NOT swap the page (render would disagree with the editor).
        doc_raw = _canvas_doc([_text_el()])
        doc_raw["canvas"]["orientation"] = "portrait"  # contradicts 86>54 aspect
        doc = CanvasDocumentModel.model_validate(doc_raw)
        html = compile_canvas_html(doc, BrandValues(), _SAMPLE, mode="send")
        assert "@page{size:86mm 54mm;margin:0}" in html


# ---- render smoke (valid PDF, page count) ---------------------------------

class TestRenderCanvas:
    def _tmpl(self, doc):
        return Template(tenant_id=None, type=TEMPLATE_TYPE_BADGE, key="k", name="n",
                        context="badge.preview", subject="", doc_json=doc)

    def test_single_side_pdf(self):
        pdf = render_canvas(None, self._tmpl(_badge_doc()), None, _SAMPLE, mode="send")
        assert pdf[:5] == b"%PDF-" and len(pdf) > 1000

    def test_two_sided_two_pages(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        import io
        doc = _badge_doc()
        doc["sides"].append({"name": "back", "elements": [_qr_el()]})
        pdf = render_canvas(None, self._tmpl(doc), None, _SAMPLE, mode="send")
        assert len(PdfReader(io.BytesIO(pdf)).pages) == 2

    def test_batch_seam_one_page_each(self):
        try:
            from pypdf import PdfReader
        except ImportError:
            return
        import io
        facts = [dict(_SAMPLE, attendeeName=f"P{i}", ticketCode=f"T{i}") for i in range(3)]
        pdf = render_canvas_batch(None, self._tmpl(_badge_doc()), None, facts)
        assert len(PdfReader(io.BytesIO(pdf)).pages) == 3


# ---- cross-surface parity (QR block + canvas divider/social/html) ----------

class TestCrossSurfaceParity:
    def test_qr_block_email_png_and_pdf_svg(self):
        from app.template_engine.compiler import compile_document
        from app.template_engine.compiler_pdf import compile_pdf_html
        from app.template_engine.schemas import TemplateDocumentModel, validate_doc

        raw = {
            "schemaVersion": 1,
            "sections": [{
                "id": "s", "layout": "100", "background": None,
                "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": "c", "blocks": [
                    {"id": "q", "type": "qr", "data": "{{link}}", "ecLevel": "M", "size": 120, "align": "center"}
                ]}],
            }],
        }
        m, probs = validate_doc(raw, "", fact_sources=(), required_facts=(), scalar_facts=["link"])
        assert probs == []
        email = compile_document(m, BrandValues(), {"link": "https://x"}, title="t")
        assert "data:image/png" in email  # email = PNG data-uri
        pdf = compile_pdf_html(m, BrandValues(), {"link": "https://x"})
        assert "<svg" in pdf  # document = vector svg

    def test_canvas_divider_social_html(self):
        els = [
            {"id": "d", "type": "divider", "x": 5, "y": 20, "w": 40, "h": 2, "rotation": 0, "color": "#000", "thickness": 0.5},
            {"id": "h", "type": "customHtml", "x": 5, "y": 30, "w": 40, "h": 10, "rotation": 0, "html": "<b>{{role}}</b><script>x()</script>"},
            {"id": "so", "type": "socialLinks", "x": 5, "y": 40, "w": 40, "h": 6, "rotation": 0,
             "links": [{"platform": "website", "href": "https://acme.com"}], "align": "left", "iconSize": 12},
        ]
        doc, problems = validate_canvas_doc(_canvas_doc(els), fact_sources=(), scalar_facts=("role",))
        assert problems == []
        html = compile_canvas_html(doc, BrandValues(), {"role": "Speaker"}, mode="send")
        assert "border-top" in html  # divider
        assert "<script" not in html  # customHtml sanitized
        assert "website" in html  # social

    def test_mixed_elements_route_by_discriminator(self):
        # Regression: a non-discriminated Union mis-matched a brandHeader in a
        # doc with several element types and reported a misleading
        # "CanvasTextElement.type" error. The discriminated union routes each
        # element to its own model.
        els = [
            {"id": "s", "type": "shape", "x": 0, "y": 0, "w": 86, "h": 12, "rotation": 0, "kind": "rect", "fill": "#FF5A00", "stroke": None, "strokeWidth": 0, "radius": 0},
            {"id": "t", "type": "text", "x": 5, "y": 20, "w": 50, "h": 10, "rotation": 0, "content": "Hi", "fontFamily": "Inter", "fontSize": 12, "weight": 400, "align": "left", "color": "#000", "lineHeight": 1.2},
            {"id": "q", "type": "qr", "x": 60, "y": 20, "w": 20, "h": 20, "rotation": 0, "data": "x", "ecLevel": "M"},
            {"id": "d", "type": "divider", "x": 5, "y": 32, "w": 40, "h": 2, "rotation": 0, "color": "#000", "thickness": 0.4},
            {"id": "bh", "type": "brandHeader", "x": 0, "y": 0, "w": 40, "h": 12, "rotation": 0, "overrides": None},
            {"id": "bf", "type": "brandFooter", "x": 0, "y": 46, "w": 86, "h": 8, "rotation": 0, "overrides": None},
        ]
        _doc, problems = validate_canvas_doc(_canvas_doc(els), fact_sources=())
        assert problems == []

    def test_discriminator_reports_the_real_field(self):
        # A genuinely bad element now reports ITS error, not "should be 'text'".
        bad = {"id": "bh", "type": "brandHeader", "x": 0, "y": 0, "w": 0, "h": 12, "rotation": 0, "overrides": None}
        _doc, problems = validate_canvas_doc(_canvas_doc([bad]), fact_sources=())
        assert problems and "text" not in problems[0].lower()

    def test_canvas_brand_header_footer(self):
        els = [
            {"id": "bh", "type": "brandHeader", "x": 0, "y": 0, "w": 86, "h": 12, "rotation": 0, "overrides": None},
            {"id": "bf", "type": "brandFooter", "x": 0, "y": 46, "w": 86, "h": 8, "rotation": 0, "overrides": None},
        ]
        doc, problems = validate_canvas_doc(_canvas_doc(els), fact_sources=())
        assert problems == []
        brand = BrandValues(tenant_name="Acme Events", primary_color="#FF5A00")
        html = compile_canvas_html(doc, brand, {}, mode="send")
        # No logo set → header renders the tenant NAME on the brand colour.
        assert "Acme Events" in html
        assert "#FF5A00" in html


# ---- context + seed -------------------------------------------------------

def test_badge_context_registered():
    ctx = get_context("badge.preview")
    assert ctx is not None
    keys = {f.key for f in ctx.facts}
    assert {"attendeeName", "ticketCode"} <= keys
    assert ctx.required_facts == ("attendeeName",)


# ---- API surface ----------------------------------------------------------

class TestCanvasApi:
    def test_create_badge_template(self, client):
        headers = _login(client)
        res = client.post("/templates", headers=headers, json={
            "name": "My badge", "subject": "", "context": "badge.preview",
            "type": "badge", "doc": _canvas_doc([_text_el(), _qr_el()]),
        })
        assert res.status_code == 201, res.text
        assert res.json()["type"] == "badge"

    def test_create_badge_invalid_422(self, client):
        headers = _login(client)
        res = client.post("/templates", headers=headers, json={
            "name": "Bad", "subject": "", "context": "badge.preview",
            "type": "badge", "doc": _canvas_doc([_text_el(content="{{nope}}")]),
        })
        assert res.status_code == 422

    def test_preview_canvas_html(self, client):
        headers = _login(client)
        res = client.post("/templates/preview", headers=headers, json={
            "context": "badge.preview", "format": "canvasHtml",
            "doc": _canvas_doc([_text_el(), _qr_el()]),
        })
        assert res.status_code == 200, res.text
        assert res.headers["content-type"].startswith("text/html")
        assert "<svg" in res.text

    def test_preview_canvas_pdf(self, client):
        headers = _login(client)
        res = client.post("/templates/preview", headers=headers, json={
            "context": "badge.preview", "format": "canvasPdf",
            "doc": _canvas_doc([_text_el(), _qr_el()]),
        })
        assert res.status_code == 200, res.text
        assert res.headers["content-type"] == "application/pdf"
        assert res.content[:5] == b"%PDF-"
