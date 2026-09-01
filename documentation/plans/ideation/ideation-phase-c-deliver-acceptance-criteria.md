# UAC - Ideation Phase C (Deliver)

**Keys back to:** `PLAN-ideation-to-delivery-program.md` (program spine) - §2 (D2, D11-D15, D17,
D20), §3 (AgentRunner, FunctionalRequirement), §5.4 (Mac Mini bridge - canonical, carries BOTH
grill and build). **If a contract here disagrees with §5.4, §5.4 wins and this file is wrong - fix
it there first.**

**Scope of Phase C:** the `AgentRunner` integration + **Mac Mini bridge** in **shared-service**, the
**Mac Mini daemon** (a separate deployable), the **GitHub integration**, the **Cloudflare-Tunnel
preview**, the **clarification bridge**, and the two build-time human gates (1.5 prototype-eyeball,
2 PR-eyeball). Depends on Phase A (Product, Idea, contacts, embed host) and Phase B (BR, FR,
templates, grilling, Gate 1 = FR approved).

**Bridge is foundational infra shared with Phase B (D20, §5.4).** shared-service has no brain - so
grilling a BR→FR is ALSO a job dispatched to Claude Code on the Mac Mini, not just building an
FR→PR. The same bridge (registration + outbound poll + events + continuation-resume) carries both
`kind: grill` and `kind: build` jobs. The registration/poll/events/resume substrate (§A-C, F below)
therefore must be **built once, early** - before Phase B's grill can work - even though it is
authored in this Phase-C file. Grill-job handling ACs (§K) are stated here alongside build so the
one bridge is specified in one place.

**Tags:** `[BE]` shared-service backend · `[FE]` shared-service embedded UI · `[E2E]` end-to-end
across daemon⇄shared-service⇄GitHub · `[T]` unit/service test. The daemon is a separate component;
its behaviour is asserted through `[E2E]` (observable via the bridge) and daemon-side `[T]`.

**Legend for status:** each AC is independently verifiable Given/When/Then. The Phase-C test report
keys PASS/FAIL/DEFERRED back to these ids.

---

## A. AgentRunner registration + API key (§3, §5.4 "Registration")

### AC-C-01 [BE] Register an AgentRunner
- **Given** a Maintainer on the Foundryx-internal tenant,
- **When** they create an `AgentRunner` with `name`, `served_product_ids[]`, and `concurrency_cap`
  (default `2`),
- **Then** a row persists with `status="offline"`, `last_seen=null`, and an `api_key_hash` is set;
  the API key **plaintext is returned exactly once** in the create response and never again.

### AC-C-02 [BE][T] API key is hashed at rest, never stored in plaintext
- **Given** an AgentRunner was created,
- **When** its row is inspected,
- **Then** only a SHA-256 `api_key_hash` + short lookup `key_prefix` exist (mirroring
  `modules/omnichannel/services/api_key_service.py`); resolution is a prefix lookup + constant-time
  `hmac.compare_digest`; no column, log, or API response ever holds the plaintext after issuance.

### AC-C-03 [BE] Key resolves to (tenant, runner, served_product_ids)
- **Given** a valid `Authorization: Bearer <runner key>`,
- **When** any `/agent-runner/*` route is called,
- **Then** the runner, its tenant, and `served_product_ids` are derived **from the key** (never the
  request body/query); an unknown, malformed, or revoked key → uniform `401` with no enumeration.

### AC-C-04 [BE] Revoke a runner key
- **Given** a registered runner,
- **When** the Maintainer revokes its key,
- **Then** the next poll/callback from that daemon fails `401`, `status` flips to `offline`, and a
  fresh key can be re-issued without deleting the runner's history.

### AC-C-05 [BE] Concurrency cap enforced server-side (default 2)
- **Given** a runner with `concurrency_cap=2` that already holds 2 in-flight jobs,
- **When** it polls for more,
- **Then** the jobs endpoint returns **empty** until an in-flight job reaches a terminal callback
  (`pr_opened`/`error`) or is released; the cap is enforced by shared-service, not trusted from the
  daemon.

---

## B. Outbound poll - `GET /agent-runner/jobs` (§5.4 "Outbound poll", "Job payload")

### AC-C-06 [BE] Poll returns only queued jobs for served products
- **Given** queued jobs of **both kinds** (`grill` and `build`, §5.4) across several products,
- **When** a runner long-polls `GET /agent-runner/jobs`,
- **Then** it receives **only** jobs whose `product_id ∈ served_product_ids`, oldest-first, bounded
  by remaining concurrency; jobs for other products are never disclosed; each job carries a
  `kind ∈ {grill, build}` discriminator so the daemon dispatches to the right handler.

### AC-C-07 [BE][T] Build-job payload shape is exact
- **Given** a queued **build** job,
- **When** it is returned by the poll,
- **Then** the payload is exactly
  `{ kind: "build", fr_id, product_id, repo, branch_base, fr_snapshot (UAC+plan+reuse), phase_cursor }`
  - byte-consistent with §5.4. `fr_snapshot` embeds the FR's acceptance criteria (UAC), technical
  approach, and `reuse_analysis`; `phase_cursor` tells the daemon where to resume
  (`prototype`/`tdd`/`review`).

### AC-C-08 [BE] Poll is outbound-only; no inbound to the Mac Mini
- **Given** the daemon behind NAT with no inbound port,
- **When** the whole delivery lifecycle runs,
- **Then** shared-service **never** connects to the daemon; every job hand-off is the daemon pulling
  via `GET /agent-runner/jobs`, and every continuation is picked up on a subsequent poll (D13).

### AC-C-09 [BE] Heartbeat sets status=online + last_seen
- **Given** a running daemon,
- **When** it polls or heartbeats,
- **Then** the runner `status` becomes `online` and `last_seen` is stamped; after a configured
  silence window with no poll/heartbeat, `status` reverts to `offline` (Mac Mini offline = builds
  queue, acceptable - program §6).

### AC-C-10 [BE][T] Job lease is idempotent / at-least-once safe (grill + build)
- **Given** a job of **either kind** (`grill` or `build`) handed to a runner,
- **When** the same runner re-polls (crash-resume) before finishing,
- **Then** it re-receives the **same** job (leased to it, not re-issued to a second runner) with the
  correct resume cursor (`phase_cursor` for build, `chat_turn`/thread cursor for grill); a job is
  never delivered to two runners at once. Lease + idempotency are `kind`-agnostic.

---

## C. Callbacks - `POST /agent-runner/events` (§5.4 "Callbacks")

### AC-C-11 [BE][T] Build callback envelope + kinds are exact
- **Given** an authenticated runner on a **build** job,
- **When** it posts `POST /agent-runner/events`,
- **Then** the body is `{ fr_id, kind, ... }` where
  `kind ∈ {progress, prototype_ready, clarification_request, pr_opened, phase_done, error}`;
  `prototype_ready` carries `preview_url`, `clarification_request` carries `question`, `pr_opened`
  carries `pr_url` (byte-consistent with §5.4). A runner may only post events for FRs whose product
  it serves (else `403`). Grill-job callbacks use the same endpoint with the grill event set (§K).

### AC-C-12 [BE] progress + phase_done advance the FR machine
- **Given** an FR in `building`,
- **When** `phase_done` (prototype) then `phase_done` (developing) arrive,
- **Then** the FR status moves along `building → prototype-review → developing → pr-review` and each
  transition is recorded; `progress` updates a visible progress field **without** changing status.

### AC-C-13 [BE] error moves the FR to a recoverable state
- **Given** an in-flight build,
- **When** the daemon posts `error` with a message,
- **Then** the FR moves to `blocked`, the error surfaces in the FR thread (device-free), the job
  lease is released, and re-queuing the FR is a first-class Maintainer action (no data loss).

### AC-C-14 [BE][T] Callback idempotency (grill + build)
- **Given** the daemon retries a callback (network flap) on **either** a grill or a build job,
- **When** the same `{job_id, event_id}` arrives twice,
- **Then** the target machine advances **once** - the FR machine for build events, the grill/FR-draft
  thread for grill events; duplicate callbacks are absorbed, not double-applied.

---

## D. Clarification bridge (D15, §5.4 "Human answers")

### AC-C-15 [BE] Agent question surfaces into the FR thread
- **Given** a build in progress,
- **When** the daemon posts `clarification_request(question)`,
- **Then** the FR status becomes `awaiting-clarification`, the question appears as a message in the
  **FR thread in shared-service** (the ONLY human surface), and the job lease is released so the
  runner's concurrency slot frees up.

### AC-C-16 [FE] Human answers in the embedded FR thread - device-free
- **Given** a Maintainer viewing the FR (via the sorento iframe embed, seamless SSO),
- **When** they read the agent's question and reply in the thread,
- **Then** no GitHub, terminal, or Mac Mini access is required; the answer is captured against the FR.

### AC-C-17 [BE][E2E] Answer re-enqueues a continuation job (no inbound to daemon)
- **Given** an FR in `awaiting-clarification` with a human answer,
- **When** the answer is submitted,
- **Then** shared-service **re-enqueues a continuation job** carrying the answer + the resume
  `phase_cursor`; the daemon picks it up on its **next poll** and resumes the same worktree - nothing
  is pushed to the Mac Mini (D15, §5.4). The **same next-poll continuation mechanism** carries a
  human grill turn back to the daemon (§K, AC-C-40) - continuation-resume is not build-only.

### AC-C-18 [BE] GitHub stays machine-only during clarification
- **Given** a clarification round,
- **When** the human answers in shared-service,
- **Then** no human ever posts on GitHub; GitHub carries only machine artifacts (issue, PR,
  milestone) - the FR thread is authoritative for the Q&A (D15).

---

## E. GitHub integration (§2, milestone status-back)

### AC-C-19 [BE] Create a GitHub issue from an FR (1:1)
- **Given** an FR reaching `approved` (Gate 1),
- **When** the delivery pipeline starts,
- **Then** exactly **one** GitHub issue is created for that FR (D4: FR→issue 1:1), its ref stored in
  `FunctionalRequirement.github_issue_ref`, and the issue body carries the FR snapshot (UAC + plan);
  re-running never creates a second issue for the same FR (idempotent on `github_issue_ref`).

### AC-C-20 [BE] PR linkage stored on the FR
- **Given** the daemon opens a PR (`pr_opened(pr_url)`),
- **When** the callback is processed,
- **Then** `FunctionalRequirement.pr_ref` is set and the PR is linked to the issue (closes-issue
  reference), so one idea is traceable Idea→BR→FR→issue→PR→merge→deploy end to end (Vision §1).

### AC-C-21 [BE][T] Milestone-only status-back mapping
- **Given** the build advancing,
- **When** each milestone fires,
- **Then** the FR status reflects **only** the milestone ladder
  `issue_created → building → prototype_review → developing → pr_review → merged → deployed`
  (D12: milestone-only, no fine-grained GitHub chatter mirrored into shared-service).

### AC-C-22 [BE] Merge + deploy webhook drives merged → deployed → Delivered
- **Given** a PR approved at Gate 2,
- **When** it is merged and the deploy completes,
- **Then** the FR moves `pr-review → merged → deployed → done`, the linked Idea/BR roll up to
  `delivered`, and the merge/deploy status arrives via a GitHub/deploy webhook (machine-only).

---

## F. Cloudflare-Tunnel preview + Gate 1.5 (D14)

### AC-C-23 [E2E] Prototype preview is a Cloudflare Tunnel to the Mac Mini session
- **Given** the daemon finished Phase-1 FE prototype in a worktree running against the **local DB**
  (prod-data copy, D14),
- **When** it posts `prototype_ready(preview_url)`,
- **Then** `preview_url` is a Cloudflare-Tunnel URL to that live Mac Mini session (not a shared-
  service-hosted build), and the FR enters `prototype-review`.

### AC-C-24 [FE] Gate 1.5 - prototype-eyeball
- **Given** an FR in `prototype-review` with a `preview_url`,
- **When** the Maintainer opens it from the FR detail (embedded UI),
- **Then** they can click through the live prototype; an **explicit approve** advances to
  `developing` (Phase-2 TDD backend) and an **explicit reject/bounce** returns the FR to grilling
  with notes - never auto-advanced (D5 "never auto-promote", D12).

### AC-C-25 [BE] Preview URL lifecycle
- **Given** a prototype approved or the session ended,
- **When** the build moves past Phase 1,
- **Then** the `preview_url` is marked stale/expired in the FR record so a dead tunnel is never
  presented as live.

---

## G. Gate 2 (PR-eyeball) → merge → deploy (D12)

### AC-C-26 [FE] Gate 2 - PR-eyeball
- **Given** an FR in `pr-review` with a `pr_ref`,
- **When** the Maintainer reviews (link out to the PR is machine-plumbing; the **decision** is taken
  in shared-service),
- **Then** an explicit approve triggers merge; an explicit request-changes bounces the FR back to
  `developing` with notes carried into a continuation job. The two build gates (1.5, 2) are both
  human-explicit (D12: exactly three gates - FR-approved, prototype-eyeball, PR-eyeball).

### AC-C-27 [E2E] Delivered end-to-end trace
- **Given** a merged + deployed FR,
- **When** the pipeline completes,
- **Then** the FR is `done` and the originating Idea is traceable through BR→FR→issue→PR→commit→
  deploy (Vision §1) - one idea, one shipped slice, fully linked.

---

## H. Two-tier reuse backstop (D11)

### AC-C-28 [E2E] Code-level reuse verify at build time
- **Given** an FR whose planning-time `reuse_analysis` (Outline docs, Phase B) may be blind to
  technical dupes (program §6 "Outline staleness"),
- **When** the daemon builds, it runs a **code-level reuse check** against the target repo before
  writing new code,
- **Then** a real duplication/overlap finding is produced (not a doc lookup) - this is the second
  tier that Phase-B doc reuse cannot catch.

### AC-C-29 [BE] Reuse finding bounces back to the FR (D11)
- **Given** the build-time reuse check finds the slice substantially already exists,
- **When** the finding is reported,
- **Then** it surfaces as a `clarification_request`/bounce into the FR thread (device-free), the FR
  moves to `bounced`/`awaiting-clarification`, and no PR is opened until a human resolves reuse-vs-
  build - a wasted duplicate build is prevented.

---

## I. Mac Mini daemon behaviour (separate deployable - asserted via bridge + daemon-side [T])

### AC-C-30 [T] Poll loop drives headless Claude Code (Agent SDK) for both job kinds
- **Given** the daemon configured with `{shared_service_url, api_key}` only,
- **When** it receives a job,
- **Then** it dispatches on `kind`: a `build` job launches the three-phase build worker (§I), a
  `grill` job launches a **headless Claude Code (Agent SDK)** grill session (reads code + Outline,
  streams Q/A, emits the FR - §K); the daemon holds **no** shared-service secrets beyond the API key
  (D13).

### AC-C-31 [T] One git worktree per FR, resumable
- **Given** a build job for `fr_id`,
- **When** the daemon starts (or resumes via a continuation job),
- **Then** it uses **one dedicated git worktree per FR** off `branch_base`; a crash/restart resumes
  the **same** worktree at the `phase_cursor`, never losing prior phase output.

### AC-C-32 [T] Three-phase build inside the daemon
- **Given** a fresh FR job,
- **When** the daemon runs it,
- **Then** it executes the mandated three phases in order - **Phase 1 FE prototype** (→
  `prototype_ready`, Gate 1.5) → **Phase 2 TDD backend + tests** (red→green→refactor) → **Phase 3
  code review** → open PR (`pr_opened`, Gate 2) - matching the program's methodology; skipping a
  phase is a violation the daemon surfaces as `error`.

### AC-C-33 [T] Git/deploy creds are LOCAL-ONLY
- **Given** the daemon needs to push, open PRs, and deploy,
- **When** it performs those operations,
- **Then** it uses git/deploy credentials that live **only on the Mac Mini**; shared-service never
  transmits them and the daemon never requests them over the bridge (D13, §5.4 "Creds").

### AC-C-34 [T] Concurrency 2 respected daemon-side
- **Given** `concurrency_cap=2`,
- **When** more jobs are available,
- **Then** the daemon runs at most 2 FR builds simultaneously (belt-and-braces with the server-side
  cap of AC-C-05).

---

## J. Cross-cutting

### AC-C-35 [BE][T] All delivery-bridge routes are API-key-gated + tenant-scoped
- **Given** the `/agent-runner/*` surface,
- **When** called without a valid runner key,
- **Then** every route (jobs, events, heartbeat) returns `401`; a runner can only see/affect FRs of
  its own tenant + `served_product_ids`.

### AC-C-36 [BE] Delivery is failure-isolated from the spine
- **Given** the GitHub API or the daemon is down,
- **When** a callback or issue-create fails,
- **Then** it is retried out-of-band (outbox pattern, mirroring
  `modules/omnichannel/services/webhook_delivery.py`) and never 500s or corrupts the FR record; the
  FR simply stays in its current state until the dependency recovers.

### AC-C-37 [FE] FR detail shows the full delivery timeline
- **Given** an FR that has run through delivery,
- **When** a Maintainer opens it in the embedded UI,
- **Then** the milestone ladder, current status, progress, preview/PR links, and the clarification
  Q&A thread are all visible in one device-free surface (D15, D17) - no need to leave shared-service.

---

## K. Grill jobs over the same bridge (D11, D20, §5.4 "Grill job payload")

> The bridge carries `kind: grill` as well as `kind: build`. shared-service has no brain (D20), so
> grilling a BR→FR is a job dispatched to Claude Code on the Mac Mini and relayed back. These ACs
> reuse the same registration/poll/events/lease/continuation substrate (§A-C) - only the payload,
> event set, and terminal artifact differ. This substrate is **foundational for Phase B** and must
> be built before the grill can work.

### AC-C-38 [BE][T] Grill-job payload shape is exact
- **Given** a BR (or set of BRs) entering `grilling` (Phase B) and a runner serving that product,
- **When** the grill job is returned by `GET /agent-runner/jobs`,
- **Then** the payload is exactly
  `{ kind: "grill", br_ids[], fr_draft_id?, chat_turn, product_id, repo }` - byte-consistent with
  §5.4. `fr_draft_id` is absent on the first turn and present on continuation; `chat_turn` carries
  the human's latest grill message; `repo` lets Claude Code read code alongside Outline for one-pass
  reuse-analysis (D11).

### AC-C-39 [BE][T] Grill callback events surface Q/A and emit the FR
- **Given** a runner on a grill job,
- **When** it posts `POST /agent-runner/events`,
- **Then** the grill event set is honoured:
  `kind ∈ {grill_progress, grill_question, clarification_request, fr_emitted, error}` -
  `grill_question` carries the agent's next question (appended to the shared-service grill chat),
  `fr_emitted` carries the structured FR (acceptance_criteria G/W/T, technical_approach,
  reuse_analysis, slice_scope, grill_notes) which shared-service persists as an FR **draft** (never
  auto-approved, D5). Events are idempotent per `{job_id, event_id}` (AC-C-14).

### AC-C-40 [BE][E2E] Human grill turn re-enqueues a continuation grill job (no inbound to daemon)
- **Given** a grill session paused after `grill_question`, awaiting a human reply in the
  shared-service grill chat,
- **When** the human sends their next turn,
- **Then** shared-service **re-enqueues a continuation grill job** carrying `fr_draft_id` + the new
  `chat_turn`; the daemon picks it up on its **next poll** and resumes the same grill session -
  nothing is pushed to the Mac Mini (D13, D15, §5.4). Continuation-resume works identically for
  grill and build.

### AC-C-41 [FE] Grill chat is the device-free surface; FR emitted as a draft
- **Given** a Maintainer/Triager grilling a BR in the embedded shared-service chat (via the sorento
  iframe, seamless SSO),
- **When** the exchange completes and the daemon posts `fr_emitted`,
- **Then** the generated FR appears as a **draft** for human review → explicit promote/approve at
  Gate 1 (D5 "never auto-promote", D12); no GitHub, terminal, or Mac Mini access is required at any
  point.

### AC-C-42 [BE] Grill jobs offline-queue and are failure-isolated like build jobs
- **Given** the Mac Mini offline,
- **When** a BR enters `grilling`,
- **Then** the grill job simply **queues** server-side until the daemon polls again (program §6,
  same as builds); a daemon/Anthropic error posts `error`, the BR/FR-draft stays recoverable, and the
  spine never 500s (AC-C-36 applies to `kind: grill` too).
