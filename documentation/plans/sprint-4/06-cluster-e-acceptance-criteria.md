# Sprint 4 · Plan 06 - Acceptance Criteria

**Scope:** Profile Portal foundation (EMS) + Generic Review/Approval engine (core) + Cluster E event configuration.
**Plan:** `06-cluster-e-submissions-review.md`. **Status:** authored 2026-06-21 from the build grills.
**Audience:** the coding agent (build target), the test agent (what to verify, real-click E2E + pytest), the review agent (merge gate). Each AC is atomic + verifiable. ID = `AC-06-NN`.

> **Definition of done for the plan:** every AC below is met, the full test matrix (§9) is green, the house process (frontend-first, TDD, Playwright real clicks at 375px + 1280px, code-review approval) is satisfied, and no hard-fail rule (DB in router, component fetching directly, `any`, raw CSS/`<style>`, module altering core tables) is violated.

---

## 0. Canonical end-to-end flow (the basis scenario)

This is the reference happy-path the test agent automates as the primary E2E (EMS event peer-review instance). Each step is an AC.

- **AC-06-01 Setup (staff):** A staff user with `reviews.manage` creates a `review_configuration` over an event submission form: picks submission form, review (rubric) form, `score_field_key`, `required_review_count`, window, and maps `review_start/revisions/accepted/rejected` to the submission form's scoped statuses. Defines roles - Author (`can_submit`, source PERSONA→participant), Reviewer (`can_review`, source RULE), Decision-maker (`can_decide`, source EXPLICIT→a Profile) - with per-config labels. EMS has seeded the default allocate workflow (trigger `entity.status_changed → review_start_status_id` → `review.allocate`).
- **AC-06-02 Author login (portal):** An anonymous email-keyed participant Profile logs into the portal by **email OTP** (no password set), with no prior activation step, and lands on the unified dashboard.
- **AC-06-03 Submit:** On an event where the Profile holds a `can_submit` role and the window is open, a **Submit** action renders; submitting creates a `form_submission` with the author actor captured as `(profile, id)` and drives the scoped graph Draft→Submitted. It appears in My Submissions with status.
- **AC-06-04 Allocate:** The Submitted transition fires the workflow; `review.allocate` resolves `can_review` actors per source (RULE = first-N up to `required_review_count`), **excludes the author**, creates `review_assignments` at `revision_number=1`, and notifies reviewers.
- **AC-06-05 Review:** A Reviewer Profile opens My Reviews, opens the two-pane grade view (read-only submission at its pinned version ‖ review form), saves a draft, resumes, and submits the review; the review's `form_submission` goes Draft→Submitted, `review_assignment.review_submission_id` is set and status = COMPLETED. A reviewer cannot see another reviewer's review.
- **AC-06-06 Average:** The submission's average of `score_field_key` is computed on read and shows live/partial as reviews complete.
- **AC-06-07 Decide:** A Decision-maker opens Decisions, sees the live average + a "ready" badge once `required_review_count` is met (and may decide before it is met), expands individual reviews, chooses Accept/Reject/Revisions with optional feedback → a `review_decisions` row is written and the corresponding status transition fires.
- **AC-06-08 Accepted/Rejected:** On accept/reject the submission lands on the mapped terminal status; the author sees lifecycle status + decision + optional feedback only (no raw reviews/scores).
- **AC-06-09 Revisions loop:** On Revisions the submission moves to `revisions_status_id`; the author (while the window is open) revises → a new revision (plan-04 clone) re-enters `review_start_status_id`; `review.allocate` re-runs with `revision_number>1` preferring the prior revision's reviewers (topping up via rules). Flow returns to AC-06-05.
- **AC-06-10 Identity routing:** The same configuration with a `can_review` role sourced from a STAFF_ROLE produces assignments with `actor_kind=user`; those reviewers grade in the **staff app** My Reviews, not the portal. `actor_kind` alone decides the surface.

---

## 1. Profile authentication (slice 0a)

- **AC-06-11** Profile auth is a SEPARATE system under `/portal/auth/*`; it never reuses or collides with the staff `/auth/*` endpoints or session.
- **AC-06-12** Login accepts **password** (primary) and **email verification code / OTP** (fallback). A Profile with no `password_hash` can log in via OTP with no prior activation/claim step.
- **AC-06-13** A logged-in Profile is identified per request by a `current_profile` dependency that resolves the Profile **tenant-scoped** and re-checks tenant lifecycle (suspended/archived tenant → 403), mirroring `get_current_user`. The JWT carries `profile_id`, `tenant_id`, effective portal-permission keys, and scoped persona memberships.
- **AC-06-14** `require_portal_permission(key)` gates every protected portal endpoint; portal endpoints never accept a `tenant_id` from client input.
- **AC-06-15** Password setup works via all three: (a) invite/confirmation **set-password link** (single-use, carries the persona+context to grant on acceptance), (b) **self-service forgot-password** (uniform 200, no enumeration, throttled), (c) **explicit staff invite** from a role's actor editor.
- **AC-06-16** Profile auth reuses core primitives - bcrypt hashing with 72-byte truncation, single-use token machinery (expiry + single redeem), and an **own throttle scope** distinct from the staff login bucket. OTP requests and failed redeems pump the throttle.
- **AC-06-17** OTP codes and reset/set-password tokens are single-use and expiring; a mail-scanner prefetch / re-click must not consume a live token twice (explicit-click redeem).
- **AC-06-18** Frontend: the `(portal)` route group has its **own NextAuth session** carrying the Profile JWT, fully separate from the staff `(protected)` session; logging into one does not authenticate the other.

## 2. Persona RBAC + surface registry + portal shell (slice 0b)

- **AC-06-19** Personas are tenant-configurable roles stored in `app_ems`, fully separate from the core `permissions` catalog. Seeded **system personas** are delete-locked (keys editable); tenants can create custom personas.
- **AC-06-20** Persona membership is **scoped** `(profile_id, persona_id, scope_type, scope_id)` with a uniqueness constraint; a Profile can hold different personas in different contexts.
- **AC-06-21** Portal-permission keys live in a **separate** `portal_permissions` catalog (+ `persona_permissions` grants); adding a key never touches the core `permissions` table (no name-collision). Personas grant portal keys.
- **AC-06-22** Persona acquisition works via all three paths: auto-derived from domain facts (e.g. registration → participant; bound to a review role → reviewer), explicit staff assignment, and invite self-claim.
- **AC-06-23** A **module-registered portal-surface registry** exists; surfaces declare a gating portal-permission key; the portal composes and filters visible surfaces (childless/empty surfaces hidden), mirroring the staff `filterMenu`. Other modules can register surfaces without core edits.
- **AC-06-24** Portal landing = ONE unified dashboard aggregating every surface the Profile can access across all events; a section renders only if its gating key is held, and its data is scoped to the granting membership's contexts. No persona/context picker on entry.
- **AC-06-25** Portal nav is surface-first with a **global event/context filter pill** that narrows every surface to one event; unfiltered, surfaces show items across contexts with the context per row.
- **AC-06-26** Staff persona-management UI (Resource shell) lets `reviews.manage`/appropriate-perm staff configure personas, grant portal keys, and assign personas to Profiles.

## 3. Generic Review/Approval engine - core (slice 1)

- **AC-06-27** The engine is a **core** form-engine extension operating on any `form_submission`; nothing in core depends on the EMS Profile table. Schema = `review_configurations`, `review_roles`, `review_role_actors`, `review_assignments`, `review_decisions` (per the plan).
- **AC-06-28** `review_roles` are free-form per config with capability flags `can_submit`/`can_review`/`can_decide`; **role behavior is driven by capabilities, role label is display-only** and per-config inline-relabelable.
- **AC-06-29** Each role is **single identity-kind** (`actor_identity_kind` ∈ {user, profile}); a role cannot mix Users and Profiles. Every actor reference is `(actor_kind, actor_id)`.
- **AC-06-30** Role population supports all three sources: **RULE** (rule tree over submission answers, first-N by `sort_order`), **EXPLICIT** (named actors of the role's kind), **PERSONA/STAFF_ROLE** binding (membership confers the role).
- **AC-06-31** `can_submit` gates **who may create a submission** for a config - an actor lacking a `can_submit` role for the config cannot submit (backend enforced; UI hides Submit).
- **AC-06-32** `review.allocate` (core ActionDef): excludes the author; on `revision_number=1` allocates first-N per RULE order; on `revision_number>1` prefers the prior revision's reviewers and tops up via the rules; is idempotent (skips already-assigned for the revision); creates assignments + notifies. Seeded as the default workflow wired to `status_changed → review_start_status_id`.
- **AC-06-33** `review.escalate` (core ActionDef): marks PENDING assignments past `window_end` as ESCALATED and re-runs allocation excluding non-responders.
- **AC-06-34** Decision is **single decider, first-wins**: any `can_decide` actor may decide; the first decision writes `review_decisions` and fires the transition; a second concurrent attempt is a no-op/409, not a double transition.
- **AC-06-35** Average is **computed on read** from completed reviews' `score_field_key` (no stored/denormalized column); partial averages display before `required_review_count`.
- **AC-06-36** `score_field_key` is guarded: config save 422s unless the key is a numeric field in the review form's published version; publishing a review-form revision that removes/retypes a referenced score field is blocked.
- **AC-06-37** `review_assignments` UNIQUE = `(config, submission_group, actor_kind, actor_id, revision_number)`; assignments are per-revision (prior rounds retained as history).
- **AC-06-38** Standalone core **"Review processes"** admin (Resource shell) lists/creates/edits `review_configurations` over any form, with role/capability/source editing, rule builder for RULE roles, score field, window, and status mapping via SearchSelects over the submission form's scoped statuses.
- **AC-06-39** Core permissions `reviews.read`/`reviews.manage` (+ surface gates `reviews.grade`/`reviews.decide`) are added via the core permissions CSV and granted to tenant Admin; the existing core permission catalog has no key collision.
- **AC-06-40** Workflow dispatch is failure-isolated: a broken/slow allocate/escalate workflow can never 500 or block the triggering submit/transition request.

## 4. Submission author capture (form-engine touch)

- **AC-06-41** A submission's author is captured as an identity-agnostic actor ref; for a Profile submitter it is recorded (`subject_type='profile'`/`subject_id`, or an equivalent author-actor ref) and resolved **tenant-scoped** at use (polymorphic-target_id rule - validate at save, scope at read).
- **AC-06-42** Author-exclusion (AC-06-32) and author-visibility (AC-06-08) both read this author ref; a User-authored submission and a Profile-authored submission both resolve correctly.

## 5. Surfaces - staff app + portal (slice 2)

- **AC-06-43 (portal)** **My Submissions**: per-event Submit (window-gated), list of the Profile's submissions with lifecycle status + decision + optional feedback, and a **Revise** action when in `revisions_status` and the window is open. Raw reviews/scores are never shown.
- **AC-06-44 (portal)** **My Reviews**: queue of the Profile's assignments (PENDING/COMPLETED, due = `window_end`) → two-pane read-only submission (pinned version) + review form with **draft-save/resume**.
- **AC-06-45 (portal)** **Decisions**: for `can_decide` Profile actors - live average, ready badge, individual reviews, accept/reject/revisions with optional feedback, early decision allowed.
- **AC-06-46 (staff)** Mirror **My Reviews** + **Decisions** in the staff `(protected)` app for `user`-kind actors, gated by core perms (`reviews.grade`/`reviews.decide`) AND per-config role capability.
- **AC-06-47** A person is routed to exactly one world by the assignment/role `actor_kind`; a Profile actor never sees the staff surface and vice versa.
- **AC-06-48** Reviews are isolated: no surface (staff or portal) shows one reviewer another reviewer's review content.

## 6. Cluster E configuration (Part 3)

- **AC-06-49** EMS seeds, on install, an event review configuration pattern + the default allocate workflow + system personas (participant, reviewer, decision-maker) and their portal-key grants.
- **AC-06-50** Event roles bind to personas (reviewer/decision-maker personas → Profiles); submitting auto-derives the participant persona.
- **AC-06-51** Status-engine participation gating still holds: a `blocks_access` Profile status refuses the actor as a submitter/reviewer (backend boundary; UI withholds the action).
- **AC-06-52** Multiple submissions per author per config are allowed; each is its own `submission_group`, reviewed independently, all listed in My Submissions.
- **AC-06-53** An accepted submission is referenceable by its `submission_group_id` (Cluster G agenda), with the author Profile as presenter - the reference resolves to the current revision.

## 7. Terminology & foolproof-UI

- **AC-06-54** Role labels are per-config free text (Author/Reviewer/Chair/Approver…); the global terminology engine relabels the nouns Submission/Review. No hardcoded "submitter/reviewer/chair" strings in shared components.
- **AC-06-55** Pickers offer only valid options: the status-mapping SearchSelects list only the submission form's scoped statuses; `score_field_key` lists only numeric fields of the review form; a role whose source is unconfigured shows a warning, never a silent runtime failure.
- **AC-06-56** No procedural how-to/instructional copy on any new surface (labels + one-line descriptions only). Every dropdown is a searchable SearchSelect/MultiSelect.

## 8. Cross-cutting - security, tenancy, layering, responsive

- **AC-06-57** Every new repository query is tenant-scoped; tenant comes from the authenticated context (staff JWT or Profile JWT), never client input. Cross-tenant access on any review/portal entity is impossible (verified by a tenant-isolation test).
- **AC-06-58** Layering respected: routers do no DB/raw SQL (Service-Repository); frontend components reach data only via hook→service→api-client; explicit TS interfaces (no `any`); no raw CSS/`<style>`; the EMS module never alters core `public` tables (cross-schema refs are plain indexed columns, not FKs).
- **AC-06-59** All datetimes (windows, assigned_at, decided_at, …) use `UTCDateTime`, stored UTC, wired through `ApiModel`, rendered in the user's/Profile's tz.
- **AC-06-60** Every new/changed surface (staff + portal) is usable with no horizontal scroll or clipped controls at **375px and 1280px**; the two-pane grade view stacks on mobile.
- **AC-06-61** Migrations: core review tables via core Alembic (`import app.models.utc_datetime` where UTCDateTime columns exist); EMS portal/persona tables via the EMS per-module Alembic; no revision-id collision; new core permission re-granted to existing tenants' Admin.

## 9. Test matrix (test agent)

- **AC-06-62 Backend pytest** covers: Profile auth (password + OTP + set/forgot, throttle scope, single-use tokens); persona RBAC scoping; all 3 actor sources; allocation first-N + author-exclusion + prior-reviewer preference + idempotency; escalation; identity-agnostic routing (user vs profile assignments); live/partial average; score-field guard (config 422 + revision block); per-revision re-allocation + UNIQUE; early decision + first-wins concurrency; window-gated revision; tenant isolation; failure-isolated dispatch.
- **AC-06-63 Frontend unit (Vitest)** covers: portal session/auth forms, persona-gated surface composition, review-config form validation, two-pane grade draft state, decision form.
- **AC-06-64 E2E (Playwright, real clicks, 375px + 1280px)**: the canonical flow AC-06-01..09 end to end (portal OTP login → submit → reviewer grade → decide → author sees feedback → revise → same reviewer re-reviews) + a staff-actor variant proving AC-06-10/46/47 + a tenant-isolation negative. No direct-URL shortcuts.
- **AC-06-65 Test Execution Report** produced (`06-cluster-e-test-report.md`) in the house format (User Story / Scenario / Precondition / Steps / Expected / Actual / Remarks).

## 10. Out of scope (must NOT be built; reviewer rejects if present)

Quorum/sequential multi-approval · mixed-identity roles · weighted/multi-criteria scoring · double-blind anonymization · org-level COI · load balancing · reviewer self-nomination/bidding · auto-threshold accept · multi-track per project · review analytics dashboard · camera-ready upload · the content web builder (A/BL-076). All → backlog.
