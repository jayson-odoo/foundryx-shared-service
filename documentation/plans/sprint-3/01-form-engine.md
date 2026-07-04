# Sprint 3 · Plan 01 — Form Builder Engine (the 5th core engine)

**Branch:** `sprint-3/01-form-engine` (slice 1) → `sprint-3/02-form-engine-public-workflow` (slice 2)
**Advances:** F1 (roadmap `sprint-3/00-foundation-gaps-roadmap.md`) — BRD R17 (abstract submissions), R14 (registration dynamic fields), R18/19 (review forms), R6 (onboarding checklists). **Two vertical slices**: 01 = builder + publish + internal fill + submissions + scoped statuses; 02 = public anonymous surface + `form.submitted` workflow trigger.
**Spawns:** BL-086 (payment field — rides F6), BL-087 (entity-sourced choice options), BL-088 (`entity.create` workflow action — lands with first F4 domain entities), BL-089 (repeater sub-field conditions), BL-090 (anonymous browser-local autosave).
**Depends on:** rule engine `evaluate`/`validate_tree`/fact registry (sprint-2/02), status engine + `status_machine.transition` (sprint-2/01) — **extended here with scoped machines**, StorageService `storage_for_tenant` (sprint-2/06), `app/uploads.py detect_mime`, throttle store (sprint-1/10), workflow engine registry (sprint-2/08–10, slice 2), EmailEditor composition pattern + `useHistory` (sprint-2/07/10), Resource shell, SearchSelect/MultiSelect, RuleBuilder.

---

## Context

An EMS lives on tenant-designed forms: event registration, paper submission, review scoring, onboarding checklists, contact forms. The BRD said "4 engines" but R17/R14/R18 all need a drag-drop form builder + runtime renderer + server-side validator — a **5th engine**, same shape as the others: forever-contract JSON document, code-side registry, validation gate, frontend mirror, rule-engine seams.

The endgame use case (user-stated): the future website builder (F5) embeds a form on a tenant's event site; a visitor/registrant fills it; submission side-effects (create participant, send confirmation) run through the **workflow engine** — Typeform + Zapier decomposition. The form engine itself stays **dumb capture**: build schema, render, validate, store answers. Everything that *reacts* to a submission is a workflow.

**Net demo at end of slice 1:** build a multi-page form in the drag-drop builder (all field types, conditional visibility via RuleBuilder), publish it, fill it as an authenticated user, watch the submission land in the form's Submissions tab, design a custom per-form status pipeline on the Flow tab (e.g. Submitted → Under Review → Accepted), transition submissions through it with graph-driven buttons.
**Net demo at end of slice 2:** open the form's public link logged-out on the tenant subdomain, fill + submit anonymously (throttled, honeypotted, file uploads sniff-gated), and watch a workflow with a `form.submitted` trigger fire — confirmation email to the respondent via `email.send` with `trigger.answers.*` merge fields.

### Engine is PLATFORM CORE, not an App Store module
Settled in the grill (user initially leaned module). All four existing engines are core; this one is consumed by clusters D (registration), E (submissions/review), H (checkpoint) — a module dependency would put modules-depending-on-modules in the critical path. It composes other core engines (rule, status, workflow) and lives where they live: `app/form_engine/` + core `public` tables + core permissions CSV. Modules *extend* it later (field-type registry seam, D17). Not a billable add-on — baseline platform capability.

---

## Locked design decisions (from grilling)

1. **D1 — Core engine.** `app/form_engine/` (mirrors `template_engine/`), tables in `public`, perms in core `permissions.csv`, present for every tenant always. Frontend mirror `types/forms.ts` ↔ `app/form_engine/schemas.py` (forever-contract parity, template-engine precedent).

2. **D2 — Form engine = dumb capture; binding = workflow engine.** The engine knows nothing about users/participants/events. One generic **`form_submissions`** store: `tenant_id`, `form_id`, `version_id` (pinned), `answers_json` (JSONB), `status_id` (status engine, D4), `user_id` (nullable — NULL = anonymous), optional **inbound polymorphic owner** `subject_type`/`subject_id` ("this form is *about* record X" — review form about a paper, registration scoped to an event; set by the embedding context at render). Polymorphic rule applies (the sprint-2/01 cross-tenant-leak lesson): subject validated against the author's tenant at save AND tenant-scoped at resolve. Outbound side-effects (create participant, notify staff, update records) are **workflows** triggered by `form.submitted` (D13) — zero built-in bindings.

3. **D3 — "Create a user" = participant/attendee domain record, never auth User.** A future `entity.create` workflow action is whitelisted to **non-auth domain entities** (participant, lead — F4). It must never mint `User`/`Role`/`Tenant` rows — auto-creating auth users from a public form would route around the parked self-signup kill-switch (BL-032, `signup_enabled`). The action itself is **deferred to BL-088**: today's triggerable-entity set (user/role/tenant/connection/template/workflow) contains nothing safe to create, and shipping an action with an empty/forbidden picker violates the foolproof-UI mandate. It lands with the first F4 domain entities.

4. **D4 — Submission lifecycle = STATUS ENGINE, via a new scoped-machine extension.** User requirement: each form configures its own submission states dynamically. Today the engine is one graph per `entity_type` per tenant — too coarse. Extension (generalizes beyond forms — Cluster B per-project-type task statuses will reuse it):
   - **`statuses.scope_id`** (nullable String, indexed). Transitions need no column — they FK status ids; scope rides along. Unscoped entities (tenant, …) keep `scope_id NULL` and behave exactly as today.
   - `StatusEntity` registry gains **`scoped: bool`** + scope metadata (scope label "Form", list/validate scopes). Core registers `form_submission` as the first scoped entity.
   - **No 3-tier fork gymnastics**: for scoped entities, statuses are **materialized at scope creation** — creating a form copies the minimal seed set into `(tenant_id, scope_id=form_id)` rows, tenant-owned from birth, directly editable. No platform→tenant→form resolution chain.
   - **Seed set = minimal**: `Draft` (`is_initial`, `is_active`) and `Submitted` (`is_active=false`), one edge Draft→Submitted. Tenants add review states per form themselves.
   - **Flag semantics, never labels**: `is_active` = *respondent may still edit answers* (Draft yes, Submitted no; a tenant-added "Revision Requested" with Active ticked reopens editing). `is_initial`/`is_terminal` as-is. No new flags.
   - `transition()` / `available_transitions()` / `fireable_edge_ids()` validate the target status belongs to the record's scope (a submission can never move onto another form's graph — same guard class as polymorphic target_id).
   - Everything rides along free: edge conditions (rule engine), edge roles, transition notifications, `entity.status_changed` workflow trigger.
   - Deleting a form deletes its scoped statuses/edges (+ submissions).

5. **D5 — Form *definition* lifecycle = workflow-style, NOT the status engine.** `status: draft|published|archived` enum + publish/version mechanism (D9). No tenant wants custom *definition* states; the configurable-graph value targets submissions.

6. **D6 — Document = Page → Section → Field** (`{schemaVersion, pages[]}`; Page = wizard step with per-page client validation; Section = titled group, optional 2-column, `conditionsJson`; Field = leaf with `conditionsJson`). Builder is a **vertical list editor on the EmailEditor composition skeleton** (Palette · Canvas · SettingsPanel, dnd-kit, `useHistory` undo/redo) — NOT FlowCanvas (form, not graph). Field config: **stable `key`** (answer key — relabel never breaks refs, workflow-node-id precedent), `label`, `required`, `placeholder`, `helpText`, type-specific validation (regex+message, min/max length/value, options), `conditionsJson`.

7. **D7 — Field taxonomy v1 = FULL (user: "don't defer the fields"):**
   | Category | Types |
   |---|---|
   | Text | `text`, `textarea`, `email`, `phone`, `url` |
   | Number | `number` (min/max/step) |
   | Choice | `select`, `multiselect`, `radio`, `checkboxes`, `yesno` |
   | Date | `date`, `datetime` |
   | Upload | `file` (max size / allowed mimes / max count), `signature` (canvas draw → PNG, same storage path) |
   | Scoring | `rating` (1–N configurable max; numeric — feeds Cluster E score-average) |
   | Composite | `address` (line1/line2/city/state/postcode/country; nested object answer; country = SearchSelect), `repeater` (author-defined sub-fields, respondent adds rows, min/max rows; answers = array of objects; **no conditions on sub-fields v1** — BL-089) |
   | Computed | `computed` — **arithmetic-only own parser** (`+ − × ÷`, parentheses, sibling field refs), NEVER eval/JS/Jinja (anti-SSTI house line); read-only, recomputed live client-side AND authoritatively server-side |
   | Display | `heading`, `paragraph`, `divider` (no answer) |
   **`payment` omitted** — F6 doesn't exist; a field that cannot work violates foolproof-UI. Additive doc schema = zero-break later (BL-086).

8. **D8 — Choice options static-only v1**, shaped `{kind:'static', items:[...]}` so `{kind:'entity', …}` (e.g. "pick your session" fed by agenda) slots in without doc break (BL-087).

9. **D9 — Versioning = workflow-engine pattern.** Mutable `draft_definition_json`; **Publish** = `validate_form_doc` gate (422: duplicate field keys, broken/forward condition refs, computed refs to missing/non-numeric fields, empty pages) → snapshot to immutable `form_versions` + set `current_version_id`. Fill surfaces serve ONLY the published version; **Preview renders the draft** (author-only). Unpublish = offline. **Submissions pin `version_id`** — faithful re-render forever (reviewer sees the form as it was). Version history = own paginated endpoint (never embedded in form GET). **Mid-fill schema change: validate against CURRENT published version**; mismatch → 422 → client re-renders new version preserving still-matching keys.

10. **D10 — Window + caps on the form row (not version):** `opens_at`/`closes_at` (closed → public GET renders friendly closed state; POST 409), `max_submissions` (atomic count-guarded insert, outbox-cancel pattern), **`submission_limit_per_user`** (nullable int — "each registrant may submit twice" = 2; enforced by authenticated identity; **greyed out for anonymous-public forms** — unenforceable, foolproof-UI).

11. **D11 — Access model: `internal` | `public` v1, `portal` reserved** (Cluster D). Public surface = the `/public/branding` pattern: `GET /public/forms/{slug}` + `POST /public/forms/{slug}/submissions`, tenant from subdomain, **uniform 404** (no enumeration). The public fill page **is the future embed contract** — the website builder (F5) renders the same surface. **Anonymous = no server-side drafts** (no identity to attach; multi-page stays client-side until final submit; browser-local autosave = BL-090).

12. **D12 — Public-tier security (the expensive part):**
    - **Throttle** public submissions per-IP (existing `ThrottleStore` pattern, own bucket) + **honeypot field** injected at render. Real captcha rides BL-041.
    - **Uploads**: sniff-first mime gate (`detect_mime`), per-file + per-submission size caps, capped reads (never buffer unbounded), keys quarantined `forms/{form_id}/{submission_id}/{field_key}/…` via `storage_for_tenant`, served back ONLY through an authed CSP-sandboxed route (`Content-Security-Policy: sandbox` + nosniff — branding-asset hardening), never public-listable.
    - Options-membership, type, regex all re-validated server-side (D14) — never trust client.

13. **D13 — `form.submitted` workflow trigger (slice 2).** Config = the form, picked via **searchable SearchSelect** (user mandate). Run-context flat keys: `trigger.formId`, `trigger.submissionId`, `trigger.answers.<fieldKey>` (address → dotted `answers.addr.city`; repeater → JSON string v1; file → storage key). **Output schema is dynamic per selected form** (published version's fields) so the `{ }` dynamic-content picker lists real keys — registry `outputs` extended to support callable-per-config (metadata endpoint already tenant-resolves statuses; same move). Confirmation mail, staff notify, record creation: all authored as workflows.

14. **D14 — Validation contract (server = the boundary, client = UX mirror):**
    1. Server re-evaluates every field/section `conditionsJson` against submitted answers (rule-engine `evaluate`, fail-closed) → derives the **visible set** → validates only that.
    2. **Hidden field with an answer → silently dropped** (never stored, never 422 — respondent may have legitimately flipped an earlier answer; and curl can't force-feed hidden fields).
    3. **`required` applies only when visible.**
    4. Per-type constraints; choice membership against the version's options; `computed` recomputed server-side (client value ignored); repeater row min/max + per-row validation; address sub-key whitelist; file sniff/caps.
    5. **422 = per-field error map** `{fieldKey: message}` → inline highlight + jump-to-page.
    6. Condition fact namespace = `answers.<fieldKey>`; conditions may reference **earlier fields only** (document order — bans cycles AND forward refs; publish-gate enforced front + back). `subject.*` facts wire later when a consumer needs them.

15. **D15 — Submission flow rides `status_machine`.** Partial save (internal/portal only) = row in scope-seeded Draft. Submit = the Draft→Submitted edge through `transition()` (every status change in the system goes through the one executor). Respondent edit allowed only while current status has `is_active`.

16. **D16 — No two-tier for form definitions.** Forms are tenant-born, `tenant_id NOT NULL` (workflow precedent). The platform tenant builds/uses forms like any tenant (rows scoped to it) — that's all "platform also enjoys it" requires. No system forms, no fork machinery, no starter gallery v1.

17. **D17 — Field-type registry is code-side** (`register_field_type`, mirrors the other registries) but **v1 ships core types only — extension API not yet a public contract** (seam exists, documented as internal). Consumers (Clusters D/E) integrate via: render-by-id component + `subject` param + the `form.submitted` trigger. No deeper coupling.

18. **D18 — UI = house patterns end-to-end.**
    - Sidebar **"Forms"** (`forms.read`-tagged in ALL THREE menu arrays). `/forms` Resource list: name, definition status, access, submission count, window, updated; bulk publish/unpublish/archive (workflow-list parity).
    - Detail = tabbed ResourceForm: **Builder** (palette·canvas·settings, Edit-toggle-gated, mobile-stacking per responsive mandate; toolbar Preview + Publish/Unpublish) · **Submissions** (embedded scoped Resource list: respondent or "Anonymous", StatusBadge, submitted_at, **author-pinned answer columns** — form setting "show as column"; CSV export, answers flattened, repeater = JSON cell v1; row → read-only render of the pinned version + graph-driven transition buttons + raw answers) · **Flow** (scoped status canvas — existing `entity-flow` components, scope-filtered) · **Settings** (access, window, caps, per-user limit, paged-vs-single display) · **Versions** (paginated).
    - Every dropdown = SearchSelect/MultiSelect; ClampedText for long answers; foolproof-UI rules (no inline how-to copy).
19. **D19 — Permissions (core CSV):** `forms.read`, `forms.manage`, `submissions.read`, `submissions.manage`. Seeded to tenant Admin. Public endpoints perm-free; **internal fill = any authenticated tenant user** (filling ≠ administering). Frontend `<RequirePermission>` + menu tags.

---

## Data model (new tables — Alembic, core)

```text
forms                 id, tenant_id (NOT NULL, idx), name, slug (per-tenant unique), description,
                      status ENUM(draft|published|archived), access ENUM(internal|public),
                      draft_definition_json JSON(none_as_null=True), current_version_id FK,
                      opens_at/closes_at UTCDateTime, max_submissions INT NULL,
                      submission_limit_per_user INT NULL, pinned_columns_json,
                      created_at/updated_at UTCDateTime

form_versions         id, form_id FK, version_number INT, definition_json, published_by, created_at
                      (immutable; UNIQUE(form_id, version_number))

form_submissions      id, tenant_id (idx), form_id FK (idx), version_id FK,
                      status_id FK→statuses, user_id NULL, subject_type/subject_id NULL,
                      answers_json JSONB, submitted_at NULL, created_at/updated_at

statuses              + scope_id (nullable String, idx)  ← engine extension (D4)
```

JSON columns: `JSON(none_as_null=True)` (house rule). Datetimes: `UTCDateTime` only. Schemas camelCase via `ApiModel`.

## API surface

```text
# authed (tenant)
GET/POST   /forms                      forms.read / forms.manage
GET/PATCH/DELETE /forms/{id}           forms.manage for writes
POST       /forms/{id}/{publish|unpublish}     forms.manage (validate gate)
GET        /forms/{id}/versions        paginated
POST       /forms/{id}/preview         renders DRAFT (author)
GET        /forms/{id}/fill            published version for internal fill (any authed)
POST       /forms/{id}/submissions     internal submit / draft save
GET        /forms/{id}/submissions     submissions.read (+ export)
GET/PATCH  /submissions/{id}           submissions.read / manage; POST /submissions/{id}/transition
GET        /submissions/{id}/files/{fieldKey}/{n}   CSP-sandboxed, submissions.read

# public (pre-auth, subdomain tenant, uniform 404, throttled)
GET        /public/forms/{slug}
POST       /public/forms/{slug}/submissions      (+ multipart upload path)
```

## Backend shape (`app/form_engine/` + service/repo/router)

- `app/form_engine/schemas.py` — Pydantic doc models (Page/Section/Field discriminated union) + `validate_form_doc` (publish gate) + answer-validation models. Datetime schemas inherit `ApiModel`.
- `app/form_engine/registry.py` — `FieldTypeDef` registry (`register_field_type`; core types only v1, seam internal per D17).
- `app/form_engine/computed.py` — arithmetic-only expression parser/evaluator (own tokenizer; `+ − × ÷`, parens, field refs; no eval).
- `app/form_engine/validation.py` — server submit pipeline (D14): visible-set derivation via rule-engine `evaluate` → drop hidden → required-if-visible → per-type constraints → computed recompute → per-field error map.
- `app/models/form.py` — `Form`, `FormVersion`, `FormSubmission` (UTCDateTime, `JSON(none_as_null=True)`).
- `app/repositories/form_repository.py` / `form_submission_repository.py` — every query tenant-scoped; atomic cap-guarded insert.
- `app/services/form_service.py` — CRUD, publish/unpublish (validate gate, version snapshot), preview, fill resolution, submit (window/cap/limit checks → validation → status seed → `transition()` Draft→Submitted), CSV export, file serving keys.
- **Status-engine extension** (in `app/status_engine/` + `app/models/status.py`): `statuses.scope_id` column, `StatusEntity.scoped` + scope metadata, scope checks in `transition`/`available_transitions`/`fireable_edge_ids`, scope-filtered graph endpoints, seed-on-form-create helper.
- Routers `app/api/v1/forms.py` (+ public router) — HTTP only, perms per D19.
- Migrations: one for `statuses.scope_id`, one for the form tables (remember `import app.models.utc_datetime` in autogen — workflow lesson).

## Frontend shape

- `types/forms.ts` — doc mirror (schemaVersion, pages/sections/fields, field-type unions) + parity-pinned with backend.
- `components/platform/form-builder/` — EmailEditor-skeleton composition: `form-builder.tsx` (container, `useHistory` undo/redo), `palette.tsx` (collapsed sections + search), `canvas.tsx` (vertical page/section/field list, dnd-kit), `settings-panel.tsx` (per-field config; SearchSelect everywhere; RuleBuilder for `conditionsJson`; options editor; validation editor).
- `components/platform/form-renderer/` — runtime fill renderer (ONE component: internal fill page, author Preview, public fill page slice 2, read-only submission view). Per-page client validation mirror, live computed, conditional show/hide, file/signature inputs, mobile-first.
- `app/(protected)/forms/` — Resource list + tabbed detail (Builder · Submissions · Flow · Settings · Versions per D18); scoped status canvas reuses `entity-flow`.
- `services/form-service.ts` (+ `.mock.ts` Phase A) + `hooks/use-forms`, `use-form-builder`, `use-form-fill`, `use-form-submissions`.
- Menu: "Forms" tagged `forms.read` in ALL THREE menu arrays.

---

## Phases (frontend-first per methodology) — Slice 1

- **Phase 0 — spikes (short):**
  (a) **Scoped-status spike first** — riskiest piece, touches the live engine: `statuses.scope_id` migration + scope-aware resolution + `transition()` guard behind a synthetic scoped test entity; full existing status-engine pytest suite must stay green (tenant lifecycle untouched).
  (b) Computed-parser spike — tokenizer/evaluator + property tests (precedence, parens, div-by-zero, missing ref).
  (c) Renderer feasibility pass — repeater + address + signature (canvas-draw) inputs render/collect on desktop + 375px.
- **Phase A — frontend (mock service):** `types/forms.ts`; form-builder (palette/canvas/settings, all D7 field types, RuleBuilder conditions, undo/redo, Edit-toggle gating, mobile stacking); form-renderer (multi-page, client validation mirror, live computed, conditional visibility); `/forms` Resource list + detail tabs (Submissions/Flow/Settings/Versions with mock data); all states tunable on `form-service.mock.ts`. Iterate UX to Typeform/Tally standard. Vitest as built.
- **Phase B — backend (TDD, tests precede code):** migrations; status-engine scoped extension (from the spike, productionized); `app/form_engine/` package; models/repos/services/routers; publish/version snapshot; submit pipeline; scoped-status seed + Flow-tab graph endpoints; CSV export; permissions CSV + seed. Swap mock → api-client at the service boundary (one-line change).
- **Phase C — E2E + report (real clicks, mock first then live):** journeys below; Test Execution Report `01-form-engine-test-report.md`; CLAUDE.md section; backlog status updates; memory.

## Phases — Slice 2 (own branch `sprint-3/02-form-engine-public-workflow`)

- **Phase A — frontend:** public fill page (pre-auth branded layout, subdomain tenant, closed/full states, honeypot, no-draft anonymous flow); Settings access toggle wired; workflow editor: `form.submitted` trigger node UI (searchable form picker, dynamic `{ }` outputs) on mock metadata.
- **Phase B — backend:** public router (uniform 404, throttle bucket, multipart sniff-gated quarantined uploads, anonymous submit path, per-user-limit grey logic server-enforced); `form.submitted` TriggerDef (dynamic output schema callable) + emit on submit (after-commit event-bus path, failure-isolated — a broken workflow must never 500 a public submit); metadata endpoint wiring.
- **Phase C — E2E + report:** anonymous journey + workflow-fires assertions; throttle/honeypot negative tests; report.

## TDD

- **Backend (pytest):** `validate_form_doc` 422 matrix (dup keys, forward/broken condition refs, computed→non-numeric, empty page); submit-validation matrix (hidden-dropped, required-if-visible, options-membership, computed recompute ignores client value, repeater min/max + row validation, address whitelist); scoped-status matrix (seed on create, cross-scope transition refused, scope-filtered graph, `is_active` edit-permission, existing unscoped entities regression-green); publish/version snapshot + validate-against-current 409/422; window/cap/limit (atomic cap race via guarded UPDATE pattern); subject polymorphic guard (cross-tenant subject → 422; unscoped resolve refused); CSV flatten; permission gates. Slice 2 adds: uniform-404, throttle 429, honeypot reject, upload sniff/cap/quarantine-key, trigger payload shape + dynamic outputs, submit-emits-after-commit isolation.
- **Frontend (Vitest+RTL):** palette add/reorder/delete per field type; settings panel edits; condition builder mount; computed live recalcs; renderer per-type validation messages; page navigation blocks on invalid page; hidden-field clearing; repeater add/remove rows; parity test pinning `types/forms.ts` defaults to backend schema (branding-tokens precedent).
- **E2E (Playwright, real clicks, timestamped names, dedicated tenant — scoped statuses mutate shared graph surfaces):** ① build a multi-page form via click-to-add (dnd-kit drag asserted in Vitest — Playwright can't drive dnd-kit pointer sensors, template-engine lesson) → conditional field → computed field → publish. ② fill internally: condition shows/hides live, computed updates, per-page validation, submit → row in Submissions tab. ③ Flow tab: add "Under Review"/"Accepted" statuses + edges → transition a submission via graph-driven buttons → StatusBadge updates. ④ Versions tab paginates; edit draft → "unpublished changes" → republish → old submission still renders v1. Slice 2: ⑤ logged-out subdomain fill + submit (throttle headroom per BL-061 caveats) → ⑥ workflow with `form.submitted` trigger + `email.send` using `trigger.answers.*` → run appears in Logs, mail in maildir rig.

## Verification (end-to-end)

1. `python -m scripts.bootstrap_db`; `python -m pytest -q` green — **including the full pre-existing status-engine suite** (scoped extension must not regress tenant lifecycle).
2. `rm -rf .next && npm run build && npm start` (wrong-build gotcha); Vitest green; confirm :3001/:8001 port ownership before E2E.
3. Manual: build → publish → fill → transition at desktop ~1280px AND ~375px (responsive mandate; builder 3-pane stacks).
4. Regression: status canvas for `tenant` entity unchanged; workflows list/editor unchanged (slice 2 touches registry).
5. Code-review agent approval before merge (hard-fail rules apply: no router DB logic, no fetch-in-component, no `any`, no raw CSS).

## Backlog spawned

| ID | Item |
|---|---|
| BL-086 | `payment` field type — lands with F6 payment provider |
| BL-087 | Entity-sourced choice options (`{kind:'entity'}`) |
| BL-088 | `entity.create` workflow action — non-auth domain entities only (participant/lead), with F4 |
| BL-089 | Conditions on repeater sub-fields (row-indexed fact keys) |
| BL-090 | Anonymous browser-local fill autosave |
