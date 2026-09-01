# PLAN - Ideation Phase B-i: Idea → Business Requirement (+ core AI subsystem)

**Status:** Planning - grilled + locked 2026-07-21. UAC written first (`ideation-phase-b-idea-to-br-acceptance-criteria.md`); no code yet.
**Classification:** **Core** (`app/ai/`) + **MODULE** (`modules/ideation/`, schema `app_ideation`). The AI subsystem is core because it is horizontal; the BR entity is ideation's.
**Repos in scope:** `foundryx-shared-service` only. No sorento, no n8n, no GitHub, **no Mac Mini**.
**Keys back to:** program spine `PLAN-ideation-to-delivery-program.md` (amended same day - **D20-A**, D10-A, D21-A, D22-A, D23-A).
**Supersedes:** the B1-B6 slice map of `PLAN-ideation-phase-b-structure.md`.
**Depends:** Phase A (Products, Ideas, `pg_trgm` dedup, embed host, roles) - all shipped and merged.

---

## 1. Goal

Turn triaged **Ideas** into **Business Requirements** through an AI **grill** that runs in shared-service, and build the reusable **core AI subsystem** that powers it.

```
Ideas (Phase A) ──cluster (trgm + LLM)──▶ select ──Promote──▶ draft BR
                                                                  │
                                              grill (shared-service LLM)
                                                  turns: {reply_text, covered_fields[]}
                                                                  │
                                            Generate ──▶ extract ──▶ form_engine validate
                                                                  │
                                                          answers_json (BR stays draft)
                                                                  │
                                            human + business_requirements.promote
                                                                  ▼
                                                              BR = ready
```

**FR is deliberately not in this plan.** Its template is shaped by what a *code-aware* grill produces, and that engine (Mac Mini) is undesigned. Phase B-ii owns it.

---

## 2. The decision that reframes everything: D20-A

The original **D20** said *shared-service runs NO LLM*. Under it, every AI turn - including grilling - was a job relayed to Claude Code on the Mac Mini, so **Phase B could not start until the §5.4 bridge existed**.

That has been amended. **The cut is code-awareness, not location:**

| Work | Where | Why |
|---|---|---|
| Grilling - asking, sharpening, extracting, emitting structured | **shared-service LLM** | Pure conversational reasoning. No checkout needed. |
| Idea clustering + labelling | **shared-service LLM** | Text only. |
| `reuse_analysis` - "we already have `form_engine`, extend it" | **Mac Mini** | Must read real code + Outline. |
| FR → PR build | **Mac Mini** | Obviously. |

Consequence: **the bridge is not a dependency of Idea→BR**, and the §8 risk *"an offline Mac Mini degrades a live human session"* does not apply to this plan at all. Grilling BR→FR later is *also* shared-service; only the reuse-analysis augmentation pass needs the runner.

---

## 3. What already exists (reuse, do not rebuild) - cited

| Need | Reuse | Where |
|------|-------|-------|
| Per-tenant external-service credentials, Fernet-encrypted, write-only, blank-to-keep | `connections` + `app/secrets.py` - and **`type='llm'` is already reserved** in the provider protocol, never implemented | `app/models/connection.py`, `app/integrations/base.py` |
| Provider contract + registry + settings UI | `IntegrationProvider` (`fields()`/`test()`), `/settings/integrations` on the Resource shell | `app/integrations/`, `components/platform/` |
| Extending the provider protocol for a richer verb set | `PaymentProvider(IntegrationProvider, Protocol)` - the exact precedent for `LLMProvider` | `app/integrations/base.py` |
| Structured artifact templates, versioned, with a validation gate | `form_engine` block doc + `validate_form_doc` | `app/form_engine/` |
| Immutable versions + movable `active` label | `ai_prompt_versions` / `ai_prompt_labels` shape (port) | sorento `app/models/ai_prompt.py` |
| Prompt/text composition **without eval** | `template_engine` `render_tokens` - substitution only, anti-SSTI | `app/template_engine/merge.py` |
| Entity lifecycle + role-gated transitions | `status_engine` `register_status_entity`, `transition_roles` edge auth | `app/status_engine/` |
| Definition-registry pattern for a generic engine | Phase A's `IntakeDefinition` (D18) - the grill is this one layer up | `modules/ideation/services/intake_definitions.py` |
| Dev-stub adapter so tests need no vendor account | omnichannel `_is_dev` (stubs every Graph call when unconfigured) | `modules/omnichannel/adapters.py` |
| Lexical similarity for candidates | `pg_trgm`, already indexed for Phase A dedup | `modules/ideation/services/dedup.py` |
| Retention sweep wired into the beat task, failure-isolated | `scheduler.prune_runs` | `app/workflow_engine/scheduler.py` |
| List/detail surfaces | config-driven Resource shell (`ResourceList` / `ResourceForm`) | `components/platform/` |

**Nothing in the credential, settings-UI, validation, or lifecycle layers is new work.** The genuinely new code is: three LLM adapters, the agent/skill registries, traces, and the grill engine.

---

## 4. Decision log

| # | Decision | Why |
|---|----------|-----|
| **Bi-D1** | LLM credentials are a **core `connections` row, `type='llm'`** - *not* a new table with its own `api_key_ciphertext`. | The type is already reserved in the protocol. Reusing it inherits Fernet, write-only, blank-to-keep, `test()`, ACTIVE/UNVERIFIED/ERROR and the entire settings UI. A bespoke table re-implements all of it. |
| **Bi-D2** | The **agent/persona layer lives in core `app/ai/`**, not in `modules/ideation/`. | Four existing engines will want agents (workflow action, form auto-fill, omnichannel reply-draft). Moving a table out of a module schema later is a migration nobody wants. |
| **Bi-D3** | **Credential ≠ persona.** Connection carries the key; agent carries model + temperature + which skill it runs. | Lets one key back many agents, and "add OpenAI support" stay a single provider file. |
| **Bi-D4** | Providers: **anthropic · openai · gemini** behind one `LLMProvider` protocol; adapters own all structured-output differences. | Owner requirement. Normalized `LLMResult.usage` keeps cost tracking provider-agnostic. |
| **Bi-D5** | **Skill = versioned first-class artifact** (name + description + body), immutable versions + movable `active` label. | Prompt quality *is* the feature; you will iterate constantly and need rollback + attribution ("this bad BR came from prompt v7"). Same mechanism B-D2 already chose for templates. |
| **Bi-D6** | Prompt composition via **`render_tokens` substitution only**. | Skill bodies become editable config; substitution-only is the standing anti-SSTI rule. |
| **Bi-D7** | **Grill is ONE generic engine** (`GrillDefinition`: source + target template + skill + agent + completion rule); target field list injected at runtime. | One `grill-me-business` skill serves BR *and* later FR. Mirrors `IntakeDefinition` (D18). |
| **Bi-D8** | **Idea→BR is a bounded clarifying conversation**, not a one-shot draft. | Ideas are thin (problem/solution/impact/department); `success_metric`, `stakeholders`, `constraints` are simply not in them. A one-shot draft must blank or invent them. |
| **Bi-D9** | Turn returns **`{reply_text, covered_fields[]}`**; **Generate** runs a **separate extraction** over the whole transcript. | Prose turns stay cheap and natural; coverage drives a visible endpoint; whole-transcript extraction lets a later answer revise an earlier one, which incremental filling handles badly. |
| **Bi-D10** | Turn transport is **synchronous**, *not* `background_jobs`. | Chat turns are frequent and small; routing each through the job table would flood the **Jobs activity drawer**, which exists for batch work. The job table is the wrong tool. |
| **Bi-D11** | **The model never writes** (D22-A). Forced response schema → our code validates → our code persists. No tools with side effects. | Makes never-auto-promote an architectural invariant instead of a prompt instruction. |
| **Bi-D12** | **Coverage-driven suggestion, human-driven trigger** (D23-A). | Claude's `grill-me` has no stop rule; we have a target schema and can do better. Matches Phase A `collecting → review → complete` + D-CONFIRM. |
| **Bi-D13** | Extraction failure → **one** retry with errors fed back, then surface to human. **Partial emit is success; invention is not.** | Bounded repair; a BR with 4 of 6 real fields beats one with 2 fabricated metrics. Mirrors the spine's clean-empty-result-over-fabrication rule. |
| **Bi-D14** | Clustering = **`pg_trgm` retrieval + LLM grouping/labelling**; no pgvector. | Trigram alone misses semantic siblings; embeddings are real infra. Cheap retrieval feeding an expensive model - the same trick `ai-quote-panel` uses with cached candidate ids. |
| **Bi-D15** | **Promote creates the draft BR first**; grill fills it. | Resolves the chicken-and-egg (chat must attach to something) and makes sessions resumable - Phase A's D8 durable-draft property one level up. |
| **Bi-D16** | Grill is a **tab on the BR `ResourceForm`**, not a bespoke route. | Conforms to the design language; inherits nav, permissions, dirty-guard. Single column ⇒ trivially responsive. |
| **Bi-D17** | Observability = **full `ai_traces` + `ai_spans`** (OTel GenAI naming), replacing a separate usage log. UI renders a **flat step list** until real depth exists. | Owner call: this platform will grow a genuine AI assistant with tool loops. Core foundation, painful to migrate later - so build the model right, defer only the tree renderer. |
| **Bi-D18** | Key resolution **tenant → platform → error**, mirroring SMTP/storage. | Zero-config for the internal tenant; BYO-key ready without rework. Platform-key usage is cross-tenant cost - capped later (BL-036 class). |
| **Bi-D19** | Testing: **stub adapter** for the routine suite + E2E; **opt-in live tests** (`-m live`) + a **live manual verification gate**. | Deterministic, free, offline CI - while guaranteeing the stub is never what QA actually exercises (Definition-of-Done #1). |
| **Bi-D21** | **`type='llm'` is carved out of `uq_connection_tenant_type`** (as `payment`/`erp` already are), so a tenant may hold several active LLM connections. Agents resolve **by `connection_id`**, not by type. *(Added during the S1 audit - Bi-D3/Bi-D4 assumed multiple providers could coexist; the index forbade it.)* | Three supported providers are pointless if only one can be active. Per-provider uniqueness (`uq_connection_tenant_provider`) still holds. Storage/email invariants untouched. |
| **Bi-D20** | Permissions: `ai_agents.read/manage` + **separate** `ai_traces.read` (core); `business_requirements.read/manage` + **separate** `.promote` (module). Grant sweep for existing tenants. | Traces hold raw prompts/completions - debugging access ≠ config access. A single `.manage` would collapse the Triager/Maintainer distinction D16 requires. |

---

## 5. Entities

### Core - `app/ai/` (schema `public`)

- **`ai_agents`** - `id`, `tenant_id`, `name`, `connection_id` → `connections`, `model`, `temperature`, `is_enabled`, audit. **No credential of its own.**
- **`ai_skills`** - `id`, `tenant_id` (NULL = platform tier), `key`, `name`, `description`, `active_version_id`.
- **`ai_skill_versions`** - immutable: `skill_id`, `version` (auto-inc per skill), `body`, `created_by`, `created_at`. Never mutated; rollback = repoint `active_version_id`.
- **`ai_conversations`** - `tenant_id`, `source_type`, `source_ids[]`, `target_type`, `target_id`, `grill_definition_key`, `prompt_version`, `template_version`, timestamps.
- **`ai_messages`** - `conversation_id`, `role`, `content`, `covered_fields_json`, `created_at`.
- **`ai_traces`** - one per run: `conversation_id`, `agent_id`, `prompt_version`, `provider`, `model`, `tokens_in/out`, `latency_ms`, `status`, `flagged`, `span_count`.
- **`ai_spans`** - `trace_id`, `parent_id` (nullable - present for the future tree), `dotted_order`, `span_kind` (`llm_call|validate|retry|tool:*`), `input_json`, `output_json` (**size-capped**), `tokens_in/out`, `latency_ms`, `status`, `error`.

All datetimes `UTCDateTime`; all JSON `JSON(none_as_null=True)`; datetime-bearing schemas inherit `ApiModel`.

### Module - `modules/ideation/` (schema `app_ideation`)

- **`business_requirements`** - `id`, `tenant_id`, `product_id`, `status_id`, `template_key`, `template_version`, `answers_json`, `created_by`, `updated_by`, timestamps. Cross-schema refs to core are **plain indexed columns, not FKs** (BL-030).
- **`idea_business_requirements`** - many-many join (D4).
- **`ideation_artifact_templates` / `_versions`** - versioned `form_engine` docs keyed by `template_key`; BR stamps its version.

**Status registration:** `ideation_business_requirement` - unscoped, tenant-owned; `draft → grilling → ready → in-FR → delivered → archived`; the `draft → ready` edge carries `transition_roles` for the promote gate.

---

## 6. Slices

Each slice = **P1 frontend-first (mock service)** → **P2 backend, test-first, swap the mock** → **P3 `/code-review`**. Per house methodology; the mock is debt that must die inside its own slice.

### S1 - Core AI foundation (AC-BI-01..14)
- **P1:** agents + skills Resource surfaces against a mock service; model `SearchSelect`; trace detail as a flat step list.
- **P2 (test-first):** `LLMProvider` protocol; `anthropic`/`openai`/`gemini` adapters; `models()` live + static fallback; `ai_*` migrations (core Alembic, **revision id ≤ 32 chars**, `import app.models.utc_datetime` in autogen output); agent + skill + version registries; trace/span writer + retention sweep in the beat task; **stub adapter** (`_is_dev` pattern) + fixture hooks; permissions CSV + grant sweep.
- **P3:** review. Also the opt-in `-m live` suite across all three providers.

### S2 - BR entity (AC-BI-15..19)
- **P1:** BR `ResourceList` + detail form with tabs, Details rendering a mock `answers_json`.
- **P2 (test-first):** module migration (BR + join); seed the BR `form_engine` template; `register_status_entity`; CRUD + list_query registration; stamped-version validation; module permissions CSV incl. `.promote`; edge-role wiring.
- **P3:** review.

### S3 - Grill engine (AC-BI-20..29)
- **P1:** Grill tab - message list, input, coverage indicator, Generate - against a mock grill service; both viewports.
- **P2 (test-first):** `GrillDefinition` registry; conversation/message store; turn endpoint (sync) returning `{reply_text, covered_fields[]}`; Generate → extraction → `form_engine` validate → one retry → persist; partial-emit rules; **author the `grill-me-business` skill** (seeded platform-tier, insert-if-missing); trace spans per step.
- **P3:** review.

### S4 - Idea → BR (AC-BI-30..37)
- **P1:** cluster suggestions on the ideas board (mock), editable selection, Promote action.
- **P2 (test-first):** trigram candidates + LLM grouping with graceful degradation; promote transaction (create draft BR + link ideas + land on Grill tab); mid-session re-seed; promote gate w/ server-side completeness check; lineage query.
- **P3:** review, E2E spec, **live verification gate**, PR.

---

## 7. Contracts this plan owns

- **`LLMProvider.complete(...) -> LLMResult`** - `text | structured` + normalized `usage`. Every future AI consumer in the platform calls this, not a vendor SDK.
- **`GrillDefinition`** - *source + target template + skill + agent + completion rule.* Phase B-ii adds BR→FR as a **row**, not as code.
- **Turn contract** - `{reply_text, covered_fields[]}`; sync; never a job row.
- **Extraction contract** - whole transcript in, template-shaped structured output out, `form_engine`-validated, one retry, partial-emit-permitted, **never promotes**.
- **Trace/span shape** - OTel GenAI field naming; `span_kind` is the seam where real tools land later with no migration.

---

## 8. Risks

- **Prompt quality is the product, and it is not testable by CI.** The stub proves plumbing; only the live gate (AC-BI-37) proves the grill produces a usable BR. Guard: live verification is a **required** DoD step, and prompt versions are attributable via traces so regressions are diagnosable.
- **Platform-key cost is cross-tenant.** Fine internally, wrong commercially. Guard: usage is recorded per trace from day one, so a cap/billing hook has data to work from. Backlog item, not a blocker.
- **Trace payload bloat.** Prompts + completions stored alongside the transcript duplicates content. Guard: size caps with truncation marked, plus TTL sweep (shorter for `ok`).
- **A grill that never converges.** A model can ask forever. Guard: question budget in the skill, coverage indicator always visible, and **Generate is always enabled** - the human can end it at any point.
- **Over-built observability.** Full spans for what is currently a 2-3 step sequence is a deliberate bet on a future assistant. Guard: build the write path and a **flat** renderer; the tree renderer waits for real depth.
- **Provider drift.** Three vendors, three structured-output mechanisms, moving model catalogs. Guard: differences confined to adapters; pinned model ids fail loudly rather than substituting.

---

## 9. Explicit non-goals

FR entity · BR→FR grill · `reuse_analysis` · Mac Mini bridge / `AgentRunner` · agent tools with side effects · embeddings/pgvector · per-tenant cost caps · streaming token output (the turn contract is unchanged when WS is added later).
