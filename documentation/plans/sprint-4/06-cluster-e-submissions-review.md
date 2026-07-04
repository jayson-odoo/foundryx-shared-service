# Sprint 4 · Plan 06 — Profile Portal (EMS) + Generic Review/Approval engine (core) + Cluster E config

**Status:** Build-grilled (2026-06-21). Scope EXPANDED TWICE: the review feature surfaced a missing **Profile portal** foundation, and the team chose to **generalize peer-review into a horizontal core Review/Approval engine** (reusable beyond EMS events). Cluster E becomes one *configuration* of that engine.
**Branch (future):** `sprint-4/06-cluster-e`
**Depends on:** `04` core form revisions · F1 form engine (submission + review forms) · rule engine (role allocation conditions) · workflow engine (allocate/escalate actions + triggers) · status engine (scoped review lifecycle).
**Source:** `01-...-grill-decisions.md` §6.9 + the 04 grill + the 2026-06-21 build grills.
**Acceptance criteria:** `06-cluster-e-acceptance-criteria.md` — the testable contract (AC-06-NN) for the coding / test / review agents; the canonical end-to-end flow is §0 there.

---

## Why this plan grew (two reframes)

1. **Reviewers must log in, but Cluster D deferred Profile portal auth.** So this plan builds the **Profile Portal** foundation (Part 1) — and not reviewer-only: it serves **all personas**, dynamic + tenant-configurable.
2. **Don't hard-code "submitter / reviewer / chair."** Peer-review is a special case of a generic pattern: **review/approval over form submissions**. So the engine is built **generic + horizontal in core** (Part 2) — free-form roles + capability flags, identity-agnostic actors (staff Users OR Profiles). "Chair" = a **decide-capable role**, relabelable. Cluster E = an EMS *configuration* + Profile-actor portal surfaces (Part 3).

**Portal ≠ web builder.** (A) Web builder = content/landing-site generator (BL-076, own later plan). (B) Profile portal = a dynamic persona-configurable **authed app**. This plan builds (B).

---

## Part 1 — Profile Portal foundation (EMS; slices 0a + 0b)

### Architectural home
- **EMS-module feature (`app_ems`).** It auths **Profiles** (an EMS table), so core can't own it. EMS owns portal auth + persona RBAC + the surface registry, and **provides the surface registry** other modules register portal surfaces into.

### Profile authentication (slice 0a)
- **Separate Profile auth, reusing core primitives.** `/portal/auth/*`; JWT carries `profile_id` + `tenant_id` + effective **portal-permission keys** (+ scoped persona memberships). `current_profile` dependency (re-resolves tenant-scoped, re-checks tenant lifecycle, mirrors `get_current_user`); `require_portal_permission(key)`.
- **Reuse, don't fork:** `security.py` hashing + 72-byte truncation, throttle store (own scope), single-use token machinery, forgot/set-password convention — all against the **Profile** table (reserved `password_hash`/`email_verified_at`/`last_login_at` light up).
- **Login (TGV-style): password primary + email verification-code (OTP) fallback.** The OTP path doubles as **zero-activation first login** — most Profiles are anonymous email-keyed (no password yet), so they log in by emailed code, optionally set a password after. No explicit claim step; registration confirmation carries a "manage in portal" link.
- **Password setup = three paths:** invite/confirmation set-password link (carries persona+context to grant on acceptance) · self-service forgot-password · explicit staff invite from a role's actor editor.

### Persona / role model (slice 0b) — parallel-to-core RBAC for Profiles
- **NEW Profile-persona system in EMS** (separate from staff RBAC — keeps the staff/external boundary clean).
- **Personas = tenant-configurable roles.** Seeded system personas (`participant`, `reviewer`, `decision_maker`/etc.) delete-locked, keys editable; tenants may add custom.
- **Persona membership is SCOPED per project/context** — a Profile is reviewer on project X, participant on project Y. Membership = `(profile_id, persona_id, scope_type, scope_id)`. Surfaces gate on key **and** scope data to the granting membership's contexts.
- **Gating = portal-permission keys** in a **separate catalog** (`portal_permissions` + `persona_permissions` in `app_ems`, fully separate from core `permissions` — no name-collision; heed the templates.read lesson). Personas grant keys.
- **Persona acquisition = three paths:** auto-derived from domain facts (registration→participant; bound to a review role→reviewer; agenda presenter→presenter) · explicit staff assignment · self-claim via invite link.

### Surface registry (slice 0b)
- **Module-registered portal-surface registry** (mirrors status-entity/terminology/importer registries). Modules register surfaces gated by a portal-permission key; the portal composes + filters like the staff `filterMenu`.

### Portal frontend + UX (slice 0b; consumed by Part 3)
- **New route group `app/(portal)/`** on the tenant subdomain, with its **own Profile NextAuth session** (distinct from the staff `(protected)` session). **Durable real app surfaces** (NOT web-builder-replaceable).
- **Landing = ONE unified dashboard** across all accessible events; sections appear only if the Profile holds the gating key, scoped to its contexts. No persona/context picker.
- **Nav = surface-first + global event filter pill.** Surfaces list items across contexts (context per row) until the filter narrows to one event.

---

## Part 2 — Generic Review/Approval engine (CORE form-engine extension; slice 1 + surfaces in slice 2)

A horizontal review/approval feature over **any** `form_submission`. Role-agnostic, identity-agnostic, reusable by any use-case/client. EMS just *configures* it.

### Core entities (`public` / `app/form_engine/`)
```
review_configurations
  id, tenant_id, name
  form_id            # the SUBMISSION form
  review_form_id     # the rubric form (reviews ARE form_submissions of this)
  required_review_count, score_field_key
  window_start, window_end
  review_start_status_id, revisions_status_id, accepted_status_id, rejected_status_id   # the submission form's scoped statuses
  is_active

review_roles                      # FREE-FORM roles per config; capability-flagged
  id, tenant_id, review_configuration_id
  key, label                      # label = per-config, inline-relabelable (Author/Reviewer/Chair/Approver…)
  can_submit, can_review, can_decide
  actor_source (RULE | EXPLICIT | PERSONA | STAFF_ROLE)
  actor_identity_kind (user | profile)        # UNIFORM per role → clean surface routing
  bound_persona_id | bound_staff_role_id       # for PERSONA / STAFF_ROLE sources
  conditions_json                              # for RULE source (rule tree over submission answers)
  sort_order

review_role_actors                # EXPLICIT source — named actors
  id, role_id, actor_kind, actor_id

review_assignments
  id, tenant_id, review_configuration_id
  reviewed_submission_group_id, revision_number   # plan-04 stable identity + per-revision
  role_id, actor_kind, actor_id
  review_submission_id            # → form_submission of the review form; NULL until graded
  status (PENDING|COMPLETED|ESCALATED|WITHDRAWN), assigned_at, completed_at
  UNIQUE(review_configuration_id, reviewed_submission_group_id, actor_kind, actor_id, revision_number)

review_decisions
  id, tenant_id, review_configuration_id
  reviewed_submission_group_id, revision_number
  decider_kind, decider_id
  decision (ACCEPTED|REJECTED|REVISIONS), feedback_text (nullable), decided_at
```

### Identity-agnostic actors
- Every actor ref = `(actor_kind: user|profile, actor_id)`. A **role is single identity-kind** (`actor_identity_kind` uniform) → surfaces/notifications route by kind without per-member branching.
- **Submission author capture:** author-exclusion + author-visibility need the submission's author as an actor ref. `form_submission.user_id` is User-only; for Profile submitters capture the author actor via `subject_type='profile'`/`subject_id` (or a small form-engine author-actor extension). Resolve tenant-scoped at use (polymorphic-target_id rule).

### Capabilities drive everything (role names are pure display)
- **`can_submit`** gates **who may create a submission** for this config (an actor must hold a can_submit role). Portal/staff "Submit" surfaces show to can_submit actors.
- **`can_review`** → graded via the review form; "My Reviews" queue shows to can_review actors with assignments.
- **`can_decide`** → terminal decision; "Decisions" surface shows to can_decide actors. **Single decider, any can_decide actor — first decision wins** (quorum/sequential = backlog).

### Role population = three sources (the reviewer-pool, generalized)
- **RULE** — `conditions_json` rule tree over submission answers; allocation picks **first-N matches** in `sort_order`.
- **EXPLICIT** — named actors (`review_role_actors`) of one kind (e.g. a fixed decision-maker).
- **PERSONA / STAFF_ROLE binding** — "anyone holding persona X" (Profiles) or "staff role Y" (Users); membership confers the role.

### Workflow actions (CORE-registered ActionDefs)
- **`review.allocate`** (config `review_configuration_id`): for each `can_review` role, populate actors per its source. **If `revision_number > 1`: prefer the prior revision's reviewers** (re-assign those still available; top up via the rules); **else first round: first-N** per RULE order. **Exclude the author**; idempotent (skip already-assigned for this revision); create `review_assignments` + notify. **Seeded as a default workflow** wired to `entity.status_changed → review_start_status_id`.
- **`review.escalate`** (config `review_configuration_id`): `PENDING` past `window_end` → `ESCALATED` + re-run allocation excluding non-responders. Tenant wires a `schedule.cron` workflow (or seeded).

### Generic admin (staff, Resource shell)
- **Standalone core "Review processes" section** — a list of `review_configurations` over ANY form; detail form picks submission form + review form + roles (capabilities + actor source + per-config label) + rules/actors + score field + window + status mapping (SearchSelects over the submission form's scoped statuses). Reusable, discoverable on its own.
- **score_field_key guarded:** config save 422s unless it's a numeric field in the review form's published version; publishing a review-form revision that drops/retypes a referenced score field is blocked. Each review reads its own pinned version → **average is computed on read, live/partial**.

### Core permissions
- `reviews.read` / `reviews.manage` (config admin) + the surface gates: staff `can_review`/`can_decide` actors reach the staff surfaces via core perms (e.g. `reviews.grade` / `reviews.decide`) **AND** their per-config role capability.

---

## Part 3 — Cluster E: events as a Review configuration (slice 1/2 wiring)

EMS configures the generic engine for events + exposes Profile-actor surfaces in the portal.
- **EMS config:** a project's review process = a `review_configuration` over the event's submission form; roles bound to **personas** (reviewer persona, decision-maker persona) so Profiles fill them; EMS seeds a default config + the allocate workflow on install.
- **Submitter = participant.** The `can_submit` role binds to the participant persona; submitting auto-derives the participant persona (already a participant).
- **Status engine still gates participation** (a `blocks_access` profile status refuses the actor).

### Flow (EMS/portal instance)
1. Author opens the **event** in the portal → **Submit** appears while the window is open → fills the submission form → `form_submission` (author actor = profile). Draft→Submitted. (May submit several distinct submissions to one call — each its own `submission_group`.)
2. Workflow on `status_changed → review_start_status_id` runs `review.allocate` → assignments + notifications.
3. **Reviewer (Profile, can_review)** → portal **My Reviews** → **two-pane**: read-only submission (FormRenderer, pinned version) + review form; **draft-save/resume**; submit (Draft→Submitted) sets `review_submission_id` + COMPLETED. Reviewers never see each other's reviews.
4. **Decision-maker (Profile, can_decide)** → portal **Decisions** surface: live partial average + a **"ready" badge** at `required_review_count` (but **may decide early**). Decision → `review_decisions` row (+ optional feedback) + fires the status transition (accepted/rejected/revisions).
5. **Revisions:** → `revisions_status_id` → author revises (new revision, **only while the window is open**) → re-enters → re-allocate, **prior reviewers preferred**.
6. **Author visibility:** lifecycle status + the decision **+ optional feedback only** — raw reviews/scores hidden.
7. **Accepted** submission referenceable by an agenda session (Cluster G, via `submission_group_id`); presenter = author Profile.

### Surfaces (both identity worlds — capability-gated)
- **Staff app (core, `(protected)`):** Review-processes admin · staff **My Reviews** + **Decisions** for `user`-kind actors (gated by core perms + per-config capability).
- **Portal (EMS, `(portal)`):** **My Submissions** (Submit/Revise + status + decision/feedback) · **My Reviews** (two-pane grade) · **Decisions** — for `profile`-kind actors (gated by portal keys + capability + persona scope).
- The assignment's `actor_kind` routes a person to the correct world.

---

## Slices
- **0a — Profile auth/session:** `/portal/auth/*` (password + OTP + set/forgot), `current_profile` + `require_portal_permission`, throttle scope, `(portal)` NextAuth session shell.
- **0b — Persona RBAC + surface registry + portal shell:** persona/permission tables + separate portal catalog, scoped memberships, three grant paths, surface registry, persona-gated portal nav + unified dashboard, staff persona-management UI.
- **1 — Generic Review engine (core):** schema (configs/roles/capabilities/identity-agnostic actors/assignments/decisions); 3 actor sources; `review.allocate` (first-N + author-exclusion + prior-reviewer preference) + `review.escalate`; seeded default workflows; live average; score-field guard; standalone "Review processes" admin; EMS event-config wiring + persona binding + seed.
- **2 — Surfaces + decision + revisions:** staff **and** portal My Submissions / My Reviews (two-pane, draft-save) / Decisions (early decision, `review_decisions`, feedback); revisions loop (consume plan 04, window-gated, prior-reviewer preference).

## Verification
- **Portal E2E** (OTP login + password login → My Submissions submit → reviewer two-pane grade → decision-maker decide → author sees decision+feedback → revise → same reviewer re-reviews) **+ staff E2E** (review-processes config / roles+sources / staff My Reviews / staff Decisions / persona mgmt) **+ backend pytest** (Profile auth+OTP, persona RBAC scoping, all 3 actor sources, allocation first-N + author-exclusion + prior-reviewer preference, escalation, identity-agnostic routing, live average, score-field guard, per-revision re-allocation, early decision, window-gated revision). Full house process.

## Open / deferred → backlog
- **(A) Content web builder** — own later plan (BL-076).
- **Quorum / sequential multi-approval** decisions (v1 = single decider, first-wins) · **mixed-identity roles** (v1 = single kind per role) · weighted/multi-criteria scoring (v1 = one score field, average) · double-blind anonymization · org-level COI · load balancing (v1 = first-N by rule order) · reviewer self-nomination/bidding · auto-threshold accept · multi-track (multiple submission forms per project) · review dashboard/analytics · camera-ready upload. Agenda binding → Cluster G.
