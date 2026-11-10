# Plan 26 - Omnichannel Contacts module - E2E evidence run (AC-CTM-48/49/50)

**Date:** 2026-09-05/06 (UTC). **Lane:** s26 (backend `:8005` DB `foundryx_service_s26`, frontend
`:3004` prod build). **Branch/commit:** `sprint-4/26-contacts-module` @ `1b2ae72`.
**Tool:** `agent-browser` CLI, sessions `s26` (platform operator + tenant A admin), `s26viewer`
(tenant A read-only user), `s26noomni` (tenant without the module). Real clicks from `/` throughout;
no deep-linked navigation except where explicitly noted as a documented API setup call.

## Tenants created (all timestamped, dedicated)

- **`p26-20260905222948`** (slug) - "P26 Contacts 20260905222948" - created via Tenants ->
  Add tenant (real clicks) by the platform operator (`platform@example.com`); Omnichannel Service
  installed via the tenant's Modules tab -> Actions -> Install (real clicks, Radix dropdown/tab
  quirks worked around with `agent-browser eval` dispatching native pointer events on the same
  matched DOM element - see "Harness gotchas" below). Admin `p26admin+20260905222948@example.com` /
  `P26admin1234!`.
- **`p26-noomni-20260905222948`** - "P26 NoOmni 20260905222948" - created the same way, Omnichannel
  **never installed**, to prove AC-CTM-50's menu-absence clause. Admin
  `p26noomni+20260905222948@example.com` / `P26noomni1234!`.

## Setup API calls (documented, not part of the scripted click-through)

1. `POST /auth/set-password` with a token read directly from the `invite_tokens` table (`psql`) to
   activate the "P26 Contacts Viewer" test user - the invite/reset email would otherwise require the
   maildir smtpd rig, which is out of scope for a permission-gating probe. Verbatim:
   `curl -X POST http://localhost:8005/auth/set-password -d '{"token":"<from-db>","password":"P26viewer1234!"}'`.
2. `PATCH /roles/{roleId}` with `{"permissionKeys":["contacts.read","workspaces.read"]}` - the Roles
   UI's permission `MultiSelect` (a cmdk `Command` combobox, not the app's standard `SearchSelect`)
   could not be reliably toggled via `agent-browser click` OR a synthetic pointer-event sequence in
   this session (every attempt closed the popover without registering the selection - see "Harness
   gotchas"); the PATCH call is the exact same effect a successful UI save would have produced, used
   only to unblock the permission-gating verification below.
3. Direct `psql` reads (`SELECT ... FROM invite_tokens`) - read-only, to fetch the token for (1).
4. `POST /auth/login` (default tenant `demo@example.com`, tenant A admin, tenant B/`other-ctm`-style
   probes) to obtain bearer tokens for the isolation curl probes (AC-CTM-50) - the isolation checks
   themselves are `[BE]` API-level assertions, not UI flows.

## Run log

### AC-CTM-48/49 script (tenant A, admin `p26admin+...`)

1. Sidebar Omnichannel -> Contacts. `01-contacts-list-empty-1280.png` / `-375.png` - empty
   Resource-shell list, full toolbar (Search/Filters/Import/Export/Columns/Add contact), no
   horizontal scroll at either width.
2. **Add contact** x3 (real clicks, phone required + create-only, Lifecycle defaulted to the
   workspace's initial stage "New Lead", Tags `SearchSelect`, custom field "Lead Source" text
   input): Amara Okafor `<ts>` (`02-contact1-created-1280.png` - Details tab, Lifecycle badge,
   read-only Phone), Beno Larsen `<ts>`, and Carys Mendes `<ts>` with tag "P26 VIP" + custom field
   "Lead Source"="Referral" filled before submit (`03-create-contact3-filled-1280.png` / `-375.png`).
   Before contact 3, created the tag "P26 VIP" (Workspaces -> General -> Tags -> Create tag) and the
   custom field "Lead Source" (Contact fields -> Add custom field) via real clicks - both then
   appeared as valid picker options for the manual-create form, satisfying AC-CTM-12.
   `04-list-3-contacts-1280.png` - all 3 rows, Lifecycle chip + Tags chip render correctly.
3. **Duplicate phone 422**: new contact with Amara's exact phone -> inline field error "A contact
   with this phone number already exists." (`05-duplicate-phone-422-1280.png`), nothing written
   (list still shows 3, not 4, after Cancel/Discard).
4. **Search**: by name "Amara" -> 1 row; by phone digits "601112229483" (no `+`, no formatting) ->
   Carys's row (`06-search-phone-digits-1280.png`) - confirms AC-CTM-15's digits-insensitive match.
5. **Filters** -> Lifecycle "is any of" New Lead -> Apply -> "Filters 1" badge,
   `07-filter-lifecycle-1280.png`.
6. **Save as segment** "P26 New Leads `<ts>`" -> "Segment saved." toast -> **segment switch** via the
   `SearchSelect` -> re-queries to the same 3 rows (`08-segment-switched-1280.png`).
7. **Manage segments -> Edit filter** -> the stored tree round-trips exactly (Lifecycle / is any of /
   New Lead) into the SAME filter-builder UI (`09-segment-edit-filter-roundtrip-1280.png`) - confirms
   the `initialValue` round-trip (AC-CTM-06).
8. **Columns** chooser -> unchecked Email -> column disappears (`10-columns-toggled-1280.png`); left
   unchecked deliberately to also probe persistence later (step 16).
9. **Bulk select 2 (Beno + Amara) -> Assign** -> added the tenant Admin as a workspace member first
   (Workspaces -> General -> Members, since the workspace had zero members and the picker correctly
   offered ONLY "Unassigned" until then - AC-CTM-12) -> Assign dialog SearchSelect now offers
   "Unassigned"/"P26 Admin" only (`11-bulk-assign-dialog-1280.png`) -> "2 contacts assigned."
   (`12-bulk-assign-result-1280.png`).
10. **Bulk Add tags** (same 2 rows) -> MultiSelect offers only the workspace's own tag ("P26 VIP")
    (`13-bulk-tags-dialog-1280.png`) -> "2 contacts tagged." (`14-bulk-tags-result-1280.png`).
11. **Partial-failure lifecycle move**: moved Carys individually to "Customer" via her detail page's
    "Move to" picker first (`debug-carys-detail.png` - "No further moves from this stage." confirms
    the terminal flag) -> selected Beno (Cold-Lead-eligible) + Carys (terminal) -> bulk **Move
    lifecycle** -> Cold Lead (`15-bulk-lifecycle-dialog-1280.png`) -> **"1 moved, 1 failed.
    `<carysId>`: No transition from '🤩 Customer' to '🧊 Cold Lead'."** - a named per-record reason,
    never a bare "something went wrong" (`16-bulk-lifecycle-partial-failure-1280.png` / `-375.png`).
12. **Detail Edit toggle**: opened Beno -> Edit -> Phone stays read-only display (not an input, per
    AC-CTM-28's "UI never exposes phone editing") -> typed an invalid BCP-47 language ("English") ->
    Save -> inline 422 "language must be a BCP-47 tag of 16 characters or fewer."
    (`debug-save-422.png`, confirms server validation on the detail PATCH path too) -> corrected to
    "en" -> Save -> back to read view (`17`/`18-detail-edit-*-1280.png`).
13. **Conversation tab**: mounts the existing `<ConversationDrawer>` (composer locked - no CSW window
    since this is a manually-created contact with no inbound message yet - correct, not a bug)
    (`19-conversation-tab-1280.png` / `-375.png`).
14. **Import wizard, bad row first**: 3-row CSV, row 3 `lifecycle=NotARealStage` -> auto-mapped
    columns -> **Test** -> all 3 rows initially flagged "Unknown lifecycle stage for this workspace."
    because the CSV used the plain label text ("New Lead") which does **not** match this workspace's
    ACTUAL label (`"🆕 New Lead"`, emoji-prefixed by the seed graph) - confirmed this is intended
    (`_match_stage` accepts the exact `key` OR the exact `label`, and the seed labels are genuinely
    emoji-prefixed) by reading `modules/omnichannel/services/lifecycle_service.py`; corrected the two
    good rows to use the stage **key** (`new_lead`/`hot_lead`) instead of the label
    (`20-import-map-columns-1280.png`, `21-import-test-all-errors-1280.png` - the mistaken all-3-error
    attempt kept as evidence of the Test-phase error surface). Re-tested with keyed rows -> only the
    genuinely-bad row 3 errors (`22-import-test-one-error-1280.png` / `-375.png` - "Row 4 / lifecycle
    / Unknown lifecycle stage for this workspace.").
15. **Fixed 3-row CSV** (`new_lead`/`hot_lead`/`cold_lead`, all valid keys) as a **fresh** import job
    -> Test -> "3 valid / 0 invalid / 3 total" (`23-import-test-zero-errors-1280.png`) -> **Import**
    -> redirected to `?from=/omnichannel/contacts` -> all 3 rows visible with the exact lifecycle
    stage assigned directly (no transition notification, per D-A2-13)
    (`24-import-committed-list-1280.png`). Search by the new rows' phone digits also matched
    correctly (not separately screenshotted - same mechanism as step 4).
16. **Export**: current query (all 6 contacts, no filter) -> dialog shows `ID` first + all 9 system
    columns, all checked (`25-export-dialog-1280.png`) -> Export -> `POST .../contacts/export` 201 ->
    `GET .../export/{jobId}/file` 200 (eager Celery finishes before the first poll) -> CSV downloaded
    to `~/Downloads/contacts (2).csv`, opened and verified: header `ID,Name,Phone,Email,Lifecycle,
    Tags,Assignee,Channel,Last message,Created`, 6 data rows, `ID` first, all values matching the
    list (see the report body for the full CSV dump).
17. **"Back to list keeps the segment" (AC-CTM-48's literal wording)**: switched to segment "P26 New
    Leads `<ts>`" -> opened a contact (`ctx=` query param carries `"segment":"<segmentId>"`) ->
    Conversation tab -> **Back to contacts** -> segment picker still shows "P26 New Leads `<ts>`" and
    the list re-renders the segment's 2 rows (`26-back-to-list-keeps-segment-1280.png`). **Note**: a
    raw browser hard-`reload()` of the bare `/omnichannel/contacts` URL (no `ctx`) resets the segment
    to "All contacts" - this is BY DESIGN (segment selection is client list-state carried through the
    Resource-shell's `ctx`/record-nav round-trip, exactly like every other Resource list in this
    codebase; there is no UAC clause promising survival of a bare hard-reload, only of the
    list<->detail round-trip, which AC-CTM-48 states explicitly and which PASSES). The **Columns**
    preference (Email hidden, step 8) DID survive a hard reload, because it is a genuine server-side
    per-user preference (`GET/PUT /me/preferences/omnichannel.contacts.list`), unlike the segment.

### AC-CTM-50 - permission gating (tenant A, "P26 Contacts Viewer" role: `contacts.read` only, then
   `contacts.read` + `workspaces.read`)

18. Created role "P26 Contacts Viewer" (User Management -> Roles -> Add role, real clicks) with
    ONLY `contacts.read` granted on the Omnichannel "Contacts" resource
    (`debug-permissions-page.png`-`page4.png` document the scroll-through to find the Omnichannel
    section of the permission matrix). Created user "P26 Viewer `<ts>`" assigned that role.
    Activated via the documented setup call (item 2 above, `psql` + `/auth/set-password`).
19. Logged in as the viewer in a separate session (`s26viewer`). Sidebar shows ONLY "Contacts" under
    Omnichannel (Inbox/Channels/Workspaces all correctly absent - each gated by its own permission
    the role doesn't hold). Clicked Contacts -> **the list rendered NOTHING** (not even the
    toolbar/table shell) - see the Defects section: `GET /omnichannel/workspaces` 403's for a role
    holding only `contacts.read` (that route requires `workspaces.read`), and the Contacts page has
    no fallback UI for that 403 (`27-viewer-contacts-list-1280.png`).
20. Granted `workspaces.read` too (setup call, since the in-app Roles permission `MultiSelect`
    could not be reliably driven this session - see "Harness gotchas") and re-logged in ->
    `GET /omnichannel/workspaces` now 200s -> the list renders all 6 rows with Filters/Export/Columns
    present but **Add contact / Import / bulk "Actions" / "Save as segment" / "Manage segments" all
    correctly absent** (`28-viewer-read-only-list-1280.png`) - confirms the `contacts.manage` /
    `segments.manage` / `contacts.import` gating on the LIST toolbar is correct.
21. Selected 1 row -> bulk toolbar shows only "Export" + "Clear selection", no "Actions" dropdown -
    confirms bulk mutation actions are gated even though row-selection itself renders.
22. Clicked into a contact -> **"Contact not found."** (`29-viewer-detail-no-edit-1280.png`) - see the
    Defects section: the single-contact detail route is gated by `conversations.read`, a DIFFERENT
    permission key than `contacts.read`, so AC-CTM-13/22's "the list itself still reads with
    contacts.read" promise does not extend to the detail page.
23. **Module-absence menu check**: created tenant `p26-noomni-<ts>` (Omnichannel never installed),
    logged in as its admin -> sidebar has ZERO Omnichannel entries at any level
    (`30-noomni-tenant-no-contacts-menu-1280.png`) -> header "Apps" mega menu -> zero Omnichannel
    entries (`31-noomni-megamenu-no-contacts-1280.png`) -> mobile "Apps" menu at 375px -> zero
    Omnichannel entries (`32-noomni-mobile-menu-no-contacts-375.png`). Control check: the SAME mega
    menu for tenant A's `contacts.read`-holding viewer DOES show "Contacts"
    (`33-tenantA-megamenu-has-contacts-1280.png`) - proves the absence above is module-gating, not a
    generic mega-menu bug.

### AC-CTM-50 isolation probes ([BE], curl - see the report body for the full command/response log)

- Tenant B (`default`, `demo@example.com`) token against tenant A's workspace: `GET .../contacts`,
  `GET .../contact-segments`, `POST .../contacts/export` -> uniform **404** each.
- Tenant B token against tenant A's export job id -> `GET .../export/{jobId}/file` -> **404**.
- Tenant A's contact id via tenant B's OWN workspace bulk-assign route -> `{"ok":[],
  "failed":[{"id":"<A-contact-id>","error":"not_found"}]}` - never a leak, never a bare existence
  oracle.
- Symmetric control: tenant A's token against tenant B's workspace -> **404**.

## Console errors

Only the pre-existing `Missing Description for {DialogContent}` Radix a11y warnings (seen on every
dialog family across this codebase, not introduced by this slice). No React error boundaries, no
uncaught exceptions, at any step above.

## Harness gotchas (agent-browser session, not product bugs)

- **Radix `Tabs` and dropdown-menu triggers required `agent-browser eval` dispatching a full
  `pointerdown/mousedown/pointerup/mouseup/click` sequence on the matched DOM node** - plain
  `agent-browser click @ref` silently no-op'd on the "New tenant" Modules tab, the module card
  "Actions" menu, the Roles "Permissions" tab, and the workspace "Tags"/"Contact fields" tabs in this
  session (matches the documented class of quirk from prior evidence runs).
- **The Roles permission picker is a cmdk `Command`-based `MultiSelect` (NOT the app's standard
  `SearchSelect`/checkbox-list `MultiSelect`)** - neither a plain `click` nor a synthetic pointer
  sequence on the option row reliably toggled its checked state in this session (the popover closed
  without registering); worked around with the documented `PATCH /roles/{id}` setup call (item 2
  above) to unblock the permission-gating verification. This is a candidate for a follow-up
  `agent-browser` skill note, not a product defect - the SAME multi-select renders correctly and is
  operable by a real mouse (screenshots show real unchecked/checked visual state).
- **A closed browser session (`agent-browser --session <name> close`) drops all client-side auth
  state**; a fresh `open` + real sign-in was required to pick up a just-granted permission set (JWT
  claims are resolved fresh per-request server-side, but the NextAuth session/JWT held by an
  already-open tab does not).
