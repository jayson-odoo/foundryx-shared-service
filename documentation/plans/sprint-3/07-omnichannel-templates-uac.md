# Sprint 3 · Plan 07 — User Acceptance Criteria (Slice B1: WhatsApp Templates Manage / Submit / Sync)

> **Source plan:** [`07-omnichannel-templates.md`](./07-omnichannel-templates.md)
> **Scope:** The **Templates tab** on the omnichannel channel form — list, build, submit, edit, delete, sync WhatsApp message templates (categories **Marketing/Utility**; header TEXT or media IMAGE/VIDEO/DOC; body+vars; footer; standard buttons). **Out of scope:** Authentication templates (plan 08), Flow/Catalog/Carousel buttons (BL-110), named vars/multi-language sets (BL-111), `template.status_changed` workflow trigger (BL-109).
>
> **How to read:** Each criterion is `Given / When / Then`, acceptance-testable by a real user clicking through the live stack (no URL shortcuts). Groups: (1) business reqs, (2) guided process, (3) UX & design language, (4) security & isolation, (5) sign-off matrix.
>
> **Pass bar:** every **MUST** criterion passes at **both** 1280px and 375px viewports, in **dev-stub mode** AND against **one real connected number** for the Meta-touching paths (flagged `[real]`).

---

## 1. Business-requirement criteria

The business need: *a tenant builds, submits, tracks, edits, and deletes WhatsApp message templates inside FoundryX — with Meta as system-of-record and an explicit Sync — instead of using the Meta WhatsApp Manager.*

### BR-1 — Templates tab lists all templates across statuses
- **Given** a tenant Admin with `templates.read` on a connected channel
- **When** I open the channel form → Templates tab
- **Then** I see an embedded Resource list with columns: **Status** (badge) · Name · Category · Quality · Language · ⋮
- **And** server-side search, Status/Category/Language filters, sort, and pagination all work
- **And** every status (Local draft, Pending, Approved, Rejected, Paused, Disabled) is shown — not just approved

### BR-2 — Rejected templates show the reason
- **Given** a template in REJECTED status
- **When** I view its row
- **Then** the `rejected_reason` is shown inline (e.g. "Rejection reason: INVALID_FORMAT") so I know what to fix

### BR-3 — Build a template in the two-pane builder
- **Given** I click **Submit Template**
- **When** the builder route opens
- **Then** I get a full-page **two-pane** view: component editor (left) + **live WhatsApp-bubble preview** (right) that updates as I type
- **And** I can set name, category (Marketing/Utility), language, header (None/Text/Media), body with `{{n}}` variables + per-variable sample values, footer, and buttons (Quick-reply / URL static+dynamic / Phone / Copy-code)

### BR-4 — Save draft persists a LOCAL_DRAFT without touching Meta
- **Given** I have built a template
- **When** I click **Save draft**
- **Then** a `LOCAL_DRAFT` row is created/updated, **no Meta call is made**, and the list shows it as "Local draft"
- **And** reopening the draft restores every field I entered (round-trips through the canonical Meta-shape store)

### BR-5 — Submit sends to Meta and moves to PENDING
- **Given** a `LOCAL_DRAFT` template
- **When** I click **Submit**
- **Then** it validates, POSTs to Meta, stores `meta_template_id`, and transitions to **PENDING**
- **And** `[real]` the template appears in the Meta WhatsApp Manager review queue

### BR-6 — Media-header submit uploads the sample to Meta
- **Given** a draft with an IMAGE/VIDEO/DOCUMENT header and an uploaded sample file
- **When** I Submit
- **Then** the sample bytes are uploaded via the Meta resumable-upload helper, the returned handle is placed in the component example, and the submit succeeds
- **And** `[real]` the media header renders in the Meta-side preview

### BR-7 — Sync reconciles status/quality/category from Meta
- **Given** templates exist
- **When** I click **Sync**
- **Then** the system pulls the Meta template list, reconciles by `meta_template_id` (fallback name+language), updates status/quality/category, and stamps `last_synced_at`
- **And** quality renders as High/Medium/Low (mapped from GREEN/YELLOW/RED)
- **And** `[real]` a template approved on Meta shows **Approved** after Sync; dev-stub Sync promotes a PENDING draft to **Approved**

### BR-8 — Webhook updates a template row asynchronously `[real]`
- **Given** real-mode with the 3 template webhook fields subscribed
- **When** Meta sends a `message_template_status_update` / `_quality_update` / `_category_update`
- **Then** the matching local row updates status/quality/category/`rejected_reason` without a manual Sync
- **And** a repeated identical webhook is idempotent (no duplicate effect)

### BR-9 — Edit is status-gated
- **Given** templates in various statuses
- **When** I open the row actions
- **Then** edit behaves per status: **LOCAL_DRAFT** = fully editable; **APPROVED/REJECTED/PAUSED** = components-only edit that re-submits to **PENDING** on save; **PENDING/DISABLED** = edit hidden/blocked (409 if forced)

### BR-10 — Delete removes the template
- **Given** a template
- **When** I delete it after a single confirm (no typed-slug)
- **Then** a `LOCAL_DRAFT` is removed locally only; a **synced** template is DELETEd on Meta then its local row is hard-deleted (no soft-trash)
- **And** the row disappears from the list

### BR-11 — Variable/sample integrity is enforced
- **Given** the builder
- **When** body text has N distinct `{{n}}` variables
- **Then** I must provide exactly N samples (header TEXT allows ≤1 var/1 sample); a mismatch is rejected with a per-field 422 and inline highlight, both client and server

### BR-12 — View payload shows the raw Meta JSON
- **Given** any template
- **When** I open **View payload**
- **Then** I see the read-only, pretty-printed Meta component array (`toMetaComponents` output) — for transparency/debugging

---

## 2. Guided-process criteria

The process must **lead** the user — gated actions, live validation, no dead-ends. (Foolproof-UI: self-evident controls, **no instructional on-screen copy**; only offer valid options.)

### GP-1 — Builder validates before submit, field by field
- **Given** an incomplete/invalid template
- **When** I Submit
- **Then** I get **per-field** inline errors (bad name, dup name, missing body, sample mismatch, bad URL/phone, button-limit) and the submit is blocked — I am never sent to Meta with input Meta will reject for a format reason

### GP-2 — Status drives available actions (no invalid choices)
- **Given** any row
- **When** I open ⋮
- **Then** I see only the actions valid for that status (Submit only on LOCAL_DRAFT; Edit only when editable per BR-9) — disallowed actions are absent, not present-then-error

### GP-3 — Dirty-guard on the builder
- **Given** unsaved builder changes
- **When** I navigate away
- **Then** the shell's **Discard-changes AlertDialog** intercepts (Cancel keeps, Discard reverts) — never `window.confirm`, never silent loss

### GP-4 — In-flight feedback + double-submit guard
- **Given** I click Save draft / Submit / Sync / Delete
- **When** the request is in flight
- **Then** the control shows loading and is disabled against re-click; completion yields a clear success/error state — never a silent no-op

### GP-5 — Errors recoverable, input preserved
- **Given** a Meta call fails (network / Meta 4xx-5xx / rate limit) on Submit/Sync/Delete
- **When** it returns
- **Then** I see a human-readable error, my builder input survives, and I can retry; the module Error Boundary keeps the dashboard alive

### GP-6 — Media header guides the upload
- **Given** I choose a media header type
- **When** I add the sample file
- **Then** the file is sniff-gated (type checked by magic bytes, not extension) with a clear reject on an unsupported type, and the chosen file is visibly confirmed before submit

### GP-7 — Sync freshness is visible
- **Given** templates were last synced some time ago
- **When** I view the list
- **Then** the "last synced" recency is shown (session timezone) so I know whether Meta state may be ahead of the mirror — without teaching copy explaining Sync

### GP-8 — Truncated cells stay recoverable
- **Given** a long template name / body preview cell
- **When** it clamps
- **Then** full content is recoverable via `ClampedText` tooltip — no bare `truncate`

### GP-9 — Button builder only offers supported buttons
- **Given** the button repeater
- **When** I add a button
- **Then** I can only pick Quick-reply / URL / Phone / Copy-code (Flow/Catalog/Carousel are absent — they need resources we don't manage), and each type reveals only its valid conditional fields

---

## 3. UX & design-language criteria

Must tally with the FoundryX Resource-shell + builder design language.

### UX-1 — List built on the Resource shell
- **Then** the Templates tab is a config-driven embedded `ResourceList` (server sort/filter/search/paginate, action registry ⋮) — no hand-rolled table

### UX-2 — Builder mirrors the email/form two-pane builders
- **Then** the builder is a full-page two-pane route (editor ‖ live preview), consistent with the email-editor / form-builder pattern — not a modal, not a bespoke layout

### UX-3 — StatusBadge registry, not the status engine
- **Then** statuses render via a frontend StatusBadge registry (Approved=green, Rejected=red, Pending=amber, Paused/Disabled=grey, Local draft=neutral) — consistent badge styling with the rest of the system

### UX-4 — Every dropdown is searchable
- **Then** category / language / button-type selects are `SearchSelect`; no bare shadcn `<Select>` (BL-062)

### UX-5 — Responsive at both breakpoints (MUST)
- **Given** the Templates tab + builder at **375px** and **1280px**
- **Then** the list toolbar/columns reflow without horizontal page scroll, and the builder two-pane **stacks** (`flex-col lg:flex-row`, preview below editor) on mobile — no clipped controls, no overlap

### UX-6 — Live preview is faithful
- **Then** the right-pane WhatsApp-bubble preview reflects header/body/footer/buttons + sample values exactly as typed, updating live — giving WYSIWYG confidence before submit

### UX-7 — Brand, white-label, no raw CSS
- **Then** Metronic utility classes only (no `<style>`/raw CSS), FoundryX tokens, no tenant-facing "FoundryX" copy

### UX-8 — House datetime formatter
- **Then** "last synced"/created timestamps render via `useDatetime`/`lib/datetime.ts` in the session timezone — no `new Date(iso)` direct formatting

### UX-9 — No instructional/teaching copy
- **Then** no procedural how-to text on screen; only field labels, a one-line description at most, and short empty-state status

---

## 4. Security & isolation criteria

### SEC-1 — Tenant scoping (MUST)
- **Given** a template/channel belonging to another tenant
- **When** any template endpoint is called with that id
- **Then** it returns **404** — never cross-tenant data

### SEC-2 — Permission gates server-side
- **Then** `GET …/templates/manage` requires `templates.read`; save/edit/submit/delete/sync require `templates.manage`; the existing send-picker (`conversations.reply`) is unchanged — frontend gating is UX-only, backend is the boundary
- **And** `templates.read`/`templates.manage` are granted to tenant Admin in `install_tenant`

### SEC-3 — Module isolation
- **Then** all changes live inside `app_omnichannel` (5 new columns via idempotent `ADD COLUMN IF NOT EXISTS`, permissions via module CSV sync) — no core `public` table altered

### SEC-4 — Dev-safe with no Meta app (MUST)
- **Given** `credentials.dev` (no `META_APP_ID`)
- **When** I run draft → Submit → Sync → Edit → Delete end-to-end
- **Then** service-layer shortcuts make the full flow work offline (Submit→PENDING+fake id, media upload→fake handle, Sync promotes PENDING→APPROVED, edit→PENDING, delete→local) with no real Meta call

### SEC-5 — Canonical single store, parity-pinned transform
- **Then** `components_json` is the single Meta-shape store; `toMetaComponents`/`fromMetaComponents` round-trip without drift and the FE/BE transform parity is pinned by a test (no divergent shapes)

### SEC-6 — Webhook application is safe
- **Then** `apply_webhook_event` matches only the correct tenant/channel row, is idempotent on repeats, and a malformed webhook payload never crashes the inbound pipeline

---

## 5. UAT sign-off matrix

| # | Criterion | Priority | Dev-stub | Real `[real]` | 1280px | 375px | Pass |
|---|-----------|----------|:--------:|:-------------:|:------:|:-----:|:----:|
| BR-1 | List all statuses + filters/search | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-2 | Rejected reason shown | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-3 | Two-pane builder | MUST | ☐ | — | ☐ | ☐ | ☐ |
| BR-4 | Save draft (no Meta call) | MUST | ☐ | — | ☐ | ☐ | ☐ |
| BR-5 | Submit → PENDING + meta id | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-6 | Media-header upload on submit | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-7 | Sync reconciles status/quality | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-8 | Webhook async update | MUST | — | ☐ | — | — | ☐ |
| BR-9 | Edit status-gated | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-10 | Delete (draft local / synced Meta) | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-11 | Variable/sample integrity 422 | MUST | ☐ | — | ☐ | ☐ | ☐ |
| BR-12 | View payload raw JSON | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| GP-1 | Field-level validation before submit | MUST | ☐ | — | ☐ | ☐ | ☐ |
| GP-2 | Status-driven action set | MUST | ☐ | — | ☐ | ☐ | ☐ |
| GP-3 | Dirty-guard AlertDialog | MUST | ☐ | — | ☐ | ☐ | ☐ |
| GP-4 | In-flight feedback + double-submit guard | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| GP-5 | Errors recoverable, input preserved | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| GP-6 | Media sniff-gated upload | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| GP-7 | Sync freshness visible | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| GP-8 | ClampedText on overflow | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| GP-9 | Only supported buttons offered | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-1 | Resource-shell list | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-2 | Two-pane builder pattern | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-3 | StatusBadge registry | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-4 | SearchSelect dropdowns | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-5 | Responsive both breakpoints | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-6 | Faithful live preview | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-7 | Brand + white-label, no raw CSS | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-8 | House datetime formatter | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| UX-9 | No instructional copy | MUST | ☐ | — | ☐ | ☐ | ☐ |
| SEC-1 | Tenant scoping → 404 | MUST | ☐ | — | — | — | ☐ |
| SEC-2 | Permission gates server-side | MUST | ☐ | — | — | — | ☐ |
| SEC-3 | Module isolation | MUST | ☐ | — | — | — | ☐ |
| SEC-4 | Dev-safe, no Meta app | MUST | ☐ | — | — | — | ☐ |
| SEC-5 | Single store + parity-pinned transform | MUST | ☐ | — | — | — | ☐ |
| SEC-6 | Webhook safe + idempotent | MUST | — | ☐ | — | — | ☐ |

**Acceptance rule:** Slice B1 is accepted when **all MUST** criteria pass in dev-stub mode at both viewports, **and** the Meta-touching paths (BR-5/6/7/8/10, GP-5/6, SEC-6) are verified `[real]` against a connected number with the 3 template webhook fields subscribed. SHOULD failures log a backlog item, non-blocking.

---

## 6. Explicitly out of scope (do not test against this slice)

- **Authentication** templates (OTP/copy-code/one-tap, auto-generated body) → plan 08
- Flow / Catalog / Carousel buttons + product templates → BL-110
- Named variables (`{{order_id}}`) + multi-language template sets → BL-111
- `template.status_changed` workflow trigger (handler is emit-ready, trigger deferred) → BL-109
- Profile photo upload (reuses the upload helper built here) → BL-108
