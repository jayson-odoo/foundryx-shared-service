# Frontend - scope-local rules (`service_frontend/`)

> **Shared-service fork:** this is the Foundryx Shared Service Platform frontend (forked from Foundryx EMS). EMS-domain route groups (`ems`, `finance`, `network`, `public-profile`, `reviews`, `store-admin`, `store-client`, the `(portal)` group) are removed; kept surfaces = the core engines + omnichannel + platform + user-management + the **Services** catalog (formerly "App Store"; route/component names unchanged). All rules below apply unchanged.
>
> Read `../PRINCIPLES.md` first (governs). `../CLAUDE.md` is the deep reference. This file = frontend-only essentials.

## Layering (enforced)
UI component → custom hook → service → `lib/api-client` → FastAPI. **Components NEVER call fetch/axios directly.** Service trio pattern (`x-service.{ts,mock,real}`) - frontend-first builds against `.mock`, then the boundary swaps to `.real`. A shipped mock behind a "done" slice is DEBT - tag it `PHASE 1 MOCK` + backlog it; never let it reach a user-perspective QA pass. Explicit TS interfaces - no `any`. Path alias `@/` → repo root.

## Must-dos
- **Resource shell for every list/form** - `components/platform/{resource-list,resource-form,...}`; clone Users; no hand-rolled tables. List = full-width, server sort/filter/search/paginate, column prefs by `view_key`. Detail = read + global Edit toggle (dirty-guard AlertDialog).
- **Every dropdown searchable** - `SearchSelect` / `MultiSelect`; no bare `<Select>`.
- **Foolproof-UI** - no instructional copy; only valid options; warn on missing prerequisites.
- **Responsive** - verify 375px AND 1280px (Playwright `setViewportSize` or screenshot both). Side-by-side panels stack on mobile.
- **White-label** - never render "Foundryx" to tenants; branded tenant w/o logo → its name.
- **Truncation** - `ClampedText`/`OverflowPills`, never bare `truncate`/`line-clamp`.
- **No `<style>` tags / no raw CSS in components or pages - Tailwind/Metronic utilities only. The ONLY sanctioned CSS files are `css/config.reui.css` (tokens), `css/foundryx-tokens.css` (brand), `css/styles.css` (utilities + the three accessibility preference blocks) and `css/demos/demo1.css` (shell); a rule that belongs to one component goes on the component as utilities.**
- **Datetimes** - `lib/datetime.ts` via `useDatetime()`; never `new Date(iso)` a backend timestamp directly.
- **Menu gating** - tag a gated entry with its page's permission key in ALL menu arrays (`MENU_SIDEBAR`/`MENU_MEGA`/`MENU_MEGA_MOBILE`); `filterMenu` prunes.
- **ActionMenu/BulkActions** `onSelect` must `preventDefault` + explicit `setOpen(false)`.

## Env + serving
`NEXT_PUBLIC_BACKEND_API_URL` + `BACKEND_API_URL` = `http://localhost:8001` (defaults point at 8000 = wrong backend). Dev port **3001**. **After any change: `rm -rf .next && npm run build` then restart 3001** (kill the stale `next-server` first - it serves old chunks otherwise). `npm install --force` (React 19 peers).

## Tests
`npm test` (Vitest, config `vitest.config.mts`). `npm run test:e2e` (Playwright, REAL clicks vs live stack - backend up + seeded). Lint gates the prod build (`npx eslint` before `npm run build`): no statement-position ternaries, no unused imports, `Array.from` to spread a Set.
