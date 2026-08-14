# Sprint 4 · Plan 06 - Cluster E Test Execution Report (AC-06-64)

**Feature:** Profile Portal + Generic Review/Approval engine + Cluster E event review configuration.
**Plan:** `06-cluster-e-submissions-review.md` · **AC:** `06-cluster-e-acceptance-criteria.md`
**Test type:** Canonical multi-actor Playwright E2E (real clicks) against the LIVE stack, at 1280px + 375px.
**Date:** 2026-06-22 · **Tester:** automated (Claude Code TESTER)
**Final status:** **AC-06-64 - PASS** (4/4 specs green; full canonical real-click lifecycle completes).

## Environment

| Component | Value |
| --- | --- |
| Backend | `http://localhost:8002` (uvicorn), DB `foundryx_service_clustere` |
| Frontend | `http://localhost:3002` (prod `next start`, worktree `cluster-e`) - fresh build carrying the portal-signout fix |
| Staff admin | `demo@example.com` / `demo1234`, tenant `default` (bare `localhost` host) |
| Eager workflows | `CELERY_TASK_ALWAYS_EAGER=true` (review.allocate fires inline on the submit transition) |
| Mail | no SMTP → OTP codes land in `email_outbox` (read via psql, the test "mailbox") |

**Prior blocking bug - FIXED before this run.** The first execution (documented in the previous revision of this report) failed every deep portal surface because `useTerminology()` routed the Profile JWT through the STAFF api-client and 401'd on `/terminology`, signing the Profile out. That has been fixed: the `(portal)` tree now resolves terminology via a Profile-safe `GET /portal/terminology` through `portal-api-client`. This run confirms the fix - all four portal surfaces (My Submissions, My Reviews, Decisions, two-pane grade) load and stay authenticated.

## Artifacts

- Setup script: `service_frontend/e2e/helpers/cluster-e-setup.ts` (operator-API scenario builder - forms, scoped status graph, persona-bound review config, profiles + persona grants; everything timestamped).
- OTP "mailbox" reader: `service_frontend/e2e/helpers/cluster-e-otp.ts` (psql → latest `portal.otp` code).
- Spec: `service_frontend/e2e/cluster-e-review.spec.ts` (real clicks; canonical flow + mobile + staff variant + isolation).
- Config: `service_frontend/playwright.cluster-e.config.ts` (baseURL :3002, reuses the running server, never boots :3001).

## Run result (final - run twice, stable)

```
Running 4 tests using 1 worker
  ✓ full lifecycle: submit → review → decide → revise → re-review → accept   (16.9s)
  ✓ mobile (375px): author can submit with no horizontal scroll             (0.9s)
  ✓ staff-actor variant (AC-06-10/46/47): user-kind on staff surface only   (1.4s)
  ✓ tenant isolation (AC-06-57): a foreign-tenant assignment is unreachable (0.5s)
  4 passed (21s)
```

Re-run for stability: 4/4 passed again (21.0s). No flake.

---

## SC-1 - Canonical portal peer-review lifecycle (AC-06-01..09) - **PASS**

- **User story:** As an author/reviewer/decision-maker Profile, I complete the full event peer-review lifecycle entirely in the portal by email-OTP login.
- **Scenario:** Author OTP login → My Submissions → Submit → 2 reviewers grade (draft-save/resume + score) → decision-maker sees the live average + ready badge and decides Revisions → author sees feedback (no scores) + revises → re-allocate → reviewer re-reviews → final Accept (terminal).
- **Precondition:** Published submission form (`allowRevisions=true`) + scoped graph (Draft→Submitted[review_start]→Accepted/Rejected/Revisions; Revisions `is_active=false`); published rubric with numeric `score`; persona-bound review config (required=2, window open); author holds participant persona, 2 reviewers hold reviewer persona, decider holds decision_maker persona; the seeded `review.allocate` workflow is active.
- **Steps (real clicks):**
  1. Author `/portal/login` → "Sign in with email code" → enter email → "Send Code" → read OTP from outbox → "Verify & Sign In" → dashboard.
  2. Open My Submissions → click the stamped event's **Submit** → fill `title`/`abstract` → Submit.
  3. Reviewer 1 OTP login → My Reviews → Open → two-pane → score 8 → **Save draft** → **reload** (resume: score still 8) → **Submit review**.
  4. Reviewer 2 OTP login → Open → score 10 → Submit review.
  5. Decision-maker OTP login → Decisions → assert **average 9.00** + **ready 2 / 2** → **Decide** → "Request revisions" + feedback → Record decision.
  6. Author (same context) reload → sees the feedback, **no raw scores** → **Revise** → edit title → Submit revision.
  7. Reviewer 1 + Reviewer 2 re-review the new revision (score 9) → decision-maker **Accept** with feedback → author reload sees **Accepted** + feedback.
- **Expected:** Every step proceeds via real clicks; the submission reaches the Accepted terminal status; the author surface shows the decision feedback and never any reviewer score.
- **Actual:** **PASS** end-to-end (16.9s). All seven steps complete. Confirmed in-DB: the author's submission goes to **Submitted**, `review.allocate` creates **2 PENDING `actor_kind=profile`** assignments for THIS run's two reviewers (author-excluded), both reviewers' scores feed the live average (9.00) and the 2/2 ready badge, the Revisions decision routes the submission back, the revise clone is a new Draft revision, re-review + Accept reach the terminal status, and the author sees only the decision feedback (the `Score 8|Score 10` assertion has 0 matches on the author surface).
- **Remarks:** The portal-signout bug is confirmed fixed - all four deep portal surfaces load and the Profile stays signed in across the whole flow. Draft-save + resume (reload → score persists), the live decision average + ready badge, author-feedback-without-scores, and the revise→re-review→accept loop are all exercised by real clicks.

## SC-2 - Author OTP login → unified dashboard (AC-06-02/24) - **PASS**

- **User story:** An anonymous email-keyed Profile logs into the portal by email OTP with no prior activation, landing on the unified dashboard.
- **Scenario:** `/portal/login` → "Sign in with email code" → enter email → "Send Code" → read OTP from the outbox → enter code → "Verify & Sign In".
- **Precondition:** Profile exists (no password); EMS installed.
- **Expected:** Lands on `/portal/dashboard`; "Welcome back" + the surface cards the Profile's personas grant.
- **Actual:** **PASS.** Exercised by all four actor logins in SC-1 and explicitly in the mobile test. Zero-activation OTP login confirmed (Profiles never set a password).

## SC-3 - Responsive at 375px (AC-06-60) - **PASS**

- **Scenario:** Author OTP login at a 375px viewport; assert no horizontal overflow on the dashboard and on the My Submissions navigation.
- **Expected:** `scrollWidth ≤ clientWidth + 1` (no horizontal scroll); controls usable.
- **Actual:** **PASS at 375px.** Dashboard fits with no horizontal scroll; navigating to My Submissions stays within bounds (`scrollWidth ≤ clientWidth + 1` on both the dashboard and the submissions list). The submissions surface now renders (the prior signout bug is gone), so this is a true mobile assertion of the surface, not just the shell.
- **375 + 1280 evidence:** SC-1 (the full lifecycle, all real-click surfaces) runs at the desktop **1280×900** viewport; SC-3 re-runs the author login + My Submissions at the mobile **375×740** viewport with the no-overflow assertion. Both widths are covered by the suite.

## SC-4 - Staff-actor variant (AC-06-10/46/47) - **PASS**

- **User story:** A `STAFF_ROLE`-sourced `can_review` role produces `actor_kind=user` assignments graded on the **staff** app, never the portal.
- **Scenario:** A second config with a STAFF_ROLE reviewer (bound to the demo admin's role); the author Profile submits via the portal API; allocation excludes the author and assigns the admin **user**.
- **Expected:** The staff surface shows the user-kind assignment; the portal does **not** (identity routing by `actor_kind`).
- **Actual:** **PASS.** Staff `/reviews/my-reviews` (admin token) contains the "E2E Staff Reviews …" assignment; the reviewer Profile's `/portal/reviews` does not. `actor_kind` alone decides the surface.
- **Remarks:** Asserted at the API level (the staff user has no password to drive a full staff-UI login; the portal submit is real and authored by a Profile).

## SC-5 - Tenant isolation (AC-06-57) - **PASS**

- **User story:** A Profile cannot reach another (or a fabricated) assignment; the portal rejects unauthenticated calls.
- **Scenario:** A reviewer Profile token requests a bogus assignment id; an unauthenticated portal call.
- **Expected:** Bogus id → 404 (tenant-scoped, invisible); no-auth → 401/403.
- **Actual:** **PASS.** `GET /portal/reviews/{bogus}` → 404; `GET /portal/reviews` (no token) → 401.
- **Remarks:** A full second-tenant UI run was out of scope; the negative is asserted at the API boundary as the AC permits.

---

## Verdict - **AC-06-64: PASS**

| Area | Result |
| --- | --- |
| Profile OTP login + unified dashboard (AC-06-02/24) | **PASS** |
| Canonical portal lifecycle submit→review→decide→revise→re-review→accept (AC-06-03..09) | **PASS** |
| Responsive 375px + 1280px (AC-06-60) | **PASS** (both widths) |
| Identity routing / staff variant (AC-06-10/46/47) | **PASS** |
| Tenant isolation (AC-06-57) | **PASS** |

The generic review **engine**, the Cluster E **backend** pipeline, and the Profile **portal front end** are all correct end-to-end. The canonical multi-actor real-click flow completes through the portal at desktop and is mobile-safe at 375px. **AC-06-64 PASS.**

---

## Product bug status

**The single High-severity bug from the prior run is FIXED and verified.** No new product bugs were found in this run.

- *(Fixed)* Portal surfaces signing the Profile out - `useTerminology()` previously routed the Profile JWT through the STAFF api-client and 401'd on `/terminology`. The `(portal)` tree now uses a Profile-safe `GET /portal/terminology` via `portal-api-client`. Verified: all four deep portal surfaces load and the Profile session survives the whole lifecycle.

## Test/env fixes applied during this run (NOT product changes)

These are spec/helper changes (TESTER scope) - no application code was touched.

1. **Deterministic event targeting (E2E residue, `cluster-e-review.spec.ts`).** The author's Submit button was matched by the generic regex `E2E Event Reviews` with `.first()`. The `participant` persona is tenant-scoped, so the author sees a Submit button per open event; with ~10 residual events from prior runs, `.first()` picked the WRONG (old) event and the submission never matched THIS run's review config (so allocation produced nothing for this run's reviewers). Fix: target the **stamped** name `E2E Event Reviews <stamp>`.

2. **Reviewer-pool residue cleanup (`cluster-e-setup.ts`).** The persona-bound reviewer pool draws **every** Profile holding the reviewer persona tenant-wide, ordered by `Profile.id.asc()` and trimmed to `required_review_count` (`modules/ems/bootstrap.py` `_persona_pool`). ~23 reviewer profiles had accumulated from prior runs, so allocation deterministically picked OLD reviewers, not this run's - the new reviewers' queues stayed empty. Fix: `buildScenario()` soft-deletes prior `e2e-reviewer%` / `e2e-decider%` / `ce-rev%` profiles before creating this run's actors (the resolver filters `is_deleted=False`; historical FK refs untouched). This is the documented E2E-residue failure class (BL-069 self-cleaning fixtures is the proper long-term home).

3. **Submission form `allowRevisions=true` (setup gap, `cluster-e-setup.ts`).** The "Request revisions" decision moves the submission to the Revisions status fine, but the author's **Revise** then requires the FORM's `allow_revisions` flag (`form_service.revise` → `FormRevisionBlocked("Revisions are not enabled for this form.")`). The submission form was created without it, so the revise dialog showed the blocked message and `#ff-title` never rendered. Fix: create the submission form with `allowRevisions: true` (the `revisionsStatusId` on the config is a separate, transition-side concept). This is a scenario-setup gap, not a product bug - the form-revision gate behaving as designed.

4. **Per-test timeout raised to 480s.** The canonical flow performs 7 OTP logins (each polls the outbox via psql with retries) plus the revise loop; 300s was tight. The passing run completes in ~17s, so the headroom is precautionary.
