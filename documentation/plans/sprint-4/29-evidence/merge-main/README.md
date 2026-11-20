# Plan 29 (Omnichannel Broadcasts v1) - post-merge smoke (origin/main -> s29)

Recorded via `agent-browser --session s29a` (real clicks from `/`; deep links only after a
click landed there, except where noted). Backend lane `:8008` on `foundryx_service_s29`,
frontend lane `:3007` (both rebuilt fresh after the merge). Login `demo@example.com` /
`demo1234` on the `default` tenant.

Purpose: re-verify plan 29's S0 (frontend mock, branched at `d302ea7`) after merging
`origin/main` (`58759ed` - plan 26 A2 Contacts module + plan 27 A3 inbox-views, both merged
onto A1) so S1 builds on current main. A4's audience picker consumes A2's real segments.

**Local-DB-only step before this run (not a code change, no file touched):** the
`broadcasts.read` / `broadcasts.manage` / `broadcasts.send` permission keys do not exist yet
(S1 lands the CSV row + grant sweep - same disclosed gap the S0 evidence run hit and the same
temporary fix). Inserted them directly into `foundryx_service_s29` and granted them to the
`default` tenant's `Admin` role via `psql` so the real `RequirePermission` / menu gating could
be exercised end-to-end for this smoke pass. A later `bootstrap_db` on this DB removes them
again (`sync_permissions` is delete-by-module, module CSV is the only source of truth) - S1
must add the real CSV rows.

## Run log

1. **01-contacts-list-1280.png** - sidebar Omnichannel > Contacts (permission `contacts.read`,
   real since A2). 5 real seeded demo contacts render (Sarah Chen, Priya Raj, Daniel Lee,
   Marcus Wong, Aisha Abdullah) via the real backend - confirms the A2 merge landed cleanly
   under the s29 lane.
2. **02-contacts-segment-created-1280.png** - Filters > `Name contains "a"` > Apply > "Save as
   segment" > named "Merge Verify 113953" > Save. Toast "Segment saved."; the segment now
   lists in "View segment" (`useContactSegments` -> real `contactSegmentService` -> real
   backend, both S0 copies of the hook/service/mock were replaced by main's real ones during
   the merge - see commit body).
3. **03-broadcasts-blocked-no-perm-1280.png** - direct navigation to `/omnichannel/broadcasts`
   BEFORE the temp permission grant: the real `RequirePermission` gate correctly renders "You
   don't have access to this page" (expected - `broadcasts.read` does not exist in the backend
   CSV yet, S0 is frontend-mock-only). Confirms the merge did not accidentally bypass RBAC.
4. **04-inbox-1280.png** / **06-inbox-375.png** - Inbox (A1, untouched by this merge) still
   renders correctly with A3's "Views" (+ button) and Lifecycle filter groups added to the
   sidebar by plan 27's merge into A2 - no regression.
5. **05-contacts-375.png** - Contacts list reflows cleanly at 375px (toolbar wraps, table
   scrolls, no overflow/clipped controls).
6. After the temp permission grant + a hard reload (session-sync D8 re-pulls `/auth/me`):
   **07-broadcasts-list-1280.png** - sidebar now shows Broadcasts between Contacts and
   Channels (menu union of S0's entry + plan 26/27's restyled block, `filterMenu` prunes
   correctly); the 6 seeded mock broadcasts render (Draft/Scheduled/Sending/Sent/Cancelled/
   Failed).
7. **08-broadcast-audience-real-segment-1280.png** - "New broadcast" > Audience > Source
   "Segment" > Segment picker lists the REAL A2 segment "Merge Verify 113953" (fetched from
   the real backend, not a mock store) - confirms the audience picker is correctly rebound to
   main's real segment service. Selecting it resolves **"5 recipient(s) resolved"** - the
   filter (`Name contains "a"`) matches all 5 real demo contacts. This count preview initially
   read 0 (a bug found during this smoke pass, fixed in the same commit - see below), because
   `broadcast-service.mock.ts`'s `resolveAudienceContacts` still imported the STALE
   `mockContactSegmentService` (an S0-only in-memory store with its own fake segment ids) to
   resolve a segment's filter tree, instead of the real, now-merged `contactSegmentService`.
   Fixed by rebinding that one lookup to the real service (the audience *picker* in
   `audience-section.tsx` was already correctly bound via `useContactSegments`; this was a
   second, independent consumer of segments inside the broadcast mock's own recipient-count/
   send-snapshot logic that the merge brief's "rebind the picker" didn't explicitly name but
   was clearly the same gap - the file's own header comment said "before A2 merges", i.e. it
   was always meant to flip once this merge landed).

## Console / errors

`agent-browser --session s29a errors` and `console` showed no errors or warnings across the
whole run (both viewports, all 8 screenshots' page loads).

## Cleanup

Segment "Merge Verify 113953" and the temp `broadcasts.*` permission rows are LOCAL-DB-only on
`foundryx_service_s29` - no code/migration touched. Left in place (same as S0's precedent) so
a re-run doesn't need to recreate them; a future `bootstrap_db` will delete the permission rows
again (S1 must add them for real via the CSV).
