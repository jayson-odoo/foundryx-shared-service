# Test Execution Report — Sprint 3 / Plan 01 Slice 2 (Form Engine: Public Surface + `form.submitted` Workflow)

**Branch:** `sprint-3/02-form-engine-public-workflow`
**Plan:** `documentation/plans/sprint-3/01-form-engine.md` (Slice 2)
**Scope:** anonymous public fill surface + the `form.submitted` workflow trigger + the file/signature quarantined-upload pipeline.

## Summary

| Layer | Result |
|---|---|
| Backend pytest (full) | **592 passed** (slice-1 baseline 570 → +22 slice-2) |
| Frontend Vitest (full) | **485 passed** (slice-1 baseline 472 → +13 slice-2) |
| E2E (live stack, real clicks) | ⑤ anonymous fill ✅ · ⑥ `form.submitted` → merged email ✅ |
| Live API negatives | honeypot-drop ✅ · 422 ✅ · uniform-404 ✅ |

New backend test files: `tests/test_form_public.py` (9), `tests/test_form_submitted_trigger.py` (4), `tests/test_form_uploads.py` (5). New frontend tests: `lib/form-submit-body.test.ts` (4), `services/public-form-service.test.ts` (6), `lib/workflow-catalog.form-trigger.test.ts` (3).

---

## User Story 1 — Anonymous public fill

**As** an event visitor with a public form link, **I want** to fill and submit the form without an account, **so that** I can register.

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|---|
| 1.1 | Open the public link logged-out | Published `public` form on a tenant subdomain | Navigate to `{slug}.localhost:3001/public/forms/{formSlug}` with no session | Branded page renders the form (no sign-in redirect) | ✅ Branded shell + form fields + Submit + off-screen honeypot in DOM | Live (Playwright MCP) |
| 1.2 | Submit anonymously | 1.1 | Fill name + email → click Submit | "Your response was submitted." | ✅ Success state shown | Live |
| 1.3 | Honeypot tripped | public form | POST with `honeypot` non-empty | 204 (pretend success), NO row stored | ✅ 204; submission count 1→1 unchanged | Live API |
| 1.4 | Server re-validates | public form | POST missing the required email | 422 `{fieldErrors}` | ✅ 422, `email` keyed | Live API + `test_public_submit_validation_422` |
| 1.5 | No enumeration | — | GET/POST an unknown form, internal form, or unpublished form | Uniform 404 | ✅ 404 in all three | `test_public_view_*` + live |
| 1.6 | Window closed / full | `closesAt` past / cap reached | GET the public view | `state=closed`/`full`, definition withheld; POST → 409 | ✅ | `test_public_submit_closed_window` |
| 1.7 | Per-IP throttle | low cap | Exceed the public bucket | 429 + `Retry-After`; login bucket untouched (own scope) | ✅ | `test_public_submit_throttle_429` |

## User Story 2 — `form.submitted` workflow trigger

**As** a tenant admin, **I want** a workflow to run when a form is submitted, **so that** I can send a confirmation using the answers.

| # | Scenario | Precondition | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|---|
| 2.1 | Trigger fires | Active workflow `form.submitted`(formA) → `email.send` custom | Submit form A (anonymously) | One run, status `success`; mail enqueued | ✅ 1 run `success`; to=ada@example.com | Live + `test_form_submitted_fires_workflow_with_answer_merge` |
| 2.2 | `trigger.answers.*` merge | 2.1, subject `Welcome {{ trigger.answers.name }}` | — | Subject merged with the answer | ✅ "Welcome Ada Lovelace" | Live (Email log) |
| 2.3 | Per-form selectivity | workflow bound to form A | Submit form B | A's workflow does NOT fire | ✅ 0 runs | `test_form_submitted_is_per_form_selective` |
| 2.4 | Editor picker + dynamic outputs | published forms exist | GET `/workflows/metadata` | `forms[]` with answer-field keys | ✅ | `test_metadata_lists_published_forms_with_fields` |
| 2.5 | Failure isolation | — | submit fires the after-commit drain | a broken/slow workflow never 500s the submit | ✅ drain is try/except-isolated (event-bus contract) | by-design + suite |

## User Story 3 — File / signature quarantined uploads

| # | Scenario | Steps | Expected | Actual | Remarks |
|---|---|---|---|---|---|
| 3.1 | Multipart file stored | submit a PNG to a `file` field | answer carries a real storage key (not `local:`/`pending`); served CSP-sandboxed | ✅ | `test_internal_file_upload_stores_and_serves` |
| 3.2 | Sniff-gate (magic bytes) | upload a `.png` containing HTML | 422, nothing stored | ✅ | `test_file_upload_bad_magic_is_rejected` |
| 3.3 | Per-field mime allow-list | upload a PNG to a PDF-only field | 422 | ✅ | `test_file_upload_disallowed_mime_rejected` |
| 3.4 | Signature stored | submit a data-URL PNG to a `signature` field | decoded + stored; answer is a storage key | ✅ | `test_signature_data_url_stored` |
| 3.5 | Public multipart submit | anonymous multipart with a file | 204, anonymous row | ✅ | `test_public_multipart_submit_anonymous` |

---

## Notes & deviations

- **Public route addressing.** Backend `GET/POST /public/forms/{tenant_slug}/{form_slug}` carries the tenant slug in the path (the `/public/branding` precedent — the browser hits the API origin directly, so a subdomain can't survive on the Host header). The frontend derives the slug from the subdomain and the public page lives at the literal `/public/forms/[slug]` route (a route group is invisible in the URL, so the page MUST sit under a real `public/` segment or it collides with `(protected)/forms/[id]` — caught at build, fixed).
- **Uploads sniff-gate images + PDF only** for v1 (SVG excluded — script-bearing; served sandboxed regardless). Office-doc magic bytes = a later widening.
- **Live-verify wrong-build/stale-server gotcha (re-confirmed).** A stale `next start` (no `/public/forms` route) and a pre-change `uvicorn` (no public route in `/openapi.json`) were both holding the ports; restarting each with the current branch's build/code was required before E2E. Always confirm `/openapi.json` carries the new route and the served build has the new page.
- **Authed file download in the submission detail view** is a follow-up: the serve route exists + is tested, but rendering it needs an authed fetch→blob (an `<img src>`/link can't carry the Bearer). The read view shows file names + a "Signature captured" chip meanwhile.

## Follow-ups logged

- BL-090 (anonymous browser-local autosave) — still open.
- BL-092 (authed file/signature download in the submission detail view).
- BL-093 (widen upload sniff-gate to office docs).

---

## Builder enhancements (post-slice-2, user-iterated — same branch)

Layered after slice-2 core, all green (backend **617**, frontend **498**):

| Area | What | Tests |
|---|---|---|
| Computed aggregates | `sum/avg/min/max(rep.col)` + `count(rep)` over repeater/table columns; live + server recompute; publish-gate earlier-numeric rule | `test_form_aggregates` (13), `computed-expr.aggregate` (12) |
| Table block | `table` field type — authored columns, per-row `computed`, `fixed` constant (server-stamped), column totals `<tfoot>`, row numbers, mobile h-scroll | `test_form_table` (10), renderer table test |
| Number precision | `integer` palette type + decimal places — input blocks `.`/pads on blur/errors on >N dp; client+server; **live on type** | `test_form_table` decimals/integer |
| Formula builder | reusable popup shell (operators + variable list + live validation) on computed field/column | (UI) |
| Drag-reorder | dnd-kit grips on table columns + repeater sub-fields | (UI) |
| File view (BL-092) | submission file/signature chips → authed blob fetch → open (CSP-sandboxed route) | (manual) |
| Record-nav | submission detail `‹ N / M ›` prev/next | (manual) |
| Fixes | click-away deselect, label column headers, branding-asset 404-not-500 | — |

E2E: the new builder features carry unit + integration coverage; no Playwright E2E added (the existing `forms.spec.ts`/`forms-public-workflow.spec.ts` still pass). Code-review pending before merge.
