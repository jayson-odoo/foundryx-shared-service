# Ideation Phase B-i — Idea → Business Requirement · Acceptance Criteria

**Source plan:** `PLAN-ideation-phase-b-idea-to-br.md` (GRILLED + LOCKED 2026-07-21)
**Program spine:** `PLAN-ideation-to-delivery-program.md` — amended same day (**D20-A**, D10-A, D21-A, D22-A, D23-A; amendment log §9b).
**Supersedes:** the B1–B6 slice map in `PLAN-ideation-phase-b-structure.md` (written under the original D20).
**Scope:** turn triaged **Ideas** into **Business Requirements** through an AI **grill** that runs *in shared-service*, plus the reusable core **`app/ai/`** subsystem that powers it. **FR is out of scope** — deferred to Phase B-ii together with Mac-Mini reuse-analysis.

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. The Test Execution Report keys back PASS/FAIL/DEFERRED per AC id.

> **The cut line (D20-A).** shared-service may call an LLM for **conversational and text-only** work. Work needing a **repository checkout** — `reuse_analysis`, the FR→PR build — stays on Claude Code on the Mac Mini. Therefore **nothing in this document depends on the §5.4 bridge**, and no runner needs to be online for any AC here.

> **The safety invariant (D22-A).** The model never writes. Structured output is a forced response schema; **our** code validates it against `form_engine` and persists `answers_json`. The agent holds **no tools with side effects**. Never-auto-promote is therefore enforced by architecture, not by prompt wording.

> **The termination model (D23-A).** Claude's own `grill-me` skill has *no* stop rule. Ours does, because we have a target schema: every turn reports `covered_fields[]`, the UI shows "N of M captured", and when coverage completes the grill **offers** to generate. The human always fires it — the same `collecting → review → complete` + **D-CONFIRM** shape Phase A already proved in `create_idea`.

---

## Slice 1 — Core AI foundation (`app/ai/` + `type='llm'` connections)

### AC-BI-01 — `llm` integration type + provider protocol [BE][T]
- **Given** `app/integrations/base.py` already reserves `type: str  # email | storage | llm | erp`, **when** slice 1 lands, **then** an `LLMProvider(IntegrationProvider, Protocol)` exists declaring `complete(config, credentials, *, model, system, messages, output_schema=None, temperature=0) -> LLMResult` and `models(config, credentials) -> list[ModelOption]` — extending the existing protocol exactly as `PaymentProvider` does.
- **Given** `LLMResult`, **then** it carries `text` **or** `structured` (mutually exclusive), plus **normalized** `usage` (`tokens_in`, `tokens_out`) so cost tracking is provider-agnostic.
- **Given** a provider adapter, **then** it owns every provider-specific detail of structured output (Anthropic tool-use/structured outputs · OpenAI `json_schema` response format · Gemini `responseSchema`); no caller branches on provider.

### AC-BI-02 — three provider adapters registered [BE][T]
- **Given** the integration registry at boot, **then** `anthropic`, `openai`, and `gemini` are registered with `type='llm'`, each exposing `fields()` (API key marked `secret`), `test()`, `models()`, and `complete()`.
- **Given** a tenant opens `/settings/integrations`, **then** all three appear as catalog cards using the **existing** Resource-shell list + form — **no new settings UI is built** for connections.

### AC-BI-03 — credentials are core-standard, write-only [BE][T]
- **Given** an LLM connection is saved, **then** the API key is stored in `credentials_json` **Fernet-encrypted** via `app/secrets.py`, is **never echoed** by any endpoint, and a **blank value on update keeps** the stored key (the documented blank-to-keep contract).
- **Given** `FERNET_KEY` is unset, **then** the failure is loud at startup/seed — never a silent per-process ephemeral key.
- **Given** a config PATCH with a subset of fields, **then** it **merges**, never wipes.

### AC-BI-03b — multiple concurrent LLM connections per tenant [BE][T]
*(Added 2026-07-21 during the S1 audit — the grill assumed this and the schema forbade it.)*
- **Given** `uq_connection_tenant_type` enforces ONE active connection per type, **then** `type='llm'` is **carved out** of that index exactly as `payment` and `erp` already are — a tenant may hold several active LLM connections at once.
- **Given** three providers, **then** a tenant can run an Anthropic connection **and** a Gemini connection simultaneously, so different agents may use different providers (e.g. a cheap model for clustering, a strong one for grilling).
- **Given** `uq_connection_tenant_provider`, **then** it still applies — **one active connection per provider** per tenant (no two active Anthropic rows).
- **Given** the type carve-out, **then** `resolve_for_type(tenant, 'llm')` is **no longer meaningful for picking an agent's connection** — an agent resolves **by its own `connection_id`**. Type-resolution remains only for the "is any LLM configured at all?" prerequisite check (AC-BI-11), which must therefore tolerate multiple rows and pick deterministically (tenant rows before platform, then oldest-active).
- **Given** storage and email, **then** their one-active-per-type invariant is **unchanged**.

### AC-BI-04 — `test()` doubles as the model-list probe [BE][T]
- **Given** a saved LLM connection and the **Test** action, **when** it runs, **then** it calls the provider's list-models endpoint; success ⇒ `ACTIVE` + `TestResult.ok`, bad key ⇒ `ERROR` with a clean message (never a raw provider traceback, never the key echoed).
- **Given** a connection that has never passed a test, **then** it displays `UNVERIFIED` until the first passing test.

### AC-BI-05 — model picker: live list, static fallback, pinned id [BE][FE][T]
- **Given** the agent form's model field, **then** it is a **`SearchSelect`** populated from the provider's live model list, filtered to chat-capable models, newest first — never a free-text input (foolproof-UI: only offer valid options).
- **Given** the live list call fails, **then** the form falls back to a curated static list per provider and **still renders** — the form never breaks on a network error.
- **Given** an agent pins a model id that the provider later retires, **when** a run is attempted, **then** it fails **loudly** ("model no longer available — pick another") and never silently substitutes a different model.

### AC-BI-06 — agent registry [BE][FE][T]
- **Given** the core `ai_agents` table, **then** a row carries `tenant_id`, `name`, `connection_id`, `model`, `temperature`, `is_enabled`, audit columns — and holds **no API key of its own** (credentials live only on the connection).
- **Given** the agents surface, **then** it is built on the **config-driven Resource shell** (list + detail form), not a hand-rolled table.
- **Given** an agent whose connection is deleted or deactivated, **then** the agent surfaces a **warning** (missing prerequisite) rather than failing silently at run time.

### AC-BI-06b — an agent equips MULTIPLE skills (MultiSelect) [BE][FE][T]
*(Revised 2026-07-22 after live review — an agent is equipped with a SET of skills, like a Claude agent, not one.)*
- **Given** the agent↔skill relationship, **then** it is **many-many** via an `ai_agent_skills` join (tenant-scoped, derived tenant_id), **not** a single `skill_id` column on the agent.
- **Given** the agent form's Skill field, **then** it is the shared **`MultiSelect`** widget (search + select-all + pills), never a single `SearchSelect`.
- **Given** agent create/update, **then** it accepts `skillIds[]`; each id is validated to belong to the tenant's own tier **or** the platform tier (a foreign-tenant skill id is refused — the polymorphic-target rule).
- **Given** the grill (slice 3), **then** the `GrillDefinition` selects WHICH of the agent's equipped skills runs for a given target; equipping is "available to this agent", firing is the definition's choice. *(Wiring lands in S3; S1 only stores the set.)*

### AC-BI-07 — skill registry = versioned prompt artifact [BE][FE][T]
- **Given** the skill model, **then** a skill has `name`, `description`, and a **body**, modelled on a Claude skill — browsable and selectable, never an anonymous text blob on the agent row.
- **Given** an edit to a skill body, **then** a **new immutable version row** is created and the movable **`active` label** is repointed; prior versions are never mutated (the `ai_prompt_versions` / `ai_prompt_labels` shape cited by B-D2).
- **Given** a rollback, **then** it is a **label move** — no content copy, no delete.
- **Given** skills are editable config, **then** they are gated `ai_agents.manage`-grade, **not** end-user content.

### AC-BI-08 — prompt composition is substitution-only [BE][T]
- **Given** a skill body containing `{{ target_fields }}` / `{{ source_artifacts }}`, **when** a run composes the prompt, **then** substitution runs through `template_engine`'s **`render_tokens`** (dotted-path substitution ONLY).
- **Given** a body containing Jinja/eval-shaped content, **then** it is **never evaluated** — the anti-SSTI house rule holds for prompts exactly as it does for tenant templates.

### AC-BI-09 — traces and spans [BE][T]
- **Given** an LLM run, **then** an `ai_traces` row records conversation, agent, **prompt version**, model, provider, tokens in/out, latency, status (`ok|error`), `flagged`; and `ai_spans` rows record each step (`llm_call`, `validate`, `retry`, and later `tool:<name>`) with input/output JSON, tokens, latency, error.
- **Given** span field naming, **then** it follows **OTel GenAI semconv** so a future OTLP export is a field-map, not a rewrite.
- **Given** the trace UI in slice 1, **then** it renders a **flat ordered step list**; a tree renderer is built only if/when real depth > 1 exists.

### AC-BI-10 — trace retention + payload caps [BE][T]
- **Given** the beat task, **then** a retention sweep prunes `ok` traces past their TTL and `error`/`flagged` traces past a **longer** TTL; the sweep is **failure-isolated** (a prune error never breaks the beat).
- **Given** a large prompt or completion, **then** stored `input_json`/`output_json` are **size-capped** with truncation marked, so a long grill cannot bloat Postgres unbounded.

### AC-BI-11 — key resolution order [BE][T]
- **Given** a tenant with its own active `type='llm'` connection, **then** it is used.
- **Given** a tenant with none, **then** the **platform tenant's** connection is used (mirrors SMTP/storage resolution).
- **Given** neither exists, **then** the grill surface shows a clear **"no AI connection configured"** prerequisite warning and the Grill action is unavailable — never a silent runtime failure.

### AC-BI-12 — deterministic stub adapter for the routine suite [BE][T]
- **Given** no active LLM connection **or** a connection flagged dev, **then** a **stub adapter** answers, mirroring omnichannel's `_is_dev` pattern — pytest, Vitest and Playwright run with **zero API key, zero cost, zero network**.
- **Given** the stub, **then** it is **fixture-driven**: a spec can declare an extraction that is invalid, or missing `success_metric`, so the retry path, the partial-emit path and the never-auto-promote guard are all deterministically testable.
- **Given** the stub is active, **then** only the provider HTTP call is faked — grill engine, coverage tracking, `form_engine` validation, status transitions and RBAC all execute for real.

### AC-BI-13 — live integration tests, opt-in [T]
- **Given** a real key in local `.env` and `pytest -m live`, **then** a small marked suite runs against **anthropic, openai and gemini**, asserting the adapter round-trips and structured output parses on each.
- **Given** a normal `python -m pytest -q` run (CI included), **then** live tests are **skipped by default** — no key required, no cost, no flake.

### AC-BI-14 — core AI permissions [BE][T]
- **Given** the core permissions CSV, **then** it declares `ai_agents.read` / `ai_agents.manage` (agents **and** skills) and **separately** `ai_traces.read`.
- **Given** the separation, **then** trace access (raw prompts/completions) can be granted **without** granting the ability to re-key providers or rewrite prompts, and vice versa.
- **Given** LLM connections, **then** they need **no new permission** — they ride the existing `integrations.read` / `integrations.manage`.
- **Given** implied-read normalization, **then** granting `ai_agents.manage` forces `ai_agents.read` server-side.

---

## Slice 2 — Business Requirement entity

### AC-BI-15 — BR table + lifecycle [BE][T]
- **Given** the `app_ideation` module migration, **then** `business_requirements` exists with `id`, `tenant_id`, `product_id`, `status_id`, `template_key`, `template_version`, `answers_json`, `created_by`/`updated_by`, timestamps (`UTCDateTime` — never a bare `DateTime`).
- **Given** cross-schema references to core (`tenants`, `users`, `statuses`), **then** they are **plain indexed columns, not DB-level FKs** (the BL-030 module rule); intra-`app_ideation` FKs are kept.
- **Given** module bootstrap, **then** `register_status_entity("ideation_business_requirement")` registers an **unscoped, tenant-owned** entity with edges `draft → grilling → ready → in-FR → delivered → archived` (B-D3).

### AC-BI-16 — versioned BR template [BE][T]
- **Given** the seeded BR template, **then** it is a **`form_engine` block document** (not a wide column set, B-D1) whose fields are `problem_statement`, `business_goal`, `stakeholders`, `success_metric`, `scope`, `constraints`.
- **Given** a BR is created, **then** it **stamps** the template version in force at creation.
- **Given** the template is later edited, **then** a **new immutable version** is created and historical BRs continue to render against their stamped version — a template edit can never reshape an existing BR (B-D2).
- **Given** `answers_json` is written, **then** it is validated against the **stamped** version, not the active one.

### AC-BI-17 — Idea ↔ BR many-many [BE][T]
- **Given** the `idea_business_requirements` join table, **then** an Idea may feed several BRs and a BR may absorb many Ideas (D4).
- **Given** an idea is linked to a BR, **then** the link is tenant-scoped and validated — a cross-tenant or cross-product idea id is refused (the polymorphic-target rule: validate on write **and** tenant-scope on read).

### AC-BI-18 — BR Resource surfaces [FE][T]
- **Given** `/business-requirements`, **then** it is a **config-driven `ResourceList`** (server sort/filter/search/paginate, per-user column prefs by `viewKey`, status segments, action registry) — never a hand-rolled table.
- **Given** a BR row is opened, **then** the detail is a **`ResourceForm`** with tabs **Details · Grill · Ideas · Trace · Versions**, global Edit toggle, dirty-guard, record-nav.
- **Given** the Details tab, **then** it renders `answers_json` through the **form-engine renderer** already used for form fill/read — no bespoke BR form.

### AC-BI-19 — BR permissions + promote gate [BE][T]
- **Given** the ideation module CSV, **then** it declares `business_requirements.read`, `.manage`, and **separately** `.promote` (Submitter / Triager / Maintainer, D16).
- **Given** a user with `.manage` but not `.promote`, **when** they open a `draft` BR, **then** they can grill and edit `answers_json` but the promote action is **absent** (frontend) and **refused 403** (backend — the real boundary).
- **Given** the promote transition, **then** it is enforced by **`require_permission("ideation.business_requirements.promote")` on the promote edge** (`br-tr-promote`). *(Revised 2026-07-22 after the S2 review: the BR status graph is **platform-tier** (`tenant_id=NULL`, shared across all tenants), so a platform-tier edge **cannot** carry per-tenant `transition_roles` ids — edge-role auth is architecturally unavailable until a tenant forks the graph. Gating the specific edge id `br-tr-promote` on the `.promote` permission is the equivalent real backend boundary, and the edge id is a **code contract**, not a tenant-editable status key, so it does not fall into the hardcoded-key trap. `transition_roles` stays available for any future tenant-forked graph.)*
- **Given** these are new permissions, **then** a **grant sweep** re-runs `tenant_admin_grant` for **existing** tenants — the feature must not silently 403 for tenants provisioned earlier (Definition-of-Done #4).

---

## Slice 3 — Generic grill engine

### AC-BI-20 — `GrillDefinition` is generic (D21-A) [BE][T]
- **Given** a `GrillDefinition`, **then** it binds *source artifact type + target template key + skill + agent + completion rule* — Idea→BR is **instance one**, and adding BR→FR later requires **a new definition row + template, not new engine code**.
- **Given** the definition, **then** the target template's field list is **injected into the prompt at runtime** (AC-BI-08), so ONE `grill-me-business` skill serves every target.
- **Given** the engine, **then** it mirrors Phase A's `IntakeDefinition` (D18) one layer up — same registry-driven shape.

### AC-BI-21 — transcript store [BE][T]
- **Given** a grill session, **then** `ai_conversations` binds `(tenant_id, source_type, source_ids[], target_type, target_id)` and `ai_messages` records role, content, timestamp.
- **Given** a completed turn, **then** the conversation stamps the `(prompt_version, template_version)` it ran under, so a poor BR is attributable to a specific prompt version.
- **Given** the user closes the tab mid-grill and returns later, **then** the draft BR **and** the full transcript are intact (the D8 durable-draft property, one level up).

### AC-BI-22 — turn contract: prose + coverage [BE][FE][T]
- **Given** a grill turn, **then** the response is `{reply_text, covered_fields[]}` — prose reply plus a cheap coverage map.
- **Given** coverage, **then** the UI shows **"N of M captured · missing: …"** derived from the target template's field list.
- **Given** every field is covered, **then** the grill **offers** to generate; it **never** generates on its own (D23-A / D-CONFIRM).
- **Given** the human hits **Generate** at any time — including with coverage incomplete — **then** it is honoured. The human ends the conversation, never the model.

### AC-BI-23 — turn transport is synchronous [BE][FE]
- **Given** a grill turn, **then** it is a **synchronous request/response** — no `background_jobs` row per turn (chat turns must not flood the Jobs activity drawer, which is for batch work).
- **Given** a turn in flight, **then** the UI shows a thinking indicator; a provider timeout or error surfaces a clean, retryable message and **leaves the transcript consistent** (no half-written turn).

### AC-BI-24 — Generate = separate extraction call [BE][T]
- **Given** **Generate**, **then** a **second, distinct** call runs with the **whole transcript + source ideas** as input and provider-native **structured output** shaped by the target template's fields.
- **Given** extraction output, **then** it is validated by **`form_engine`** before persistence.
- **Given** extraction sees the full conversation at once, **then** a later answer correctly **revises** an earlier one (this is why extraction is not incremental per-turn).

### AC-BI-25 — validation failure → one retry, then human [BE][T]
- **Given** extraction output that fails `form_engine` validation, **then** exactly **one** retry runs with the validation errors fed back.
- **Given** the retry also fails, **then** the failure is surfaced to the human with the errors — **never** an infinite repair loop, never a silent discard.
- **Given** both attempts, **then** each is a `validate` / `retry` span on the trace.

### AC-BI-26 — partial emit is success, invention is not [BE][T]
- **Given** fields the transcript cannot ground, **then** they are left **blank** for the human to fill — never invented.
- **Given** a partial extraction, **then** it is persisted and the BR remains usable (same "clean empty result over fabrication" rule the spine sets for reuse-analysis).
- **Given** a stub fixture returning an extraction missing `success_metric`, **then** a test asserts the field is blank, the BR saved, and no placeholder text fabricated.

### AC-BI-27 — extraction never promotes (D22-A) [BE][T]
- **Given** a successful extraction, **then** it writes `answers_json` on a BR that **remains `draft`**.
- **Given** any non-human path (AI, import, timer, API), **then** the transition to `ready` is **refused by the status engine** — asserted by test.
- **Given** the agent's tool definitions, **then** **none** has a side effect; a test asserts the agent cannot reach a write path.

### AC-BI-28 — the business `grill-me` skill is authored [BE][FE]
- **Given** the seeded skill `grill-me-business`, **then** it is a **business-register** rewrite of Claude's developer-flavoured `grill-me` — the *"explore the codebase instead"* instruction is replaced with *"ground answers in the linked ideas and prior BRs before asking"*, since a shared-service agent has **no repository access**.
- **Given** the skill body, **then** it additionally carries what the original **lacks**: the target field list (injected), a question budget, a grounding rule, and the emit contract.
- **Given** a seeded platform-tier skill, **then** re-seeding is **insert-if-missing** — an operator's edits survive a reseed.

### AC-BI-29 — Grill tab UI [FE][T]
- **Given** the Grill tab, **then** it renders message list + input + coverage indicator + **Generate** button, inside the BR `ResourceForm` — inheriting breadcrumb, record-nav and permissions from the shell.
- **Given** a mobile viewport (**375px**) and a desktop viewport (**1280px+**), **then** the tab is usable at both with no horizontal scroll and no clipped controls (single column stacks; the tab strip scrolls).
- **Given** the foolproof-UI mandate, **then** the surface carries **no instructional/how-to copy** — labels, a one-line description and short empty-state status only.

---

## Slice 4 — Idea → BR

### AC-BI-30 — clustering: trigram retrieval + LLM grouping (D10-A) [BE][T]
- **Given** the ideas board, **when** clusters are requested, **then** `pg_trgm` first narrows to candidate neighbours (reusing the Phase A dedup index) and **one** LLM call then groups and **names** each cluster.
- **Given** semantically-related ideas with no lexical overlap ("checkout is slow" / "payment page takes forever"), **then** they can land in the same cluster — the reason pure trigram was insufficient.
- **Given** clustering, **then** it introduces **no pgvector and no embedding pipeline**.
- **Given** the LLM call fails, **then** trigram candidates are still returned ungrouped — clustering **degrades**, never blocks the board.

### AC-BI-31 — clustering only suggests [FE][T]
- **Given** a suggested cluster, **then** the selection is **fully editable** before promotion — deselect, add another idea, promote a single idea alone.
- **Given** D16, **then** no cluster is ever promoted automatically.

### AC-BI-32 — promote creates the draft BR anchor [BE][FE][T]
- **Given** a selection of ideas and **Promote to BR**, **then** in one transaction a **`draft` BR is created**, the ideas are linked, and the user lands on its **Grill tab**.
- **Given** the BR row exists from turn zero, **then** the grill has a durable anchor and an interrupted session is resumable (AC-BI-21).
- **Given** promotion, **then** the created BR stamps the active template version (AC-BI-16).

### AC-BI-33 — ideas added mid-session [BE][FE]
- **Given** an idea linked to the BR **after** grilling started, **then** the **next turn** re-seeds source context to include it — the conversation is **not** restarted.

### AC-BI-34 — the promote gate (Gate 0) [BE][FE][T]
- **Given** a `draft` BR with `answers_json` complete per the stamped template, **when** a user holding `business_requirements.promote` fires it, **then** it transitions `draft → ready`.
- **Given** required fields are missing, **then** promotion is **refused** with a "missing: …" message — and the same check is enforced **server-side**, not only in the UI.
- **Given** promotion, **then** it is an explicit human action through the status engine (B-D4) with the actor recorded, gated by `ideation.business_requirements.promote` on the `br-tr-promote` edge (see AC-BI-19's revised note) — no AI/import/timer path can reach `ready`.

### AC-BI-35 — traceability [BE][T]
- **Given** a BR, **then** a lineage query resolves **BR → linked ideas → submitter contacts**, so every requirement traces back to the raw WhatsApp ideas that produced it.
- **Given** the BR detail **Ideas** tab, **then** it lists the linked ideas with a link to each.

### AC-BI-36 — E2E: idea to promoted BR, real clicks [E2E]
- **Given** seeded ideas and the **stub** LLM adapter, **when** the spec drives the real UI — open ideas board → select a cluster → **Promote to BR** → answer grill turns → watch coverage reach complete → **Generate** → review Details → **Promote** — **then** a `ready` BR exists with populated `answers_json` and linked ideas.
- **Given** the spec, **then** it navigates **only by clicking** (never by typing a URL) and creates **timestamped** entity names (never a fixed literal, per the E2E-residue rule).
- **Given** the responsive mandate, **then** the journey is verified at **375px and 1280px**.

### AC-BI-37 — live verification (Definition-of-Done gate) [E2E]
- **Given** a **real** API key configured through the UI, **then** the full journey is driven manually against a **real model** on a freshly rebuilt frontend (`rm -rf .next && npm run build`) with correctly-owned ports (3001 / 8001), and the resulting BR is judged **usable by a human**.
- **Given** this gate, **then** the stub adapter must **never** be what a "verify from the user's perspective" pass exercises (Definition-of-Done #1 — a mock reaching QA is the failure this project has repeatedly paid for).

---

## Out of scope (Phase B-ii and later)

| Deferred | Why |
|---|---|
| FR entity, FR template, issue-payload serializer | The FR field set is largely determined by what a **code-aware** grill produces; specifying it before that conversation risks a template we rewrite. |
| BR → FR grill | Same engine, new `GrillDefinition` + template — cheap once B-i lands. |
| `reuse_analysis` | Needs a repository checkout → Mac Mini + the §5.4 bridge. |
| Mac Mini bridge (`AgentRunner`, poll, callbacks) | Not required by anything in this document (D20-A). |
| Agent **tools** (search ideas, read prior BRs mid-grill) | Would make the span tree genuinely deep — the point at which the flat step list becomes a tree renderer. |
| Per-tenant LLM cost caps / billing | Platform-key fallback means cross-tenant cost; acceptable while the ideation tenant is FoundryX-internal. Backlog, class of BL-036. |
| Semantic clustering via embeddings + pgvector | Trigram + LLM grouping is sufficient at current idea volume; upgrade path is one function. |
