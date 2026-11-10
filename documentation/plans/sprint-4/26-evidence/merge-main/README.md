# Merge-main smoke run (post-merge verification)

Branch `sprint-4/26-contacts-module`, worktree `.claude/worktrees/s26`. Merged
`origin/main` (`d302ea7` - plan 23 design-language restyle PR #41 + plan
25/A1 contact-data-model PR #42) into the S1 head (`937e16d`). This run
verifies the merge did not regress plan 26's S0 (frontend mock) / S1
(backend list endpoint) work and that the post-merge alignment fixes (sonner
-> `lib/toast`, `mode: 'onTouched'`, PageHeader/loading.tsx inventory gates)
hold up under real clicks.

Session: `agent-browser --session s26`. Servers: backend `:8005`
(`DATABASE_URL=...foundryx_service_s26`), frontend `:3004` (fresh
`rm -rf .next && npm run build` + `npm start -- -p 3004`). Login
`demo@example.com` / `demo1234` (default tenant, bare `localhost:3004`).

## Run log (real clicks from `/`, no typed URLs except viewport-setup opens)

1. Signed in via `/signin` form (email + password fields, Sign In button).
2. Sidebar: expanded "Omnichannel" (`find role button --name Omnichannel`),
   clicked "Contacts" -> `/omnichannel/contacts`.
   - `01-contacts-list-1280.png` / `02-contacts-list-375.png` - PageHeader
     (title/breadcrumb/description), search, "All contacts" segment
     picker, Filters/Import/Export/Columns toolbar, "Add contact", real
     seeded rows (Sarah Chen, Priya Raj, ... lifecycle badges + tags).
3. Clicked **Filters**, set `Name contains "Sarah"`, **Apply**.
   - `03-contacts-filters-1280.png` (builder open) /
     `04-contacts-filtered-save-segment-appears-1280.png` (1 row, "Save as
     segment" action appears in the header - proves the merged
     `resource-list.tsx`'s `onFilterChange` effect + plan 23's restyled
     `PageHeader` coexist correctly).
4. Clicked **Save as segment**, named it `Sarah test segment <timestamp>`,
   **Save segment**.
   - `05-save-segment-dialog-1280.png`, `06-segment-saved-toast-1280.png`
     ("Segment saved." toast - confirms the `hooks/use-contact-segments.ts`
     sonner -> `@/lib/toast` fix dispatches through the real `<Toaster>`).
5. Clicked **Manage segments** - the new segment is listed alongside the
   seeded ones (No recent activity / Unassigned / Urgent & high priority).
   - `07-manage-segments-1280.png`.
6. Clicked the filter icon on the test segment - the `FilterBuilder` opened
   PRE-SEEDED with `Name contains "Sarah"` (`08-edit-segment-filter-
   initialValue-1280.png` - proves `filter-builder.tsx`'s merged
   `initialValue`/`ruleToDraft` prop still works against the restyled
   builder). Closed via Escape, then deleted the test segment (typed-confirm
   dialog, "Segment deleted." toast) to leave no residue.
7. Cleared the filter, clicked **Add contact** -> `/omnichannel/contacts/new`.
   - `09-create-contact-1280.png` / `10-create-contact-375.png` - two-column
     (1280) / stacked (375) form, `Phone *` required marker, verb+noun
     buttons ("Create contact", "Cancel"), SearchSelect pickers (Lifecycle
     stage, Lead Source, Tags) with no free-text hint copy.
8. Clicked **Back to contacts**, clicked **Sarah Chen** ->
   `/omnichannel/contacts/cnt-001?ctx=...` (ctx-restore confirmed - filter
   from step 3 round-tripped into the URL, and clearing/re-entering the list
   round-tripped cleanly for the 375px pass too).
   - `11-contact-detail-details-tab-1280.png` (Details tab: two-column facts,
     Lifecycle badge + "Move to..." picker, Tags) /
     `12-contact-detail-conversation-tab-1280.png` (Conversation tab - the
     A1 message-thread panel embedded inside the contact detail, with
     internal-note styling, timestamps, read receipts, composer).
   - 375px repeat: `13-...-375.png` / `14-...-375.png` - record-nav pager
     (`1 / 27`) and both tabs reflow cleanly, composer stacks.
9. Back to the list, selected 2 rows (checkboxes) - bulk toolbar appeared
   ("2 selected", Actions/Export/Clear).
   - `15-bulk-select-1280.png`, `16-bulk-actions-menu-1280.png` (Assign /
     Add tags / Move lifecycle).
10. Clicked **Move lifecycle** - dialog opened ("Move lifecycle for 2
    contacts", SearchSelect stage picker, verb+noun "Move"/"Cancel"); cancelled
    without applying (`17-bulk-move-lifecycle-dialog-1280.png`).
11. 375px repeat: selected 1 row, opened Actions -> **Assign** -
    `18-bulk-select-375.png` / `19-bulk-assign-dialog-375.png` (stacked
    buttons, "Unassigned" default option, no hint copy). Cancelled.
12. Sidebar -> **Workspaces** -> clicked **General**.
    - `20-workspaces-list-1280.png` (Active|Trashed segments) /
      `21-workspace-detail-settings-tab-1280.png` (Settings/Channels/
      Members/**Lifecycle**/Contact fields/Tags/API Keys tab strip - the
      plan-26 Lifecycle tab survived the merge alongside plan-25's Contact
      fields/Tags/API Keys tabs).
    - Clicked **Lifecycle** - `22-workspace-lifecycle-tab-1280.png`: the
      scoped status FlowCanvas renders (New Lead -> Hot Lead -> Payment ->
      Customer, Cold Lead, edge labels) with a "Customized" badge (expected;
      the badge's scoped-entity mislabeling is tracked separately as
      `BL-SS-065`, not a regression from this merge).
    - 375px repeat: `23-workspaces-list-375.png` /
      `24-workspace-detail-settings-tab-375.png` (tab strip scrolls
      horizontally to reveal Lifecycle/Contact fields - confirmed by
      scrolling the `[role=tablist]` container) /
      `25-workspace-lifecycle-tab-375.png` (canvas box reflows to the
      narrower viewport).

## Findings

- **No console errors or page errors** at any point in the run (`agent-
  browser console` / `errors` both empty at the end); only two pre-existing
  Radix `Missing Description for {DialogContent}` a11y warnings on the
  Conversation tab dialog family (unrelated to this merge, seen the same in
  the Vitest suite for `alert-dialog.test.tsx`/`sheet.test.tsx`).
- **Fixes applied before this run** (see the coder's report for detail):
  `sonner` -> `@/lib/toast` in 6 plan-26 files (2 eslint errors ->0
  no-restricted-imports violations were actually 6, all fixed); `mode:
  'onTouched'` added to the 2 `useForm` calls in the contacts module
  (`use-contact-form.tsx`, `save-segment-dialog.tsx`); 3 new `loading.tsx`
  siblings (`contacts/`, `contacts/[id]/`, `contacts/new/`) closing the
  `AC-DLA-48` inventory gap; `contacts/page.tsx` migrated off the retired
  `ToolbarPageTitle`/`Toolbar*` onto `PageHeader` (`hideHeader` +
  `restoreFromCtx` on the embedded `ResourceList`) closing the `AC-DLA-27`
  inventory gap. All confirmed live in this run (steps 2, 7, 9, 12).
- **Merge correctness spot-checked structurally** (diffs, not just runtime):
  `bootstrap.py` carries both main's deferred-actions hook registration AND
  S1's `phone_digits`/`contact_segments` idempotent DDL + backfill;
  `menu.config.tsx` carries both main's Metronic-demo stripping (single
  "Dashboards" leaf, `MENU_SIDEBAR_CUSTOM` removed) AND the Contacts entry +
  full Omnichannel section in all three menu arrays (sidebar/mega/mobile-
  mega, no duplicates); the three shared Resource-shell files
  (`resource-list.tsx`/`types.ts`/`filter-builder.tsx`) carry both plan 23's
  restyle and plan 26's additive `onFilterChange`/`initialValue` props,
  confirmed both structurally and live (steps 3-6).
- **Migrations**: core `alembic upgrade head` -> `b7c1d2e3f4a5` (matches
  main); module chain -> `0010_omni_contacts_module` (single linear chain,
  down_revision `0008_omni_contact_model`, no fork). `bootstrap_db` ran
  clean end to end (migrated + seeded + modules).
