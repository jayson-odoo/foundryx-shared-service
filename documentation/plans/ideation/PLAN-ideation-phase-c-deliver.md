# PLAN — Ideation Phase C (Deliver)

**Status:** Planning (UAC-first, no code yet — 2026-07-18). Keys back to
`PLAN-ideation-to-delivery-program.md` (program spine). UAC:
`ideation-phase-c-deliver-acceptance-criteria.md` (AC-C-01…37).

**Classification:** MODULE / Service on the FoundryX shared-service platform (tenant =
FoundryX-internal). Delivery *runner* is a **separate deployable** (the Mac Mini daemon) — NOT
shared-service code — but its protocol is owned here (canonical in program §5.4).

**Depends on:** Phase A (Product, Idea, contacts, embed host, `product_domain_base`) and Phase B
(BusinessRequirement, FunctionalRequirement, fixed templates, heavy grilling chat, Gate 1 = FR
approved). The **build** side of Phase C begins the moment an FR reaches `approved`.

**⚠ Bridge is foundational infra shared with Phase B — build it once, early (D20, program §4, §5.4).**
shared-service has no brain, so the Phase-B grill (BR→FR) is ALSO a job dispatched to Claude Code on
the Mac Mini — not just the Phase-C build (FR→PR). The Mac Mini bridge (`AgentRunner` registration +
outbound poll + events + lease + continuation-resume) carries **both `kind: grill` and `kind: build`
jobs**. Although this substrate is authored here in the Phase-C plan, it must be delivered **before
Phase B's grill can work** — the registration/poll/events/resume slices (C1–C3, C5) are a
prerequisite of Phase B, not a follow-on to it. Only the build-specific slices (C4, C6–C9) truly
gate on an approved FR.

**Scope (program §4, row C):** `AgentRunner` integration · Mac Mini **grill+build bridge** · Mac
Mini daemon · GitHub integration · Cloudflare-Tunnel preview · build loop (3-phase) · grill relay ·
clarification bridge · milestone status-back · gates 1.5 + 2.

---

## 1. What Phase C delivers, in one paragraph

Phase C builds the **one Mac Mini bridge** that carries two job kinds (D20, §5.4). A **`grill` job**
(BR→FR, Phase B's engine): a BR entering `grilling` is enqueued, the daemon drives **headless Claude
Code** to read code + Outline, streams questions into the shared-service grill chat, and emits a
structured **FR draft** — no brain in shared-service, which only relays. A **`build` job** (FR→PR):
an **approved FR** (the vertical slice, D4) becomes a **GitHub issue (1:1)**, is enqueued, and pulled
by the daemon over the **same outbound-only** long-poll; the daemon drives Claude Code through the
three-phase build (FE prototype → TDD backend → code review → PR), **one git worktree per FR**,
resumable. Two human gates punctuate the build — **1.5 prototype-eyeball** (via a Cloudflare-Tunnel
preview to the live Mac Mini session against the local DB) and **2 PR-eyeball** — both taken
**inside shared-service**, the only human surface. Agent questions and reuse bounce-backs surface
into the **FR thread** (device-free); a human answer — or the next grill turn — **re-enqueues a
continuation job** the daemon picks up on its next poll. GitHub stays machine-only; status flows back
to the FR as **milestones**. Merge + deploy → `done`, and the originating idea is traceable end to
end.

---

## 2. Decision log (Phase C — inherits program §2 D1–D21)

| # | Decision | Rationale / grounding |
|---|----------|-----------------------|
| C-D1 | The delivery bridge is an **integration on shared-service**, modelled as an `AgentRunner` entity (§3) — NOT a `Connection` row. | `AgentRunner` needs `served_product_ids[]`, `concurrency_cap`, `status`, `last_seen`, and a runner-issued API key — a different shape from the `(tenant, provider)` `Connection` registry (`app/models/connection.py`). Reuse the *key-hashing pattern*, not the Connection table. |
| C-D2 | **API key = SHA-256 hash + prefix + constant-time compare**, plaintext returned once. | Directly reuse the proven pattern in `modules/omnichannel/services/api_key_service.py` (`_hash_key`, `_prefix_of`, `hmac.compare_digest`, `secrets.token_urlsafe`). New scheme prefix e.g. `fxr_live_` (runner) to visually distinguish from `fxw_live_` (workspace). |
| C-D3 | **Outbound long-poll only**; shared-service never dials the Mac Mini (D13). | NAT-free, no inbound port on the Mac Mini. All hand-offs (jobs) and continuations are daemon *pulls*. |
| C-D4 | **Server-side concurrency cap** (default 2) — the jobs endpoint refuses to lease beyond the cap; the daemon also self-limits. | Belt-and-braces: a buggy daemon can't overrun; server stays authoritative (AC-C-05, AC-C-34). |
| C-D5 | **Job lease, at-least-once, idempotent callbacks** (event id de-dupe). | Crash-resume must re-deliver the *same* job to the *same* runner, never fan a job to two runners (AC-C-10); retried callbacks apply once (AC-C-14). |
| C-D6 | **GitHub is machine-only** (D15); humans never touch it. Issue 1:1 with FR; PR closes issue; **milestone-only** status-back. | Keeps one human surface (shared-service). FR carries `github_issue_ref` + `pr_ref` for the end-to-end trace. |
| C-D7 | **Clarifications + reuse bounces re-use the FR thread** (D11, D15). A human answer — or the next **grill turn** — re-enqueues a **continuation job** with the resume cursor (`phase_cursor` for build, `chat_turn`/`fr_draft_id` for grill). | Device-free; no inbound to the daemon; the same worktree/grill session resumes. Continuation-resume is `kind`-agnostic. |
| C-D13 | **One bridge, two job kinds** (`grill`, `build`) per D20/§5.4 — shared-service has no brain, so grilling BR→FR is ALSO a Claude-Code job, not just building FR→PR. The registration/poll/events/lease/continuation substrate is **shared and built once, early** — it is a prerequisite of **Phase B's grill**, not a Phase-C follow-on. | Avoids two bridges. Phase B literally cannot grill without this substrate (D20 cancelled the old assistant port); so the "bridge" slices (C1–C3, C5) land ahead of Phase B, and only the build-specific slices (C4, C6–C9) wait on an approved FR. |
| C-D8 | **Preview = Cloudflare Tunnel to the live Mac Mini session against the LOCAL DB** (D14) — not a shared-service-hosted build. | The prototype must be eyeballed against prod-shaped data; the daemon owns the running session, exposes it via a tunnel, and reports the URL in `prototype_ready`. |
| C-D9 | **Delivery is failure-isolated** from the spine via an **outbox** for outbound calls (issue-create, status-back). | Mirror `modules/omnichannel/services/webhook_delivery.py` (durable rows, backoff, dead-letter). GitHub/daemon down must never 500 the FR machine (AC-C-36). |
| C-D10 | **FR status machine is the source of truth**; milestones + callbacks are *inputs* to it, GitHub is a *mirror* of it. | The FR states already exist in §3 (`building → prototype-review → developing → pr-review → merged → deployed → done` + `blocked`/`awaiting-clarification`/`bounced`). Phase C only wires the transitions. |
| C-D11 | Preview URL has an explicit **lifecycle/expiry** on the FR (AC-C-25). | A dead tunnel must never be shown as live. |
| C-D12 | The daemon holds **only the shared-service API key**; git/deploy creds are **local-only** (D13, §5.4). | Blast radius: a stolen API key can poll/callback but cannot push code or deploy. |

---

## 3. Data model (shared-service)

New/extended tables (core schema — this is FoundryX-internal spine, normal FKs; per program §3 the
entities live in shared-service). Migrations via core Alembic (`alembic revision --autogenerate`).

- **`agent_runners`** (§3 `AgentRunner`) — `id`, `tenant_id`, `name`, `key_prefix`, `api_key_hash`,
  `served_product_ids` (JSON array of `products.id`), `concurrency_cap` (default `2`), `status`
  (`offline|online`), `last_seen`, `created_at`, `revoked_at`. Key hashing mirrors
  `ApiKeyService`.
- **`agent_jobs`** (the one queue + lease ledger for **both** `grill` and `build`, D13/C-D13) —
  `id`, **`kind`** (`grill|build`), `product_id`, `runner_id` (nullable until leased), `state`
  (`queued|leased|awaiting_clarification|awaiting_grill_turn|done|error`), `resume_cursor`
  (build: `prototype|tdd|review|continuation`; grill: `chat_turn`), `lease_expires_at`,
  `payload_json` (the job snapshot — build or grill shape), `is_continuation` (bool),
  `answer_ref` (nullable — the clarification answer / grill turn that spawned it), `created_at`,
  `updated_at`. Kind-specific FKs: **build** → `fr_id` (FK → functional_requirements); **grill** →
  `br_ids[]` (JSON) + `fr_draft_id` (nullable FK → functional_requirements, set once the FR draft is
  emitted). **Idempotent lease:** at most one non-terminal build job per FR, and at most one
  non-terminal grill job per BR set. (Named `fr_build_jobs` in earlier drafts — generalized to
  `agent_jobs` now the same table carries grill jobs.)
- **`agent_job_events`** — inbound callback log for idempotency + timeline (build **and** grill).
  `id`, `job_id`, `fr_id` (nullable — build, or grill once `fr_draft_id` exists), `event_id`
  (daemon-supplied de-dupe key), `kind` (build: progress/prototype_ready/clarification_request/
  pr_opened/phase_done/error; grill: grill_progress/grill_question/clarification_request/
  fr_emitted/error), `payload_json` (preview_url / question / pr_url / grill FR / error / progress),
  `created_at`. `UNIQUE(job_id, event_id)`. (Named `fr_build_events` in earlier drafts.)
- **`delivery_outbox`** — outbound calls to GitHub / deploy webhooks (issue-create, milestone
  status-back). Same shape/discipline as `webhook_deliveries` (status, attempt_count,
  next_attempt_at, backoff, dead-letter). Reuse the delivery worker pattern from
  `modules/omnichannel/services/webhook_delivery.py`.
- **`FunctionalRequirement`** (extend, Phase B entity) — ensure/confirm columns:
  `github_issue_ref`, `pr_ref`, `preview_url`, `preview_expires_at`, `build_progress` (free text),
  `clarification_thread_id` (reuse the omnichannel/thread store if the FR thread rides on it).

**pgvector:** not needed for Phase C (dedup was Phase A). No new vector work here.

---

## 4. Backend surface (shared-service) — the delivery bridge

All under a new module/router mounted public (API-key auth like the omnichannel public gateway),
resolver `get_agent_runner` modelled on `modules/omnichannel/api_auth.py::get_api_workspace`.

### 4.1 Registration + key (AC-C-01..05, AC-C-35)
- `POST /agent-runners` (Maintainer, native auth) → create runner, mint key, return plaintext once.
- `POST /agent-runners/{id}/rotate-key`, `POST /agent-runners/{id}/revoke`.
- `GET /agent-runners` / `GET /agent-runners/{id}` → status, last_seen, in-flight count.
- `get_agent_runner(Authorization: Bearer fxr_live_…)` → `(tenant_id, runner_id,
  served_product_ids)`; uniform 401 on miss; stamps `last_seen`/`status=online` (heartbeat side
  effect, AC-C-09).

### 4.2 Outbound poll (AC-C-06..10, 38)
- `GET /agent-runner/jobs` (runner key) — long-poll (hold open ~25–30s, return `[]` on timeout).
  Leases up to `concurrency_cap − in_flight` queued jobs of **either kind** whose
  `product_id ∈ served_product_ids`, oldest-first. Sets `state=leased`, `runner_id`,
  `lease_expires_at`. Re-poll before lease expiry re-returns the same leased job (AC-C-10). Every job
  carries a `kind` discriminator; payload is **exactly** one of:
  - **build** — `{ kind: "build", fr_id, product_id, repo, branch_base, fr_snapshot, phase_cursor }`
    (AC-C-07, §5.4).
  - **grill** — `{ kind: "grill", br_ids[], fr_draft_id?, chat_turn, product_id, repo }`
    (AC-C-38, §5.4).
- `POST /agent-runner/heartbeat` (runner key) — refresh `last_seen`, renew leases, report in-flight.

### 4.3 Callbacks (AC-C-11..14, 39)
- `POST /agent-runner/events` (runner key) — body `{ job_id, fr_id?, kind, event_id, ... }`, kind set
  depending on the job:
  - **build:** `kind ∈ {progress, prototype_ready, clarification_request, pr_opened, phase_done, error}`
    (§5.4) → drives the FR machine (§4.4).
  - **grill:** `kind ∈ {grill_progress, grill_question, clarification_request, fr_emitted, error}`
    (§4.7) → appends questions to the grill chat and persists the emitted FR as a **draft**.
  De-dupe on `UNIQUE(job_id, event_id)`; apply once. Runner may only post for jobs of products it
  serves (403 otherwise).

### 4.4 FR machine transitions (AC-C-12/13/15, §5, AC-C-21/22)
Centralize in an `FrDeliveryService` (reuse `status_engine` if Phase B put FR status on it):

| Input | FR transition | Side effect |
|-------|---------------|-------------|
| FR approved (Gate 1) | `approved → building` | enqueue GitHub issue-create (outbox) → on success `github_issue_ref`, milestone `issue_created`; enqueue `fr_build_job` (phase_cursor=`prototype`) |
| `progress` | (no status change) | update `build_progress` |
| `prototype_ready(preview_url)` | `building → prototype-review` | store `preview_url` + `preview_expires_at`; milestone `prototype_review`; release lease |
| Gate 1.5 approve | `prototype-review → developing` | enqueue continuation job (phase_cursor=`tdd`); milestone `developing` |
| Gate 1.5 reject | `prototype-review → grilling` (bounce, Phase B) | carry notes |
| `phase_done` (developing) | `developing → pr-review` (on `pr_opened`) | — |
| `pr_opened(pr_url)` | ensure `pr-review` | store `pr_ref`; link PR→issue; milestone `pr_review` |
| `clarification_request(question)` | `* → awaiting-clarification` | post question to FR thread; release lease |
| human answer | `awaiting-clarification → building/developing` | enqueue **continuation job** w/ answer + resume cursor (AC-C-17) |
| `error(message)` | `* → blocked` | surface in FR thread; release lease; allow re-queue |
| Gate 2 approve | triggers merge (GitHub) | — |
| merge webhook | `pr-review → merged` | milestone `merged` |
| deploy webhook | `merged → deployed → done` | milestone `deployed`; roll up Idea/BR → `delivered` |

### 4.5 GitHub integration (AC-C-19..22)
- A thin GitHub adapter (App or PAT stored as a `Connection` secret via `app/secrets.py`, or in the
  outbox job config). Operations: `create_issue(fr_snapshot)`, `link_pr_to_issue`, `merge_pr`,
  and **inbound** `POST /agent-runner/github/webhook` (HMAC-verified like
  `modules/omnichannel/routers/webhooks.py`) for milestone/merge/deploy events. Issue-create is
  idempotent on `github_issue_ref` (AC-C-19).

### 4.6 Clarification bridge (AC-C-15..18)
- `clarification_request` → append to the FR thread (device-free surface). A Maintainer reply
  (`POST /functional-requirements/{id}/thread`) with the FR in `awaiting-clarification` triggers
  `enqueue_continuation_job(fr_id, answer, resume_cursor)`. **No push to the daemon** — the next
  `GET /agent-runner/jobs` returns it (AC-C-17, D15).

### 4.7 Grill relay — BR→FR over the same bridge (AC-C-38..42, D11/D20)
> shared-service has no brain (D20); the grill is a `kind: grill` job dispatched to Claude Code and
> **relayed**. This is what Phase B's grilling chat sits on — hence the bridge is a **Phase-B
> prerequisite** (build C1–C3 + this relay before Phase B ships).
- **Enqueue:** a BR (or BR set) entering `grilling` enqueues a grill job
  `{ kind:"grill", br_ids[], fr_draft_id?, chat_turn, product_id, repo }` (AC-C-38). First turn has
  no `fr_draft_id`.
- **Relay in:** `grill_question` events append to the shared-service **grill chat** (the embedded UI,
  §5); the BR/FR-draft moves to `awaiting_grill_turn`, the lease is released so the concurrency slot
  frees.
- **Human turn → continuation:** a Maintainer/Triager reply in the grill chat
  (`POST /business-requirements/{id}/grill` or the FR-draft thread) calls
  `enqueue_continuation_grill_job(fr_draft_id, chat_turn)` — **no push to the daemon**; the next poll
  returns it and the daemon resumes the same grill session (AC-C-40). Continuation-resume is
  `kind`-agnostic (shares the §4.6 mechanism).
- **FR emit:** `fr_emitted` persists the structured FR (acceptance_criteria G/W/T, technical_approach,
  reuse_analysis, slice_scope, grill_notes) as an FR **draft** linked to `br_ids[]` — **never
  auto-approved** (D5); Gate 1 remains the human promote step (AC-C-39/41).
- **Failure-isolation:** grill jobs offline-queue and error-isolate exactly like build jobs (AC-C-42,
  §4.4 `error` handling applies with the BR/FR-draft as the target).

---

## 5. Frontend surface (shared-service embedded UI) — AC-C-16, 24, 26, 37

Rendered inside the sorento iframe embed (D17, program §5.3) — seamless SSO, one device-free
surface. All on the **FR detail** screen:

- **Delivery timeline** — milestone ladder (`issue_created → building → prototype_review →
  developing → pr_review → merged → deployed`), current status, `build_progress`, preview/PR links.
- **Gate 1.5 card** — when `prototype-review`: "Open preview" (Cloudflare-Tunnel `preview_url`) +
  explicit **Approve** / **Reject with notes** (never auto-advance, D5). Approve → `developing`.
- **Gate 2 card** — when `pr-review`: link to PR (machine plumbing) + explicit **Approve & merge** /
  **Request changes with notes**. The *decision* is taken here.
- **Clarification thread** — agent questions render as thread messages; the reply box re-enqueues a
  continuation job on send. Reuse the omnichannel conversation thread component if the FR thread
  rides on that store.
- Follow shared-service FE layering + `SearchableSelect`/CRUD-UX standards; delete/destructive
  actions use the confirm dialog standard.
- **Grill chat (Phase-B FE) rides the §4.7 relay.** The BR→FR grilling chat and its FR-draft review
  are authored in Phase B, but they consume this Phase-C bridge (`kind: grill` enqueue + relay +
  continuation). Its reply box calls `enqueue_continuation_grill_job` — the same next-poll mechanism
  the FR clarification box uses. Reuse the omnichannel conversation-thread component for both.

---

## 6. Mac Mini daemon (SEPARATE DEPLOYABLE — not shared-service code)

> **This is a distinct component with its own repo/deploy.** shared-service owns only the *protocol*
> (§5.4, this plan §4). The daemon implementation is out of scope for shared-service PRs; this
> section is the contract + operational design so the daemon team builds to the same bytes.
> **No implementation code is written in Phase C shared-service work.**

### 6.1 Component shape
- A long-running process on the Mac Mini (launchd service). Config = **`{shared_service_url,
  api_key}`** and nothing else from shared-service (D13). Local-only: git creds, deploy creds,
  Cloudflare-Tunnel token, an Anthropic API key for the Agent SDK, and clones/worktrees of the
  served repos.
- Holds the shared-service API key (`fxr_live_…`) in the OS keychain / local secret store.

### 6.2 Poll loop (AC-C-08, 09, 30, 34)
```
loop forever:
    heartbeat()                          # POST /agent-runner/heartbeat (status=online, renew leases)
    if in_flight < concurrency_cap (2):
        jobs = GET /agent-runner/jobs    # long-poll ~25s; returns [] on timeout
        for job in jobs:
            if job.kind == "build": spawn build_worker(job)   # §6.3
            elif job.kind == "grill": spawn grill_worker(job) # §6.6
                                             # bounded by concurrency_cap
    sleep(backoff)                       # short; long-poll already blocks
```
- Outbound-only; nothing listens for inbound. Offline Mac Mini ⇒ jobs simply queue server-side
  (program §6, acceptable).

### 6.3 Build-job execution — one worktree per FR, resumable (AC-C-31, 32, 33)
On receiving `{ kind:"build", fr_id, product_id, repo, branch_base, fr_snapshot, phase_cursor }`:
1. **Worktree** — `git worktree add ../fr-<fr_id> <branch_base>` (create once; reuse on
   continuation). One worktree per FR; a crash/restart re-attaches at `phase_cursor`.
2. **Headless Claude Code (Agent SDK)** — launch against the worktree with the FR snapshot (UAC +
   plan + reuse_analysis) as the driving spec. Emit `progress` callbacks as phases advance.
3. **Three-phase build** (mandated order; skipping ⇒ `error`):
   - **Phase 1 — FE prototype** against mock/stub data. On completion, start the local dev server
     against the **local DB** (prod-data copy), open a **Cloudflare Tunnel**, and callback
     `prototype_ready(preview_url)`. **Pause** — release the job; wait for the continuation job that
     the Gate-1.5 approval will enqueue.
   - **Phase 2 — TDD backend + tests** (red→green→refactor; pytest/vitest/playwright). Resumes from
     the `tdd` continuation job.
   - **Phase 3 — code review** (self-review pass) → **open PR** (`closes #<issue>`), callback
     `pr_opened(pr_url)`. **Pause** for Gate 2.
4. **Reuse backstop (D11, AC-C-28/29)** — before writing new code in Phase 2, run a **code-level
   reuse verify** against the target repo. A substantial-overlap finding → callback
   `clarification_request`/bounce (don't open a PR); wait for the human decision.
5. **Clarifications** — whenever the agent needs a human decision, callback
   `clarification_request(question)`, release the job, and resume from the continuation job carrying
   the answer.
6. **Merge/deploy** — on the Gate-2 merge (driven server-side via GitHub), the daemon (or CI on the
   Mac Mini) runs the deploy using **local-only** creds; deploy result reaches shared-service via the
   deploy webhook. Git push + deploy creds never leave the Mac Mini (AC-C-33).

### 6.4 Resumability & idempotency (AC-C-10, 31)
- Worktree + a small local job-state file per FR let a restart resume mid-phase.
- Every callback carries an `event_id` so a re-sent callback (after a daemon restart) is de-duped
  server-side (AC-C-14).
- The daemon self-limits to `concurrency_cap` (2) in addition to the server cap.

### 6.5 Failure modes
- Daemon offline → server queues jobs (**grill and build alike**); on reconnect the leases it still
  holds re-return on poll.
- Anthropic/API-SDK error mid-build **or mid-grill** → callback `error(message)`; the FR (build) or
  BR/FR-draft (grill) → recoverable state; Maintainer re-queues.
- Cloudflare Tunnel dies → `preview_url` marked expired (AC-C-25); a new preview requires a re-run.

### 6.6 Grill-job execution — relayed BR→FR session, resumable (AC-C-30, 38..42, D11/D20)
On receiving `{ kind:"grill", br_ids[], fr_draft_id?, chat_turn, product_id, repo }`:
1. **Read context** — clone/attach the served `repo` (read-only for grill) and pull the relevant
   Outline docs; Claude Code does **one-pass reuse-analysis over code + Outline** (D11 — no separate
   two-tier).
2. **Headless Claude Code (Agent SDK)** — run a grill session seeded with the BR(s) + the human's
   `chat_turn`. Emit `grill_progress` as it works.
3. **Ask** — when it needs the human, callback `grill_question(question)`, **release the lease**, and
   wait for the continuation grill job the human's next chat turn enqueues (AC-C-40). Resume the same
   session keyed by `fr_draft_id`.
4. **Emit FR** — when the grill converges, callback `fr_emitted(structured_fr)` (acceptance_criteria
   G/W/T, technical_approach, reuse_analysis, slice_scope, grill_notes). shared-service persists it as
   an FR **draft** (never auto-approved, D5) — Gate 1 is the human promote step.
5. **No creds needed** — grill is read-only on the repo; it never pushes, opens PRs, or deploys, so
   git/deploy creds are not used (they remain local-only regardless, AC-C-33). Only the Anthropic key
   (local) and the runner API key are in play.
- **Resumability/idempotency:** a small local grill-session state file per `fr_draft_id` lets a
  restart resume; every callback carries an `event_id` for server-side de-dupe (AC-C-14). Self-limit
  to `concurrency_cap` counts grill and build jobs together.

---

## 7. Phase breakdown (build order within Phase C)

Follows the program methodology (grill → UAC [done] → FE prototype → TDD backend → review). Each
slice is a vertical bite keyed to AC ids.

| Slice | Delivers | AC ids | Notes |
|-------|----------|--------|-------|
| **C1 — AgentRunner + key** | `agent_runners` table, register/rotate/revoke, `get_agent_runner` resolver, hashed key | AC-C-01..05, 35 | Reuse `ApiKeyService` pattern. FE: a minimal "Runners" admin list (register → show plaintext once). TDD from AC-C-02/03/04. |
| **C2 — Job queue + poll** | `agent_jobs` (both kinds), `GET /agent-runner/jobs` long-poll, kind-agnostic lease/idempotency, heartbeat, FR `approved → building` enqueue | AC-C-06..10, 12(part) | Build + grill payloads byte-exact (AC-C-07, 38). Golden-set lease/concurrency tests first. |
| **C3 — Callbacks + FR machine** | `POST /agent-runner/events`, `agent_job_events` de-dupe (build + grill event sets), all transitions in §4.4 | AC-C-11..14, 12, 13 | Idempotency tests first. |
| **C4 — GitHub integration** | issue-create (outbox, 1:1), PR linkage, milestone status-back, GitHub/deploy webhook receiver | AC-C-19..22, 36 | Outbox mirrors `webhook_delivery.py`; issue-create idempotent on `github_issue_ref`. |
| **C5 — Clarification bridge** | FR thread question surfacing, answer → continuation job | AC-C-15..18 | Device-free; no inbound to daemon. |
| **C10 — Grill relay (Phase-B prerequisite)** | `kind: grill` enqueue on BR `grilling`, grill event set (`grill_question`/`fr_emitted`/…), grill-turn → continuation grill job, FR-draft persist | AC-C-38..42 | Rides the C1–C3+C5 substrate. **Must land before Phase B ships** (D20 — Phase B has no other brain). |
| **C6 — Preview + Gate 1.5** | `preview_url` lifecycle, prototype-review FE card, approve/reject | AC-C-23..25, 24 | Cloudflare-Tunnel URL from `prototype_ready`. |
| **C7 — Gate 2 + merge/deploy** | pr-review FE card, approve→merge, merge/deploy webhooks → `done`, Idea/BR roll-up | AC-C-26, 22, 27 | End-to-end trace assertion. |
| **C8 — Reuse backstop** | build-time code-level reuse verify + bounce-back into FR | AC-C-28, 29 | Daemon-side check; server handles the bounce. |
| **C9 — Daemon (separate deployable)** | Poll loop dispatching **both kinds**, build worktree-per-FR + grill session, 3-phase build, resumable, local creds, tunnel | AC-C-30..34, 38..42 (daemon `[T]` + `[E2E]` via bridge) | Built in the daemon repo; verified against the shared-service bridge on staging. |

**Build order is NOT the numeric order.** Slices **C1→C3 + C5 + C10 are the shared bridge substrate
and a prerequisite of Phase B** (grill has no other brain, D20) — deliver them **early, before Phase
B ships**. The build-specific slices **C4, C6, C7, C8** truly gate on an approved FR and can follow.
C1→C3 are the spine (nothing works without them); C4/C5/C6/C7/C10 are independently demonstrable.
The daemon (C9) dispatches both `grill` and `build` kinds and is proved last against the live bridge
— a real BR grilled to an FR draft, then a real FR built to a PR.

---

## 8. Security summary

- **Runner key**: hashed at rest (SHA-256 + prefix + constant-time compare, `app/secrets.py`/
  `ApiKeyService` patterns), plaintext once, revocable, resolves tenant + served products from the
  key (never the body).
- **Git/deploy creds**: local-only on the Mac Mini; the daemon holds *only* the runner API key
  (D13). A leaked runner key can poll/callback but cannot push or deploy.
- **GitHub inbound**: HMAC-verified webhook (mirror `webhooks.py::_signature_valid`), fail-closed in
  prod.
- **Outbound (issue-create/status-back)**: signed + failure-isolated outbox; a broken GitHub can
  never 500 the FR machine.
- **Tenant + product scoping**: every `/agent-runner/*` route restricts to the runner's tenant and
  `served_product_ids`.

---

## 9. Open questions / risks (Phase C-specific; program §6 governs the rest)

1. **Cross-repo delivery is net-new** (program §6) — the daemon⇄shared-service bridge is the
   highest-effort, highest-risk surface. Mitigate by making the *protocol* (§4, §5.4) rock-solid and
   idempotent before the daemon is built; test the bridge with a stub runner (a script that polls +
   posts callbacks) before the real Agent-SDK daemon exists.
2. **Autonomous build quality** — the daemon opening PRs unattended lives or dies on the FR/UAC being
   tight (program §6). Phase C can't fix a loose FR; the reuse backstop (C8) + Gate 1.5/2 are the
   safety nets.
3. **Long-poll at scale** — with concurrency 2 and one runner it's trivial; if more runners land,
   the lease/heartbeat design (C2) must stay correct under concurrent polls (already covered by
   AC-C-10).
4. **Preview against the local (prod-copy) DB** — a prototype that mutates data touches a prod-shaped
   copy; the daemon's local DB must be a *copy*, never prod itself (D14). Confirm the Mac Mini's
   local DB provenance in the daemon runbook.
5. **Continuation-job resume correctness (grill AND build)** — for **build**, the worktree must
   resume at the exact `phase_cursor` with the human answer applied; for **grill**, the session must
   resume against the same `fr_draft_id` with the human's new `chat_turn` applied. A mis-resume of
   either kind silently drops context. Exercise crash-resume + clarification-resume **and
   grill-turn-resume** explicitly (AC-C-10, C-17, C-31, C-40).
6. **Bridge sequencing** — because the bridge is a **Phase-B prerequisite** (D20/C-D13), the
   registration/poll/events/lease/continuation + grill-relay slices (C1–C3, C5, C10) must be built
   and hardened **before** Phase B can grill at all. Slipping the bridge blocks Phase B, not just
   Phase C's build. Test the bridge with a stub runner covering **both** job kinds before the real
   Agent-SDK daemon exists.

---

## 10. Definition of Done (Phase C)

- All AC-C-01…42 PASS (or explicitly DEFERRED with reason) in a Phase-C test report keyed to the
  UAC ids.
- The bridge substrate + grill relay (C1–C3, C5, C10) demonstrably supports **Phase B**: a real BR
  runs a grill round device-free (BR `grilling` → grill job → `grill_question` in chat → human turn →
  continuation grill job → resume → `fr_emitted` → FR draft) with no LLM in shared-service (AC-C-38..42).
- A real FR runs end-to-end on staging: approved → issue → build → prototype preview (Gate 1.5
  approve) → TDD → PR (Gate 2 approve) → merge → deploy → `done`, with the originating Idea rolled
  up to `delivered` and fully traceable (AC-C-27).
- One clarification round exercised device-free (question in FR thread → answer → continuation job →
  resume) (AC-C-15..17).
- One reuse bounce-back exercised (AC-C-28/29).
- Git/deploy creds verified absent from every shared-service payload to the daemon (AC-C-33).
