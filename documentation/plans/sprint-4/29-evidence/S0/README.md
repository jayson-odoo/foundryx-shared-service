# Plan 29 (Omnichannel Broadcasts v1) - S0 evidence run

Recorded via `agent-browser --session s29` (real clicks from `/`, never a typed URL for
navigation - deep links are hit only after a click landed there). Backend lane `:8008` on
`foundryx_service_s29`, frontend lane `:3007`. Login `demo@example.com` / `demo1234` on the
`default` tenant.

**Local-DB-only step before this run (not a code change, no file touched):** the three
`broadcasts.read` / `broadcasts.manage` / `broadcasts.send` permission keys do not exist yet
(S1 lands the CSV + grant sweep). Inserted them directly into `foundryx_service_s29` and
granted them to the `default` tenant's `Admin` role via `psql` so the real `RequirePermission`
/ `useCan()` gating could be exercised end-to-end. This is disclosed, not silently worked
around - S1 must add `modules/omnichannel/permissions/permissions.csv` rows + the manifest-
version grant sweep for real.

## Run log

1. **01-list-1280.png** - sidebar Omnichannel > Broadcasts. All 6 seeded broadcasts render,
   one per `BroadcastStatus` (Draft, Scheduled, Sending, Sent, Cancelled, Failed). Columns:
   Name, Labels, Channel, Audience, Recipients, Status, Scheduled/Sent at, Sent/Delivered/
   Read/Failed, Created by, Created (AC-BRD-02). Segment `SearchSelect` shows "All" (AC-BRD-03).
2. **02/03-detail-overview-1280.png** - "Order confirmations" (SENDING, 40 recipients) detail:
   Overview + Recipients tabs (AC-BRD-10), read-only (no Edit toggle - status has left Draft),
   Details/Audience/Channel sections render.
3. **04-message-binding-preview-1280.png** - "Welcome series" (DRAFT) in Edit mode: Message
   section renders the template's exact 2 body slots with per-slot source `SearchSelect`
   (Contact field | Static text) and the reused `WaBubblePreview` shows the live-filled bubble
   (AC-BRD-07).
4. **05-recipients-tab-1280.png** - the 40-recipient Sending broadcast's Recipients tab: an
   embedded Resource-shell list (search/filters/columns), `StatusBadge` pills per state,
   paginated ("1 - 25 of 40").
5. **06 through 09 (new-broadcast, new-message, new-message-filled, new-review)** - the full
   create flow at 1280px: Details (name + labels chips) -> Audience (source `SearchSelect` ->
   Selected contacts -> `MultiSelect` of the 5 real demo contacts -> live "5 recipient(s)
   resolved") -> Channel (`chn-demo`) -> Message (template `booking_update`, slot 1 bound to
   Contact field First name / fallback "there", slot 2 to static text "your order has
   shipped", live preview updates per keystroke) -> Schedule (Send now) -> Review (read-only
   summary + Test send + primary Send now, disabled until every step is valid).
6. **Test send** - "Send test message" opened a contact-picker dialog, sent to Sarah Chen,
   dialog closed on success (no recipient row created, D-A4-18).
7. **10/11 (after-send-detail, new-broadcast-recipients)** - clicking "Send now" auto-saved the
   draft, called `send()`, showed the "Broadcast is sending." toast, and navigated to the new
   detail page; the Recipients tab shows the 5 REAL demo contacts with real phones and mixed
   states (queued/sent/delivered), proving the audience was snapshotted at send time (D-A4-2)
   and the mock's wall-clock tick advances the count.
8. **12-list-after-send-1280.png** - list state after a hard reload (expected: the in-memory
   mock resets on a full navigation - S1's real backend persists across reloads; documented
   below, not a product bug).
9. **13-cancel-scheduled-1280.png** - "Weekend promo" (SCHEDULED) row Actions menu -> Cancel
   (AC-BRD-11, AC-BRD-54): "Broadcast cancelled." toast, status flips, zero further sends.
10. **14-duplicate-1280.png** - "Welcome series" Actions menu -> Duplicate: "Duplicated as
    'Welcome series (copy)'" toast, navigated straight into the new DRAFT's edit form,
    prefilled with the same audience/channel/template/bindings, distinct name, no recipients
    copied.
11. **15 through 19 (\*-375.png)** - the same list / create-builder / message-preview / detail-
    overview / recipients surfaces at 375px: everything stacks, no horizontal page scroll, the
    binding-editor's `lg:grid-cols-[1fr_320px]` collapses to one column with the preview bubble
    below.
12. **20/21 (send-from-actions, onreload-fix-recipients)** - Send now via the form's own
    Actions menu (not the builder) on a second DRAFT, confirming the action registry serves
    the form surface identically to the row/bulk surfaces (AC-BRD-11), and that the form
    refreshes immediately after a mutating action (see bugs below).

## Bugs found and fixed during this run (before declaring S0 done)

1. **Seed `templateId` didn't match the real backend template id** (`tpl-booking-update`
   placeholder vs the real `tpl-001`) - the Message section's Template picker and the
   BindingEditor/preview silently showed empty because `SearchSelect`'s `value` never matched
   any fetched option. Fixed: all 6 seeded broadcasts now reference the real `tpl-001`
   (`booking_update`, APPROVED, no header, 2 body vars - matches the channel's actual seeded
   template).
2. **`recipientsStore` (the Map the mock's `recipients()`/`send()`/`cancel()` methods read)
   was never populated from `seed()`'s returned `recipients` map** - only `rows` was wired up,
   so every broadcast's Recipients tab showed "No data available" despite the seed building
   rich per-broadcast recipient data. Fixed in `broadcast-service.mock.ts` (`loadState()` now
   copies `state.recipients` into the module-level `recipientsStore` on load AND on
   `__mockResetBroadcasts()`).
3. **The embedded Recipients tab rendered a full duplicate `PageHeader`** (a second
   "Broadcasts" title + breadcrumb inside the tab, ON TOP of the record's own header) - missing
   the `hideHeader` prop `<ResourceList>` exposes for exactly this (an embedded list inside a
   parent record's tab). Fixed: `<ResourceList config={recipientsConfig} hideHeader />`.
4. **A mutating form-surface action (Send/Cancel/Duplicate) left the form showing STALE data**
   (still offering "Edit" after the broadcast had already transitioned out of Draft) - a second
   click correctly 409'd server-side ("This broadcast cannot be sent again"), proving the
   underlying transition worked but the UI never refetched. `ResourceFormConfig.onReload` was
   missing. Fixed: `use-broadcast-form.tsx` now wires `onReload: refresh`.
5. **Missing `DialogDescription` on the Test-send dialog** (Radix a11y console warning). Fixed:
   added a one-line factual description (not instructional copy).

## Known, accepted S0-mock limitations (not bugs, disclosed)

- **Mock state is in-memory only and resets on a hard page navigation** (`agent-browser open`,
  a real browser reload, or a re-login). A newly created broadcast survives client-side
  routing (Save -> redirect, Send -> redirect) but not a full reload - expected for a
  frontend-only mock; S1's real backend persists to Postgres.
- **The live "Audience preview" for a HISTORICAL seeded broadcast whose audience references
  synthetic contact ids** (the 40-recipient "Order confirmations" demo) shows "0 recipient(s)
  resolved" on the Overview tab, while its Recipients tab correctly shows the frozen 40-row
  snapshot. This is the intended D-A4-2 semantics (a snapshot is frozen at send time; the live
  preview always re-resolves against CURRENT contacts) applied to synthetic seed data that
  doesn't correspond to any live contact - not reachable with real data.
- **`useCan()`-based hiding of Send/Cancel/Test-send for a user without `broadcasts.send`**
  (AC-BRD-12) was verified by code review of the action registry's `permission` fields (every
  action declares one), not by a second live role in this run - provisioning a second role was
  out of scope for the time available in S0; flagged for the S4 wire-up pass to re-verify live.

## Traps hit (agent-browser mechanics, not product bugs)

- A record row's link and a menu's icon-only "Actions" trigger both threw
  `DOM.getBoxModel` on a plain `click <ref>` (the plan-23 motion wrapper) - resolved with a
  native `element.click()` (row link) or a full `pointerdown/mousedown/pointerup/mouseup/click`
  dispatch sequence (dropdown trigger + menu items), matching the documented trap.
- The "Actions" trigger is icon-only (`aria-label="Actions"`, empty `textContent`) - `find role
  button click --name "Actions"` intermittently missed it; matching by `aria-label` directly in
  `eval` was reliable.
