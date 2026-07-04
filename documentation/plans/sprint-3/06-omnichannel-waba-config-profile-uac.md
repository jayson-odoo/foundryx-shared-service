# Sprint 3 · Plan 06 — User Acceptance Criteria (Slice A: Configuration + Profile)

> **Source plan:** [`06-omnichannel-waba-config-profile.md`](./06-omnichannel-waba-config-profile.md)
> **Scope:** Configuration tab + Profile tab on the omnichannel channel form. Templates (plan 07), Auth templates (plan 08), Balance/Calls (backlog) are **out of scope** — any criterion touching them is deferred.
>
> **How to read:** Each criterion is `Given / When / Then`, acceptance-testable by a real user clicking through the live stack (no URL shortcuts). Grouped into:
> 1. **Business-requirement criteria** — does the system do the job the tenant needs?
> 2. **Guided-process criteria** — is the user led, never stranded?
> 3. **UX & design-language criteria** — does it look/feel like the rest of FoundryX?
> 4. **Security & isolation criteria** — RBAC, tenant scope, dev-safety.
> 5. **Sign-off matrix** — the pass/fail checklist for UAT.
>
> **Pass bar:** every **MUST** criterion passes at **both** 1280px and 375px viewports, in **dev-stub mode** AND against **one real connected number** (real-mode rows flagged `[real]`).

---

## 1. Business-requirement criteria

The business need: *a tenant manages their WABA identity + WhatsApp Business Profile from inside FoundryX, without logging into the Meta dashboard, with Meta as the system-of-record.*

### BR-1 — Channel form surfaces three tabs
- **Given** I am a tenant Admin with `channels.read` on a connected WhatsApp channel
- **When** I open the channel form
- **Then** I see exactly three tabs: **Configuration**, **Templates**, **Profile**, in that order
- **And** Configuration is the default-selected tab on open
- **And** the form is **read-only by default** (no input is editable until I engage Edit)

### BR-2 — Configuration shows our data + Meta-owned identity
- **Given** the Configuration tab is open
- **When** the tab renders
- **Then** I see **editable** fields: internal name, workspace, active toggle
- **And** I see **read-only synced** fields: phone number, phone number ID, WABA ID, **business account name**, **verified name**, last-verified timestamp
- **And** each synced field carries a "Last synced …" caption rendered in **my** timezone (not UTC, not server tz)

### BR-3 — Sync pulls live WABA + phone identity from Meta
- **Given** I have `channels.manage` and the Configuration tab open
- **When** I click **Sync**
- **Then** the system calls Meta for phone details + WABA name, writes `display_phone_number`, `verified_name`, `business_account_name` locally, and stamps `last_verified_at`
- **And** the synced fields update on screen without a full page reload
- **And** `[real]` against a real number the displayed verified name + business account name match the Meta WhatsApp Manager values

### BR-4 — Profile tab mirrors the WhatsApp Business Profile
- **Given** the Profile tab is open
- **When** the tab renders
- **Then** I see the mirrored profile: about, address, description, email, vertical, website 1, website 2, and a read-only current profile photo
- **And** values render from the **local mirror** (no Meta call on tab open — instant render)
- **And** if never synced, fields show empty / neutral placeholders (never "FoundryX", never a raw null)

### BR-5 — Sync Profile pulls latest profile from Meta
- **Given** I have `channels.manage` on the Profile tab
- **When** I click **Sync Profile**
- **Then** the system GETs the Meta business profile, overwrites local profile fields, stamps `profile_synced_at`, and the on-screen values + "last synced" caption update

### BR-6 — Save writes profile changes through to Meta (write-through)
- **Given** I am in Edit mode on the Profile tab and have changed About + Vertical
- **When** I click **Save**
- **Then** **only the changed fields** are POSTed to Meta
- **And** on Meta success the local mirror is refreshed from the response and the form returns to read-only
- **And** `[real]` reloading the Meta WhatsApp Manager shows the same About + Vertical

### BR-7 — Vertical is constrained to the Meta enum
- **Given** I am editing the Profile and open the Vertical control
- **When** I pick a value
- **Then** I can only choose from the 22 Meta verticals (`UNDEFINED … OTC_DRUGS`)
- **And** the control is a searchable `SearchSelect` (typing filters the list), never a free-text field

### BR-8 — Server rejects invalid profile input with field-level errors
- **Given** I am editing the Profile
- **When** I submit an invalid email, a 3rd website, or (via tampering) a vertical outside the enum
- **Then** the save is rejected with a **422** and a **per-field** message; the field is highlighted inline; nothing is written locally or to Meta
- **And** the website cap of **2** is enforced (no UI affordance to add a third)

### BR-9 — Identity fields are never editable
- **Given** I am in **Edit** mode on either tab
- **When** I look at phone number, phone number ID, WABA ID, business account name, verified name
- **Then** they remain read-only (Meta-owned identity is never tenant-editable, even in edit mode)

### BR-10 — Persistence survives reload
- **Given** I have Saved a profile change or run a Sync
- **When** I reload the channel form
- **Then** the persisted values are still shown (sourced from the local mirror)

---

## 2. Guided-process criteria

The process must **lead** the user — no dead-ends, no silent failures, no guessing. (Foolproof-UI mandate: the UI is self-evident from controls/labels alone; **no instructional on-screen copy**.)

### GP-1 — Read-by-default, explicit Edit toggle
- **Given** any tab
- **When** it opens
- **Then** it is read-only and the single global **Edit** toggle is the only path to mutation — the user is never accidentally editing

### GP-2 — Dirty-guard on unsaved changes
- **Given** I have edited a profile field but not Saved
- **When** I switch tabs, navigate the record-nav, or leave the form
- **Then** the shell's **Discard-changes AlertDialog** intercepts (Cancel keeps me; Discard reverts) — `window.confirm` is **not** used

### GP-3 — Action affordances are obvious and gated
- **Given** I hold only `channels.read` (not `.manage`)
- **When** I view either tab
- **Then** Sync / Sync Profile / Save / Test Connection are **absent or disabled** (not present-then-403); I am never shown an action I can't complete

### GP-4 — In-flight feedback on every async action
- **Given** I click Sync / Sync Profile / Save / Test Connection
- **When** the request is in flight
- **Then** the control shows a loading state and is disabled against double-submit
- **And** on completion I get a clear success or error toast/inline state — never a silent no-op

### GP-5 — Errors are recoverable, not terminal
- **Given** a Meta call fails (network, Meta 4xx/5xx, rate limit)
- **When** the action returns
- **Then** I see a human-readable error, the form keeps my entered values (no data loss), and I can retry — the page never crashes (module Error Boundary holds)

### GP-6 — Staleness is visible
- **Given** identity/profile data was last synced some time ago
- **When** I view the tab
- **Then** the "Last synced {relative/absolute time}" caption tells me how fresh the mirror is, so I know whether to re-Sync — without any teaching copy explaining what Sync does

### GP-7 — Test Connection is a no-input check
- **Given** the Configuration tab
- **When** I click **Test Connection**
- **Then** it runs a connection health check with no required input and reports pass/fail (per the system's Test-button convention)

### GP-8 — Truncated values stay recoverable
- **Given** a long synced value (e.g. a long verified name or website URL)
- **When** it is clamped in the layout
- **Then** the full value is recoverable via `ClampedText` tooltip on real overflow — never a bare `truncate` that hides content

---

## 3. UX & design-language criteria

Must tally with the FoundryX Resource-shell design language and brand.

### UX-1 — Built on the Resource shell, not hand-rolled
- **Then** the channel form is the config-driven `ResourceForm` (icon tabs, global Edit toggle, record-nav, `FormRow` with `*` on required) — no bespoke table/form markup

### UX-2 — Every dropdown is searchable
- **Then** the Vertical picker (and any other select) is a `SearchSelect`; no bare shadcn `<Select>` (BL-062 mandate)

### UX-3 — Responsive at both breakpoints (MUST)
- **Given** the channel form at **375px** and at **1280px**
- **Then** the 3-tab strip scrolls horizontally (never clips), the profile form **stacks single-column** on mobile and uses available width on desktop, and no control overlaps or causes horizontal page scroll

### UX-4 — Brand + white-label compliance
- **Then** the surface uses Metronic utility classes only (no `<style>`, no raw CSS), FoundryX tokens, and no tenant-facing copy says "FoundryX"; empty profile states use neutral placeholders

### UX-5 — Datetime rendering follows the house formatter
- **Then** every timestamp ("last synced", "last verified") renders through `useDatetime`/`lib/datetime.ts` in the session timezone with no `new Date(iso)` direct formatting

### UX-6 — Read vs edit affordance is unmistakable
- **Then** read mode shows values as text; Edit mode reveals inputs with clear focus/affordance, and the active/dirty state of the form is visually evident (consistent with other Resource forms)

### UX-7 — No instructional/teaching copy on screen
- **Then** there is no procedural how-to text ("Click Sync to pull from Meta…"); only field labels, a one-line tab/entity description at most, and short empty-state status

---

## 4. Security & isolation criteria

### SEC-1 — Tenant scoping (MUST)
- **Given** a channel belonging to another tenant
- **When** any Config/Profile endpoint is called with that channel id
- **Then** it returns **404** (never cross-tenant data, never 403-that-leaks-existence)

### SEC-2 — Permission gates enforced server-side
- **Then** `GET /channels/{id}/profile` requires `channels.read`; `sync-config`, `PATCH profile`, `profile/sync` require `channels.manage` — frontend gating is UX-only, backend is the boundary

### SEC-3 — Module isolation
- **Then** all changes live inside `app_omnichannel` (no core `public` table altered); new columns added via idempotent `ADD COLUMN IF NOT EXISTS`, no core pollution

### SEC-4 — Dev-safe with no Meta app (MUST)
- **Given** `META_APP_ID`/`META_APP_SECRET` unset (`credentials.dev`)
- **When** I run Sync / Sync Profile / Save
- **Then** the adapter dev-stubs return canned data, local writes succeed, and the full flow demos end-to-end with **no** real Meta call

### SEC-5 — Write-through atomicity
- **Then** local profile fields are refreshed **only after** Meta confirms the POST; a Meta failure leaves the local mirror unchanged (no half-written state)

---

## 5. UAT sign-off matrix

| # | Criterion | Priority | Dev-stub | Real `[real]` | 1280px | 375px | Pass |
|---|-----------|----------|:--------:|:-------------:|:------:|:-----:|:----:|
| BR-1 | Three tabs, read-by-default | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-2 | Config editable + synced fields | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-3 | Sync pulls WABA/phone identity | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-4 | Profile mirrors business profile | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-5 | Sync Profile pulls from Meta | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-6 | Save write-through (changed only) | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-7 | Vertical constrained to enum | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-8 | 422 field-level validation | MUST | ☐ | — | ☐ | ☐ | ☐ |
| BR-9 | Identity fields never editable | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| BR-10 | Persistence survives reload | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| GP-1 | Read-default + Edit toggle | MUST | ☐ | — | ☐ | ☐ | ☐ |
| GP-2 | Dirty-guard AlertDialog | MUST | ☐ | — | ☐ | ☐ | ☐ |
| GP-3 | Actions gated, not present-then-403 | MUST | ☐ | — | ☐ | ☐ | ☐ |
| GP-4 | In-flight feedback + double-submit guard | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| GP-5 | Errors recoverable, no data loss | MUST | ☐ | ☐ | ☐ | ☐ | ☐ |
| GP-6 | Staleness caption visible | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| GP-7 | Test Connection no-input check | SHOULD | ☐ | ☐ | ☐ | ☐ | ☐ |
| GP-8 | ClampedText on overflow | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| UX-1 | Resource shell (no hand-roll) | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-2 | SearchSelect dropdowns | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-3 | Responsive both breakpoints | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-4 | Brand + white-label | MUST | ☐ | — | ☐ | ☐ | ☐ |
| UX-5 | House datetime formatter | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| UX-6 | Read/edit affordance clear | SHOULD | ☐ | — | ☐ | ☐ | ☐ |
| UX-7 | No instructional copy | MUST | ☐ | — | ☐ | ☐ | ☐ |
| SEC-1 | Tenant scoping → 404 | MUST | ☐ | — | — | — | ☐ |
| SEC-2 | Permission gates server-side | MUST | ☐ | — | — | — | ☐ |
| SEC-3 | Module isolation, no core pollution | MUST | ☐ | — | — | — | ☐ |
| SEC-4 | Dev-safe, no Meta app | MUST | ☐ | — | — | — | ☐ |
| SEC-5 | Write-through atomicity | MUST | ☐ | ☐ | — | — | ☐ |

**Acceptance rule:** Slice A is accepted when **all MUST** criteria pass in dev-stub mode at both viewports, **and** BR-3/BR-6/SEC-5 are verified once `[real]` against a connected number. SHOULD items are tracked but non-blocking; any SHOULD failure logs a backlog item.

---

## 6. Explicitly out of scope (do not test against this slice)

- Templates tab behavior → plan 07 (tab is present as a label only in Slice A)
- Authentication templates → plan 08
- WABA Balance / Billing & Usage → BL-106
- WhatsApp Calls settings → BL-107
- Profile **photo upload** (display-only this slice) → BL-108
