"""Document render tests (plan sprint-3/03 slice 1) - table/repeater expansion,
PDF compiler HTML-intermediate goldens (never byte-golden the PDF),
render_document smoke, validate_doc document-branch matrix, url_fetcher asset
resolution, and the /templates/preview?format=pdf endpoint."""

from app.template_engine.compiler import BrandValues
from app.template_engine.compiler_pdf import FONT_BASE_URL, compile_pdf_html
from app.template_engine.contexts import ensure_core_contexts, get_context
from app.template_engine.expand import expand_iterators, has_iterators
from app.template_engine.schemas import TemplateDocumentModel, validate_doc
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD


# ---- doc builders ---------------------------------------------------------


def _doc(blocks, *, page_setup=None):
    doc = {
        "schemaVersion": 1,
        "sections": [
            {
                "id": "sec_1",
                "layout": "100",
                "background": None,
                "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
                "columns": [{"id": "col_1", "blocks": blocks}],
            }
        ],
    }
    if page_setup is not None:
        doc["pageSetup"] = page_setup
    return doc


def _table(footer=None):
    block = {
        "id": "tbl_1",
        "type": "table",
        "source": "lineItems",
        "columns": [
            {"key": "description", "header": "Item", "align": "left"},
            {"key": "qty", "header": "Qty", "align": "center"},
            {"key": "amount", "header": "Amount", "align": "right"},
        ],
    }
    if footer is not None:
        block["footer"] = footer
    return block


def _repeater(body):
    return {"id": "rep_1", "type": "repeater", "source": "lineItems", "body": body}


def _invoice_ctx():
    ensure_core_contexts()
    return get_context("document.invoice_preview")


def _preview_facts(ctx):
    facts = dict(ctx.sample_facts())
    for lf in ctx.list_facts:
        facts[lf.key] = [dict(r) for r in lf.sample]
    return facts


# ---- expansion units ------------------------------------------------------


def test_has_iterators_flag():
    plain = TemplateDocumentModel.model_validate(
        _doc([{"id": "h", "type": "heading", "text": "Hi", "level": 2, "align": "left"}])
    )
    withtbl = TemplateDocumentModel.model_validate(_doc([_table()]))
    assert has_iterators(plain) is False
    assert has_iterators(withtbl) is True


def test_table_expands_one_row_per_item():
    model = TemplateDocumentModel.model_validate(_doc([_table()]))
    facts = {"lineItems": [{"description": "A", "qty": "1", "amount": "$5"},
                           {"description": "B", "qty": "2", "amount": "$9"}]}
    exp, _aug = expand_iterators(model, facts)
    blocks = [b for _s, _c, b in exp.iter_blocks()]
    assert len(blocks) == 1 and blocks[0].type == "customHtml"
    html = blocks[0].html
    # header row + one body row per item (no footer) = 3 <tr>
    assert html.count("<tr>") == 3
    tbody = html[html.find("<tbody>"):html.find("</tbody>")]
    assert tbody.count("<tr>") == 2
    assert ">A<" in html and ">B<" in html


def test_table_cell_values_html_escaped():
    """Row values are escaped (the surrounding CustomHtml block compiles raw)."""
    model = TemplateDocumentModel.model_validate(_doc([_table()]))
    facts = {"lineItems": [{"description": "<b>x</b>", "qty": "1", "amount": "$5"}]}
    exp, _ = expand_iterators(model, facts)
    html = next(b for _s, _c, b in exp.iter_blocks()).html
    assert "<b>x</b>" not in html
    assert "&lt;b&gt;x&lt;/b&gt;" in html


def test_table_footer_merges_scalar_facts():
    footer = [{"cells": [
        {"text": "Total", "align": "right", "span": 2},
        {"text": "{{total}}", "align": "right", "span": 1},
    ]}]
    model = TemplateDocumentModel.model_validate(_doc([_table(footer=footer)]))
    facts = {"lineItems": [{"description": "A", "qty": "1", "amount": "$5"}], "total": "$5.00"}
    exp, _ = expand_iterators(model, facts)
    html = next(b for _s, _c, b in exp.iter_blocks()).html
    assert "<tfoot>" in html
    assert "$5.00" in html  # scalar footer fact merged
    assert 'colspan="2"' in html


def test_repeater_expands_body_per_item_with_row_substitution():
    body = [
        {"id": "h", "type": "heading", "text": "{{ row.description }}", "level": 3, "align": "left"},
        {"id": "t", "type": "text", "html": "Qty {{ row.qty }}", "align": "left"},
    ]
    model = TemplateDocumentModel.model_validate(_doc([_repeater(body)]))
    facts = {"lineItems": [{"description": "A", "qty": "2"}, {"description": "B", "qty": "5"}]}
    exp, aug = expand_iterators(model, facts)
    blocks = [b for _s, _c, b in exp.iter_blocks()]
    assert len(blocks) == 4  # 2 body blocks × 2 rows
    # row.* rewritten to per-item context keys, the facts carry the values.
    assert aug["__row0.description"] == "A"
    assert aug["__row1.qty"] == "5"


def test_sample_fallback_used_when_facts_lack_source():
    """Preview path: the list-fact SAMPLE drives the table when no live binding."""
    ctx = _invoice_ctx()
    model = TemplateDocumentModel.model_validate(_doc([_table()]))
    facts = _preview_facts(ctx)  # injects lineItems from the sample
    exp, _ = expand_iterators(model, facts, mode="preview")
    html = next(b for _s, _c, b in exp.iter_blocks()).html
    assert "Booth rental" in html  # from the context's sample rows


def test_no_iterators_doc_unchanged():
    blocks = [{"id": "h", "type": "heading", "text": "Hi", "level": 2, "align": "left"}]
    model = TemplateDocumentModel.model_validate(_doc(blocks))
    exp, facts = expand_iterators(model, {"x": "y"})
    assert exp is model and facts == {"x": "y"}


# ---- compiler_pdf HTML-intermediate goldens -------------------------------


def test_pdf_html_has_page_rule_default_a4():
    model = TemplateDocumentModel.model_validate(
        _doc([{"id": "h", "type": "heading", "text": "Hi", "level": 1, "align": "left"}])
    )
    html = compile_pdf_html(model, BrandValues(), {})
    assert "@page" in html
    assert "size: A4 portrait" in html
    assert "margin: 15mm 15mm 15mm 15mm" in html
    assert "table-header-group" in html  # thead repeats across pages
    assert f'src:url("{FONT_BASE_URL}/Inter.ttf")' in html  # bundled @font-face


def test_pdf_html_honours_page_setup():
    model = TemplateDocumentModel.model_validate(
        _doc(
            [{"id": "h", "type": "heading", "text": "Hi", "level": 1, "align": "left"}],
            page_setup={"size": "Letter", "orientation": "landscape",
                        "margins": {"top": 10, "bottom": 20, "left": 5, "right": 8}},
        )
    )
    html = compile_pdf_html(model, BrandValues(), {})
    assert "size: letter landscape" in html
    assert "margin: 10mm 8mm 20mm 5mm" in html


def test_pdf_html_renders_table_structure():
    model = TemplateDocumentModel.model_validate(_doc([_table()]))
    facts = {"lineItems": [{"description": "A", "qty": "1", "amount": "$5"},
                           {"description": "B", "qty": "2", "amount": "$9"},
                           {"description": "C", "qty": "3", "amount": "$1"}]}
    exp, aug = expand_iterators(model, facts)
    html = compile_pdf_html(exp, BrandValues(), aug)
    assert "<thead>" in html
    assert html.count("<tbody>") == 1
    # 3 source rows + the header row = 4 <tr>
    assert html.count("<tr>") == 4


def test_pdf_html_50_50_section_uses_flex():
    doc = {
        "schemaVersion": 1,
        "sections": [{
            "id": "s", "layout": "50/50", "background": None,
            "padding": {"top": 0, "bottom": 0, "left": 0, "right": 0},
            "columns": [
                {"id": "c1", "blocks": [{"id": "a", "type": "text", "html": "L", "align": "left"}]},
                {"id": "c2", "blocks": [{"id": "b", "type": "text", "html": "R", "align": "left"}]},
            ],
        }],
    }
    model = TemplateDocumentModel.model_validate(doc)
    html = compile_pdf_html(model, BrandValues(), {})
    assert "display:flex" in html
    assert html.count('class="tpl-col"') == 2


# ---- render_document smoke ------------------------------------------------


def test_render_document_returns_pdf_bytes(session_factory):
    from app.models.template import TEMPLATE_TYPE_DOCUMENT, Template
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.template_engine.renderer import render_document
    from app.template_engine.seed_templates import _invoice_doc

    db = session_factory()
    ctx = _invoice_ctx()
    template = Template(
        tenant_id=DEFAULT_TENANT_ID, type=TEMPLATE_TYPE_DOCUMENT, key="__t__",
        name="Inv", context="document.invoice_preview",
        subject="Invoice {{invoiceNumber}}", doc_json=_invoice_doc(),
    )
    pdf = render_document(db, template, DEFAULT_TENANT_ID, _preview_facts(ctx), mode="preview")
    db.close()
    assert isinstance(pdf, bytes) and len(pdf) > 1000
    assert pdf[:5] == b"%PDF-"


# ---- validate_doc document-branch matrix (D10) ----------------------------


def _validate(doc, *, subject="Invoice {{invoiceNumber}}"):
    ctx = _invoice_ctx()
    _model, problems = validate_doc(
        doc, subject,
        fact_sources=list(ctx.fact_sources),
        required_facts=list(ctx.required_facts),
        list_facts=ctx.list_facts,
        scalar_facts=[f.key for f in ctx.facts],
    )
    return problems


def test_validate_clean_invoice_doc():
    from app.template_engine.seed_templates import _invoice_doc

    assert _validate(_invoice_doc()) == []


def test_validate_unknown_list_source():
    bad = dict(_table()); bad["source"] = "nope"
    problems = _validate(_doc([bad, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("not a list field" in p for p in problems)


def test_validate_unknown_row_key_in_table_column():
    bad = dict(_table())
    bad["columns"] = [{"key": "ghost", "header": "X", "align": "left"}]
    problems = _validate(_doc([bad, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("not a row field" in p for p in problems)


def test_validate_empty_table_columns():
    bad = {"id": "t", "type": "table", "source": "lineItems", "columns": []}
    problems = _validate(_doc([bad, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("at least one column" in p for p in problems)


def test_validate_empty_repeater_body():
    bad = {"id": "r", "type": "repeater", "source": "lineItems", "body": []}
    problems = _validate(_doc([bad, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("at least one block to the body" in p for p in problems)


def test_validate_unknown_row_key_in_repeater_body():
    body = [{"id": "h", "type": "heading", "text": "{{ row.ghost }}", "level": 3, "align": "left"}]
    problems = _validate(_doc([_repeater(body), {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("is not a field of" in p for p in problems)


def test_validate_row_token_outside_iterator_scope_leak():
    leaked = {"id": "h", "type": "heading", "text": "{{ row.amount }}", "level": 2, "align": "left"}
    problems = _validate(_doc([leaked, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("only work inside a table or repeater" in p for p in problems)


def test_validate_footer_row_token_rejected():
    footer = [{"cells": [{"text": "{{ row.amount }}", "align": "right", "span": 1}]}]
    bad = _table(footer=footer)
    problems = _validate(_doc([bad, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]))
    assert any("footer binds totals" in p for p in problems)


def test_validate_invalid_page_setup():
    doc = _doc(
        [{"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}],
        page_setup={"size": "A3", "orientation": "portrait", "margins": {"top": 15, "bottom": 15, "left": 15, "right": 15}},
    )
    problems = _validate(doc)
    assert problems  # A3 is not in the Literal - Pydantic rejects


def test_email_path_skips_list_checks_but_catches_scope_leak():
    """Without list_facts (email path) source/row-key checks are skipped, but a
    stray row.* outside an iterator is still a scope leak."""
    leaked = {"id": "h", "type": "heading", "text": "{{ row.x }}", "level": 2, "align": "left"}
    _m, problems = validate_doc(
        _doc([leaked]), "", fact_sources=(), required_facts=(),
    )
    assert any("only work inside a table or repeater" in p for p in problems)


# ---- url_fetcher resolves a brand asset to bytes --------------------------


def test_url_fetcher_resolves_font_bytes(session_factory):
    from app.models.tenant import DEFAULT_TENANT_ID
    from app.template_engine.renderer import make_url_fetcher

    db = session_factory()
    fetch = make_url_fetcher(db, DEFAULT_TENANT_ID)
    result = fetch(f"{FONT_BASE_URL}/Inter.ttf")
    db.close()
    assert isinstance(result["string"], bytes) and len(result["string"]) > 1000
    assert result["mime_type"] == "font/ttf"


def test_url_fetcher_resolves_branding_asset_bytes(session_factory):
    from app.config import settings
    from app.models.tenant import DEFAULT_TENANT_ID, Tenant
    from app.models.tenant_branding import TenantBranding
    from app.services.storage import storage_for_tenant
    from app.template_engine.renderer import make_url_fetcher

    db = session_factory()
    tenant = db.get(Tenant, DEFAULT_TENANT_ID)
    storage = storage_for_tenant(db, DEFAULT_TENANT_ID)
    key = storage.save("logo", b"\x89PNG\r\n\x1a\nLOGOBYTES", "image/png")
    db.add(TenantBranding(tenant_id=DEFAULT_TENANT_ID, logo_key=key, logo_mime="image/png", version=1))
    db.commit()

    fetch = make_url_fetcher(db, DEFAULT_TENANT_ID)
    url = f"{settings.public_base_url}/public/branding/{tenant.slug}/asset/logo?v=1"
    result = fetch(url)
    db.close()
    assert result is not None
    assert b"LOGOBYTES" in result["string"]
    assert result["mime_type"] == "image/png"


# ---- preview endpoint -----------------------------------------------------


def _login(client):
    res = client.post("/auth/login", json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_preview_pdf_endpoint_returns_pdf(client):
    from app.template_engine.seed_templates import _invoice_doc

    headers = _login(client)
    res = client.post(
        "/templates/preview",
        headers=headers,
        json={"context": "document.invoice_preview", "subject": "Invoice {{invoiceNumber}}",
              "doc": _invoice_doc(), "format": "pdf"},
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "application/pdf"
    assert res.content[:5] == b"%PDF-"
    assert "inline" in res.headers.get("content-disposition", "")


def test_preview_pdf_download_attachment(client):
    from app.template_engine.seed_templates import _invoice_doc

    headers = _login(client)
    res = client.post(
        "/templates/preview?download=true",
        headers=headers,
        json={"context": "document.invoice_preview", "subject": "Invoice {{invoiceNumber}}",
              "doc": _invoice_doc(), "format": "pdf"},
    )
    assert res.status_code == 200
    assert "attachment" in res.headers.get("content-disposition", "")


def test_preview_html_format_unchanged(client):
    headers = _login(client)
    res = client.post(
        "/templates/preview",
        headers=headers,
        json={"context": "template.test", "subject": "Hi",
              "doc": _doc([{"id": "h", "type": "heading", "text": "Hi", "level": 2, "align": "left"}])},
    )
    assert res.status_code == 200
    body = res.json()
    assert "html" in body and "subject" in body


def test_preview_pdf_invalid_doc_422(client):
    headers = _login(client)
    # table bound to an unknown source → 422 from validate
    bad = {"id": "t", "type": "table", "source": "nope", "columns": [{"key": "x", "header": "X", "align": "left"}]}
    res = client.post(
        "/templates/preview",
        headers=headers,
        json={"context": "document.invoice_preview", "subject": "Invoice {{invoiceNumber}}",
              "doc": _doc([bad, {"id": "k", "type": "heading", "text": "{{invoiceNumber}}", "level": 2, "align": "left"}]),
              "format": "pdf"},
    )
    assert res.status_code == 422


# --- code-review fixes (SSRF guard + row-token literal safety) -------------

def test_row_token_rewrite_is_token_scoped():
    """Only ``{{ row.<k> }}`` rebinds - literal copy + unrelated tokens stay."""
    from app.template_engine.expand import _rewrite_row_tokens

    assert _rewrite_row_tokens("See you tomorrow. {{ row.amount }}", 0) == (
        "See you tomorrow. {{ __row0.amount }}"
    )
    # an unrelated token starting with 'arrow' must NOT be touched
    assert _rewrite_row_tokens("{{ arrow.size }} {{ row.qty }}", 3) == (
        "{{ arrow.size }} {{ __row3.qty }}"
    )
    # literal substrings 'row.' outside a token are untouched
    assert _rewrite_row_tokens("narrow road, borrow.it", 1) == "narrow road, borrow.it"


def test_url_fetcher_blocks_ssrf():
    """The render fetches tenant-authored <img src> server-side - internal hosts
    must be refused (SSRF), public https + data: allowed."""
    from app.template_engine.renderer import _is_blocked_fetch_url as blocked

    for url in (
        "http://169.254.169.254/latest/meta-data/",
        "http://localhost:8001/x",
        "http://127.0.0.1/",
        "http://10.0.0.5/a.png",
        "file:///etc/passwd",
    ):
        assert blocked(url), url
    for url in ("https://example.com/logo.png", "data:image/png;base64,iVBOR"):
        assert not blocked(url), url
