# Foundryx Playbook UIUX in Shared Service

This file records how the Foundryx Playbook UIUX is applied to Shared Service (playbook step 8, "First time on a system"). It is the playbook's record for this repo: what was asked, what was answered, and what differs here.

Playbook version: 0.71.0

## System

- **Existing system**, not a new one: `service_frontend/` (Next.js 15, React 19, Tailwind 4, Metronic demo1 shell) with its own UI kit (`components/ui/`) and shared platform shells (`components/platform/`), about 140 pages.
- **Shipped behind the Foundryx UIUX switch, off by default.** With the switch off every page looks and behaves exactly as before. The only thing the playbook adds while off is the switch itself, in the Theme panel. The workflow never changes: same pages, steps, fields, rules and results.

## How the switch is built

- **Per browser, not synced.** First-party cookies: `fx_uiux=on` turns it on (off is the cookie's absence); `fx_theme=<light palette>.<dark palette>.<font>.<size>` keeps the viewer's palette, font and size. Mode (light, dark, auto) stays on next-themes' own setting, shared with the user menu's Dark Mode switch.
- **Server-rendered first paint.** `app/layout.tsx` reads the cookies; while on, `<html>` gets `data-fx="on"`, `data-fx-pal`, `data-fx-dpal`, `data-fx-font` and `--fx-scale`, and `<head>` gets one Google Fonts stylesheet (Geist, Plus Jakarta Sans, Inter, Manrope, DM Sans). While off the markup is exactly the old one.
- **Where the switch lives:** a palette (Theme) icon button in the top bar on wider screens; on phones the same panel opens from a "Theme" row in the user menu, under Dark Mode, because the 375px top bar has no room for another icon.
- **Name and version** come from one place, `service_frontend/lib/fx/version.ts` (`FX_SWITCH_NAME`, `FX_PLAYBOOK_VERSION`), shown as "Foundryx UIUX (0.71.0)".
- **Scope:** every route. Embedded pages (`app/embed/**`) are always off (`<FxOff>` in `app/embed/layout.tsx`: components and global look). Sign-in (`app/(auth)`), the public portal (`app/(public)`) and `/wa-callback` get only the global look (font, size, scrollbars) for a browser that opted in: `<FxComponentsOff>` in their layouts makes `useFx()` false there, so shared fields stay legacy and none of their pages is converted.
- **Advanced settings** (behaviour knobs) are stored per browser in `localStorage` key `fx_settings`, holding only values that differ from the playbook defaults. The full list with defaults is `service_frontend/lib/fx/settings-schema.ts`.
- **Advanced settings panel:** the Theme panel's "Advanced settings" link (shown only while on) opens a floating, draggable, see-through panel (`service_frontend/components/fx/settings/advanced-panel.tsx`): master switch, presets (Save, Export, Import, Delete with Undo; stored per browser in `fx_presets`; files are validated and clamped to the schema), Find a setting, one section per area with Reset, and Reset all. Its place is remembered per browser (`fx_adv_pos`). It shows only rows whose behaviour has been built: `FX_BUILT_SLICES` in `settings-schema.ts` lists the merged slices, and each slice that builds a setting adds itself there. Until company-wide admin settings exist (backend work), every value is per browser.
- **Size base:** the root font size is SS's 16px base times the Theme panel size, so "Normal (90%)" renders 14.4px root text while the switch is on.
- **CSS** stays in SS's four sanctioned CSS files, every fx rule scoped under `:root[data-fx="on"]` (`service_frontend/css/fx-scope.inventory.test.ts` enforces it).
- **Off is tested:** `service_frontend/components/fx/__parity__/` holds switch-off snapshots of the shared shells, recorded before any switch work. A change that needs one of them updated is wrong by definition.

## Answers to the fundamental questions (2026-11-18, verbatim)

- Q1 One Main Action per page (red #CC3333, top right; others become quiet icon actions; full-action label on hover): "ok"
- Q2 Other Actions as icon buttons with tooltip labels (More menu past ~4; existing confirm dialogs kept, new words + 3 s press-and-hold): "ok"
- Q3 Toasts (what/for whom/how many/by whom; Undo, 6 s bar) everywhere now; done pages for broadcast/template sends only shown in the mock as a separate before/after choice (workflow change): "ok"
- Q4 Table lists (Smart/Table view, Columns panel, header search/filter/sort, frozen header row, pager 50, empty/error/no-access states, cards on phones, Hold to Copy): "all ok"
- Q5 Fields, money fields, steppers: "all ok"
- Q6 Theme panel + size slider (Foundryx UIUX switch off by default): "all ok"
- Q7 Side panel rail + top bar: "all ok"
- Q8 Hover pop and motion: "all ok"
- Step 5 "Do you want to see mocks first?": "yes show mocks" -> UI mock of 5 pages (before/after), then UX mock.

## Gap audit (2026-11-18)

The audit listed 89 SS patterns: 43 covered by the playbook, 3 where SS does better, 43 not covered. Fifteen were kept as proposed playbook rules (3 better, 12 not covered), most useful first:

1. Editing a record, and leaving with unsaved changes
2. Work that runs in the background
3. Import and export
4. Undo by waiting (deletes held for a short window)
5. A list beside its open item
6. Hidden or greyed: permissions vs "not yet"
7. A blocked area says what it waits for
8. Reduce transparency and more contrast
9. Times and time zones
10. Money in more than one currency
11. Secrets shown once
12. Connected services
13. Coming back to a list; next and previous record
14. Type to confirm the few that wipe a lot
15. Lists and numbers that update by themselves

Options chosen for its open points (owner, verbatim: "#2 ok to go with the recommendations"; every open point takes its recommended option): one Jobs place; Check always before Import; "Undo" with 10 s for deletes / 5 s otherwise; 12-hour clock; organisation zone for day totals; RM for home currency + ISO codes for others; type the record name/number to delete (replaces the hold); record arrows grey out at the ends; view-only pages as plain text; Hold to Copy tip and RCT solid; Connect on each card; single-click Discard; connection banner after 5 s; no hover-widen on the list.

Whether these rules are added to the playbook itself is decided in the playbook's own repo; this file records only the options chosen for SS.

## Agreed differences (these win for Shared Service)

From the gap audit, SS-specific patterns that stay as they are:

1. Chat thread details in the omnichannel inbox (bubbles, delivery ticks, reactions, quoted replies, voice notes, quick replies).
2. The WhatsApp 24-hour messaging window and template-only sending.
3. Embedded (iframe) mode: host handshake, host theme, token refresh, allowed origins. Embedded pages stay outside the switch.
4. The `/wa-callback` page specifics.
5. The WhatsApp template builder with bubble preview and approval statuses.
6. Broadcast campaign specifics: audience count, test send, live delivery counts.
7. AutoCount sync tooling: SQL editor, schema tree, mapping simulator, formula builder, batch review.
8. Workflow and status canvas builders.
9. The form builder with conditional fields and formulas.
10. The code editor and raw JSON payloads in logs and traces.
11. Terminology overrides (a tenant renames nouns).
12. The numbering format editor.
13. White-label branding: tenants never see "Foundryx"; tenant logo, colours and name on the shell and public pages. This conflicts with "the red action stays Foundryx red" and with the switch's name; see the open choices below.
14. The ideation portal (public board, roadmap, changelog, upvotes).
15. The document drive explorer (folder tree, grid, versions).
16. The web chat visitor widget and its settings.
17. The impersonation banner keeps its "Hide banner" control.
18. "Every dropdown searchable" is SS's own house rule; which wins over the playbook's about-12-options threshold is still open (Q-DD).

From the build:

- **Token names:** the playbook's tokens are prefixed `--fx-` here (`--fx-act`, `--fx-ink-3`, `--fx-ease-out`, `--fx-z-pop`, ...), because SS already uses `--z-header` and Tailwind already defines `--ease-out`. They exist only while the switch is on.
- **Layers** map onto SS's named z-scale: `--fx-z-header` = `--z-header` (10), `--fx-z-pop` 40, `--fx-z-dialog` = `--z-modal` (50), SS's banner 60, `--fx-z-toast` 70, `--fx-z-tip` 1000.
- **Theme panel copy:** the panel shows no explanatory sentences (the playbook draft's "Saved in this browser..." line and the mock's "Off: SS looks and works exactly as today..." line), because SS's foolproof-UI rule bans instructional copy on screen.
- **Phones:** the Theme entry sits in the user menu, not the top bar (see "How the switch is built").
- **Confirm dialogs:** which actions ask first is unchanged (SS's carve-out list). Plain confirms get the 3 s press and hold; the typed ones (module uninstall, tenant purge, bulk share revoke) type the record's name or number instead of holding (gap-audit choice), matched ignoring case and spaces, with the action greyed and "Type the name to confirm." under it until it matches. The safe button is "Keep" plus the action's object ("Keep tenant"), or "Go back" when the action names no object. Discard changes is a single click.
- **Undo by waiting:** the tenant windows stay (10 s deletes, 5 s otherwise, Settings > General); under the switch the countdown reads "Deleting 12 contacts in 8 s" with "Undo", and it does not pause under the pointer because the server's clock does not stop. Done toasts (`toast.fxDone`) keep the playbook's 6 s with a pause.
- **The attention pulse keeps its 1.8 s under reduced motion** (the playbook says it is not decoration), so it names its own duration rather than the `--fx-t-pulse` token, which reduced motion stills.
- **Keyboard focus slides an icon action's label out** (playbook) although SS's design language bans motion on a keyboard-initiated action; the playbook rule wins under the switch, and reduced motion still stops it.
- **Header search and filters run on the server**, so a column gets one only where its list already declares that field filterable: text searches (contains), date ranges (whole days, both ends) and status ticks. Status ticks show no counts and number or amount columns get no range, because the list API returns neither counts per value nor number ranges (its range filter takes dates only). A column with nothing to filter sorts when its header is clicked.
- **"Showing 51-100 of 12,340"** uses a hyphen, not the playbook's en dash (SS bans en dashes in every tracked file).
- **Lists under the switch keep the page and filters in the address** (`ctx`) whenever the list owns its page; an embedded list never writes the record's own `ctx`. With the switch off only lists that opted in do, as before.
- **Smart view never shortens a value:** long values wrap inside their capped width (no two-line limit, since a clamp would add the "..." the playbook bans). Lists that reorder their rows by dragging keep today's table (the toggle and moving columns would fight the row order). Hand-resizing columns is off under the switch; the widths come from the content.
- **Dragging a header** moves the header row live and the column's cells on drop; the Columns panel drags on touch after a short press anywhere on the row rather than only from the grip, so a quick swipe still scrolls the list.
- **View and column choices are stored with the user's other list preferences** (new keys next to the list's own), so they follow the person across devices, unlike the per-browser switch.
- **The Advanced settings show the actions and lists rows** now that both are built; "Hover lift" turned off stops the lift on fields and list cards.

## Mocks

- UI mock (five pages, before and after): https://claude.ai/artifact/NNK9pn3QhSpqVg34oDLP9t
- UX mock (the same pages, interactive): https://claude.ai/artifact/UEqSsXkU4dWUChxvAZRiji

The owner said the mocks need no major change.

## Open product choices (open, default applied)

Each is still with the owner; the build uses the default shown until answered.

- **Q-PLACE:** where the switch lives while off. Default: a Theme icon button in the top bar, as mocked (phones: the user menu, see above).
- **Q-PHONE:** inbox on phones as browser-style tabs (mock) or one pane at a time with a back button. Default: browser-style tabs, as mocked.
- **Q-24H:** a closed WhatsApp window shows a warning strip with "Choose template" or the inline template picker (mock). Default: the warning strip with "Choose template".
- **Q-INBOX:** the inbox red action is Close conversation or Assign to me. Default: Close conversation.
- **Q-SEND:** add "ask first, press and hold" before a broadcast sends. Default: no; it sends at once, as today.
- **Q-TPL:** "template sends" means sending a WhatsApp template in a conversation, or submitting a template for approval. Default: only the broadcast done page until clarified.
- **Q-WL:** may tenant users see the label "Foundryx UIUX (0.71.0)", and does the red action stay #CC3333 for branded tenants. Default: the label shows as built (one constant in `lib/fx/version.ts`, easy to rename) and the red action stays #CC3333.

Also in place as build defaults, still open with the owner: the switch and theme are per browser (Q-SYNC); sign-in, public portal and embedded pages stay outside the switch (Q-SCOPE); fx CSS stays in the four sanctioned CSS files (Q-CSS); Advanced settings are per browser (Q-ADV).

Decided since:

- **Q-TOP (decided by the owner):** one Jobs button replaces Uploads, Imports, Jobs and Downloads in the top bar; Notifications, Chat and Apps stay beside it as icon buttons (the mock had removed Chat and Apps), and so does the Theme button (phones: the Theme row in the user menu).
- **Q-QT (decided by the owner):** the Clipboard, Quick Tool and right-click tool are not built.

## Fields (slice F4)

Built defaults for the field rules, each kept in one place so it is easy to change:

- **Every dropdown is searchable**, whatever its size (SS's own rule; Q-DD default). The playbook's ~12-option threshold is not used.
- **Moments** use a 12-hour clock while the switch is on: "14 Nov 2026, 2:14 pm"; dates read "14 Nov 2026"; recent ones in lists read "now", "5 min", "3 h", "Yesterday", then "14 Nov". `useDatetime()` switches by itself, so every page that already goes through it gets this. The zone line under a time picker reads "Kuala Lumpur time (GMT+8)".
- **Day totals and quick picks** count in the report's own zone (the picker's `timeZone`), since SS has no organisation zone yet (Q-TZ default). The range quick picks are the playbook's (Today, This week, This month, Last month, This year) plus SS's Last 7 days and Last 30 days; weeks start on Monday.
- **Money:** "RM" only when the currency is MYR; every other currency shows its ISO code, whatever the tenant default (Q-CUR default; `FX_HOME_CURRENCY` in `service_frontend/lib/money.ts`). `formatMoney` is unchanged; `formatMoneyFx` is the new formatter.
- **Secret fields:** the show/hide eye is reachable by Tab and carries `aria-pressed` while the switch is on (today it is skipped by Tab).
- **The bare `Select`** (a few screens) gets the playbook look only; it does not switch to the phone's own picker on touch, because its options are not known to the field.

## Shell (slice F5)

Built defaults for the side panel, top bar and banners:

- **Side panel:** the icon rail is max(64px, 5% width) and opens to SS's own 280px panel width. It opens on hover or keyboard focus, waits for the "Wait before it folds to icons" setting (0.3 s), then slides shut over 0.65 s; the slide stays under reduced motion, as the playbook says. The pin is remembered per browser. Icons take the six side-menu hues in menu order. The menu and its gating (permissions, modules, platform entries) are exactly the legacy panel's. Touch screens at desktop width get no hover opening: a tap on an icon goes straight to its page.
- **No safe triangle:** SS's side panel has no flyout submenus (its groups open in place) and every other submenu is a Radix menu with its own pointer grace area, so no safe-zone code was built and the "Show the submenu safe zone" setting stays hidden.
- **Top bar:** the mega menu stays on wider screens, so no way to a page is lost. The search box opens SS's existing search; cross-record search is a separate feature. SS has no branch picker, so only the search box moves into the page header on merge. Search fades into the header over 0.2 s (the playbook's hover step) rather than 0.25 s, which is not one of its timing steps.
- **Phones:** the page header scrolls away under the frozen top bar (it is frozen only on wider screens). Condensed, the bar's icon buttons and the avatar fold into one menu button.
- **One Jobs place:** until slice W3-JOBS builds the playbook's single Jobs list, the Jobs sheet shows SS's four existing lists (Uploads, Imports, Jobs, Downloads) as tabs; whatever opened one of the old drawers now opens the sheet on that tab. The badge is the number of uploads, imports, jobs and downloads still running.
- **Impersonation banner:** a system banner in the warn set, "Viewing as <name>. Anything you create or change is still recorded under your own account.", with "Stop viewing as <name>"; "Hide banner" stays (agreed difference 17) and folds it to a pill as today.
- **Lost connection:** the system banner "Reconnecting. New messages may be late." shows after 5 s without the live connection (owner choice) and leaves once it is back (`useConnectionBanner`).
- **Blocked area:** a thin warn strip at the top of the blocked part, one line and one text button (`FxBlockedArea`, gap audit item 7).

## What was applied (record of the build, 2026-11-18 to 2026-11-19)

Every slice below is merged into `development` and sits behind the switch, off by default. Numbers are pull requests in this repo.

Foundation:

- #276 F1: the switch, theme tokens, Theme panel and the switch-off parity harness.
- #277 F4: fields (dates, money, steppers, notes, secrets, password strength, moments and zone lines).
- #278 F2: the red Main Action, icon actions, confirm dialogs, done toasts and the page header.
- #279 S-ADV: Advanced settings panel and presets.
- #285 F3a: lists (Smart and Table view, Columns panel, header search, filter and sort, pager).
- #288 F3b: list selection bar, empty and error states, phone cards, Hold to Copy, record arrows.
- #287 F5: side panel rail, top bar, the one Jobs button, banners.
- #291: dropdown options clickable under the new look.
- #295: the reason shows when impersonation is refused; the app logos are restored.
- #297: foundation follow-up from the first page wave (record pages get their red action and More menu from the form config, list Create handed to the page header, the countdown names its record, steppers clamp without snapping, end-aligned amount columns, more icons).
- #305: fix batch (list date filters use the user's day, the live feed reconnects, the discard guard asks before leaving typed values in both looks, media limit, frozen list header, phone card status, merged search).

Pages (109 routes under `app/(protected)/`):

- Wave 1: #292 conversation pane, #294 inbox, #289 contacts list, #296 contact record and new contact, #293 new broadcast and its done page, #290 products.
- Wave 2: #299 broadcasts list and detail, dashboard, reports; #298 channels, connect wizard, WhatsApp template builder; #300 workspaces, media limits, quick replies, embed access, migration.
- Wave 3: #301 users, roles, teams; #303 jobs, imports, the import steps, the Jobs sheet; #302 tenants, status engine, platform rules, App Store; #306 documents drive, shared links, document types, document settings; #304 developer logs, log settings, email log, AI traces, AutoCount calls.
- Wave 4: #308 general, branding, terminology, numbering, statuses, rules, workflow settings, import settings, meeting settings; #311 email templates and integrations; #307 Claude connector, AI agents, AI skills; #312 My Account and My meetings.
- Wave 5: #313 AutoCount companies, entities and the task editor chrome; #314 AutoCount review, pull and find.
- Wave 6: #317 feedback, triage board, business requirements, embed connections; #315 workflows, forms, the fill page and submissions.

Fixes to today's look that the check of the new look found, merged 2026-11-19 by the owner's word:

- #319: the share dialog's Expiry and Password switches open their fields; a share's expiry ends at midnight in the viewer's zone.
- #320: the broadcast Recipients filter works with several delivery states ticked (includes a small backend change); the dashboard and reports stop loading and offer "Try again" when a load fails.

Not converted, on purpose: `/` (template dashboard), `/dark-sidebar`, `/i18n-test`; sign-in, the public portal, embedded pages and `/wa-callback` (see "How the switch is built").

## Agreed differences added during the page waves

Owner decisions carried by the page-wave brief (2026-11-18 to 2026-11-19), on top of the lists above:

- **Workflow unchanged:** no new steps and no removed steps beyond what the answers approve. Every write or send made under the switch is the same request as today's for the same input; each page slice carries a test comparing both looks.
- **Deletes:** where the playbook asks for a strong confirm, the user types the record's name or number (no press and hold): erase a contact (its name), tenant purge (the slug), module uninstall (the module name), delete forever in Documents (the entry's name, or the count when several are ticked), bulk revoke of shared links and of Claude connector grants (the count). This settles Q-ERASE and Q-BULK.
- **Undo** only where the existing API can really reverse the action; everywhere else the done toast has no Undo. Deletes keep the tenant's deferred window (10 s deletes, 5 s otherwise).
- **Per-section editing stays** on the contact record (settles Q-EDIT): the record has no single red action; each section keeps its own Edit.
- **Money:** "RM" only when the currency is MYR, the ISO code otherwise (settles Q-CUR). **Day totals** use the report's own zone (settles Q-TZ). **Every dropdown is searchable** (settles Q-DD).
- **Secrets and keys** are shown once, then as "ending a91c"; write-only where the answers say so.
- **One Jobs place** (the shell's Jobs sheet) and **Check always before Import**.

Owner decisions of 2026-11-19:

- A product with no currency keeps showing "RM" (the frontend has no tenant default currency to fall back to).
- A failed send keeps the message in the thread and the text in the box.
- Rotate secret keeps the 3 second press and hold.
- The pasted-token "Try again" is kept.
- Rotating the embed signing secret keeps its confirm.
- The contacts branch (workspace) picker stays in the page header for now; the top bar has no slot for it.

Differences that came out of the build (each recorded in its pull request):

- **Connect on each card:** Channels and Integrations have no red action; each service card carries its own Connect (gap-audit choice). Read-only pages (dashboard, reports, jobs, imports, logs, email log, AI traces, AutoCount calls, review, shared links, triage board) and list-of-settings pages (terminology, numbering, statuses, rules, branding) have no red action either, because they have no single main thing to do.
- **Channel disconnect** stays the deferred action with Undo, not a confirm (the confirm carve-out list does not grow).
- **Import steps 2 to 4 stay on the import page** instead of moving into the dialog: a dialog cannot refresh the list behind it after an import.
- **AutoCount batch review:** "Preview push" stays a visible button so the blocked red action can point at it.
- **Form fill page:** number fields keep today's input (a stepper cannot hold an empty answer, and the decimal field submits a padded string today).
- **Inbox rail** shows no counts (the API returns none per view, stage or team).

## Not built, and why

- **"Template sends" done page** (owner decision, Q-TPL): only the broadcast done page exists.
- **Clipboard, Quick Tool, right-click tool** (owner decision, Q-QT).
- **Ask first before a broadcast sends** (Q-SEND default): it sends at once, as today.
- **Undo** after: a lifecycle move, erase, reopening a closed conversation, send now, cancel and duplicate of a broadcast, API key mint, revoke and rotate, workspace create and save, migration start and abort, user and role edits, invitations, tenant create, save and purge, module install and uninstall, every import step, email retry, numbering changes, grant revoke, AutoCount company saves, batch approve and discard, feedback status moves, comments and captures. The API has no reverse for any of them.
- **Done toast buttons other than Undo** ("Download", "View errors"): the toast takes only Undo.
- **"A job that ended with errors stays marked until opened":** nothing stores a seen state.
- **Counts on status filter ticks and number or amount ranges in list headers:** the list API returns neither.
- **Counts on the inbox rail:** see above.
- **Company-wide admin settings and a synced switch** (Q-ADV, Q-SYNC): both need backend work; everything stays per browser.
- **Storage migration wizard:** restyled and unit-tested, but no page mounts it, so it cannot be reached.
- **The playbook's own audit script was skipped by the owner on 2026-11-19** (this settles Q-AUDIT): it drives a browser tool this repo has retired and bans from every tracked file. The full check below was done by hand with the repo's allowed browser tool instead.

## Full check (2026-11-19)

Run on `development` at `b89a7184` (before #319 and #320 merged; both are fixes to today's look and were not re-run in a browser), against a throwaway local stack (scratch database, sandbox channels, demo admin and platform operator).

- Lint 0 errors (259 warnings); 675 test files and 5,607 tests pass; production build passes; the four convention greps are empty.
- 105 of the 109 converted routes were opened at 1280 and 375, switch on and off (420 page loads). Menu pages were reached by side-menu clicks at 1280 in both looks; record and "new" pages by clicks from their list under the switch at 1280, then by address for the other three passes. No page scrolled sideways at 375 in either look. With the switch off no page carried `data-fx`. With it on every page carried the new shell, and every page except the form fill and submission pages carried the new page header (FX-39 below).
- Not reached (no local way to create the record): a migration job, an AI trace, a Claude connector grant, an AutoCount review batch. The AutoCount mapping page was opened only in its "not configured" state.
- Flows done once in each look with the same input, and the write requests compared: add product, new broadcast and Send now (sandbox), send a message in a conversation, new quick reply, new team, users import (upload, check, import), save general settings, capture feedback, fill and submit a form. All identical. Under the switch only: the Theme panel and the switch, Jobs sheet, users search, trash a user and Undo, erase a contact by typing its name, the discard guard, reopen a conversation, light and dark, reduced motion (three pages).
- Could not run locally: real WhatsApp and Meta sends and AutoCount calls (checked up to the request or the blocking message).
- Console: no page errors. Failed requests seen: the Branding page asks for `/media/foundryx/foundryx-logo.png`, which is not in the build (both looks); the new email template page sends two preview requests that are refused (422) before anything is typed (new look only).

## Known open items

Still open after the full check (ids from the programme's findings list):

- FX-05: on phones the breadcrumb wraps beside the red action (not seen in this check; not fixed by any slice).
- FX-06: the see-through Advanced settings panel lets the red action glow through. Needs an owner decision.
- FX-07: status filter ticks show no counts (needs backend counts).
- FX-08: the default sort shows as an active sort.
- FX-14: a product with no currency shows "RM" (decided 2026-11-19: keep).
- FX-18: the top bar has no slot for a branch picker (decided 2026-11-19: stays in the page header for now).
- FX-23: shared form sections show field errors as text that takes layout space.
- FX-24: with the switch off, the contacts page can scroll 3px sideways at 375 when Manage segments shows (exists today; not seen in this check).
- FX-28: a list cannot be refetched in place from outside.
- FX-29: the conversation socket reports its connection only to the inbox, so the broadcast page cannot show the lost-connection banner.
- FX-34: the typed-confirm hint says "name" also for a number.
- FX-35: confirm dialogs have no new-look-only title or wording fields.
- FX-36: the storage migration wizard is mounted on no page.
- FX-37 (new): the Branding page's logo preview asks for a file that is not shipped (`/media/foundryx/foundryx-logo.png`, 404), in both looks.
- FX-38 (new): under the switch the new email template page sends two refused preview requests (422) on load.
- FX-39 (new): under the switch the form fill and submission pages keep today's header and orange Submit button (no page header, no red action).

Closed during the programme: FX-01, FX-02, FX-03, FX-04, FX-09, FX-10, FX-11, FX-12, FX-13, FX-15, FX-16, FX-17, FX-19, FX-20, FX-21, FX-22, FX-25, FX-26, FX-30 (#320), FX-31 (#320), FX-33 (#319). FX-27 and FX-32 were process notes.

## Final confirmation

Final confirmation: confirmed by the owner on 2026-11-19

Final confirmation of the design, in words: confirmed by the owner on 2026-11-19, after the owner tested the new look on a local build of `development` that included the two fixes #319 and #320 and the record #321. The switch still ships off by default, and this record changes no product code. FX-37, FX-38 and FX-39 from the full check stay open and unfixed.
