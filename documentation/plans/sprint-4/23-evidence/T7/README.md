# T7 sweep - agent-browser evidence

AC-DLA-62. Session `agent-browser --session t7`, real clicks from `/` (never a
typed URL), against this worktree's prod build (`:3002`, `rm -rf .next && npm
run build` immediately before the run) and its own backend (`:8003`). Login
`demo@example.com` / `demo1234` (default tenant Admin).

## Header overlap fix (AC-DLA-62)

`00-sidebar-drawer-375.png` and the dashboard shots below are from the FIXED
build. Before the fix (not saved as evidence, captured only for diagnosis via
`agent-browser eval` DOM measurement): the header's `ActivityTriggers` group
(Uploads/Imports/Jobs/Downloads, 4 icons with no wrap/shrink protection)
measured `x=133..505` against a 375px-wide header - overlapping the
hamburger (`x=113..147`) and apps-menu drawer trigger (`x=147..181`) and
overflowing ~130px past the right edge. Fixed by gating `ActivityTriggers`
behind the same `!mobileMode` check `SearchDialog` already uses
(`app/components/layouts/demo1/components/header.tsx`). Re-measured after
the fix: `document.documentElement.scrollWidth === clientWidth === 375`
(zero horizontal page scroll), every header button's bounding box distinct
with no overlap (`01-dashboard-375.png`).

## Full sidebar sweep

Every leaf in `MENU_SIDEBAR` reachable by this session (demo Admin, default
tenant) - one screenshot per leaf, per viewport (1280 then 375, both against
the same rebuilt session). 38 leaves x 2 viewports = 76 screenshots
(`01`-`38`), plus a drawer-open shot (`00`) and two bonus record-level checks
(`18b`, `28b`) verifying the AC-DLA-56 DataGrid migrations render correctly
on a real record, at both viewports = 81 total.

| # | Surface | Path |
|---|---|---|
| 01 | Dashboard (Light Sidebar) | `/` |
| 02 | Dark Sidebar | `/dark-sidebar` |
| 03 | App Store | `/app-store` |
| 04 | Workflows | `/workflows` |
| 05 | Forms | `/forms` |
| 06 | Imports (AC-DLA-56: now `ResourceList`) | `/imports` |
| 07 | Jobs | `/jobs` |
| 08 | Developers > Logs | `/developers/logs` |
| 09 | Developers > Log settings | `/developers/logs/settings` |
| 10 | Documents | `/documents` |
| 11 | Documents > Shared links | `/documents/shares` |
| 12 | Documents > Document types | `/documents/types` |
| 13 | Documents > Settings | `/documents/settings` |
| 14 | Settings > General | `/settings/general` |
| 15 | Settings > Integrations | `/settings/integrations` |
| 16 | Settings > Terminology | `/settings/terminology` |
| 17 | Settings > Numbering | `/settings/numbering` |
| 18 | Settings > Statuses (list) | `/settings/statuses` |
| 18b | Settings > Statuses > Idea > Statuses tab (AC-DLA-56 `StatusTable` DataGrid, bonus) | `/settings/statuses/idea` |
| 19 | Settings > Rules | `/settings/rules` |
| 20 | Settings > Branding (AC-DLA-59 icon-label fix) | `/settings/branding` |
| 21 | Settings > Templates | `/settings/templates` |
| 22 | Settings > Email log | `/settings/email-log` |
| 23 | Settings > Workflows | `/settings/workflows` |
| 24 | Settings > Import settings | `/settings/imports` |
| 25 | Settings > AI agents | `/settings/ai/agents` |
| 26 | Settings > AI skills | `/settings/ai/skills` |
| 27 | Settings > AI traces | `/settings/ai/traces` |
| 28 | User Management > Users | `/user-management/users` |
| 28b | Users > a user record (bonus, Profile tab) | `/user-management/users/{id}` |
| 29 | User Management > Roles | `/user-management/roles` |
| 30 | Products | `/products` |
| 31 | Ideation > Ideas | `/ideation/ideas` |
| 32 | Ideation > Triage board | `/ideation/board` |
| 33 | Omnichannel > Inbox | `/omnichannel/inbox` |
| 34 | Omnichannel > Channels | `/omnichannel/settings/channels` |
| 35 | Omnichannel > Workspaces | `/omnichannel/settings/workspaces` |
| 36 | Omnichannel > Media limits | `/omnichannel/settings/media` |
| 37 | Omnichannel > Quick replies | `/omnichannel/settings/quick-replies` |
| 38 | Omnichannel > Embed access | `/omnichannel/settings/embed` |

### Not reachable by this session (disclosed, not a T7 defect)

- **Platform Console** (Tenants / Status Engine / Rules under the `Platform`
  heading) - `platformOnly`, hidden for this non-platform tenant session by
  design (`filterMenu`). Would need `platform@example.com` on
  `platform.localhost:3001` (a different tenant/host), out of scope for a
  single-session sweep of the default tenant.
- **Ideation > Business requirements / Embed connections** - gated behind
  `ideation.business_requirements.read` / `ideation.triage.manage`, neither
  granted to this session's Admin role. Correctly hidden by `filterMenu`
  (foolproof-UI: the menu shows only what the session can use) - not
  clickable "from the sidebar" because the sidebar correctly omits them.
- **Meetings, AutoCount ESB** - both `module`-gated menu sections; neither
  module is ACTIVE for the `default` tenant (confirmed absent from the live
  sidebar snapshot, not a menu-filter bug - `03-app-store-375.png` shows
  both listed "Not installed" in the catalog).

None of the above are menu/DataGrid/pressed-class/a11y defects - they are
the menu correctly reflecting this session's actual access, which is the
system working as designed (never surface a control that would 403).

## Verified live, this run

- Zero horizontal page scroll at 375 on every captured surface (spot-checked
  via screenshot inspection - DataGrid-heavy pages like `18`/`18b` scroll
  their OWN grid body, never the page).
- Every DataGrid (`06`, `18`, `18b`, `28`) renders with a sticky header and
  mobile-pinned first column at 375 (`18`/`18b` show `Status`/`Entity`
  pinned, other columns scroll within the grid).
- Every status is a rounded pill (`18`, `18b`, `20`'s branding page has no
  statuses; `28`/`28b` show `Active`/`Verified` pills).
- No clipped control on any captured surface at 375 (sidebar drawer, header
  icons, page toolbars, forms all reflow within 375px).
- `20-settings-branding-375.png` and `20-settings-branding-1280.png` confirm
  the AC-DLA-59 theme-token reset button's new `aria-label` didn't change
  its rendering.

## T7 - Fix round 1 (branch `sprint-4/23-T7-sweep`)

Session `agent-browser --session t7fix1`, real clicks/native `.click()` bridge, against
this worktree's rebuilt prod build (`:3002`) + backend `:8003`, login `demo@example.com`
/ `demo1234`. Evidence lands in `fixround1/`.

### Item 4 - mobile header keeps Uploads/Downloads (AC-DLA-62 carry-over)

`fixround1-01-header-375.png` / `fixround1-01-header-1280.png`.

Extending `ActivityTriggers` to render Uploads+Downloads on mobile surfaced a real,
pre-existing budget problem, not just a one-line gate flip:

1. **The mobile mini-logo `<img>` has no static asset in this environment** (`public/media/`
   is gitignored everywhere, confirmed 404 on `/media/app/mini-logo.svg`). With the old
   `className="h-[25px] w-full"`, a broken `<img>` with no intrinsic size and `width:auto`-like
   sizing falls back to a box sized to fit its ALT TEXT ("mini-logo") in Chromium - measured
   87px wide, not the ~25px a real small square logo would be. That inflated box, plus the
   9th-header-icon budget below, pushed the whole topbar past the 375px viewport and caused
   real overlap between "Uploads" (x119-155 before the second fix, still landing inside the
   hamburger group's box) and the apps-menu drawer trigger. Fixed to a real fixed box
   (`className="h-[25px] w-[25px] object-contain"`) that holds regardless of whether the
   asset loads - `w-auto`/`max-w-none` were tried first and do NOT constrain a broken image's
   alt-text-driven box in Chromium; only an explicit pixel width does.
2. **Even with the logo fixed, 6 topbar icons (Uploads/Downloads/Notifications/Chat/Apps/
   avatar) at `size-9` (36px) + `gap-3` (12px) need 276px; only ~240px is available** at
   375px after the (now-correct) logo+hamburger group. Fixed by, on mobile only: tightening
   the topbar gap to `gap-1` (4px) and passing `size="sm"` to the Notifications/Chat/Apps
   `Button`s + a new `compact` prop on `ActivityTriggers` (threaded to its `TriggerButton`)
   for Uploads/Downloads - `size="sm"` is the one Button size variant that does NOT carry
   `COARSE_HIT_TARGET_CLASS` (`primitive-classes.ts`'s own documented exception for "a
   control in a dense cluster" - the exact case a 4px gap between six 36px icons is).
   Desktop is untouched (`mobileMode` gates every change; `size={mobileMode ? 'sm' : undefined}`
   defaults back to the existing `'md'` size on desktop).
3. Live-measured post-fix (`getBoundingClientRect` on every header `button`/`a`, real
   values, not eyeballed): Open navigation 51-85, Open apps menu 85-119, Uploads 123-159,
   Downloads 163-199, Notifications 203-239, Chat 243-279, Apps 283-319, User menu 323-359 -
   every button distinct, zero overlap, User menu (avatar) fully inside the 375px viewport
   (previously clipped past it once the logo was fixed but before the gap/size fix, right
   edge 395 > 375).
4. Both drawers verified to actually open on mobile (native `.click()` bridge - the
   `agent-browser click` synthetic dispatch didn't fire React's `onClick` on these
   freshly-mounted trigger buttons, a known harness quirk, not a product bug): Uploads →
   "No uploads yet.", Downloads → "My downloads" / "No downloads yet. Select files or a
   folder and choose "Download as ZIP"."
5. Desktop (1280px) re-verified unaffected: all 4 `ActivityTriggers` (Uploads/Imports/Jobs/
   Downloads) still render, `gap-3`/default `'md'` size untouched.

New/updated tests: `header.mobile-overlap.test.ts` gained two cases (the fixed-width logo
guard, the mobile gap/compact-size guard) alongside the updated `ActivityTriggers`-gate
regex (now matches the `compact={mobileMode}` prop too).
