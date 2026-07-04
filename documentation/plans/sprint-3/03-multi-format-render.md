# Sprint-3 / 03 — Multi-Format Render (F2): Template → PDF + Fixed-Canvas Designer

**Status:** BOTH SLICES MERGED to main (2026-06-12). Slice 1 (document/flowing-PDF) merged `f0b0562`; slice 2 (fixed-canvas badge/ticket/cert) merged `9b53238` — report `03-multi-format-render-slice2-test-report.md`. Slice-2 render REVISED from SVG to absolute-HTML+CSS→WeasyPrint (native text wrap, one render stack). BL-071 + BL-072 closed.
**Source:** `00-foundation-gaps-roadmap.md` §3 (F2); research `documentation/research/template-engine-builder-landscape.md` §4. Predecessor foundation: F1 form engine (`01-form-engine.md`, MERGED).
**Backlog roots closed/advanced:** BL-071 (badge/ticket canvas), BL-072 (repeater block).

---

## 0. Thesis

The template engine already proves the hard parts: a forever-contract **block document**, **merge** (anti-SSTI `{{ dotted.path }}` substitution-only), **rule-engine block visibility**, **brand seam** (live-follow), **two-tier** platform/tenant, **context registry** (fact vocabulary). F2 adds **render targets**, not a new engine — exactly the research conclusion: *separate editors, shared merge + brand seam*.

Two render surfaces ship as two slices. Both ride **one PDF backend (WeasyPrint)** and the **one** merge/brand/conditions/context seam:

- **Slice 1 — Document render (flowing PDF):** invoices/certificates. Extends the existing block-doc with a **PDF compile path** + **table** + **repeater** blocks. Thinnest end-to-end (reuses the editor + schema; forks only the emit step). Carries the slice alone via the invoice story.
- **Slice 2 — Fixed-canvas designer:** badges/tickets. New Konva editor + absolute-positioned canvas doc + server-side SVG→PDF render. Bigger/riskier surface; lands second.

**Domain-ahead stance (roadmap):** neither slice has a domain entity to bind yet (invoice = Cluster F, badge/attendee = Cluster H). Both ship the **designer + render infra exercised with sample contexts**; real binding = "register a context + bind the entity" later, reusing the identical editor/render. This is the COGS bet: build the reusable render spine now so clusters become wiring.

---

## 1. Slice 1 — Document render (flowing PDF)

### D1 — Two slices, document-PDF first
F2 = 2 slices (above). Slice 1 = document/flowing-PDF (reuses block-doc, minimal new editor surface); slice 2 = fixed-canvas. Certificate placement (flowing vs canvas) **parked** — likely canvas (cert = fixed single-page design), resolved at slice-2 grill; invoice carries slice 1 alone.

### D2 — Second compiler, WeasyPrint
Email compiler emits **MJML → mrml → email-table HTML** (email-client-safe, wrong for paper). Documents get a **second compiler** (`compiler_pdf.py`): block-doc → **semantic HTML + print CSS** (`@page { size; margin }`, `page-break-*`, flex) → **WeasyPrint** → PDF bytes.
- **WeasyPrint over Puppeteer:** BSD, no-Node (matches the mrml/native stance), no 300MB Chromium babysit, smallest PDFs, JS-execution irrelevant for static docs. Accepted CSS limits (no full-Chromium grid/JS) — fine for invoices.
- Shares schema / merge / conditions-prune / brand-resolve with email; forks only the **emit step**.
- Render seam mirrors `render_email`:
  ```
  render_document(db, template, tenant_id, facts, rule_objects) -> bytes (PDF)
    = brand-resolve → prune-by-conditions → expand-iterators → compile_pdf(HTML+CSS) → WeasyPrint
  ```

### D3 — Document = new `type` on the existing `Template` row
No new entity. `templates.type` already exists (default `email`); add **`document`**.
- **Same** two-tier (platform `tenant_id NULL` → fork-on-edit), **same** `context` registry, **same** `is_system` locks, **same** Resource list (segment by type), **same** `templates.read/manage` perms.
- **Same `doc_json` block schema** (`TemplateDocumentModel`). New blocks (`table`, `repeater`) added to the **shared** discriminated union (usable in invoice *email* too).
- **Page setup at `doc_json` root** (forever-contract, not a column): `{schemaVersion, pageSetup:{size:'A4'|'Letter', orientation, margins:{...}}, sections[]}`.
- **Reuse `EmailEditor`** via a `surface` prop (precedent: `structureLocked`). Document surface swaps palette (document blocks), settings (page-setup panel), preview pane (PDF viewer). **No parallel editor.** Compiler branches on `type`.
- Slice 1 has **no consumer entity** → ships editor + `render_document` + **preview/test-render returns PDF inline (download)**. No persistence, no binding.

### D4 — Table block (columnar, domain-owned totals)
Invoice lines = a **table** (header + aligned body-from-list + footer), not free layout.
```
TableBlock {
  kind:'table', source:'<listFactKey>',
  columns:[{key, header, align, width?}],
  footer?:[{cells:[{text, align?, span?}]}]   // cells bind SCALAR facts
}
```
Render: `<thead>` from columns → `<tbody>` one row per `source` item (`row.<key>`) → `<tfoot>` footer cells (merge scalar facts). WeasyPrint repeats `<thead>` across page breaks via `display:table-header-group`.
**Summation = domain, not engine.** The invoice entity computes `subtotal/tax/total` server-side (authoritative — tax/rounding/currency), exposes them as **scalar facts**; the footer cell binds `{{ total }}` aligned under the amount column. **Engine never aggregates money.** Engine-side `sum()` = deliberately rejected (spreadsheet creep + non-authoritative money); backlog if ever.

### D5 — Repeater block (free-layout iteration)
Ship alongside the table for non-columnar lists (agenda cards, etc.), mirroring the **form-engine repeater** for consistency.
```
RepeaterBlock { kind:'repeater', source:'<listFactKey>', body:Block[] }
```
- **Grammar:** body blocks reference `{{ row.<key> }}`; render expands per item against `{**parentFacts, "row.<k>":v}`. Source-agnostic.
- **Direction note:** form repeater = data *entry* (respondent adds rows → list answer); template repeater/table = data *display* (bind list fact → stamp output). A form-repeater answer **is** a valid list fact → invoice PDF straight from submission data. Keep `row` key naming aligned with form sub-field keys.
- **v1 limits:** single level (no repeater-in-repeater), **merge-only rows** (no per-row rule conditions — rows are plain dicts, not registered rule-source objects; bridging = backlog). Whole-repeater/table visibility via a condition on the block itself (doc-level facts) **stays**.

### D6 — List facts in the context registry
New registry shape so the picker knows row sub-fields + preview samples:
```python
ListFact(key='lineItems', label='Line items',
         item_facts=[ContextFact('description',...), ContextFact('amount',...)],
         sample=[{...},{...}])   # sample drives preview
```
Binding code (Cluster F) supplies `facts['lineItems']=[dict,...]`; preview uses `sample`. Picker inside a table/repeater lists `row.*` from the source's `item_facts`.

### D7 — Editor preview + PDF serving (on-demand, embedded viewer)
- `POST /templates/{id}/preview?format=pdf` → render draft with context **sample facts** → `application/pdf` inline.
- Document preview pane = **embedded PDF viewer** (`<iframe src=blob:…>`), **on-demand** ("Refresh preview"), NOT live-per-keystroke (compile ~300-600ms too heavy to keystroke). Email keeps instant HTML preview. Design/Preview toggle carries over.
- Embedded PDF (multi-page) over PNG-of-page-1.
- Test-render/download = same endpoint, `Content-Disposition: attachment`. No persistence (slice 1).

### D8 — Render runtime (non-blocking, no premature job queue)
- **Threadpool offload** for single preview/render (`run_in_threadpool` / `asyncio.to_thread`): WeasyPrint is CPU-bound sync — running it inline in an async handler blocks the event loop. Offload keeps the server non-blocking; request stays one round-trip + client spinner. **No job queue / polling** for a sub-second single doc (queue overhead > render; async-job-for-a-short-task is an anti-pattern).
- **Batch (200 docs) = Celery → slice 2** (no domain to batch over in slice 1). The `render_document` unit is the seam; slice-2 batch wraps it N times, zero rework.
- **Fonts:** bundle **Poppins + Inter TTFs** in `app/assets/fonts/` + `@font-face` to local files. Deterministic PDFs across hosts (system-fontconfig fallback would make dev≠prod).
- **Assets:** custom WeasyPrint **`url_fetcher`** intercepts our brand/asset/storage URLs → resolves to **bytes in-process** from `storage_for_tenant` (no HTTP round-trip, works offline, kills the email-logo `public_base_url`/localhost gotcha). External `https://` images fetch normally.
- **Native deps:** WeasyPrint needs Pango/cairo/gdk-pixbuf/libffi → `requirements.txt` + CLAUDE.md ops note + deploy image. Still no-Node, no Chromium.

### D9 — Sample context + starter template (exercise-ahead)
- Seed **one sample document context** (`document.invoice_preview`): scalar facts (`companyName`, `recipientName`, `invoiceNumber`, `subtotal`, `tax`, `total`) + list fact `lineItems` (+ samples). Preview/test-render exercising only.
- Seed **one starter platform-tier document template** (basic invoice: header + table + totals footer) → day-one content + E2E target. Mirrors `seed_templates.py`.
- Cluster F registers the **real** invoice context (real facts/resolvers) + binds the entity → reuses the identical editor/render. Sample context = the placeholder proving the seam. (One starter only — cert seed later, possibly on the slice-2 canvas surface.)

### D10 — Validation gate (extends `validate_doc`, branch on type)
Authoritative backend 422 (+ front mirror), `{problems:[...]}` shape (form-engine style). Document adds:
- Page setup invalid (unknown size/orientation, negative margins).
- Table/repeater `source` references a **list fact not declared in the context** (unknown-ref).
- `{{ row.<k> }}` in a table/repeater body not in the source's `item_facts` (unknown row key).
- Table footer cell / scalar token referencing an unknown context fact.
- Table with **zero columns** / repeater with **empty body** (empty-structure).
- **`row.*` used OUTSIDE a table/repeater body** (row-scope leak).
Existing email checks (block shapes, conditions via rule engine, `required_facts`, HTML sanitize) unchanged.

### D11 — Permissions
Reuse `templates.read/manage` (same entity). No new keys.

### Slice-1 tests (TDD)
- **Backend:** `compiler_pdf` HTML+CSS **intermediate goldens** (deterministic) — **never byte-golden PDFs** (timestamps/font hinting non-deterministic); + render smoke (valid PDF, expected page count, non-empty). Table/repeater **expansion** units. `validate_doc` document-branch matrix (D10). `render_document` end-to-end (sample context). `url_fetcher` resolves brand bytes. Two-tier/fork unchanged.
- **Frontend:** document palette + table/repeater editors, page-setup panel, validate mirror parity, PDF preview pane.
- **Parity:** add `test_template_parity` (none exists today) covering `types/templates.ts` ↔ `schemas.py` for the new blocks + pageSetup + list-fact.
- **E2E:** design invoice (header + table bound to `lineItems`, footer `{{total}}`) → Refresh preview → PDF viewer → download.

---

## 2. Slice 2 — Fixed-canvas designer (badge / ticket / certificate)

Grilled 2026-06-12. Build-detail ready; sub-branch `sprint-3/03b-canvas-designer` after slice 1 (F3 holds plan numbers 04+05).

### D12 — Entity = reuse `Template`, polymorphic `doc_json`, one new editor
Canvas = **`type='badge'`** (covers badge/ticket/cert — size-parametric) on the existing `Template` row. `doc_json` is **polymorphic by type**: block-doc when email/document, **canvas-doc** when badge. `validate_doc` branches on type. Shares two-tier fork / context registry / `templates.read/manage` / Resource list (segment adds Badge). The **one genuine fork** = a new **CanvasEditor** (Konva) — research stance (separate editors, shared seam). Rejected: a separate `canvas_templates` entity (re-duplicates two-tier/context/fork/list machinery).

**Cert decision (was parked): cert = A4 canvas in slice 2.** A certificate = a fixed single-page design (name on a decorative background), not flowing. The canvas surface is **size-parametric** — badge 54×86mm, ticket small, cert A4. Slice 1 = invoices only; slice 2 canvas covers badge + ticket + cert.

### D13 — Render = absolute HTML+CSS → WeasyPrint (REVISED from SVG)
`canvas doc → absolute-positioned HTML+CSS per side → WeasyPrint → PDF`. **Revised away from a separate SVG emitter** — SVG `<text>` has no auto-wrap (manual tspan/measurement pain). HTML abs-pos gives native CSS text wrapping + the **same bundled `@font-face`** + the **same `url_fetcher`** + the **same WeasyPrint backend** as slice 1 (one render stack, not two). Each side → `<div style="position:relative;width:Wmm;height:Hmm">` + children `position:absolute; left/top/width/height; transform:rotate(...)`. Shapes via CSS / tiny inline-SVG. mm positioning is exact in WeasyPrint; PDF output vector-crisp.
- **Client Konva NEVER renders the artifact** (un-headless/un-reproducible/security). Konva = interactive editor only; **server HTML = authoritative**; Preview tab shows server PDF (like slice 1). Editor↔renderer parity is a burden either way → pick the renderer most robust for text = HTML+CSS.
- **QR = server-side** (`segno` → SVG/PNG), dropped as an image element; data from `{{fact}}`.
- **Double-sided** = front → page 1, back → page 2.
- Same **threadpool(single) / Celery(batch)** split as slice 1.

### D14 — Canvas doc schema (forever-contract)
```
CanvasDoc {
  schemaVersion,
  canvas: { width, height, unit:'mm', orientation, bleed? },   // ONE size per template
  sides: [ { name:'front', elements:[...] }, { name:'back', elements:[...] }? ],
  contextKey
}
Element (base) { id, type, x, y, w, h, rotation, z(=array order), conditionsJson? }
  text  { content(merge tokens), fontFamily, fontSize, weight, align, color, lineHeight }
  image { src(static asset OR {{fact}}), fit:'contain'|'cover' }
  shape { kind:'rect'|'ellipse'|'line', fill, stroke, strokeWidth, radius? }
  qr    { data({{fact}}), ecLevel }
```
- **Units: mm canonical underneath** (print-authoritative → `@page`). **Display/input unit configurable** (`mm | in | px`, per-template default from tenant pref): editor ruler/inputs show+accept the chosen unit, convert to mm on store (`in×25.4`; px = px@96dpi → `px/96×25.4`). px is screen-referenced (unit-picker notes it). Render always mm. Rationale: a tenant gets their preferred unit; the physical artifact stays unambiguous (raw px would be DPI-ambiguous on paper).
- **Double-sided** = `sides[]` (front + optional back). Single-sided (ticket/cert) = one side. N sides → N pages.
- **One size per template** (multiple sizes = multiple templates — Webex/Cvent stance).
- **4 element types** (text/image/shape/qr). "Dynamic-field" **collapsed into text-with-tokens + image-with-fact-src** — a bound field IS an element whose content/src carries `{{fact}}` (same merge seam everywhere; no separate type).
- **Binding = merge tokens** in `content`/`src`/`data` (existing merge-field picker, chips; mixed static+dynamic). **Per-element `conditionsJson`** = rule-engine visibility ("speaker ribbon if role=speaker" — premium feature, schema carries it from v1).
- **z = array order**; **`bleed`** carried for print trim (3mm) even if UI defers.

### D15 — CanvasEditor UX (Konva; desktop AND mobile — both mandatory)
Palette · canvas · inspector (side panels on desktop; **bottom-sheet drawers on mobile**, canvas full-width).
- **Palette** = 4 element types, flat (tiny catalog, no search). **Click-to-add** (Playwright-drivable) + drag; drops at canvas center unwired (no auto-placement guessing — plan-09 lesson).
- **Canvas (Konva):** select / move / resize / rotate handles, **smart alignment guides** + **arrow-key nudge**, zoom/pan + fit-to-view, **bleed + safe-area guide overlay**, **side switcher** (front/back), **unit ruler**.
- **Inspector:** position/size/rotation (**numeric inputs** — precision on coarse-finger mobile), z-order (forward/back), type-specific props, **binding** (merge-field picker), **visibility** (`RuleBuilder` → `conditionsJson`).
- **Mobile editing is mandatory** (CLAUDE.md both-sizes mandate — NOT read-only): touch gestures (tap-select, drag-move, **pinch-zoom**, two-finger pan; Konva touch), **larger touch hit-targets** for handles, **no hover-dependence** (handles visible on selection), numeric inputs + on-screen nudge for precision. Verify at **375px AND 1280px**.
- **Reuse:** `useHistory` (undo/redo + ⌘Z), `RuleBuilder`, merge-field picker, `SearchSelect`. Keyboard **Delete** with the focus-guard (skip when focus on any interactive control — plan-09).

### D16 — Batch render: seam now, binding with Cluster H
- **Single render** (preview/test): one artifact, **sample-context** facts → PDF inline (threadpool, like slice 1). Fully exercisable now.
- **Batch seam:** `render_canvas_batch(template, [facts,...]) -> PDF` over **Celery** (existing infra), wrapping single render N times. **Output = one multi-page PDF** (one artifact/page; zip-of-PDFs = backlog, a Cluster-H email-attach concern). Exercised with **synthetic sample-fact dicts** now; the real **trigger** ("print all badges for Event X" → attendee query) lands with **Cluster H** (no attendee entity exists yet).

### D17 — Domain-ahead seed
Seed `badge.preview` sample context (`attendeeName`, `role`, `company`, `ticketCode`→QR) + one starter platform badge template (54×86mm: name + role + QR) → E2E-exercisable. Real attendee context/binding = Cluster H.

### D18 — Validation gate (`validate_doc`, `type='badge'` branch)
Positive canvas dims + known unit; ≥1 side, each side named; element `id` unique within a side; merge tokens reference known context facts (unknown-ref 422); QR element non-empty `data`; image `src` scheme-valid; conditions via rule engine. **No hard out-of-bounds fail** (bleed = intentional overflow; allow).

### D19 — Permissions: reuse `templates.read/manage`. No new keys.

### Slice-2 tests
- **Backend:** canvas schema; `compile_canvas` **HTML-intermediate golden** (never byte-golden PDF); QR-gen; render smoke (N sides = N pages, valid PDF); `validate_doc` badge-branch matrix; batch seam over synthetic facts.
- **Frontend:** CanvasEditor (add/select/move/resize/rotate, side switch, binding picker, conditions), unit conversion, validate mirror.
- **Parity:** extend `test_template_parity` for the canvas doc (`types/templates.ts` ↔ `schemas.py`).
- **E2E:** design badge (text bound `{{attendeeName}}` + QR `{{ticketCode}}`) → preview PDF → download; verified at 375px + 1280px.

---

## 3. Build order (per house methodology)

Both slices grilled. Each: frontend-first (mock service) → backend (Service-Repository, swap mock→real) → TDD both layers → Playwright E2E (mock then live) → Markdown test report → code-review → merge.

1. **Slice 1** on `sprint-3/03-multi-format-render`:
   - FE: `EmailEditor` `surface='document'` (palette + page-setup + PDF preview), table/repeater block editors, validate mirror.
   - BE: `compiler_pdf.py`, `render_document`, `table`/`repeater` schema + expansion, `validate_doc` document-branch, list-fact registry, sample context + starter seed, bundled fonts + `url_fetcher`, preview/download endpoints, threadpool offload.
   - Tests + E2E + report → review → merge.
2. **Slice 2** on `sprint-3/03b-canvas-designer` (after slice 1 merges; F3 doc-mgmt already holds plan numbers 04+05 — F2 is one plan doc, slice 2 is a sub-branch not a new number):
   - FE: new **CanvasEditor** (Konva) — palette/canvas/inspector, mobile bottom-sheets + touch, unit picker, binding picker, `RuleBuilder` conditions, `useHistory`.
   - BE: canvas schema (`type='badge'`), `compile_canvas` (HTML+CSS per side) + `render_canvas`, QR-gen (`segno`), `validate_doc` badge-branch, `badge.preview` context + starter seed, `render_canvas_batch` Celery seam.
   - Tests + E2E (375px + 1280px) + report → review → merge.

## 4. Deferrals (backlog)
- Per-row rule conditions inside repeater/table (merge-only v1).
- Engine-side aggregation (`sum()` over a column) — money stays domain-authoritative.
- Real domain binding (invoice → Cluster F; badge/attendee → Cluster H).
- Generic nested repeaters; multiple size-variants in one canvas doc.
- Zip-of-individual-PDFs batch output; real batch trigger / Zebra direct-print (Cluster H).
- Cert starter seed (canvas surface, post-slice-2).

## 5. Open decisions
None blocking. Slice-2 fine-detail (alignment-guide thresholds, exact mobile bottom-sheet layout) resolves in build.
