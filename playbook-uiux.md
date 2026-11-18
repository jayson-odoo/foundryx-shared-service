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

## Mocks

- UI mock (five pages, before and after): https://claude.ai/artifact/NNK9pn3QhSpqVg34oDLP9t
- UX mock (the same pages, interactive): https://claude.ai/artifact/UEqSsXkU4dWUChxvAZRiji

The owner said the mocks need no major change.

## Open product choices (open, default applied)

Each is still with the owner; the build uses the default shown until answered.

- **Q-TOP:** keep Chat and Apps in the top bar beside the one Jobs button (the mock removed them). Default: one Jobs button; Notifications, Chat and Apps stay as icons.
- **Q-PLACE:** where the switch lives while off. Default: a Theme icon button in the top bar, as mocked (phones: the user menu, see above).
- **Q-PHONE:** inbox on phones as browser-style tabs (mock) or one pane at a time with a back button. Default: browser-style tabs, as mocked.
- **Q-24H:** a closed WhatsApp window shows a warning strip with "Choose template" or the inline template picker (mock). Default: the warning strip with "Choose template".
- **Q-INBOX:** the inbox red action is Close conversation or Assign to me. Default: Close conversation.
- **Q-SEND:** add "ask first, press and hold" before a broadcast sends. Default: no; it sends at once, as today.
- **Q-TPL:** "template sends" means sending a WhatsApp template in a conversation, or submitting a template for approval. Default: only the broadcast done page until clarified.
- **Q-WL:** may tenant users see the label "Foundryx UIUX (0.71.0)", and does the red action stay #CC3333 for branded tenants. Default: the label shows as built (one constant in `lib/fx/version.ts`, easy to rename) and the red action stays #CC3333.
- **Q-QT:** build the Clipboard, Quick Tool and right-click tool now. Default: not built until asked.

Also in place as build defaults, still open with the owner: the switch and theme are per browser (Q-SYNC); sign-in, public portal and embedded pages stay outside the switch (Q-SCOPE); fx CSS stays in the four sanctioned CSS files (Q-CSS); Advanced settings are per browser (Q-ADV).

## Fields (slice F4)

Built defaults for the field rules, each kept in one place so it is easy to change:

- **Every dropdown is searchable**, whatever its size (SS's own rule; Q-DD default). The playbook's ~12-option threshold is not used.
- **Moments** use a 12-hour clock while the switch is on: "14 Nov 2026, 2:14 pm"; dates read "14 Nov 2026"; recent ones in lists read "now", "5 min", "3 h", "Yesterday", then "14 Nov". `useDatetime()` switches by itself, so every page that already goes through it gets this. The zone line under a time picker reads "Kuala Lumpur time (GMT+8)".
- **Day totals and quick picks** count in the report's own zone (the picker's `timeZone`), since SS has no organisation zone yet (Q-TZ default). The range quick picks are the playbook's (Today, This week, This month, Last month, This year) plus SS's Last 7 days and Last 30 days; weeks start on Monday.
- **Money:** "RM" only when the currency is MYR; every other currency shows its ISO code, whatever the tenant default (Q-CUR default; `FX_HOME_CURRENCY` in `service_frontend/lib/money.ts`). `formatMoney` is unchanged; `formatMoneyFx` is the new formatter.
- **Secret fields:** the show/hide eye is reachable by Tab and carries `aria-pressed` while the switch is on (today it is skipped by Tab).
- **The bare `Select`** (a few screens) gets the playbook look only; it does not switch to the phone's own picker on touch, because its options are not known to the field.

## Final confirmation

Final confirmation of the design, in words: not yet. Until then the switch stays off by default, and the original UI is not replaced.
