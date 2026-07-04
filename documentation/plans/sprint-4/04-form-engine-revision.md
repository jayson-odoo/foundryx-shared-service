# Sprint 4 · Plan 04 — Form Engine: Submission Revisions (core foundation enhancement)

**Status:** GRILLED (2026-06-18) — design locked, ready to slice + build.
**Branch (future):** `sprint-4/04-form-revisions`
**Type:** Core form-engine enhancement. **Generic** — any form benefits (vendor onboarding resubmit, grant re-application, EMS abstracts).
**Prerequisite for** Cluster E review (plan 06) — reviewer-requested-changes → author resubmits a revision.
**Source:** `01-...-grill-decisions.md` §6.9 + this grill.

> **Scope split (grilled):** REVISION is generic (no Profile) → **core form engine, this plan.** REVIEW needs Profile reviewers → **EMS module, plan 06.** Dependency direction stays EMS→core, never core→EMS. The earlier "form engine gains revision + review" splits here.

---

## Headline

Today a `form_submission` is editable only while in an `is_active` (Draft) status; once Submitted it's frozen forever. **Revision** lets an author produce a **new immutable snapshot** of a submitted entry (correction, or reviewer-requested changes), preserving the prior verbatim. Each revision is its own `form_submission` row sharing a stable group identity.

## Locked decisions (this grill)

1. **Identity = `submission_group_id` + `revision_number` + `is_current` (R1).** Each revision = its own immutable `form_submission` row sharing a stable `submission_group_id`; `revision_number` increments; `is_current` flags the live one. External refs (agenda session, EMS review, dedup) point at **`submission_group_id`** → resolve to `is_current`. Backfill: existing rows get `group_id = id`, `revision_number = 1`, `is_current = True`.

2. **Trigger + gating (R2).** Form-level **`allow_revisions`** toggle. **Revise** = clone the CURRENT revision's answers → a NEW row at the scoped **initial** status (Draft), re-fillable, **pinning its OWN `version_id`** at revise time (faithful re-render of whatever was published then); prior revision frozen, `is_current = False`, **keeps its last status** (no forced "Superseded" state). Allowed **only from a non-editable (frozen) status** (editing a Draft = just edit it). Caller = submission **owner** (`user_id`) **OR** `submissions.manage`. Anonymous/public revision **deferred**.

3. **Status across revisions (R3).** New revision re-enters the scoped graph from initial; resubmits via the EXISTING submit/transition flow. Prior revisions retain their final status, `is_current = False`. **Lists default to `is_current = True`** (one row per group); history is accessible on demand.

4. **Files (default).** Cloned answers reference the SAME storage blobs (no byte copy — blobs are immutable); changing a file in the revision uploads a new key. Blob lifecycle by reference (don't delete a blob still referenced by a sibling revision).

---

## Data model (core `form_submissions` + `forms`)

```
forms
  + allow_revisions  BOOLEAN NOT NULL DEFAULT false

form_submissions
  + submission_group_id  STRING NOT NULL INDEX   # stable identity across revisions (= id for originals)
  + revision_number      INTEGER NOT NULL DEFAULT 1
  + is_current           BOOLEAN NOT NULL DEFAULT true INDEX
  # version_id already per-row (each revision pins its own); status_id/answers_json/submitted_at already per-row
```
Core Alembic migration + **backfill** (`group_id = id`, `revision_number = 1`, `is_current = true` for all existing rows). Partial index `(submission_group_id) WHERE is_current` for fast "latest" lookups.

## Service surface (`FormService`)

```python
def revise(self, tenant_id: str, submission_id: str, user: User) -> FormSubmission:
    # guards: form.allow_revisions; submission.is_current; submission's status is_active == False
    #         (frozen); user.id == submission.user_id OR has submissions.manage
    # clone:  new row, same submission_group_id, revision_number+1, is_current=True;
    #         prior is_current=False; status_id = scope initial (Draft); version_id = form.current_version_id;
    #         answers_json = deep-copy of prior clean answers (file refs by reference); submitted_at=None
    # returns the new Draft revision (author then edits + submits via existing endpoints)
```
- **Listing:** `submissions()` default filters `is_current = True`; a `group` param (or `is_current=all`) returns the full chain for history.
- Existing `submit`/`transition`/file-serve unchanged — the new revision rides them.

## API

- **`POST /forms/{id}/submissions/{sid}/revise`** → new Draft revision (owner or `submissions.manage`); 409 if `allow_revisions` off / not current / not frozen.
- **`GET /forms/{id}/submissions?group={groupId}`** (or `/submissions/{sid}/revisions`) → the revision chain (read-only, each pinned to its own version).
- `PATCH /forms/{id}` accepts `allow_revisions`.

## Frontend

- **Form settings:** an `allow_revisions` toggle.
- **Submission detail:** a **Revise** action (visible only when `allow_revisions` + frozen + owner/manager) → opens the new Draft revision in the renderer (`mode='fill'`); a **revision history** panel listing revisions (number, status, submitted_at) — each opens read-only via the renderer **pinned to ITS `version_id`** (faithful). A **"current" / "rev N"** badge on the detail header + list.
- `types/forms.ts`: `FormSubmissionRow` gains `submissionGroupId`/`revisionNumber`/`isCurrent`; form gains `allowRevisions`. Parity-pinned.

## Slices

1. **Backend revisions** — columns + migration + backfill; `revise()` + guards; list default `is_current`; history endpoint; tests (clone answers + files-by-ref; increment + flip `is_current`; pin own version; re-enter Draft; guard matrix: toggle-off / not-frozen / not-owner; list-default-current; history read; backfill correctness).
2. **Frontend** — `allow_revisions` toggle; Revise action + revision-history viewer + badges; E2E (submit → revise → edit → resubmit → history shows 2 immutable revisions, latest current).

## Open risks / backlog
- **Anonymous/public revision** (claim-link to revise a public submission) → backlog (overlaps BL-090 autosave).
- **Blob GC** when a revision is hard-deleted: only delete blobs unreferenced by sibling revisions.
- **Revision diff view** (what changed between revisions) → nice-to-have backlog.
- Each revision currently pins the CURRENT published version at revise time; if the form was unpublished, revise is blocked (no current version) — surface a clear 409.
