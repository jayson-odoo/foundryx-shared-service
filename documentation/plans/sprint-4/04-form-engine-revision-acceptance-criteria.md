# Sprint 4 · Plan 04 — Form Engine Submission Revisions — User Acceptance Criteria

**Source plan:** `04-form-engine-revision.md` (GRILLED 2026-06-18)
**Scope:** Generic core form-engine revision (no Profile/review — that lives in EMS plan 06).
**Format:** Given / When / Then. Each AC is independently verifiable. ID = `AC-04-RV-NN`.

---

## A. Form-level toggle (`allow_revisions`)

### AC-04-RV-01 — Toggle defaults off
- **Given** a newly created form
- **When** I open its Settings
- **Then** `allow_revisions` is OFF by default; existing forms backfill to OFF.

### AC-04-RV-02 — Toggle persists
- **Given** a form open in Settings with Edit on
- **When** I enable `allow_revisions` and Save
- **Then** `PATCH /forms/{id}` stores `allow_revisions=true`; the toggle reflects true on reload.

### AC-04-RV-03 — Toggle gates the Revise action
- **Given** `allow_revisions=false`
- **When** I view any submission detail for that form
- **Then** the **Revise** action is NOT shown, and `POST .../revise` returns **409**.

---

## B. Creating a revision (`POST /forms/{id}/submissions/{sid}/revise`)

### AC-04-RV-04 — Revise clones the current revision into a new Draft
- **Given** a frozen (non-editable) current submission on a form with `allow_revisions=true`, as the owner
- **When** I Revise
- **Then** a NEW `form_submission` row is created sharing the same `submission_group_id`, with `revision_number` = prior + 1, `is_current=true`, `status_id` = scope **initial** (Draft), `submitted_at=null`, and `answers_json` = deep copy of the prior clean answers.

### AC-04-RV-05 — Prior revision is frozen and demoted
- **Given** a revision was just created from a prior submission
- **When** I inspect the prior row
- **Then** its `is_current=false`, its `status_id` is UNCHANGED (keeps its last status — no forced "Superseded"), and its `answers_json`/`version_id` are byte-for-byte unchanged (immutable snapshot).

### AC-04-RV-06 — New revision pins its OWN version
- **Given** the form was republished (new `current_version_id`) after the original submission
- **When** I Revise
- **Then** the new revision's `version_id` = the form's CURRENT published version at revise time (not the prior revision's version).

### AC-04-RV-07 — Files clone by reference, not byte copy
- **Given** the prior revision has file/signature answers
- **When** I Revise
- **Then** the new revision's file answers reference the SAME storage blobs (no new keys created); replacing a file IN the revision uploads a new key and leaves the sibling's blob intact.

### AC-04-RV-08 — Revised Draft rides existing submit/transition
- **Given** a newly created Draft revision
- **When** I edit answers and submit via the EXISTING submit endpoint
- **Then** it re-enters the scoped graph from initial and transitions via the existing flow; no revision-specific submit path exists.

---

## C. Guard matrix (each returns 409 with a clear message)

### AC-04-RV-09 — Revisions disabled
- **Given** `allow_revisions=false`
- **When** Revise is called
- **Then** 409 (revisions not enabled for this form).

### AC-04-RV-10 — Not the current revision
- **Given** an old revision (`is_current=false`)
- **When** Revise is called on it
- **Then** 409 (revise only the current revision).

### AC-04-RV-11 — Not frozen (still editable)
- **Given** a submission whose status is `is_active=true` (Draft / editable)
- **When** Revise is called
- **Then** 409 (editing a Draft = just edit it; revise is for frozen entries only).

### AC-04-RV-12 — Not owner and lacks permission
- **Given** a caller who is neither the submission `user_id` owner nor holds `submissions.manage`
- **When** Revise is called
- **Then** 403/409 (refused); an owner OR a `submissions.manage` holder succeeds.

### AC-04-RV-13 — Form unpublished (no current version)
- **Given** a form with `allow_revisions=true` but no current published version (unpublished)
- **When** Revise is called
- **Then** 409 with a clear "form has no published version" message (cannot pin a version).

---

## D. Listing & history

### AC-04-RV-14 — Lists default to current only
- **Given** a group with multiple revisions
- **When** the submissions list loads (default)
- **Then** exactly ONE row per group is returned (the `is_current=true` row); revisions do not multiply list rows.

### AC-04-RV-15 — History chain on demand
- **Given** a group with N revisions
- **When** I request `GET /forms/{id}/submissions?group={groupId}` (or `/submissions/{sid}/revisions`)
- **Then** all N revisions return read-only, ordered, each carrying its own `revision_number`/`status`/`submitted_at`/`version_id`.

### AC-04-RV-16 — History re-render is version-faithful
- **Given** a prior revision pinned to an older version
- **When** I open it from the history panel
- **Then** it renders read-only through the renderer pinned to ITS `version_id` (faithful to how the form looked then), even if the draft was since renamed/republished.

---

## E. Backfill / migration

### AC-04-RV-17 — Existing rows backfilled correctly
- **Given** submissions that existed before this migration
- **When** the Alembic migration + backfill runs
- **Then** every existing row gets `submission_group_id = id`, `revision_number = 1`, `is_current = true`; no row is duplicated or orphaned.

### AC-04-RV-18 — Latest-lookup index present
- **Given** the migration applied
- **When** the schema is inspected
- **Then** a partial index `(submission_group_id) WHERE is_current` exists for fast latest lookups, plus indexes on `submission_group_id` and `is_current`.

---

## F. Frontend / UX

### AC-04-RV-19 — Revise action visibility
- **Given** a submission detail
- **Then** **Revise** shows ONLY when `allow_revisions` AND frozen AND (owner OR `submissions.manage`); otherwise hidden (foolproof-UI — backend remains the real boundary).

### AC-04-RV-20 — Revise opens the new Draft in fill mode
- **When** I click Revise
- **Then** the new Draft revision opens in the renderer `mode='fill'`, editable.

### AC-04-RV-21 — Revision badge
- **Given** a group with >1 revision
- **Then** the detail header and list row show a **current / rev N** badge.

### AC-04-RV-22 — Revision history panel
- **Given** submission detail for a group
- **Then** a history panel lists each revision (number, status, submitted_at); each opens read-only pinned to its own version.

### AC-04-RV-23 — Type parity
- **Given** `types/forms.ts`
- **Then** `FormSubmissionRow` carries `submissionGroupId`/`revisionNumber`/`isCurrent` and the form carries `allowRevisions`; parity test passes (FE ↔ backend schema).

---

## G. Responsive (user mandate)

### AC-04-RV-24 — Both viewports
- **Given** the settings toggle, submission detail, Revise action, badge, and history panel
- **Then** each renders usable at ~1280px AND ~375px (no horizontal scroll, no clipped controls; history panel stacks/scrolls on mobile).

---

## H. E2E happy path (the slice-2 acceptance journey)

### AC-04-RV-25 — Submit → revise → edit → resubmit → history
- **Given** a published form with `allow_revisions=true`
- **When** I submit an entry, Revise it (frozen), edit an answer, resubmit, then open history
- **Then** history shows **2 immutable revisions** — rev 1 frozen with its original answers, rev 2 current with the edit; the original answers are unchanged; only one row shows in the default list.

---

## Out of scope (deferred — must NOT regress / must surface clearly)
- Anonymous/public revision (claim-link) → backlog (overlaps BL-090 autosave). Revise from a public/anonymous submission is refused.
- Blob GC on hard-delete: only blobs unreferenced by sibling revisions may be deleted (no AC here — backlog item, but must not delete a referenced blob).
- Revision diff view → backlog nice-to-have.
