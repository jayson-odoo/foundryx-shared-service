# Ideation Phase B - Structure + Grill - Acceptance Criteria

**Program:** keys back to `PLAN-ideation-to-delivery-program.md` (the spine). This UAC is written FIRST; the Phase-B plan (`PLAN-ideation-phase-b-structure.md`) fulfils it; the Phase-B test report keys back to these ids.
**Scope of Phase B (from program §4):** BusinessRequirement + FunctionalRequirement entities & lifecycles (§3) on **fixed versioned templates** (D5, built on `template_engine`/`form_engine`); Idea↔BR many-many + BR↔FR many-many (D4); authoring pattern **AI drafts structured → human refines → explicit promote gate** (D5, D16); **heavy interactive grilling chat** at BR→FR whose **brain is Claude Code on the Mac Mini** - shared-service provides only a chat UI that **dispatches a `grill` job over the §5.4 bridge and relays** streamed questions/answers (D11/D20); **reuse-analysis produced by Claude Code in a single pass over code + Outline** (no separate doc-RAG tier, D11); **Gate 1 = FR approved** (D12); the **FR is the GitHub-issue payload** (D4).
**shared-service runs NO LLM (D20):** all AI compute - the grill turns, the structured BR/FR drafts, the reuse-analysis - is dispatched to Claude Code on the Mac Mini via the §5.4 bridge and relayed back; shared-service is data + UI + relay only. No assistant port, no LLM key, no embedding pipeline in shared-service.
**Depends:** Phase A (Product + Idea entities, respond.io contact sync, ideation embed host, roles Submitter/Triager/Maintainer per D16) **and the Mac Mini bridge (§5.4)** - the outbound-poll bridge that carries the `grill` job kind is **shared infra with Phase C**; build it once, early. Phase A entities and the bridge are treated as prerequisites here.
**Classification:** MODULE / Service on foundryx-shared-service (D1); own schema `app_ideation` with normal cross-schema FKs into `public` (users/tenants) - the omnichannel module precedent (`modules/omnichannel/`, schema `app_omnichannel`, `bootstrap.py` install hooks, per-module Alembic).

Every AC is tagged `[BE]` / `[FE]` / `[E2E]` / `[T]`. Grouped by slice.

---

## Slice B1 - BusinessRequirement entity, lifecycle & versioned template

### AC-B-01 - BR entity in `app_ideation` [BE][T]
- **Given** the ideation module is installed for the Foundryx-internal tenant, **when** its migrations run, **then** a `business_requirements` table exists in schema `app_ideation` carrying `id`, `tenant_id` (FK `public.tenants`), `product_id` (FK the Phase-A products table), `status_id`, `template_key`, `template_version`, `answers_json` (form_engine answers), `created_by`/`updated_by` (FK `public.users`), timestamps - matching program §3 (`problem_statement`, `business_goal`, `stakeholders`, `success_metric`, `scope`, `constraints` live inside `answers_json`, not as columns).

### AC-B-02 - BR lifecycle on status_engine [BE][T]
- **Given** the BR entity is registered via `register_status_entity` (`app/status_engine/registry.py`) as an **unscoped, tenant-owned** entity `entity_type="ideation_business_requirement"`, **when** a BR is created, **then** it starts at `draft` and the platform-fixed edge set `draft → grilling → ready → in-FR → delivered → archived` is the only path; illegal transitions are rejected by the engine (parity with the `tenant` / `form_submission` registrations).

### AC-B-03 - versioned BR template [BE][T]
- **Given** a fixed BR artifact template authored as a **form_engine document** (`app/form_engine/schemas.py` Page→Section→Field) and versioned (immutable snapshots + a movable `active` label, mirroring `ai_prompt_versions`/`ai_prompt_labels`), **when** a BR is created, **then** it stamps the `template_version` in force at creation and `answers_json` is validated by `validate_form_doc`'s runtime twin against **that** version's document - a later template edit never mutates an existing BR (forever-contract).

### AC-B-04 - Idea↔BR many-many (D4) [BE][T]
- **Given** the join table `idea_business_requirements` (`idea_id`, `business_requirement_id`, both cross-schema FKs within `app_ideation`), **when** ideas are attached to a BR, **then** one idea may back many BRs and one BR may cite many ideas; `BR.linked_idea_ids[]` reflects the join and detaching is idempotent.

### AC-B-05 - BR list + detail render [FE][E2E]
- **Given** the ideation UI reached **via the sidebar** (never a deep URL), **when** the Triager opens Business Requirements, **then** a DataGrid lists BRs (fixed layout, resizable columns, `truncate`+`title`) and a detail page renders **every** template section even when empty (explicit empty state + CTA per the CRUD UX standard), showing linked ideas and current status.

---

## Slice B2 - FunctionalRequirement entity = GitHub-issue payload

### AC-B-06 - FR entity in `app_ideation` [BE][T]
- **Given** the module migrations, **when** they run, **then** a `functional_requirements` table exists in `app_ideation` with `id`, `tenant_id`, `product_id`, `status_id`, `template_key`, `template_version`, `answers_json`, `github_issue_ref`, `pr_ref`, `created_by`/`updated_by`, timestamps.

### AC-B-07 - FR template = the issue payload shape (D4) [BE][T]
- **Given** the versioned **FR form_engine template**, **when** inspected, **then** its fields are exactly the GitHub-issue payload: `acceptance_criteria[]` as Given/When/Then rows (form_engine `repeater`/`table`), `technical_approach`, `reuse_analysis`, `slice_scope`, `grill_notes`, `lavish_artifact` (a reference/URL) - one FR = one issue = one vertical slice (no columns beyond these live in `answers_json`).

### AC-B-08 - FR lifecycle on status_engine [BE][T]
- **Given** FR registered `entity_type="ideation_functional_requirement"` (unscoped, tenant-owned), **when** created, **then** it starts `draft` and rides the fixed edge set `draft → grilling → approved → building → prototype-review → developing → pr-review → merged → deployed → done`, plus side states `blocked/awaiting-clarification` and `bounced`; illegal jumps rejected.

### AC-B-09 - BR↔FR many-many (D4) [BE][T]
- **Given** the join table `business_requirement_functional_requirements`, **when** FRs are linked to BRs, **then** one BR may spawn many FRs and one FR may satisfy many BRs; `FR.linked_br_ids[]` reflects the join.

### AC-B-10 - FR payload exportable as issue body [BE][T]
- **Given** an `approved` FR, **when** the issue-payload serializer runs, **then** it emits a deterministic Markdown body from `answers_json` (G/W/T list + technical_approach + reuse_analysis + slice_scope + grill_notes + lavish_artifact link) that Phase C can hand to the GitHub adapter unchanged - the serializer is pure (no network, Phase B owns only the shape).

---

## Slice B3 - Authoring pattern: AI drafts structured → human refines → explicit promote gate (D5, D16)

### AC-B-11 - Triager promotes ideas → BR; similarity suggests clusters, human decides [BE][FE][E2E]
- **Given** triaged ideas on the board, **when** the clustering suggester runs (**`pg_trgm` text-similarity** neighbours - no embedding/LLM in shared-service per D10/D20), **then** it **suggests** idea clusters as promotion candidates but **never** creates a BR itself; a **Triager** explicitly selects a cluster and confirms "Promote to BR", which creates the BR (`draft`) and attaches the chosen ideas (AC-B-04).

### AC-B-12 - AI draft is structured (produced by Claude Code, stored by shared-service), not prose [BE][T]
- **Given** a promote-to-BR (or generate-FR) action, **when** shared-service dispatches the draft to **Claude Code over the §5.4 bridge** (shared-service runs no LLM, D20), **then** Claude Code returns **structured `answers_json`** conforming to the target template - never free prose dumped into one field; fields it cannot fill are left empty for the human; shared-service validates the returned `answers_json` against the stamped template version and **stores** it.

### AC-B-13 - human refine before promote [FE][E2E]
- **Given** an AI-drafted BR or FR in `draft`/`grilling`, **when** a human edits any template field, **then** the edit persists to `answers_json` and re-validates against the stamped template version; the record stays in its pre-promote status.

### AC-B-14 - explicit promote gate, never auto-promote [BE][T]
- **Given** a BR at `draft`/`grilling` or an FR at `grilling`, **when** anything other than an explicit human promote action (with the required role) attempts the transition to `ready` (BR) / `approved` (FR), **then** the status_engine transition is **refused** - no AI path, no timer, no import can auto-promote (D5).

### AC-B-15 - promote requires role [BE][T]
- **Given** the D16 roles, **when** promote is attempted, **then** BR→`ready` and FR→`approved` require **Triager or Maintainer**; a Submitter is `403`. (RBAC via the platform permission catalog seeded by the module `bootstrap.py`, omnichannel `permissions.csv` precedent.)

---

## Slice B4 - Heavy interactive grilling chat at BR→FR (D11) - brain is Claude Code, shared-service relays

### AC-B-16 - grill session bound to a BR [BE][T]
- **Given** a BR at `ready`, **when** a Maintainer starts a grill, **then** shared-service creates a grilling **conversation** bound to `(tenant_id, business_requirement_id)` (a plain message/transcript store - data only, no assistant engine, D20), dispatches a **`grill` job over the §5.4 bridge** (`{ kind: "grill", br_ids[], fr_draft_id?, product_id, repo }`), and the BR moves to `in-FR` / a nascent FR is created at `grilling` - the FR is the grill's target artifact.

### AC-B-17 - device-free, embedded surface (D11/D15/D17) [FE][E2E]
- **Given** the grilling chat, **when** a human uses it, **then** it renders inside the **embedded ideation UI** (iframe SSO via the omnichannel embed framework - `/embed/session` assertion→token, `frame-policy`, connection `allowedOrigins`; `modules/omnichannel/services/embed_session_service.py`), so the entire grill happens in **one device-free surface**; device-free because the Mac Mini is always-on (grill turns require the Mac Mini online, same as builds); no GitHub, no separate tool.

### AC-B-18 - Claude Code runs the grill turns; shared-service relays [BE][T]
- **Given** a grill turn, **when** the human sends a message, **then** shared-service **relays it over the §5.4 bridge to Claude Code** (which grills by reading code + Outline in one pass) and **streams the returned question/answer back into the conversation** - shared-service itself runs **no** prompt registry, no schema-forced parse, no MCP dispatch, no LLM (D20); each turn is stored in the transcript and the bridge job's milestone events are recorded for inspection.

### AC-B-19 - FR generated AFTER the grill (D11) [BE][E2E]
- **Given** a grill judged sufficient by the human, **when** they hit "Generate FR", **then** the `grill` job completes and **Claude Code emits a structured FR `answers_json`** (AC-B-07); shared-service validates and stores it, captures the full transcript into the FR's `grill_notes`, and the FR remains at `grilling` (not auto-approved - AC-B-14).

### AC-B-20 - grill is not keyword-tuned [T]
- **Given** paraphrased BRs, **when** grilled, **then** Claude Code's questioning generalizes (LLM-as-NLP; no overfit classifier) - the test set is paraphrases, asserting the grill surfaces scope/edge-case/constraint gaps, not a fixed script.

---

## Slice B5 - Reuse-analysis by Claude Code in one pass over code + Outline (D11)

> Reframed per D11/D20: shared-service does **not** run a doc-RAG service, embed Outline, or provision pgvector for reuse. Claude Code - which reads the product's **code and Outline docs together in a single pass** during the `grill` job - is the sole reuse analyst. There is **no two-tier split** (no "doc tier now, code tier in Phase C"): the code-level view is available at grill time.

### AC-B-21 - reuse-analysis is a Claude Code pass over code + Outline [BE][T]
- **Given** a `grill` job for a product (carrying `repo` and the product's Outline access), **when** Claude Code grills, **then** it produces reuse-analysis by reading **both the product's repo code and its Outline docs in the same pass** - shared-service performs **no** ingestion, embedding, or indexing (D20); the reuse analysis originates entirely on the Mac Mini and is returned over the §5.4 bridge.

### AC-B-22 - reuse-analysis surfaced during the grill / into the FR [BE][FE][E2E]
- **Given** a grill for a product, **when** Claude Code returns reuse candidates (capability name + code/doc reference + rationale), **then** shared-service **stores** them into the FR's `reuse_analysis` field and shows them in the grill surface - "this capability may already exist, see …".

### AC-B-23 - reuse-analysis is code-aware, not deferred [BE][T]
- **Given** the `reuse_analysis` output, **when** produced, **then** it reflects a **single code-and-doc pass by Claude Code** (not a doc-only planning tier) - there is no "code-level verification deferred to Phase C" note (D11 one-pass); Phase B carries the reuse view Claude Code produced at grill time.

### AC-B-24 - clean "no candidates" return [BE][T]
- **Given** a product where Claude Code finds no matching existing capability in code or docs, **when** reuse-analysis runs, **then** the `reuse_analysis` field records "no reuse candidates" cleanly (no hallucinated matches) - Claude Code returns an explicit empty result, never fabricated matches.

---

## Slice B6 - Gate 1: FR approved (D12)

### AC-B-25 - Gate 1 is a human-gated transition [BE][T]
- **Given** an FR at `grilling` with a complete `answers_json` (all required template fields present per `validate_form_doc`), **when** a Maintainer clicks "Approve FR", **then** the status_engine transitions `grilling → approved`; an FR with missing required fields is refused with the field list (publish-gate parity).

### AC-B-26 - approval readiness surfaced [FE][E2E]
- **Given** the FR detail page, **when** required fields are incomplete, **then** the Approve action is disabled with an explicit "missing: …" state; when complete, Approve is enabled - the human sees exactly why the gate is open or shut.

### AC-B-27 - approved FR is Phase-C-ready, no build yet [BE][T]
- **Given** an FR reaches `approved`, **when** Phase B ends, **then** it is queued for delivery **conceptually only** - Phase B performs **no** GitHub/issue/build side-effect (that is Phase C §5.4); the issue-payload serializer (AC-B-10) is available but not invoked against any network.

### AC-B-28 - traceability idea → BR → FR intact [BE][E2E]
- **Given** an `approved` FR, **when** its lineage is queried, **then** it resolves back through `linked_br_ids[]` → each BR's `linked_idea_ids[]` → the originating ideas - one idea traceable to the FR that will become the shipped slice (program vision).

---

## Cross-cutting

### AC-B-29 - module install/uninstall hygiene [BE][T]
- **Given** the ideation module, **when** installed then uninstalled for a tenant, **then** its `app_ideation` artifacts follow the App-Store module contract (`bootstrap.py` `install`/`install_tenant`/`uninstall_tenant`, per-module Alembic, `manifest.json` schema + `alembic_version_table`) - the omnichannel precedent; durable cross-tenant records are unaffected.

### AC-B-30 - no UUIDs in the UI, mobile-scrollable [FE][E2E]
- **Given** any ideation screen, **when** rendered, **then** UUIDs are resolved to human-readable identifiers, every dropdown is a `SearchableSelect`, destructive/detach actions confirm via `AlertDialog` (never `confirm()`), and modals scroll at ~375px width (submit reachable).
