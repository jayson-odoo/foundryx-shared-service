# Merge-main smoke - plan 25 (A1) after merging origin/main (plan 23 design-language alignment)

Coder smoke, not the formal E2E (that's the tester's job on the merge before the PR re-review).
Run via `agent-browser --session s25` against a fresh `rm -rf .next && npm run build` on `:3003`
(this worktree, PID confirmed via `lsof -p <pid> | grep cwd`) and the restarted backend on `:8004`
(PID confirmed, same worktree). Login `demo@example.com` / `demo1234`, default tenant, workspace
"General" (`1d591b7a-c500-42cd-a820-caa3fa877966`) - same fixture data as the plan-25 S4-smoke run,
now viewed through main's plan-23 restyle (new PageHeader/breadcrumb/tabs/button primitives).

## What plan 23 changed visually that this run confirms still works

- Breadcrumb + `PageHeader` restyle (bold H1, "Back to workspaces" outline button, orange primary
  `Edit` button) - visible on every screenshot, mounts cleanly under the Lifecycle/Contact fields/
  Tags tabs plan 25 added after Members.
- Tab strip restyle (orange underline on the active tab, icon + label) - all 7 tabs (Settings /
  Channels / Members / Lifecycle / Contact fields / Tags / API Keys) render and are individually
  selectable; at 375px the strip scrolls horizontally (pre-existing `min-w-0` + scrollable
  `TabsList` fix from the form-engine plan) and each of the 3 new tabs is reachable via
  `scrollintoview` + click.
- Conversation drawer restyle (rounded contact avatar chip, orange priority/status badges,
  restyled composer) - Inbox thread view, Contact panel toggle, and the panel's own `DETAILS` /
  `LIFECYCLE` / `TAGS` sections all mount without visual regression.
- `lib/toast` house wrapper (plan 23 D12) - real POST-driven toasts (tag create/update) still fire
  correctly now that `contact-tag-dialog.tsx`, `contact-field-dialog.tsx`,
  `components/platform/conversation-drawer/tag-chips.tsx`,
  `components/platform/conversation-drawer/lifecycle-move.tsx`,
  `hooks/use-contact-fields.ts`, `hooks/use-contact-tags.ts` and `hooks/use-lifecycle-moves.ts`
  were switched from a direct `sonner` import to `@/lib/toast` (post-merge fix, see the handoff
  report - main's `no-restricted-imports` ESLint rule bans the direct import outside the three
  sanctioned files).
- `PRESSED_CLASS` guardrail (plan 23 T8, AC-DLA-58) - the tag color-swatch button
  (`contact-tag-dialog.tsx`) and the tag-chip remove button (`tag-chips.tsx`) needed the class
  added; both exercised live below (swatch picked when creating "Merge Check", remove button used
  to un-tag "Merge Check" from Priya Raj).
- Verb+noun primary-button guardrail (plan 23 T8, AC-DLA-35) - `contact-details-form.tsx`'s Save
  button relabeled "Save" -> "Save details"; screenshot 07 shows the read state, and the Edit-mode
  click confirmed the new label live (not in a screenshot, captured via `snapshot -i`).
- `mode: 'onTouched'` guardrail (plan 23 T8, AC-DLA-61) - added to `contact-tag-dialog.tsx` and
  `contact-field-dialog.tsx`'s `useForm(...)` calls (inventory test was failing before the fix).

## Screenshots (1280px unless noted `-375`)

| # | File | Shows |
|---|---|---|
| 01 | `01-workspace-settings-tab-1280.png` | Workspace form, restyled PageHeader/breadcrumb, all 7 tabs in the strip. |
| 02 | `02-lifecycle-tab-1280.png` | Lifecycle tab - real seed graph (5 stages), `EntityFlow` canvas mounts under the new tab-strip styling. |
| 03 | `03-contact-fields-tab-1280.png` | Contact fields tab - embedded Resource-shell list, 4 real fields incl. ones from prior smoke runs. |
| 04 | `04-tags-tab-1280.png` | Tags tab before create - 2 pre-existing real tags. |
| 05 | `05-tag-created-1280.png` | Created tag "Merge Check" (blue swatch) - real POST, row appears, `@/lib/toast` toast fired. |
| 06 | `06-inbox-thread-1280.png` | Inbox restyled conversation drawer - thread list badges (lifecycle + tags) render on the new design. |
| 07 | `07-contact-panel-1280.png` | Contact panel toggled open - Details/Lifecycle/Tags sections all present on the restyled shell. |
| 08 | `08-tag-added-to-contact-1280.png` | Added "Merge Check" tag to Priya Raj via the Add-tag picker - chip appears in panel AND thread-list row (same WS push), then removed via the fixed `PRESSED_CLASS` remove button (verified in DOM snapshot, not a separate screenshot). |
| 09 | `09-lifecycle-moved-1280.png` | Moved Daniel Lee New Lead -> Hot Lead via the "Move to" picker (only fireable edges offered) - panel AND thread-list row updated live, no reload. |
| 10 | `10-inbox-thread-375.png` | Contact panel as a full-screen mobile sheet with a close X. |
| 11 | `11-inbox-list-375.png` | Thread list at 375px - no clipping/overlap, badges wrap correctly, Daniel Lee shows the just-moved "Hot Lead" badge. |
| 12 | `12-workspace-form-375.png` | Workspace form at 375px - PageHeader/tabs reflow, tab strip scrollable. |
| 13 | `13-lifecycle-tab-375.png` | Lifecycle tab reachable via horizontal tab-strip scroll at 375px; canvas contained in its own scroll region. |
| 14 | `14-contact-fields-tab-375.png` | Contact fields tab at 375px - Resource-shell list reflows, no overlap. |

## Console / errors

`agent-browser console` / `errors` after the full walkthrough: zero page errors; one pre-existing
Radix warning (`Missing Description or aria-describedby for {DialogContent}`), unrelated to plan 25
or this merge (tracked generically in the a11y guardrail inventory, not a new regression).

## Not covered here (formal E2E is the tester's job)

- API-key gateway parity (`/api/v1/omnichannel/*`) - unaffected by the plan-23 merge (no wire
  changes), not re-walked in this smoke.
- Members / API Keys tabs - untouched by either plan, not screenshotted (already covered by the
  original plan-25 E2E run).
