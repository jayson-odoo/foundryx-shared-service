# PLAN - Ideation → Delivery Pipeline (program master)

**Status:** Planning (grilled + aligned 2026-07-18; UAC-first, no code yet).
**Classification:** MODULE / Service on the Foundryx shared-service platform (tenant = Foundryx-internal for now).
**Repos in scope:** `foundryx-shared-service` (primary), `sorento_crm` (FE iframe host + `ideate` intent), `sorento_crm_n8n` (routing).
**This file is the spine.** Per-repo UAC + PLAN files key back to the **Cross-Repo Contracts** section here. If a contract changes, change it *here first*, then the per-repo plans.

---

## 1. Vision

A "Canny + delivery" Service: raw ideas land via WhatsApp (text/voice), get structured into
Business Requirements, grilled into Functional Requirements, then **autonomously built on the
Mac Mini** (TDD + Playwright) and **human-gated** before merge/deploy. One idea is traceable end
to end to the shipped code. Every human touchpoint happens in **one device-free surface**
(shared-service, embedded seamlessly into each product's own domain via iframe SSO). GitHub is
machine-only plumbing.

```
Ideas ──▶ BR (AI draft, human refine)
   BR ──▶ 🔥 heavy interactive grill (shared-service chat + Outline reuse-analysis) ──▶ FR (= UAC + plan)
   FR ──▶ approved (gate 1)
       ──▶ Mac Mini daemon builds:
              Phase 1 FE prototype ──▶ Cloudflare Tunnel preview (local DB) ──▶ eyeball (gate 1.5)
              Phase 2 TDD backend + tests ──▶ Phase 3 code review ──▶ PR (unattended)
                 ──▶ eyeball PR (gate 2) ──▶ merge ──▶ deploy ──▶ Delivered
```

## 2. Locked decisions (from the grill)

| # | Decision |
|---|----------|
| D1 | Ideation is a **Service on foundryx-shared-service**; tenant = Foundryx-internal. |
| D2 | Spine (Idea→BR→FR) lives in shared-service; delivery (build→PR→merge) runs on the Mac Mini; GitHub = code/PR/preview only. |
| D3 | **Product** entity, `kind: goods\|software`; software products carry polymorphic adapter objects (`GitHubAdapter`, `AgentRunnerAdapter`, `DeployAdapter`, embed connection). One product per idea. NOT sorento's physical goods master. |
| D4 | Cardinality: Idea↔BR **many-many**, BR↔FR **many-many**, FR→GitHub issue **1:1** (the FR is the vertical slice). |
| D5 | Fixed, versioned artifact **templates** (built on shared-service `template_engine`/`form_engine`). Authoring = **AI drafts structured → human refines → explicit promote gate**. Never auto-promote. |
| D6 | **Intake = same CRM WhatsApp number** (one workspace, one `respond_contacts` row, one `session_vars`). Ideation = a new **`ideate` intent** in the CRM brain; deterministic (no AI channel-routing of the *product* - product is derived from the workspace↔Application binding). |
| D7 | **Intake logic lives in an MCP tool (`create_idea`) on shared-service**, not in sorento/n8n. The tool validates required fields, computes captured/missing, persists a **draft Idea on turn 1**, decides collecting/complete, mints the link. sorento's brain only detects `domain=ideate` → calls the tool → carries `draft_id` in `session_vars.ideation` → relays the reply. |
| D8 | **State model:** the **draft Idea in shared-service is the durable system-of-record**; `session_vars.ideation` carries only the **pointer** (`draft_id`). Resilient to interrupts (a CRM question mid-collection leaves the draft open; next `ideate` turn resumes by `draft_id`). |
| D9 | Voice transcribed at **n8n**; the raw text + audio attachment reach the tool. |
| D10 | Duplicates: high match → **upvote existing**, via **`pg_trgm` text-similarity**. *(Originally justified by "no LLM at shared-service"; that constraint was lifted by D20-A and the decision was RE-TAKEN on its own merits 2026-07-21 - see D10-A. Phase A dedup is unchanged.)* |
| **D10-A** | **Idea clustering = `pg_trgm` retrieval + LLM grouping/labelling** (2026-07-21). Trigram narrows to candidate neighbours (cheap, indexed, already shipped for Phase A dedup); ONE LLM call then groups and *names* the cluster ("these 4 are all approval-flow latency"). Purely lexical matching missed semantic siblings ("checkout is slow" vs "payment page takes forever"). **No pgvector, no embedding pipeline** - retrieval stays trigram; upgrading to embeddings later changes one function. Clustering only ever **suggests**; the human edits the selection and decides promotion (D16). |
| D11 | ~~grill brain = Claude Code~~ **AMENDED 2026-07-21 by D20-A.** **Grilling is a shared-service capability** run by a shared-service LLM agent - at Idea→BR *and* at BR→FR. It is conversational reasoning and needs no checkout. What still runs on the Mac Mini is **`reuse_analysis`** (must read code + Outline), applied as a **separate augmentation pass** over an already-grilled FR - not a different grill. So BR→FR grilling no longer requires the Mac Mini online; only reuse-analysis does. |
| **D21-A** | **Grill is ONE generic engine, not a per-artifact feature** (2026-07-21). A `GrillDefinition` binds *source artifact(s) + target template + skill + agent + completion rule*; Idea→BR is instance one, BR→FR is instance two. Mirrors Phase A's `IntakeDefinition` (D18) one layer up. The target template's field list is **injected into the prompt at runtime** via `template_engine`'s substitution-only `render_tokens` (anti-SSTI), so ONE `grill-me-business` skill serves every target. |
| **D22-A** | **The model never writes.** Structured output is a forced response schema; **our** code validates it against `form_engine` and writes `answers_json`. The agent has **no tools with side effects**. This is what makes **never-auto-promote** (D5/D12) an enforced invariant rather than a prompt instruction. Promotion is always an explicit, role-gated status transition. |
| **D23-A** | **Grill termination = coverage-driven suggestion, human-driven trigger.** Unlike Claude's `grill-me` (which has no stop rule), our grill has a target schema, so each turn returns `{reply_text, covered_fields[]}` and the UI shows "N of M captured · missing: …". When coverage completes the grill *offers* to generate; the human always fires it. Same machine as Phase A's `create_idea` `collecting → review → complete` loop + **D-CONFIRM** (never auto-completes), one level up. |
| D12 | Three human gates: **FR-approved → prototype-eyeball → PR-eyeball**. Milestone-only status-back. |
| D13 | Delivery runner = **any always-on device** (this laptop for experimentation now; a Mac Mini later - device-agnostic, zero plan change). **Outbound-polling** daemon (no inbound/NAT), headless Claude Code (Agent SDK), **concurrency 2**, git/deploy creds **local-only**, daemon holds only a shared-service API key issued by an `AgentRunner` integration. Runner is needed ONLY for Phase B (grill) + Phase C (build); **Phase A has no runner dependency.** |
| D14 | Preview = **Cloudflare Tunnel to the Mac Mini session, against the local DB** (prod-data copy). |
| D15 | Build-time agent clarifications surface **back into the FR thread in shared-service** (device-free); the answer re-triggers the session. **shared-service is the ONLY human surface; GitHub is machine-only.** |
| D16 | Roles: **Submitter / Triager / Maintainer**. Ideas AI-suggests clusters, human decides BR promotion. Idea has its own lifecycle. |
| D17 | **Embed:** generalize the omnichannel embed framework (assertion→token, `parentOrigin`/`allowedOrigins`, `frame-policy`). Product linkage = embed connection (`allowedOrigins` + signing + `product_domain_base`). Sorento gets an "Ideas" menu → iframe of the full ideation UI (board + detail + grilling chat), seamless SSO, product-domain links. |
| D18 | **Intake is a generic Conversational-Intake engine**: `create_idea` is one *Intake Definition* (form_engine schema + completion rule + on-complete sink); future "form over WhatsApp" flows are new definitions, no new conversation code. |
| D19 | **Sequencing choice X:** build the `ideate` intent into the *current* sorento brain now (fast, no production cutover). |
| D20 | ~~**shared-service runs NO LLM - it is data + UI + relay only.**~~ **AMENDED 2026-07-21 → see D20-A.** Original text: all AI compute lives elsewhere (sorento's brain for intake field-extraction; Claude Code on the Mac Mini for grill BR→FR + build FR→PR); no assistant port, no LLM key, no embedding pipeline in shared-service. Retained from the original: **the "Phase 0 assistant port" stays cancelled** - what replaces it is narrower and differently shaped (D20-A). |
| **D20-A** | **AMENDS D20 (2026-07-21). The cut is CODE-AWARENESS, not location.** shared-service **may** call an LLM for **conversational + text-only** work (grilling toward a template, drafting artifact fields, clustering/labelling ideas). Work that requires **reading the repository** - `reuse_analysis`, and the FR→PR build - stays on **Claude Code on the Mac Mini** via the §5.4 bridge, because an API-key LLM has no checkout to read. Consequences: shared-service now holds an **LLM API key** (core `connections`, `type='llm'`, Fernet-encrypted) and a core **`app/ai/`** subsystem (agents · versioned skills/prompts · transcript store · traces). The Mac Mini bridge is **NOT required for Idea→BR** and is deferred out of that flow entirely. |
| D21 | **respond.io in shared-service = its own cron-synced contact copies** (mirrors sorento's sync) pulled from the respond.io API. On `create_idea`, shared-service **matches** the incoming contact (by phone) to its own copy - it does NOT blindly trust a ref handed over by sorento. Shared-service keeps a separate copy of the contact, kept fresh by cron. |
| D-CONFIRM | **Capture always ends on an EXPLICIT user confirmation - never auto-completes.** `create_idea` gains a **`review`** status: once all required fields are captured, it echoes the captured summary and asks the user to confirm or revise; the draft moves `draft → captured` (and mints the link) **only** when `confirm=true`. Revision turns carry `fields`/`remove` (add/change/clear answers) that merge into the draft and re-enter `review`; the loop repeats until explicit confirm. shared-service stays deterministic (echo is templated, no LLM); the sorento brain does the NLU (confirm-vs-revise, field ops) and passes it structured. Applies even when the very first turn is fully complete - still `review` first. See §5.1. |

## 3. Entities (shared-service)

- **Product** - `id`, `kind (goods\|software)`, `name`, `slug`, `product_domain_base`, adapters[] (polymorphic).
- **Idea** - `id`, `product_id`, `status` (`draft → captured → triaged → linked → building → delivered → closed`; + `duplicate`, `rejected`), `problem`, `raw_text`, `source`, `submitter_contact_id`, `attachments[]`, `upvotes`, `embedding`.
- **BusinessRequirement** - `id`, `product_id`, `status` (`draft → grilling → ready → in-FR → delivered → archived`), template fields (`problem_statement`, `business_goal`, `stakeholders`, `success_metric`, `scope`, `constraints`), `linked_idea_ids[]`.
- **FunctionalRequirement** - `id`, `product_id`, `status` (`draft → grilling → approved → building → prototype-review → developing → pr-review → merged → deployed → done`; + `blocked/awaiting-clarification`, `bounced`), template fields (`acceptance_criteria[]` G/W/T, `technical_approach`, `reuse_analysis`, `slice_scope`, `grill_notes`, `lavish_artifact`), `linked_br_ids[]`, `github_issue_ref`, `pr_ref`.
- **IntakeDefinition** - `key`, `target_schema` (form_engine), `completion_rule`, `on_complete_sink`, `agent_role`.
- **AgentRunner** - `id`, `name`, `api_key_hash`, `served_product_ids[]`, `concurrency_cap`, `status`, `last_seen`.
- Reuse: omnichannel conversation store (contacts/threads), `template_engine`/`form_engine`, `status_engine`, embed framework.

## 4. Phasing

| Phase | Delivers | Repos | Depends |
|-------|----------|-------|---------|
| **A - Capture** | Generic Conversational-Intake engine + `create_idea` HTTP endpoint (no LLM) · Product + Idea entities · **respond.io cron contact-sync + matching** (D21) · Canny triage board · dedup (`pg_trgm`) · idea lifecycle · notifications · embeddable idea board · sorento `ideate` intent + iframe host · n8n `ideate` routing | shared-service · sorento · n8n | - |
| **B - Structure** | **RE-CUT 2026-07-21 under D20-A.** Now split in two: **B-i (Idea→BR)** = core `app/ai/` subsystem (LLM connection · agents · versioned skills · traces) + generic grill engine + BR entity + promote gate - **no Mac Mini, no bridge**; **B-ii (BR→FR)** = FR entity + issue-payload serializer + the same grill retargeted at the FR template, then reuse-analysis augmentation (**that pass alone** needs the bridge) + Gate 1. | shared-service (B-i) · + Mac Mini (B-ii reuse-analysis only) | A |
| **C - Deliver** | `AgentRunner` integration · Mac Mini daemon · **grill+build bridge** · GitHub integration · Cloudflare-Tunnel preview · build loop (3-phase) · clarification bridge · milestone status-back · gates 1.5 + 2 | shared-service · Mac Mini · sorento · GitHub | A |

> **No Phase 0.** The old "assistant port" is cancelled and stays cancelled - what shared-service gained under D20-A is narrower and differently shaped: a core `app/ai/` subsystem (LLM connection · agents · versioned skills · transcript · traces), **not** a port of sorento's assistant.
>
> **Bridge sequencing - REVISED 2026-07-21 (D20-A).** The Mac Mini bridge is **no longer a Phase-B-i dependency**. Grilling runs on shared-service, so Idea→BR ships without any runner. The bridge is needed for **reuse-analysis (B-ii)** and **builds (C)** - still shared infra between them, still worth building once, but it no longer gates the first interactive human surface. This retires the "interactive flow blocked by an offline Mac Mini" risk from §8 for Idea→BR.

## 5. Cross-Repo Contracts (canonical - all per-repo plans MUST match)

### 5.1 `create_idea` - shared-service HTTP endpoint (server-to-server; sorento brain calls per turn)
> **Transport (reconciled §8-R3):** an authenticated **HTTP endpoint** on shared-service, called server-to-server by the sorento brain with an API key - NOT an MCP tool (shared-service has no MCP write server; `sorento_crm_mcp` is read-only). "create_idea" is the endpoint name; the sorento side wraps it behind its own `POST /api/v1/external/ideation/turn`.
- **Input:** `{ product_id, submitter_contact_id, message_text, attachments?, draft_id?, discard_draft_id?, fields?, remove?, confirm? }`
  - `product_id` **derived sorento-side** from its `respond_workspaces.ideation_product_id` binding and passed in (reconciled §8-R2); shared-service validates it exists. Never from the human.
  - `submitter` passed as **phone (E.164)**; shared-service **matches** it to its own cron-synced respond.io contact copy (D21) - it does not trust a sorento row id. Unmatched phone → shared-service creates/enriches its contact copy from the respond.io API.
  - `create_idea` runs **no LLM** (D20): deterministic merge-into-schema + `pg_trgm` dedup + persist + **deterministic echo composition**. All NLU - field-extraction from `message_text`, and on a `review` turn deciding *confirm* vs *revise* vs *new info* - happens in **sorento's brain** and is passed structured (D-CONFIRM):
    - `fields` = `{answer_key: value, ...}` the brain extracted this turn (adds/overwrites captured answers).
    - `remove` = `[answer_key, ...]` the brain resolved from a "remove/clear X" instruction.
    - `confirm` = `true` ONLY when the user **explicitly** confirmed the echoed summary. shared-service never infers confirmation from silence or from `message_text`.
  - `message_text` still passed (raw, for audit + the dedup text).
  - **`attachments[]` (multi-modal capture, DC-9)** - replaces the retired singular `audio_attachment_ref`. Unified media array `[{ source_msg_id, url, type: "image"|"video"|"file"|"audio", filename?, caption? }]`. The **sorento brain** has already resolved these: pulled recent media from the Respond List Messages API, had the human confirm-gate pick which relate (backward lookback), **durably stored** the bytes to its own R2/S3 (Respond CDN URLs expire), and, for images, run a **vision caption**. shared-service persists the pointers only (fetches nothing) on `app_ideation.idea_attachments`, **idempotent on `(idea_id, source_msg_id)`** - the same media re-sent across turns upserts one row. `caption` is display-only (the idea's text already carries it - sorento folds the caption into `message_text`). Voice: n8n transcribes (Whisper) into `message_text`; the audio file rides here as `type=audio`.
  - **`discard_draft_id?` (is_new_idea restart, DC-10)** - when the user starts a genuinely new idea while an old draft is still open, the sorento brain (parser `is_new_idea` flag, semantic, not keyword) opens a **fresh** draft (no `draft_id`) and names the abandoned one here; shared-service transitions it `draft → rejected` (best-effort: unknown / already-terminal id is a silent no-op, never a 500). There is **no time-based draft TTL** - topic, not time, is the discriminator; default is always-resume.
  - `draft_id` absent on the first `ideate` turn; present on continuation.
- **Behaviour (deterministic state machine):** if no `draft_id` → create a **draft Idea** (status `draft`). Merge `fields`/`remove` into the draft's `captured_json` against the `form_engine` schema, run dup-check on the problem text, recompute captured/missing per the `completion_rule`, then pick the status:
  - **`duplicate`** - problem text is a high `pg_trgm` match to an existing Idea → upvote it, return `duplicate_of`. (Checked before review; short-circuits.)
  - **`collecting`** - `missing != []` → `reply_text` echoes what's captured so far **and** lists what's still missing.
  - **`review`** - `missing == []` **and** `confirm != true` → **NEVER auto-completes.** `reply_text` echoes the full captured summary and asks the user to confirm or say what to change. Draft stays `draft`. A subsequent turn may carry more `fields`/`remove` (revision) → re-merged, re-echoed, stays `review`; if a required key is removed → falls back to `collecting`.
  - **`complete`** - `missing == []` **and** `confirm == true` → **only now** does the Idea move `draft → captured`; `link` = product-domain deep link (§5.3); caller clears `session_vars.ideation`.
- **Output:** `{ draft_id, status: "collecting"|"review"|"complete"|"duplicate", captured: {...}, missing: ["field", ...], reply_text, link? , duplicate_of? }`
  - `reply_text` is composed **deterministically** by shared-service (template over `captured_json` + schema field labels - no LLM): a "captured so far / still missing" line (`collecting`), a "here's your idea … confirm or tell me what to change" summary (`review`), or a confirmation + `link` (`complete`).
- **Idempotency:** repeated calls with the same `draft_id` are safe (re-merge, never duplicate the draft). `confirm=true` on an already-`captured` idea is a no-op that returns `complete` + `link`. Revising a *field* while in `review` is idempotent per identical `fields`.

### 5.2 `session_vars.ideation` (sorento owns the blob; shape is the contract)
```json
{ "ideation": { "draft_id": "<uuid>", "status": "collecting|review", "missing": ["impact","department"], "updated_at": "<iso>" } }
```
- Written by sorento after each `create_idea` call; **cleared** on `status=complete`/`duplicate`.
- `status` tells the sorento brain the draft is in **`review`** so the next turn is interpreted as *confirm vs revise* (produce `confirm`/`fields`/`remove`), not as fresh collection (D-CONFIRM).
- Carries the **pointer only** - the durable draft lives in shared-service (D8).
- Persisted via the existing `POST /api/v1/external/conversation-variables/{contact_id}` (namespaced key `ideation`, must not clobber CRM keys).

### 5.3 Product-domain link + embed SSO
- shared-service mints the link as `{product_domain_base}/ideas/{idea_id}` (e.g. `https://fe-sorento.foundryx.my/ideas/123`) - never a shared-service URL.
- Sorento route `/ideas/{id}` renders an `<iframe src="{shared_service}/embed/ideas/{id}">`.
- Sorento BE mints a **signed assertion** for the logged-in user → `POST {shared_service}/embed/session` → embed token (`typ="embed"`). Connection `allowedOrigins` includes the sorento origin; `frame-policy` permits the frame. (Generalized from omnichannel plan 11H.)

### 5.4 Mac Mini bridge (daemon ⇄ shared-service - carries BOTH grill and build)
> This bridge is used by **Phase B (grill)** and **Phase C (build)** - shared-service has no brain (D20), so every AI turn (grilling a BR→FR *and* building an FR→PR) is a job dispatched to Claude Code on the Mac Mini and relayed back.
- **Registration:** `AgentRunner` integration issues an API key; daemon config = `{shared_service_url, api_key}`.
- **Outbound poll:** daemon long-polls `GET /agent-runner/jobs` (auth: API key) → returns queued jobs (`kind: grill | build`) for its `served_product_ids`. Heartbeat sets `status=online`.
- **Grill job payload:** `{ kind: "grill", br_ids[], fr_draft_id?, chat_turn, product_id, repo }` → Claude Code grills (reads code + Outline), streams questions/answers back; on completion emits the structured FR.
- **Build job payload:** `{ kind: "build", fr_id, product_id, repo, branch_base, fr_snapshot (UAC+plan+reuse), phase_cursor }`.
- **Callbacks (daemon → shared-service):** `POST /agent-runner/events` with `{fr_id, kind}` where `kind ∈ {progress, prototype_ready(preview_url), clarification_request(question), pr_opened(pr_url), phase_done, error}`.
- **Human answers** to `clarification_request` post to the FR thread in shared-service; shared-service re-enqueues a continuation job (the daemon picks it up on next poll - no inbound to the Mac Mini).
- **Status-back = milestones only:** `issue_created → building → prototype_review → developing → pr_review → merged → deployed`.
- **Creds:** git/deploy keys are local to the Mac Mini; the daemon never receives them from shared-service.

### 5.5 n8n routing (thin - X)
- On a turn classified `domain=ideate` (by the existing reformulator/parser), n8n calls the sorento brain path that invokes `create_idea` with the current `session_vars.ideation.draft_id`.
- n8n stores whatever the brain returns back into `session_vars` (existing `save-session-vars`) and relays `reply_text` (+ `link` on completion) via the existing send-message sub-flow.
- **No new state store in n8n.** No PG-memory node. Voice → transcribe (existing node) → text into the turn.

## 6. Risks

- **Live-flow surgery:** adding `ideate` to `sorento-consume-main` touches a production flow - must be additive + guarded (domain gate), never regress CRM intents.
- **Interrupt correctness:** CRM question mid-collection must not corrupt/clear the open draft; `draft_id` resume must be exercised.
- **pgvector** not present in shared-service today - provision it for dedup.
- **Outline staleness** - doc-based reuse-analysis is blind to technical dupes; the Phase-C code-level verify must be real, with bounce-back.
- **Cross-repo delivery is net-new** - the daemon⇄shared-service bridge is the highest-effort surface.
- **Autonomous build quality** - the headless agent opening PRs unattended lives or dies on the FR/UAC being tight.
- **Mac Mini single point** - offline = builds queue (acceptable).

## 8. Contract reconciliations (2026-07-18, after per-repo authoring)

Resolved during authoring - the per-repo plans already reflect these; recorded here as canonical:

- **R1 - Product namespacing.** The program `Product` collides with core `public.products` (goods catalog). **Resolution:** ideation Product lives in **`app_ideation.products`** (distinct entity). Update §3 mentally to `app_ideation.products`.
- **R2 - Binding + identity (REVISED per D21).** The **workspace↔Product binding lives sorento-side** (`respond_workspaces.ideation_product_id`); sorento derives `product_id` and passes it. **Contact identity is NOT a passed ref** - shared-service keeps its **own cron-synced respond.io contact copies** and **matches by phone (E.164)** on `create_idea` (D21).
- **R3 - `create_idea` transport = HTTP endpoint**, server-to-server (not MCP). See §5.1.
- **R4 - Dedup (REVISED per D10/D20).** No LLM/embedding in shared-service → dedup uses **`pg_trgm` text-similarity**, not pgvector. Semantic dedup later = delegate embedding to Claude Code/sorento.
- **R5 - Embed generalization = core-primitive extraction** (`provider="ideation_shared"`, audience `"ideation-embed"`), with per-module copy-pattern as documented fallback. `/embed/session` reuses the existing omnichannel `embed_session_service` shape.
- **R6 - media (multi-modal capture, DC-9)** = unified `attachments[]` of durable sorento-stored URLs (retires the singular `audio_attachment_ref`); idempotent on `source_msg_id`; sorento owns lookback + snapshot + vision, n8n owns Whisper STT + reference-position + `is_new_idea` extraction (§5.1).

## 9. Open decisions - RESOLVED 2026-07-18 (owner directive)

1. ~~**Grill's brain → Claude Code, relayed.**~~ **RE-RESOLVED 2026-07-21 (D11/D20-A): grilling is a shared-service LLM capability**, at both Idea→BR and BR→FR. Only `reuse_analysis` and the build stay on Claude Code. Phase 0 remains cancelled.
2. **respond.io sync → RESOLVED: shared-service cron-syncs its own contact copies + matches by phone (D21).** Not a passed ref.
3. ~~**LLM key → not needed.**~~ **RE-RESOLVED 2026-07-21 (D20-A): shared-service DOES hold an LLM key.** Stored as a core `connections` row, `type='llm'` (a type already reserved in the `IntegrationProvider` protocol but never implemented), Fernet-encrypted in `credentials_json`, write-only over the API. Providers **anthropic · openai · gemini** minimum. Resolution mirrors SMTP: tenant connection → platform connection → error. Platform-key usage is cross-tenant cost - capping/billing is a backlog item (class of BL-036), not a blocker while the ideation tenant is Foundryx-internal.

Dedup/clustering: `pg_trgm` retrieval retained, LLM grouping added on top (D10-A). No pgvector.

## 9b. Amendment log

| Date | Change | Driver |
|------|--------|--------|
| 2026-07-21 | **D20 → D20-A**: the AI cut line is *code-awareness*, not location. shared-service may run conversational/text LLM work; repo-reading work stays on the Mac Mini. Adds D10-A (clustering), D21-A (generic grill engine), D22-A (model never writes), D23-A (coverage-driven termination). Phase B re-cut into B-i (Idea→BR, no bridge) and B-ii (BR→FR + reuse-analysis). | Owner grill session - Phase A shipped; Idea→BR wanted without a runner dependency. **Supersedes the B1-B6 slice map in `PLAN-ideation-phase-b-structure.md`**, which was written under the original D20. |

## 7. Doc index (the per-repo triples key back here)

- **shared-service** - `documentation/plans/ideation/PLAN-ideation-*.md` + `*-acceptance-criteria.md` (Phase A core, B, C).
- **sorento** - `documentation/plans/ideation/PLAN-ideation-ideate-intent.md` + iframe host + their UAC files.
- **n8n** - `n8n-workflows-init/plans/ideation-intake-plan.md`.
