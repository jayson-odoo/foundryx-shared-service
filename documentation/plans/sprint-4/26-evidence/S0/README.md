# Plan 26 S0 - Contacts module frontend mock - agent-browser evidence run

Run date: 2026-09-05/06. Lane: `s26` (backend `:8005` on `foundryx_service_s26`, frontend `:3004`).
Tool: `agent-browser` CLI (`--session s26fresh` after a stale-server false start under `--session s26`,
see "Environment gotchas" below). Login `demo@example.com` / `demo1234` at `http://localhost:3004`.

Screens are numbered in the order they were captured; `-1280` = ~1280px viewport, `-375` = ~375px.

## Steps + evidence

1. **Sign in** at `/signin`, land on `/`.
2. **Sidebar -> Omnichannel -> Contacts** (`01-list-1280.png`). List renders full-width, Resource-shell
   columns Name/Phone/Email/Lifecycle/Tags (+ Assignee/Channel/Last message/Created off-screen right),
   search box, segments `SearchSelect` ("All contacts"), Filters/Export/Columns/Add contact toolbar,
   leading select column + trailing row "..." menu. Lifecycle badges show the REAL workspace's
   status-engine stages (New Lead/Hot Lead/Payment/Customer/Cold Lead) with their authored emoji+colour.
3. Created 2 real tags (VIP, Follow up), 1 real custom field (Lead Source, dropdown list), and added 5
   real workspace members via the EXISTING (already-real, A1) Workspace settings tabs - this seeds the
   mock's synthetic rows with real ids so every picker (tags/lifecycle/assignee) offers only-real,
   never-invented options (see `services/contact-service.mock.ts` header doc).
4. **Filters** -> field "Tags" -> "is any of" -> "VIP" -> Apply (`04-list-filtered-by-tag-1280.png`).
   Server-shaped mock filtering narrows the list; Filters badge shows "1".
5. **Segments** `SearchSelect` -> "Urgent & high priority" (`05-list-segment-urgent-1280.png`) - the
   segment's stored filter (`priority in [HIGH, URGENT]`) ANDs with the still-active ad-hoc Tags
   filter (10 rows, all carrying VIP AND priority HIGH/URGENT).
6. **Columns** chooser - toggled "Channel" off/on, confirmed persistence + narrower table while hidden.
7. **Add contact** (`06-create-contact-1280.png`) - First/Last name, Phone*, Email, Language, Country,
   Lifecycle stage (defaulted "New Lead"), Tags, and the registered custom field "Lead Source" all
   render with typed inputs. Filled Zara Ismail + VIP tag + Website lead source -> Create ->
   navigates to `/omnichannel/contacts/mock-contact-new-1`
   (`07-created-contact-detail-1280.png` - outer shell loads from the mock; Details tab correctly
   shows "Contact not found." since this synthetic id has no real backend record yet - expected S0
   boundary, see "Known S0 limitations" below).
8. **Search** "Zara" from the list -> the created contact appears with its Lifecycle + Tags
   (`08-search-zara-1280.png`).
9. **Open a REAL anchor contact** (Sarah Chen, `cnt-001`, seeded by the backend's
   `seed_demo_conversations`) - Details tab (`02-detail-details-tab-1280.png`) shows the REAL thread's
   system fields, Lifecycle section (StatusBadge + "Move to..." picker) and Tags section, all via the
   reused A1 `ContactPanel`. Conversation tab (`03-detail-conversation-tab-1280.png`) mounts
   `<ConversationDrawer compact>` and renders Sarah's REAL seeded message history end-to-end.
10. **Bulk select 2 rows** (Sarah Chen, Priya Raj) -> Actions -> **Move lifecycle** ->
    (`09-bulk-move-lifecycle-dialog-1280.png`) -> pick "Hot Lead" -> Move ->
    (`10-bulk-move-lifecycle-result-1280.png`) "2 contacts moved." toast, both rows now show Hot Lead.
11. **Partial-failure demo**: selected Chandra Muthu (Payment stage) + Denise Ismail (Customer, a
    terminal/"won" stage) -> Move lifecycle -> Cold Lead -> `11-bulk-partial-failure-1280.png` -
    "1 moved, 1 failed. mock-contact-004: No move from Customer." (deterministic mock rule mirroring
    the real status-machine's "no edge from a terminal stage").
12. **Bulk Assign** -> `12-bulk-assign-dialog-1280.png` (SearchSelect, Unassigned + the 5 real
    workspace members) -> Demo User -> `13-bulk-assign-result-1280.png` "2 contacts assigned.", rows
    updated.
13. **Bulk Add tags** -> `14-bulk-add-tags-dialog-1280.png` (MultiSelect of the 2 real tags) -> VIP ->
    "2 contacts tagged." toast, rows updated (screenshot of the confirmed state captured mid-run, see
    terminal log; same shape as steps 10/12).
14. **Export** (no selection, "All contacts", 28 rows > the mock's 15-row wait-window threshold) ->
    `15-export-dialog-1280.png` (ID-first column checklist) -> Export ->
    `16-export-pending-toast-1280.png` - "The export is still running - it will finish in Jobs." with
    a "View Jobs" action, dialog stays open (D-A2-6a fallback - never a silent failure).
15. **Export a small selection** (2 rows) -> `17-export-selected-success-1280.png` - dialog closes
    cleanly (fast path resolves, CSV blob download fires via the shell's existing `downloadCsv`).
16. **Import** button: NOT rendered. Expected - gated on `contacts.import`, a permission that does not
    exist on the real backend yet (ships in S1 per D-A2-7); no real user, including this session's
    Admin, holds a not-yet-existing key. Verified by code read that `ResourceListConfig.importer =
    {entityType:'omnichannel_contacts', writePermission:'contacts.import', context:{workspaceId}}` is
    wired correctly and the shell's existing `can(config.importer.writePermission)` gate is exactly
    what suppresses it - the same mechanism will show the button the moment S1 grants the key.
    "Save as segment" / "Manage segments" are gated on `segments.manage`, in the same boat.
17. **Responsive pass at 375px**: list (`18-list-375.png`), create form (`19-create-375.png`), contact
    detail Details tab (`20-detail-375.png`), Conversation tab (`21-conversation-375.png`), and a bulk
    dialog (Move lifecycle, `22-bulk-dialog-375.png`) - no horizontal page scroll, no clipped/
    overlapping controls, dialogs stack their buttons and stay fully usable.

## Console errors

`agent-browser console` showed only Radix `Missing Description for {DialogContent}` a11y warnings on
the 4 new plain dialogs (`bulk-assign-dialog`, `bulk-tags-dialog`, `bulk-lifecycle-dialog`,
`save-segment-dialog`) - no functional errors, no React error boundaries, no failed fetches other than
the ones fixed during the run (see below). Logged as a follow-up, not a hard-fail (cosmetic dev-console
warning only, `ExportDialog`'s own `DialogDescription` is the pattern to copy).

## Bugs found + fixed during this run

- **Wrong status-engine `entityType` string.** The mock (`hooks/use-contact-lifecycle-stages.ts`,
  `services/contact-service.mock.ts`) queried `entityType=omnichannel_contact`; the real backend
  registers the contact lifecycle scoped machine as `omnichannel_contact_lifecycle`
  (`modules/omnichannel/services/lifecycle_service.py ENTITY_TYPE`). Fixed both files - confirmed via
  `GET /statuses?entityType=omnichannel_contact_lifecycle&scopeId=<workspaceId>` returning 200 with the
  real 5-stage graph instead of 404.
- **Stale `next-server` process surviving a rebuild** (the documented "wrong-build" class of bug,
  `docs/reference/process-lessons.md`) - `kill -9 <pid>` on the FIRST rebuild silently no-oped (the pid
  was still alive with the SAME start timestamp afterward), so the browser kept getting a stale build's
  HTML referencing a chunk hash the new `.next/` no longer had (`400` on
  `_next/static/chunks/6858-...js`). Confirmed via `ps -p <pid> -o lstart` + comparing the requested
  chunk hash against `ls .next/static/chunks/` before killing again and restarting cleanly. Not a code
  bug - a process-hygiene note for the next coder.

## Environment gotchas hit in this run

- **`agent-browser click @ref` (CDP-dispatched mouse click) intermittently did not fire the
  underlying `onClick`** for this build's shadcn/Radix `Button`/`Tabs`/`DropdownMenu` components (the
  documented class of harness quirk in `CLAUDE.md` - "a native `.click()` via `browser_evaluate` does").
  Worked around by dispatching a native `.click()` (or a full `pointerdown/mousedown/pointerup/mouseup/
  click` sequence for Radix `Tabs`/`DropdownMenu` triggers, which listen on `pointerdown`) via
  `agent-browser eval --stdin`. `agent-browser find text/role ... click` had the same intermittent
  failure on the sidebar accordion trigger and the row-level "+1" overflow badge; row clicks and
  `<a href>` navigations via `find`/`click` worked fine. This is a harness quirk, not a product bug -
  every affected control was also verified via a real ref-based `agent-browser click` succeeding on
  OTHER attempts in the same session (non-deterministic, not control-specific).
- Session `--session s26` was used first; after the stale-server incident above it was abandoned in
  favour of a fresh `--session s26fresh` browser + a fresh login, to guarantee no cached JS survived
  the rebuild. All evidence screenshots in this directory are from `s26fresh`.

## Known S0 limitations (by design, not defects)

- **Synthetic mock rows' Details/Conversation tabs 404 against the real backend.** Per plan §2 ("no
  second way to mutate a contact"), the Details/Conversation tabs are wired to the ALREADY-REAL A1
  `conversation-service` (`useMessages` -> `conversationService.getThread`), not to the new S0 mock
  `contact-service`. The 5 "anchor" rows (`cnt-001..005`, the dev-seed demo contacts) are real backend
  records and their Details/Conversation tabs work end-to-end (steps 9 above); the ~22 synthetic rows
  exist only in this file's in-memory store (for list-level tuning - 25+ contacts spanning lifecycle/
  tags/channels/assignees) and correctly show "Contact not found." rather than crashing. S1's real list
  endpoint replaces the whole mock file and every row becomes real.
- **Bulk-mutated rows only update the MOCK's in-memory summary, not the real backend record** for the
  same reason - `cnt-001`'s real lifecycle stage is untouched by the mock bulk-move in step 10 (visible
  if you reopen its real Details tab afterward - still shows the stage the real seed left it at). S2
  wires the real bulk endpoints onto the same UI.
- **Import wizard round-trip is untestable in S0** (button correctly hidden - see step 16); the wizard
  itself, `import-service`, and `jobs-service` are pre-existing, REAL, unmodified core engines reused
  unchanged per plan §2 - only the entity registration (`ImporterDef("omnichannel_contacts")`) is
  missing until S1/S3.
