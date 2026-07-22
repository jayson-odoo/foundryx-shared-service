# Ideation Phase B-ii — Business Requirement → Functional Requirement · Acceptance Criteria

**Source plan:** `PLAN-ideation-phase-b-ii-br-to-fr.md` (this UAC is written FIRST, per methodology).
**Program spine:** `PLAN-ideation-to-delivery-program.md` (D4 cardinality · D20-A code-awareness cut · D21-A generic grill · D22-A model-never-writes · D23-A coverage termination) + `PLAN-ideation-phase-c-deliver.md` (the AgentRunner bridge C-D1..C-D10 — pulled forward here for reuse-analysis).
**Builds on:** Phase B-i (`app/ai/` subsystem, generic `GrillEngine`, `BusinessRequirement`, promote gate) — MERGED.
**Scope:** grill a **Business Requirement** into a **Functional Requirement** (= UAC + technical approach), human-gated at **Gate 1** (FR approved); then augment the approved FR with a **reuse-analysis** produced on a repo-reading **AgentRunner** daemon (this laptop now, a Mac Mini later — same protocol).

Format: each AC is independently verifiable (Given / When / Then). Grouped by slice. `[BE]` backend · `[FE]` frontend · `[E2E]` real-click · `[T]` unit/integration test. The Test Execution Report keys back PASS/FAIL/DEFERRED per AC id.

> **The cut line (D20-A).** The BR→FR **grill runs in shared-service** (conversational, no checkout) — Slice 1 depends on **no** runner. Only **reuse-analysis** reads the repository, so **only Slice 2** needs the AgentRunner bridge + an online daemon. A slice-1 FR is fully usable with `reuse_analysis` empty.

> **The safety invariant (D22-A).** The model never writes and never promotes. The grill emits a forced response schema; **our** code validates it against `form_engine` and persists `answers_json`. The reuse daemon returns **text only** (an analysis) that our code writes into one field — it holds no shared-service write capability beyond the runner-key `events` callback. Gate 1 (FR approved) is always a human step.

> **The termination model (D23-A).** Same `collecting → review → complete` + human-fires-generate shape as B-i. Every turn reports `covered_fields[]` against the FR template; "N of M captured"; coverage-complete **offers** to generate; the human always fires it.

> **Cardinality (D4).** Idea↔BR many-many (B-i) · **BR↔FR many-many** (this slice) · FR→GitHub issue 1:1 (Phase C). One grill session produces **one** FR (a vertical slice); a heavy BR is sliced by **promoting to FR repeatedly**.

---

## Slice 1 — BR → FR grill + Gate 1 (shared-service only, no runner)

### AC-BII-01 — `FunctionalRequirement` entity [BE][T]
- **Given** the ideation module, **when** slice 1 lands, **then** a `FunctionalRequirement` model exists in `app_ideation` mirroring `BusinessRequirement`: `id`, `tenant_id` (plain indexed, BL-030), `product_id`, `status_id` (status engine), `template_key`/`template_version` (form_engine-stamped), `answers_json`, timestamps.
- **Given** the FR template fields (AC-BII-03), **then** `answers_json` holds exactly them; compiled/rendered content is never stored — always the answer map (the B-i contract).
- **Given** cross-schema references, **then** `product_id` and `status_id` are **plain indexed columns, not DB FKs** (BL-030); intra-`app_ideation` links keep FKs.
- **Given** the migration, **then** its revision id is **≤32 chars** and continues the single ideation head (`0009_...`), verified against live Postgres — never only `create_all`.

### AC-BII-02 — BR↔FR many-many link [BE][T]
- **Given** an FR promoted from a BR, **then** a `BrFunctionalRequirement` join row links them (mirrors `IdeaBusinessRequirement`); **and** an FR may link **multiple** BRs and a BR may spawn **multiple** FRs.
- **Given** a link insert, **then** its `tenant_id` is **derived from the owning FR**, never statically defaulted (the BL-015 rule).
- **Given** a stored `br_id`/`fr_id` resolved at use time, **then** the query is **tenant-scoped** (the polymorphic-target_id defense-in-depth rule).

### AC-BII-03 — FR template = UAC + technical approach [BE][T]
- **Given** the seeded platform-tier FR `form_engine` template (`functional_requirement`), **then** it declares: `acceptance_criteria` (**repeater** of `{given, when, then}` rows), `technical_approach` (long text), `slice_scope` (text — the ONE vertical slice this FR covers), `grill_notes` (text), plus **`reuse_analysis`** (text, **grill leaves blank** — filled in Slice 2) and **`lavish_artifact`** (text, deferred — never required).
- **Given** the required set, **then** `acceptance_criteria` (≥1 row, each with all three of G/W/T non-blank), `technical_approach`, and `slice_scope` are **required**; `grill_notes`/`reuse_analysis`/`lavish_artifact` are optional.
- **Given** parity, **then** the template is seeded insert-if-missing (operator edits survive reseed) exactly like the BR template.

### AC-BII-04 — BR→FR is a new `GrillDefinition`, zero engine edit [BE][T]
- **Given** D21-A, **when** slice 1 lands, **then** BR→FR is a **new `GrillDefinition` row/registration** binding *source = BR (+ its linked ideas as context) · target = FR template · skill = the existing `grill-me-business` · agent · completion rule* — the generic `GrillEngine` (`app/ai/grill.py`) is **not modified**.
- **Given** the FR template's field labels/descriptions (technical framing: "acceptance criteria as Given/When/Then", "technical approach"), **then** they are injected into the prompt via the existing substitution-only `render_tokens` — the ONE skill serves both BR and FR targets (no `grill-me-technical` needed).
- **Given** the grill turn, **then** it is the SAME structured shape as B-i (`{replyText, coveredFields[], capturedSummary[], generateSignal}`) with capture **accumulating** across turns (the B-i AC-BI-29c fix), rendered "N of M captured · missing: …".

### AC-BII-05 — grill agent for BR→FR [BE][T]
- **Given** an existing per-tenant grill agent, **then** BR→FR **reuses the seeded `ideation-grill` agent** (resolved by stable key, not display name) — no second agent seeded; it already resolves its LLM connection by `connection_id`.
- **Given** no LLM connection configured for the tenant, **then** the FR Grill tab shows the **prerequisite warning** (not a silent later 502) and the grill does not fire — identical to B-i AC-BI-11.

### AC-BII-06 — Promote BR → FR (absorb + auto-open) [BE][FE][T]
- **Given** a BR in `ready`, **when** the user fires **"Promote to FR"** (available on the BR **list row**, **bulk**, and **form** "…"), **then** a new FR `draft` is created, linked to the BR, and the user lands on the new FR's **Grill** tab.
- **Given** promotion, **then** the FR **absorbs** the BR (AC-BI-32b pattern): FR title from the BR title; `slice_scope`/`technical_approach` left for the grill; the BR's `problem_statement`/`business_goal`/`scope`/`constraints` feed the grill as **full source context** (not hardcode-mapped into FR fields — the FR is a different shape).
- **Given** a fresh promoted FR with a linked BR + an LLM connection, **then** the grill **auto-opens once** (greet + summarize the BR + ask the first technical question), idempotent, `openedForRef`-guarded — identical to B-i AC-BI-29b.
- **Given** promote, **then** the source BR transitions `ready → in-FR` (the program BR status chain) via the status engine — surfacing that the BR now has downstream FRs.

### AC-BII-07 — Generate = extraction into FR `answers_json` [BE][T]
- **Given** coverage completes and the user prompts to generate (or the model raises `generateSignal`), **then** a **separate extraction pass** over the whole transcript emits the FR fields, is validated by `form_engine` with **`enforce_required=False`** (partial emit is success), one retry on validation failure, and writes `answers_json`.
- **Given** extraction, **then** the model **never** advances FR status (D22-A) — the FR stays `draft`; only our Gate-1 action promotes it.
- **Given** the extraction schema, **then** it marks every FR key `required` + carries the completeness directive (the B-i AC-BI-24c fix) so `technical_approach`/`slice_scope`/AC rows are synthesized across turns, not shallow-emitted.

### AC-BII-08 — FR status machine + Gate 1 [BE][T]
- **Given** the FR status graph seeded for the tenant, **then** it has at minimum `draft → grilling → approved` with the `grilling → approved` edge = **Gate 1**; the downstream build states (`building → … → done`, `blocked`/`bounced`) are **out of scope here** (Phase C) — seed them inert or add in C.
- **Given** the Gate-1 edge, **then** it is gated by a dedicated permission `ideation.functional_requirements.approve` and its server handler **re-validates the stamped FR doc with `enforce_required=True`** → 422 `{fieldErrors, message}` if AC/technical_approach/slice_scope are incomplete (mirrors the BR promote gate; the FE maps to inline errors + a friendly toast, never raw "Unprocessable Content").
- **Given** a tenant renames or forks FR statuses, **then** no code hardcode-looks-up an FR status **key** — the gate resolves the edge by id off the graph (the tenant-editable-keys rule).

### AC-BII-09 — FR Resource surface [FE][T]
- **Given** the sidebar Ideation section, **then** a **"Functional requirements"** entry (gated `ideation.functional_requirements.read`, tagged in all three menu arrays) opens the FR **Resource list** (search/sort/column-prefs/select/export, id-first export).
- **Given** an FR row, **then** it opens a tabbed **ResourceForm**: **Details** (flat — straight to `acceptance_criteria`, no Title/heading chrome, the B-i AC-BI-29c `flat` FormRenderer) · **Grill** (viewport-fit, pinned input, accumulating capture) · **Business Requirements** (Resource-shell `ResourceList`, reverse link, navigable) · **Trace** · **Versions**.
- **Given** a BR detail, **then** it gains a **"Functional Requirements"** tab (Resource-shell list, reverse link) so BR→FR lineage is navigable both directions.
- **Given** both viewports, **then** the FR surfaces are verified at **375px and 1280px** (responsive mandate).

### AC-BII-10 — permissions + grant sweep [BE][T]
- **Given** the new keys `ideation.functional_requirements.read/manage/approve`, **then** they are added to the ideation module CSV (grep-checked against core for collisions).
- **Given** existing tenants' Admin roles, **then** a **grant sweep** (`tenant_admin_grant` re-run / migration) reaches them — the FR feature never silently 403s on an already-provisioned tenant.

### AC-BII-11 — trace + failure isolation [BE][T]
- **Given** any FR grill/extraction LLM call, **then** it writes an `ai_traces`/`ai_spans` trace; on `LLMError` the flushed trace is **committed** before a clean `GrillError` (502) surfaces (the B-i trace-on-error rule) — a failed FR grill leaves an error trace.
- **Given** a broken/slow grill, **then** it never corrupts the FR row or the BR (each step one commit).

### AC-BII-12 — E2E: BR → FR → approved [E2E]
- **Given** a fresh dedicated tenant with an LLM connection (stub-deterministic in CI; real-Gemini in the live gate), **when** a test clicks BR "Promote to FR" → grill turns → generate → fills AC + technical_approach + slice_scope → fires Gate 1, **then** the FR reaches `approved`, an empty-FR Gate-1 attempt is refused with a friendly message, and BR shows `in-FR`. Real clicks only (no URL shortcuts).

---

## Slice 2 — AgentRunner bridge + reuse-analysis (needs an online daemon)

### AC-BII-20 — `AgentRunner` entity + key auth [BE][T]
- **Given** C-D1, **when** slice 2 lands, **then** an `agent_runners` table exists (`id`, `tenant_id`, `name`, `key_prefix`, `api_key_hash`, `served_product_ids[]`, `concurrency_cap`, `status`, `last_seen`) — a runner-key registry, **not** a `Connection` row (reuse the key-**hashing** pattern from `modules/omnichannel/api_auth.py`, not the table).
- **Given** a runner Bearer key `fxr_live_…`, **then** `get_agent_runner(Authorization)` resolves `(tenant_id, runner_id)` by hash lookup, tenant-scoped, and rejects unknown/revoked keys uniformly.
- **Given** management endpoints (native session auth, gated a Maintainer perm): `POST /agent-runners` (mint key, return plaintext **once**), `POST /agent-runners/{id}/rotate-key`, `POST /agent-runners/{id}/revoke`, `GET /agent-runners[/{id}]` (status/last_seen/in-flight). The key is **write-only** thereafter (only the hash stored).

### AC-BII-21 — reuse-analysis job queue [BE][T]
- **Given** an `agent_runner_jobs` store, **then** a job = `{id, tenant_id, kind:'reuse_analysis', product_id, fr_id, payload_json (fr_snapshot + repo), status: queued|leased|done|error, lease_expires_at, result_json, event dedup}`.
- **Given** `GET /agent-runner/jobs` (runner key, long-poll ~25–30s), **then** it returns queued jobs for the runner's `served_product_ids` under a **lease** (claim is atomic — two runners never double-claim), heartbeat renews the lease, and a lapsed lease re-queues the job (crash-safe).
- **Given** `POST /agent-runner/heartbeat`, **then** it refreshes `last_seen`, sets `status=online`, renews leases, reports in-flight count.
- **Given** the queue is empty, **then** the long-poll returns `[]` on timeout (no busy-loop).

### AC-BII-22 — "Run reuse analysis" action on an FR [BE][FE][T]
- **Given** an FR (any status from `draft` up; the analysis is advisory), **when** the user fires **"Run reuse analysis"**, **then** a `reuse_analysis` job is enqueued with the FR snapshot (AC + technical_approach + slice_scope) and the product's repo, and the FR shows a **pending** indicator.
- **Given** no `github` product-adapter (no repo) on the product, **then** the action is **withheld / warns** (foolproof-UI: only offer valid options) — never enqueues a job that must fail.
- **Given** no runner has ever been online for the product, **then** the action still enqueues (jobs queue) but the UI states it is **waiting for a runner** — never a silent hang.
- **Given** the analysis completed once, **then** it is **re-runnable** (re-enqueues; the latest result wins) — an FR edited after analysis can be re-analysed.

### AC-BII-23 — runner callback writes `reuse_analysis` [BE][T]
- **Given** `POST /agent-runner/events` (runner key) with `{job_id, fr_id, kind:'reuse_done'|'error', event_id, result?}`, **then** on `reuse_done` the server writes `answers_json.reuse_analysis` on the FR, marks the job `done`, clears pending; on `error` it marks the job `error` with a clean message the FR surfaces (never a raw daemon traceback).
- **Given** `event_id`, **then** callbacks are **idempotent** (a redelivered event never double-writes).
- **Given** the callback, **then** the daemon can write **only** `reuse_analysis` via this typed path — it holds no general FR-write capability (D22-A blast-radius).
- **Given** the tenant scope, **then** the `fr_id`/`product_id` in the callback are validated to belong to the runner's tenant + `served_product_ids` (a runner can never write another tenant's FR).

### AC-BII-24 — the daemon (this laptop now) [BE][T]
- **Given** a local **outbound-polling daemon** (headless Claude Code / Agent SDK) configured with `{shared_service_url, runner_api_key}`, **then** it long-polls `GET /agent-runner/jobs`, and for a `reuse_analysis` job **checks out the product's repo** (repo-only v1 — Outline deferred), runs a repo-reading analysis prompt (existing engines/capabilities/modules reusable for this FR's slice vs net-new), and posts the result to `/agent-runner/events`.
- **Given** the daemon, **then** it is **device-agnostic** — moving it to a Mac Mini is config-only, zero protocol change (D13); git/deploy creds stay **local to the daemon**, never sent by shared-service (only the runner API key flows).
- **Given** `concurrency_cap`, **then** the daemon runs at most that many jobs at once.
- **Given** the daemon is offline, **then** shared-service is unaffected — jobs queue, the FR shows waiting, and no user surface 500s.

### AC-BII-25 — `github` product-adapter wired (repo) [BE][FE][T]
- **Given** the dormant `github` `AdapterKind`, **then** slice 2 **wires** it: a product carries a `github` `ProductAdapter` with a `repo` (owner/name or clone URL) + optional default branch, editable on the product surface; the reuse job reads it. No new adapter framework — the registry already exists.
- **Given** a software product with no `github` adapter, **then** reuse-analysis is unavailable (AC-BII-22 withhold) rather than broken.

### AC-BII-26 — reuse-analysis visible on the FR [FE][T]
- **Given** the FR Details tab, **then** `reuse_analysis` renders as a read section (markdown-safe, sanitized) with its pending/done/error state and a "Run reuse analysis" / "Re-run" action; empty state is a plain status, never instructional copy (foolproof-UI).
- **Given** both viewports, **then** verified at 375px and 1280px.

### AC-BII-27 — E2E: enqueue → daemon → reuse populated [E2E]
- **Given** an approved FR on a product with a `github` adapter and a registered runner, **when** a test clicks "Run reuse analysis", a **stubbed daemon** (a test double posting a canned `reuse_done` to `/agent-runner/events`) processes the job, **then** the FR's `reuse_analysis` populates and the pending indicator clears. (The real Claude-Code daemon is exercised in a manual live gate against a real repo, reported separately.)

### AC-BII-28 — issue-payload serializer (Phase-C handoff seam) [BE][T]
- **Given** an approved FR, **then** an `fr_issue_payload(fr)` serializer produces the GitHub-issue body (UAC G/W/T + technical_approach + slice_scope + reuse_analysis) — **built + unit-tested here** as the Phase-C handoff contract, but **not wired to GitHub** in B-ii (no issue is created; that is Phase C, Gate-1→building).

---

## Out of scope (deferred)
- **Build loop (FR→PR)**, Cloudflare-Tunnel preview, Gate 1.5 / Gate 2, milestone status-back, the `build` job kind — **Phase C**.
- **GitHub issue creation** + PR mirror — Phase C (the serializer AC-BII-28 is the seam).
- **Outline doc-reuse** in reuse-analysis — deferred (repo-only v1).
- **`lavish_artifact`** field population — deferred.
- **FR downstream statuses** (`building`→`done`) beyond `approved` — Phase C wires the transitions.

## Definition of Done (gate — every slice)
Mock→real swapped · new column/entity backfilled for existing rows+tenants · no hardcoded tenant-editable keys · new perms grant-swept · verified end-to-end with **real data** at 375px + 1280px on a freshly rebuilt frontend against correctly-owned ports · migration ids ≤32 chars verified on live Postgres.
