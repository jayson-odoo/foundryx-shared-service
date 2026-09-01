# PLAN - Ideation Phase B: Structure + Grill

> ## ⚠️ SUPERSEDED (2026-07-21) - historical reference only
>
> This plan was written under program decision **D20** ("shared-service runs NO LLM"), which has been **amended to D20-A**: the AI cut line is **code-awareness, not location**. Grilling is now a shared-service LLM capability; only `reuse_analysis` and the build stay on the Mac Mini.
>
> **What that invalidates here:** the **B1-B6 slice map (§5)**, the claim that the grill brain is Claude Code (**B-D6/B-D11**), the "no LLM in shared-service" framing throughout, and the **Mac Mini bridge dependency (§7)** for Idea→BR.
>
> **What survives and is still authoritative:** the reuse table (§2), the entity shapes (§3), and decisions **B-D1** (BR/FR are form_engine documents), **B-D2** (immutable template versions + movable label), **B-D3** (unscoped tenant-owned status entities), **B-D4** (promote is an explicit role-gated transition), **B-D10** (pure issue-payload serializer), **B-D12** (clustering suggests, human decides).
>
> **Active successor:** `PLAN-ideation-phase-b-idea-to-br.md` + `ideation-phase-b-idea-to-br-acceptance-criteria.md` (Phase B-i). Phase B-ii (BR→FR + reuse-analysis) is not yet planned.

**Status:** Planning (UAC-first written 2026-07-18; no code). Keys back to `PLAN-ideation-to-delivery-program.md` (the spine) and `ideation-phase-b-structure-acceptance-criteria.md`.
**Classification:** MODULE / Service on foundryx-shared-service (D1). Own schema `app_ideation`, normal cross-schema FKs into `public` (users/tenants) and into the module's own Phase-A tables (products/ideas). App-Store module contract per `modules/omnichannel/` (bootstrap install hooks, `manifest.json`, per-module Alembic).
**Repos in scope:** `foundryx-shared-service` only. (No sorento/n8n/GitHub work in Phase B; the FR issue-payload is *shaped* here, *shipped* in Phase C.)
**Depends:** Phase A (Product + Idea entities, respond.io contact sync, ideation embed host, roles Submitter/Triager/Maintainer) **and the Mac Mini bridge (program §5.4)** - the outbound-poll bridge that carries the `grill` job kind, **shared infra with Phase C, built once and early**. See "Dependency on the Mac Mini bridge" below - the highest-risk coupling. (No LLM, no assistant port, no pgvector in shared-service - D20.)

---

## 1. Goal

Turn triaged **ideas** into **BusinessRequirements**, grill those into **FunctionalRequirements**, and hand Phase C an **approved FR = one GitHub issue = one vertical slice** (D4). Every artifact rides a **fixed, versioned template** (D5) and every promotion is a **human gate** (D5, D12, D16). All humans work in **one device-free embedded surface** (D11/D15/D17).

Data spine delivered by Phase B:
```
Idea (Phase A) ──many-many──▶ BusinessRequirement ──many-many──▶ FunctionalRequirement ──Gate 1──▶ approved
                              (template, lifecycle)   (grill @ BR→FR)   (issue-payload template)
```

## 2. What already exists (reuse, do not rebuild) - cited

| Need | Reuse | File |
|------|-------|------|
| Structured artifact templates, versioned | `form_engine` block-doc (Page→Section→Field) + `validate_form_doc` publish gate; static options | `service_backend/app/form_engine/schemas.py` |
| Template = versioned document, printable/exportable | `template_engine` block-doc + `validate_doc` + seed-if-missing-by-key | `service_backend/app/template_engine/schemas.py`, `seed_templates.py` |
| Immutable versions + movable label (template/prompt versioning) | `ai_prompt_versions` (immutable, auto-inc per name) + `ai_prompt_labels` (movable pointer) | sorento `app/models/ai_prompt.py` (port shape) |
| Entity lifecycle / gates | `status_engine` `register_status_entity` (unscoped tenant-owned like `tenant`; scoped like `form_submission`); auto-edges + record facts | `service_backend/app/status_engine/registry.py` |
| Grill chat transcript store (data only - no assistant engine) | conversation/message store shape (transcript + milestone events); **no** node-trace engine, **no** LLM - the brain is Claude Code over the bridge (D20) | shape ref only: sorento `app/models/ai_assistant.py` (data columns), program §5.4 |
| AI compute (grill turns, BR/FR structured drafts, reuse-analysis) | **Claude Code on the Mac Mini via the §5.4 bridge** (`grill` job kind) - shared-service dispatches + relays, runs no LLM | program §5.4 (Mac Mini bridge) |
| Device-free iframe SSO surface | omnichannel embed framework: `/embed/session` assertion→token, `EmbedJti` single-use, `frame-policy`, `Connection.allowedOrigins`, external-agent identity | `service_backend/modules/omnichannel/services/embed_session_service.py`, `routers/embed.py`, `app/models/connection.py` |
| Idea-cluster + dedup similarity | `pg_trgm` text-similarity (no embedding/pgvector in shared-service - D10/D20) | Postgres `pg_trgm` |
| Module packaging | schema-isolated module w/ install hooks + manifest + per-module Alembic | `service_backend/modules/omnichannel/bootstrap.py`, `manifest.json` |

## 3. Entities (Phase B additions, schema `app_ideation`)

- **BusinessRequirement** - `id`, `tenant_id`→`public.tenants`, `product_id`→products, `status_id`, `template_key='business_requirement'`, `template_version`, `answers_json` (holds `problem_statement`/`business_goal`/`stakeholders`/`success_metric`/`scope`/`constraints`), `created_by`/`updated_by`→`public.users`, timestamps.
- **FunctionalRequirement** - `id`, `tenant_id`, `product_id`, `status_id`, `template_key='functional_requirement'`, `template_version`, `answers_json` (holds `acceptance_criteria[]` G/W/T, `technical_approach`, `reuse_analysis`, `slice_scope`, `grill_notes`, `lavish_artifact`), `github_issue_ref`, `pr_ref`, audit cols.
- **IdeationArtifactTemplate** + **…TemplateVersion** - versioned form_engine documents keyed by `template_key`; immutable versions + a movable `active` label (mirror `ai_prompt_versions`/`_labels`). BR/FR stamp the version in force at creation (forever-contract, AC-B-03).
- **Join tables** - `idea_business_requirements`, `business_requirement_functional_requirements` (D4 many-many).
- **GrillConversation / GrillMessage** - plain transcript store (data only, no assistant engine, D20), bound to `(tenant_id, business_requirement_id)` and target `functional_requirement_id`; each message carries who/role/text/timestamp. The grill's reasoning lives in Claude Code on the Mac Mini (§5.4); shared-service only persists the relayed turns.
- **GrillJob** - a `grill`-kind bridge job (program §5.4): `br_ids[]`, `fr_draft_id?`, `product_id`, `repo`, `status`, `last_event`, milestone events (dispatched/streaming/fr_emitted/error) recorded for inspection. No trace/span engine - just the bridge job lifecycle.
- **Reuse-analysis** is **not** a shared-service entity - Claude Code produces it (code + Outline, one pass) and returns it over the bridge; shared-service stores the result inside the FR's `answers_json.reuse_analysis`. No `ProductReuseDoc`, no Outline embedding corpus, no pgvector (D11/D20).

Status registrations (code-side, `register_status_entity` at module bootstrap):
- `ideation_business_requirement` - unscoped, tenant-owned; edges `draft → grilling → ready → in-FR → delivered → archived`.
- `ideation_functional_requirement` - unscoped, tenant-owned; edges `draft → grilling → approved → building → prototype-review → developing → pr-review → merged → deployed → done` + `blocked/awaiting-clarification`, `bounced`. (Building-and-later states are *driven* by Phase C; Phase B only owns up to `approved`.)

## 4. Decision log

| # | Decision | Why |
|---|----------|-----|
| B-D1 | BR/FR are **form_engine documents** (`answers_json` validated against a versioned template), NOT wide column sets. | D5 "fixed versioned templates on form_engine"; template fields evolve without migrations; `validate_form_doc` gives the completeness gate for free (AC-B-25). |
| B-D2 | Template versioning = **immutable version rows + movable `active` label**, BR/FR **stamp** their version. | Forever-contract (AC-B-03): editing the template must never mutate historical artifacts. Reuses the proven `ai_prompt_versions`/`_labels` shape. |
| B-D3 | BR/FR lifecycles are **unscoped tenant-owned status_engine entities** (not scoped-per-record). | The edge set is platform-fixed per *type*, identical for every BR/FR - that is exactly what `tenant` does, not the per-record graphs `form_submission` uses. |
| B-D4 | **Promote is an explicit, role-gated status transition**; no AI/timer/import path exists to `ready`/`approved`. | D5 never-auto-promote (AC-B-14/B-15). The engine is the boundary; the AI only *fills* `answers_json`. |
| B-D5 | AI drafting is **schema-forced structured output** into `answers_json`, never prose - **produced by Claude Code over the §5.4 bridge**, then validated + stored by shared-service (which runs no LLM, D20). | AC-B-12; keeps the human refining fields, not parsing an essay; all AI compute lives on the Mac Mini. |
| B-D6 | The grill is a **transcript-store conversation bound to a BR** that **relays turns to Claude Code**; the FR is emitted **only when the human hits Generate FR**. | D11 "FR generated after the grill" (AC-B-19); the grill target is the FR, transcript → `grill_notes`; shared-service stores, Claude Code reasons. |
| B-D7 | Grill surface is the **embedded ideation iframe** via the omnichannel embed framework. | D11/D15/D17 device-free single surface (device-free because the Mac Mini is always-on); reuse `/embed/session` + frame-policy rather than a bespoke auth. |
| B-D8 | Reuse-analysis is a **single Claude Code pass over code + Outline** (no doc-only tier, no Phase-C deferral). | D11 one-pass - Claude Code reads code **and** Outline together at grill time, so the code-level view is present in Phase B; no two-tier split. |
| B-D9 | Reuse-analysis is produced **on the Mac Mini and returned over the bridge**; shared-service stores it into `answers_json.reuse_analysis` with a **clean "no candidates"** path. | AC-B-21/B-24; no ingestion/embedding/pgvector in shared-service (D20); Claude Code returns an explicit empty result rather than hallucinating matches. |
| B-D10 | The **FR issue-payload serializer is pure** (Markdown from `answers_json`, no network) in Phase B. | AC-B-10/B-27; Phase C owns the GitHub side-effect (§5.4). Keeps the B/C boundary clean. |
| B-D11 | **No assistant/LLM in shared-service - the grill brain is Claude Code on the Mac Mini, reached via the §5.4 bridge** (`grill` job kind). shared-service provides only the chat UI + transcript store + relay. | D20 (shared-service runs no LLM; Phase 0 assistant port cancelled). See §7. The bridge is shared infra with Phase C - build it once, early. |
| B-D12 | **Similarity cluster suggestion for idea→BR**, human decides. | D16; clustering uses **`pg_trgm` text-similarity** (no embedding/pgvector in shared-service, D10/D20); it only proposes candidates (AC-B-11). |

## 5. Phase breakdown (three-phase loop per slice; test-first in Phase 2)

Ordering: **B1 → B2 → B3 → B4 → B5 → B6**, each a UAC slice. B1/B2 are pure data+engine (no prototype ambiguity → lighter Phase-1). B3/B4 are UX-heavy → real Phase-1 prototype first.

### B1 - BR entity, lifecycle, versioned template (AC-B-01..05)
- **P1 (FE prototype):** BR list DataGrid + detail page rendering every template section (mock answers). Nail the "render empty sections + CTA" contract.
- **P2 (BE, test-first):** `app_ideation` migration (BR table + Idea↔BR join); `IdeationArtifactTemplate(+Version)` with the seeded BR form-doc; `register_status_entity("ideation_business_requirement")`; CRUD routes + list_query registration; validate `answers_json` against stamped template version. Wire FE off mocks. pytest: lifecycle edges, template-version stamping, join cardinality.
- **P3:** `/code-review`.

### B2 - FR entity = issue payload (AC-B-06..10)
- **P1:** FR detail page rendering the issue-payload template (G/W/T repeater, technical_approach, reuse_analysis, slice_scope, grill_notes, lavish_artifact) with mock data.
- **P2 (test-first):** FR table + BR↔FR join migration; seed FR form-doc template; `register_status_entity("ideation_functional_requirement")`; **pure issue-payload serializer** (`answers_json` → deterministic Markdown) with golden-string pytest FIRST. Wire FE.
- **P3:** review.

### B3 - Authoring pattern: draft → refine → promote gate (AC-B-11..15)
- **P1:** Board "Promote to BR" flow from a suggested cluster (mock suggestions); BR/FR edit forms; disabled-Promote states.
- **P2 (test-first):** idea-cluster suggester (**`pg_trgm` neighbours**, suggest-only); AI draft **dispatched to Claude Code over the §5.4 bridge**, returning structured `answers_json` that shared-service validates + stores (no LLM in shared-service, D20); role-gated promote transitions wired through status_engine; RBAC via module `permissions.csv`. pytest: never-auto-promote (AC-B-14), role denial (AC-B-15), draft is structured (AC-B-12, assert against a stubbed bridge response).
- **P3:** review.

### B4 - Grilling chat at BR→FR (AC-B-16..20) - **highest effort**
- **P1:** Embedded grill chat surface (iframe) with stubbed relayed turns; "Generate FR" button; job-milestone timeline (mock events).
- **P2 (test-first):** grill **transcript store** (conversation/message, data-only) + **`grill`-job dispatch/relay over the §5.4 bridge** (B-D11) - shared-service relays each turn to Claude Code and streams the reply back into the transcript; "Generate FR" completes the job and Claude Code's returned structured `answers_json` is validated + stored, transcript → `grill_notes` (FR stays `grilling`). Embed via `/embed/session`. **No prompt registry / schema-forced parse / MCP dispatch / LLM in shared-service.** pytest against a **stubbed bridge** + a Playwright grill E2E (paraphrase set, AC-B-20, real fixtures; the bridge is stubbed to a deterministic Claude Code responder in CI).
- **P3:** review.

### B5 - Reuse-analysis by Claude Code (code + Outline, one pass) (AC-B-21..24)
- **P1:** reuse-candidates panel in the grill/FR surface (mock candidates + clean "no candidates" state).
- **P2 (test-first):** the `grill` job carries `repo` + Outline access so Claude Code runs reuse-analysis in one code+doc pass and returns candidates over the bridge; shared-service **stores** them into `answers_json.reuse_analysis` and surfaces them. **No ingester, no `ProductReuseDoc`, no pgvector.** pytest against a stubbed bridge: candidates stored+surfaced, clean empty-result path (AC-B-24), single-pass framing (no Phase-C deferral note, AC-B-23).
- **P3:** review.

### B6 - Gate 1: FR approved (AC-B-25..28)
- **P1:** Approve action with enabled/disabled + "missing: …" state.
- **P2 (test-first):** completeness check (required fields via `validate_form_doc` twin) gating `grilling → approved`; lineage query (FR→BR→idea). pytest: refuse-incomplete, traceability, **no GitHub side-effect** (AC-B-27).
- **P3:** review + PR for the whole Phase-B branch.

## 6. Contracts owned by Phase B (feed Phase C / the program spine)

- **FR issue-payload (Markdown body):** deterministic render of `answers_json` - G/W/T acceptance criteria, `technical_approach`, `reuse_analysis`, `slice_scope`, `grill_notes`, `lavish_artifact` link. Consumed by Phase C §5.4 `fr_snapshot`. Phase B produces the bytes; Phase C transmits them.
- **FR status surface for status-back:** `approved` is the Phase-B terminus; Phase C drives `building → … → deployed` (program §5.4 milestone status-back) on the same `ideation_functional_requirement` entity.
- **`grill` job contract (consumed by the §5.4 bridge):** shared-service dispatches `{ kind: "grill", br_ids[], fr_draft_id?, chat_turn, product_id, repo }` and consumes the streamed questions/answers + the final structured FR `answers_json` (incl. `reuse_analysis`). The grill's prompts live **with Claude Code on the Mac Mini, not in shared-service** (D20) - shared-service owns only the job shape and the transcript store.

## 7. Dependency on the Mac Mini bridge (report to program)

**The grilling chat (B4), the AI drafts (B3), and the reuse-analysis (B5) all run their AI compute on Claude Code on the Mac Mini - shared-service runs NO LLM (D20).** shared-service provides only the chat UI, the transcript store, and the **relay**: it dispatches a `grill`-kind job over the **program §5.4 bridge** and streams Claude Code's questions/answers/FR back. **The old "assistant port / scoped mini-port" is cancelled (D20) - there is no assistant, no prompt registry, no LLM key in shared-service.**

The §5.4 bridge is **foundational infra shared by Phase B (grill) and Phase C (build)** - the same outbound-poll daemon carries both `kind: "grill"` and `kind: "build"` jobs. **Build the bridge once, early**; Phase B cannot grill without it, and Phase C cannot build without it.

**Explicit sequencing asks for the program owner:**
1. **Mac Mini bridge (§5.4) must land before B3/B4/B5** - the `AgentRunner` registration + outbound-poll `GET /agent-runner/jobs` (with the `grill` job kind) + callback `POST /agent-runner/events`. This is shared with Phase C; sequence it as shared infra, not a Phase-C-only asset. B's grill/draft/reuse turns are all bridge jobs.
2. Phase A must land the **ideation embed host + Connection/allowedOrigins** for the product - B4's device-free grill reuses it (D17); if A ships only the idea board embed, B extends the same connection for the grill route.
3. **No pgvector / no LLM key needed in shared-service** (D20). Idea clustering (B3) and dedup use **`pg_trgm`** (D10); reuse-analysis (B5) is Claude Code's code+Outline pass on the Mac Mini. The Mac Mini being always-on is what makes the grill device-free; **offline Mac Mini = grill/draft jobs queue** (same acceptance as builds, program §6).

## 8. Risks (Phase-B-specific; program §6 still applies)

- **Bridge dependency for a UX-facing flow** - unlike Phase C (async builds), the grill is an **interactive** chat, so the §5.4 relay must feel responsive and an offline Mac Mini degrades a live human session (not just a queued build). Guard: build the bridge early as shared infra (§7.1), stream turns, and surface a clear "grill agent offline - turns queued" UI state; no LLM ever creeps into shared-service to "cover" for an offline Mini (D20).
- **Template-version drift** - a template edit that isn't a new immutable version would silently reshape historical BR/FR. Guard: versions immutable, movable label only (B-D2), enforced by test.
- **Reuse-analysis false confidence** - Claude Code's code+Outline matches could read as certainty. Guard: `reuse_analysis` presents candidates with rationale + references (not verdicts) and returns a clean "no candidates" rather than fabricating matches (AC-B-24); it is a single code+doc pass (AC-B-23), not a code-guaranteed dedupe.
- **Gate leakage** - an AI/import path that reaches `approved` breaks the whole human-gated promise. Guard: AC-B-14 test asserts every non-human path is refused by the engine.
