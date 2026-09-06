# Plan 29 S4 - coder smoke run (broadcasts wired to the real backend)

Recorded `agent-browser --session s29b` run against `http://localhost:3007`
(prod build, `npx next start -p 3007`) + `http://localhost:8008` backend
(`DATABASE_URL=...foundryx_service_s29`, `CELERY_TASK_ALWAYS_EAGER=true`).
Real clicks from the sidebar, no typed URLs except direct navigations used
only to re-enter a page mid-debug (noted below). This is the CODER's own
DoD smoke check, not the tester's formal AC-BRD-53/54/55 recorded run.

Login: `demo@example.com` / `demo1234` at `http://localhost:3007`.

## Journey

1. Sidebar -> Omnichannel -> Broadcasts. List already carried real rows from
   earlier S1/S2 backend-coder live-verification sessions on this same
   Postgres lane (`S2a live probe...`, `S2b live probe...`, etc.) - proof the
   list was already wired to real data. **`01-list-1280.png`**
2. Broadcasts -> New broadcast. Filled Name (timestamped), Audience = Selected
   contacts -> Select all (the 5 seeded demo contacts), Channel = Demo
   WhatsApp (sandbox), Template = `booking_update (en)` (only APPROVED,
   non-media-header templates offered - D-A4-6 confirmed live), bound slot 1
   to Contact field First name (fallback "there"), slot 2 to static text
   "confirmed" - the live `WaBubblePreview` updated on every keystroke.
3. Send test message -> picked Sarah Chen -> "Test message sent." toast (real
   `POST .../test-send` 200 `{messageId}`). **`02-test-send-1280.png`**
4. Send now -> navigated to the detail page. Because Celery runs eager inline
   in this lane, the broadcast reached SENT immediately: Overview shows the
   new `StatusSummary` card (Status pill + all six counts + Started/Finished
   timestamps) - Total 5, Sent 5, rest 0. **`03-status-sending-1280.png`**
5. Recipients tab - all 5 contacts state `Sent` with real `Attempted at`
   timestamps. **`04-recipients-1280.png`**
6. Actions -> Duplicate -> new Draft "... (copy)", zero counts, editable.
   **`05-duplicate-draft-1280.png`**
7. Opened the duplicate for edit, switched Schedule to "Schedule for", set a
   future datetime (`Timezone: Asia/Kuala_Lumpur` label confirms
   `useDatetime()` wiring) - Review section reflected it live.
   **`06`-`08-schedule-ready-1280.png`**
8. Clicked **Schedule broadcast** -> real `POST .../send` with the
   `scheduledAt` body -> broadcast now SCHEDULED, "Scheduled for" timestamp
   shown. **`09`/`10`-scheduled screenshots`**, confirmed after a full reload
   at **`11-scheduled-reload-1280.png`**.
9. List view re-confirmed the row now shows status "Scheduled".
10. Detail page -> Actions -> **Cancel** (no confirm dialog, the documented
    S0/plan decision) -> "Broadcast cancelled." toast, Status = Cancelled,
    Finished timestamp stamped, counts stay zero. **`12-cancelled-1280.png`**
11. Responsive pass at 375px: list (**`13`**), a Cancelled broadcast's
    Overview/`StatusSummary` (**`14`** - the counts grid reflows to 3
    columns, nothing clips), the builder's Details/Audience cards
    (**`15`**), the Recipients table (**`16`**) - no horizontal page scroll,
    every control stays reachable.

No browser console errors were observed at any point (`agent-browser console`
checked after the full journey).

## Bugs found and fixed during this run (frontend-only, no backend change)

1. **An existing Draft (e.g. a just-duplicated broadcast) had no way to
   Send/Schedule from the Overview tab** - the S0 build gated the primary
   Send/Schedule button on `creating` alone, so re-opening a saved Draft
   only offered "Send test message". Fixed in `broadcast-form-view.tsx`:
   the primary action now shows whenever `(creating || status === 'DRAFT')
   && editing` (AC-BRD-09/10 - editable "for as long as it's still Draft").
2. **A real saved broadcast's audience failed to re-validate when loaded
   back into the builder** - `BroadcastAudienceOut` always emits all four
   audience keys with the three unused branches as JSON `null`, but
   `broadcastAudienceSchema` only accepted `undefined` for those fields
   (the S0 mock never produced a stray `null`). This silently disabled the
   Send/Schedule button with no visible error (zod validation isn't
   surfaced as a form error outside `trigger()`). Fixed by widening
   `BroadcastAudience`'s optional fields to `| null` (`types/omnichannel.ts`)
   and the matching zod fields to `.nullable().optional()`
   (`broadcast-schema.ts`), with two new regression tests in
   `broadcast-schema.test.ts`.
3. **The list's "Recipients" column was sortable client-side with no
   backend sort support** - `BroadcastRepository._sort_columns` whitelists
   only `name/status/channel/scheduledAt/createdAt/createdBy`; clicking the
   Recipients header would have sent `sortBy=recipients` and gotten a 422.
   Set `enableSorting: false` on that column in
   `use-broadcasts-list-config.tsx`.

None of these required a backend change - all three are frontend wiring/
validation bugs the mock never exercised.
