# Plan 26 review round 2 - evidence run

Lane: worktree `s26`, branch `sprint-4/26-contacts-module`. Backend :8005 (DB
`foundryx_service_s26`), frontend :3004 (prod build, `rm -rf .next && npm run
build && npx next start -p 3004`). Real clicks via `agent-browser --session
s26c`, logged in as `demo@example.com` (default tenant Admin).

**Lane setup note (environment, not a code defect):** at session start the
default tenant's Admin role on `foundryx_service_s26` had never been granted
the plan 26 `contacts.*`/`segments.*` permissions (this lane's DB predates
the permission-CSV sync + `tenant_admin_grant` re-run other lanes already
had), and the shared `service_backend/.env`'s `CORS_ORIGINS` only listed
`:3001,:3002` (not `:3004`) - both blocked the Omnichannel menu from
appearing at all. Fixed for this lane only: ran `PermissionService.sync_
permissions("omnichannel", ...)` + `tenant_admin_grant` against
`foundryx_service_s26` directly, and started uvicorn with `DATABASE_URL`
and `CORS_ORIGINS` exported inline (no shared `.env` file edited) so the
fix is isolated to this process. Neither is a plan 26 code change.

## Run log

1. **01-contacts-list-1280.png** - Contacts list renders with existing
   residue data (prior manual/E2E runs on this lane's DB); segment control
   shows "All contacts".
2. Opened "Manage segments" with one pre-existing segment ("VIP Gold").
   **02-manage-segments-open-1280.png**.
3. Clicked Delete on "VIP Gold" - the countdown toast rendered OVER the
   still-open dialog (Blocker 1's exact repro scenario), and the dialog's
   own row buttons disabled. **03-delete-countdown-over-dialog-1280.png**.
   Screenshot latency meant the window lapsed before Cancel was clicked here
   - committed (removed) instead; re-verified Cancel separately in step 6-7
   below with tighter timing. **04-after-commit-empty.png** confirms the
   commit path (segment gone, list empty per the active filter).
4. Created a fresh segment ("R2 Test Segment ...") via Filters -> Save as
   segment, to redo the Cancel path with correct timing.
5. Opened Manage segments, clicked Delete, then clicked Cancel on the
   toast within the window (Blocker 1 fixed: the click reaches the button
   through the Radix Dialog's `pointer-events: none` body override).
   **06-cancel-dialog-stays-open-1280.png** - the segment is intact, row
   controls re-enabled, and (after the `floatingAncestry.ts` follow-up fix
   below) the "Manage segments" dialog itself stayed open. Confirmed via
   `GET .../contact-segments` that the segment still exists server-side.
6. **07-manage-segments-375.png** / **08-delete-countdown-375.png** - same
   dialog + countdown-over-dialog state at 375px (mobile). The commit fired
   before Cancel could be clicked at this viewport (mobile find-text timing)
   - **09-commit-empty-375.png** confirms the commit-and-refresh path at
   375px too (dialog now shows "No saved segments yet.").
7. Created a second segment ("Sarah Segment", filter `name contains
   "Sarah"`), selected it as the ACTIVE segment view (the "View segment"
   `SearchSelect`, not just "All contacts"). **10-selected-segment-before-
   delete-1280.png**.
8. Deleted the SELECTED segment via Manage segments and let the window
   lapse (commit). The segment view fell back to "All contacts" - no error,
   no stranded 404. **11-fallback-to-all-contacts-1280.png** (should-fix 3).
9. Created a third segment ("Close Mid Countdown"), opened Manage segments,
   clicked Delete, then IMMEDIATELY clicked the dialog's own Close (X)
   button while the countdown was still live. The toast persisted on the
   page after the dialog closed (confirmed via a live snapshot showing
   "Deleting in 3s" with the dialog gone), and after the window lapsed the
   delete committed server-side (`GET .../contact-segments` -> `[]`) AND the
   page's own "Manage segments" button disappeared (>0-segments gate),
   proving `refreshSegments()` fired from the page-level controller with the
   dialog unmounted the whole time. **12-close-mid-countdown-commits-and-
   refreshes-1280.png** (should-fix 4).
10. Console log check (`agent-browser console`) across the whole run: only
    the pre-existing "Missing Description for DialogContent" a11y warning
    (present on every Dialog in this codebase, unrelated to plan 26) - no
    errors.
11. **Post-fix rebuild sanity re-check**: after fixing the `floatingAncestry.ts`
    follow-up (step 5/9's discovery), did a clean `rm -rf .next && npm run
    build` + restart and re-ran the Delete -> Cancel path end to end one more
    time on the FRESH build - dialog stayed open, segment intact
    (**13-post-rebuild-sanity-check-1280.png**), then deleted the sanity
    segment for real (let it commit) to leave the lane's segment list clean.

## Findings this run additionally surfaced and fixed

Fixing Blocker 1 (the toast became clickable over an open Dialog) exposed a
SECOND, previously-unreachable issue live during this exact run: clicking
the toast's Cancel button closed the whole "Manage segments" Dialog too,
because sonner's toaster portal (`document.body`, sibling to the Dialog's
own portal) was outside `components/common/floatingAncestry.ts`'s
`FLOATING_SURFACE_SELECTOR` allowlist - Radix's dismissable-layer read the
click as "outside the dialog" and closed it. Fixed by adding
`[data-sonner-toaster]`/`[data-sonner-toast]` to that ONE shared selector
(the same seam `dialog.tsx`/`alert-dialog.tsx`/`sheet.tsx` already use for
popovers/menus opened from within a dialog) - a generic, house-wide fix, not
a Contacts-specific patch. Covered by
`components/common/floatingAncestry.test.ts` (2 new cases).
