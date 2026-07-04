# F2 Slice 1 — Document/Flowing-PDF Render — Test Execution Report

**Plan:** `03-multi-format-render.md` §1 (slice 1). **Branch:** `sprint-3/03-multi-format-render` (worktree, off main).
**Stack added:** WeasyPrint 69 + segno (native deps Pango/cairo/gdk-pixbuf/libffi), bundled Poppins/Inter TTFs.

## Summary

| Layer | Suite | Result |
|-------|-------|--------|
| Backend | `pytest -q` (full) | **448 passed** (+28 new), 0 regressions |
| Backend | `test_document_render.py` | 28 (expansion, compiler goldens, render smoke, validate matrix, url_fetcher, preview endpoint) |
| Backend | `test_template_parity.py` | 4 (block discriminants + table/repeater/pageSetup/listFacts mirror) |
| Frontend | `npm test` (vitest) | **432 passed** (+24), whole suite green |
| Frontend | `npm run lint` | 0 errors (no `any`, no raw CSS) |
| Integration | starter `document.invoice` → `render_document` | 12.7 KB valid `%PDF-` (seed → table expansion → bundled fonts → WeasyPrint) |

## Scenarios

| # | Scenario | Precondition | Steps | Expected | Actual |
|---|----------|--------------|-------|----------|--------|
| 1 | Block-doc → PDF | document template | `render_document(sample facts)` | bytes start `%PDF-`, non-empty | PASS (12.7 KB) |
| 2 | Table expansion | doc with `table` bound to `lineItems` | expand → compile | thead + N tbody rows + tfoot total; row values HTML-escaped | PASS |
| 3 | Repeater expansion | doc with `repeater` over a list | expand | body stamped per item, `row.*` substituted | PASS |
| 4 | Domain-owned total | table footer cell `{{ total }}` | render with scalar fact | footer shows the domain total (engine never sums) | PASS |
| 5 | Validation — bad source | table `source` not a listFact | publish/preview | 422 named problem | PASS |
| 6 | Validation — unknown row key | `{{ row.x }}` not in itemFacts | preview | 422 | PASS |
| 7 | Validation — scope leak | `{{ row.x }}` outside an iterator | preview | 422 | PASS |
| 8 | url_fetcher | brand asset URL in doc | render | resolved to bytes in-process (no localhost round-trip) | PASS |
| 9 | Preview endpoint | `POST /templates/preview format=pdf` | request | `application/pdf` inline; `?download=true` → attachment; threadpool offload | PASS |
| 10 | Page setup | A4/Letter, orientation, mm margins | compile | `@page{size;margin}` honored | PASS |
| 11 | Editor — document surface | `EmailEditor surface='document'` | mount | document palette (table/repeater), page-setup panel, PDF preview pane | PASS (vitest) |
| 12 | Editor — table bind | add table, pick source, add column | mutate doc | doc reflects columns + source | PASS |
| 13 | Editor — repeater row picker | repeater body merge picker | open picker | offers `row.<key>` from source itemFacts | PASS |
| 14 | PDF preview on-demand | document editor | click Refresh preview | service called, blob iframe rendered (not per-keystroke) | PASS |
| 15 | Parity | types ↔ schemas | parity test | block discriminants + new structures match | PASS |

## Pending (next step)

- **Live Playwright E2E** (real clicks: design invoice → Refresh preview → PDF viewer → download) against the live stack — to run with the server up; verified at 375px + 1280px per the responsive mandate. Unit + integration coverage above exercises the full pipeline; E2E is the real-click confirmation.

## Notes / deviations

- Table cells merged + HTML-escaped **at expansion** (the carrier block compiles raw) — anti-XSS contract preserved while table tags survive.
- Real Poppins + Inter TTFs bundled (1.3 MB, tracked) → deterministic PDFs across hosts; `@font-face` resolved via the in-process `url_fetcher`.
- WeasyPrint dict `url_fetcher` emits a deprecation warning on 69.0 (works correctly) — trivial future cleanup to `URLFetcherResponse`.

## Live E2E (slice 1)

Spec: `service_frontend/e2e/document-templates.spec.ts` (chromium, real user clicks
against the live stack — backend :8001, served prod build :3001). Run:
`npx playwright test e2e/document-templates.spec.ts --reporter=line` → **3 passed**.

Preconditions: stack already up + seeded; a platform-tier **document** template
"Invoice" (`document.invoice`, context `document.invoice_preview`) present. Login
`demo@example.com` / `demo1234` on the bare host = the `default` tenant. No tenant
state mutated (view-only), so the spec is parallel-safe and needs no provisioning.

Navigation is fully click-driven and viewport-aware: desktop opens the header
"Settings" mega-menu then the "Templates" link; mobile (375px) opens the hamburger
sheet, expands the "Settings" accordion, then "Templates". The Invoice list row is
opened by clicking its name cell.

Implementation note discovered during verification: the document preview iframe is
rendered via **`srcDoc` inside a `sandbox=""` frame** (our own renderer — the same
fully-sandboxed pattern as the email preview pane), not a `blob:` `src` as an earlier
draft used. The spec asserts on the populated `srcdoc` HTML sheet + its rendered
content accordingly.

### Journey 1 — Design → Preview renders the in-app HTML sheet
- **User Story:** As a tenant admin, I open a document template and preview the
  compiled paper sheet in-app (no browser PDF-viewer chrome).
- **Scenario:** Sign in → Settings → Templates → open "Invoice" → Design tab →
  Preview toggle.
- **Steps:** real clicks through the nav + tabs; flip the editor mode to Preview.
- **Expected:** `pdf-preview-pane` visible; the sandboxed `pdf-preview-frame` receives
  a populated `srcdoc` and its rendered body shows real document content; Refresh
  preview + Download PDF controls present.
- **Actual:** PASS. `srcdoc` = 4100 chars; the rendered frame body shows the seeded
  invoice ("Invoice INV-1042 … Bill to Jordan Lee … Item/Qty …"). Backend
  `POST /templates/preview?format=docHtml` → 200 `text/html`.

### Journey 2 — Download PDF
- **User Story:** As a tenant admin, I download the authoritative PDF of the document.
- **Scenario:** In Preview, click "Download PDF".
- **Steps:** open the preview (as J1) → click Download PDF → await a browser download.
- **Expected:** a download starts; suggested filename ends `.pdf`.
- **Actual:** PASS. `page.waitForEvent('download')` fires; filename matches `/\.pdf$/`.
  (Direct API probe confirmed `format=pdf` returns real `%PDF-` bytes, ~13 KB.)

### Journey 3 — Responsive (mobile + desktop)
- **User Story:** The preview surface is usable at both phone and desktop widths.
- **Scenario:** Re-run the Preview render at 375×800 and 1280×800.
- **Steps:** for each viewport — navigate (viewport-appropriate nav) → open Invoice →
  Preview; measure horizontal overflow + pane width.
- **Expected:** pane visible; no horizontal page overflow (scrollWidth ≤ clientWidth);
  the pane fits within the viewport width at both sizes.
- **Actual:** PASS at both 375px (mobile hamburger nav) and 1280px (desktop mega-menu);
  zero horizontal overflow; pane within viewport.

**Result: all 3 journeys PASS; journey 3 verified at both viewports. 3 passed (~4–6s).**
