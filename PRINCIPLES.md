# PRINCIPLES.md - the non-negotiable contract (read FIRST)

## What this is (shared-service fork)

> **This repository is the Foundryx Shared Service Platform** - a central multi-tenant **service host** forked from Foundryx EMS. Each installable module is a **Service**; the platform is the shared spine (auth, RBAC, tenants, users, the module/App-Store platform, and all core engines). **The first Service is `omnichannel`** (WhatsApp-as-a-service, respond.io-style: per-workspace API key, public `/api/v1/omnichannel/*` gateway, consumer webhooks, Redis Streams event bus - built out in later slices). **The EMS domain (events / CRM / finance / profile portal / reviews) has been stripped**; any EMS-specific guidance is historical/reference-only. All engineering rules below (layering, datetime, RBAC, tenant scoping, reuse, foolproof-UI, module governance) apply unchanged to every Service. "App Store" is user-labelled **"Services"** (routes/components unchanged).

The slim, always-true rules. `CLAUDE.md` is the detailed per-engine reference; **this file governs - on conflict, this wins.** Keep it short; deep detail belongs in `CLAUDE.md` / `documentation/`.

## Methodology (mandatory order, every feature)
1. **Grill → UAC → plan** (`grill-me`). After the grill, **write the User Acceptance Criteria FIRST** (`<NN>-<feature>-acceptance-criteria.md`) - the independently-verifiable Given/When/Then list the feature must satisfy. **THEN** write the numbered plan (`<NN>-<feature>.md`) so it fulfils the UAC. UAC is the contract; the plan is how you meet it; the test report (step 6) is keyed back to the UAC ids. No plan ships without its UAC file. Defer-items go to `documentation/backlogs/backlog.md`.
2. **Component-library discipline** - reuse first; new variant = add a prop/mode to the shared component, never a parallel one-off.
3. **Frontend-first** - UI → hook → service → **mock**, tune all states, THEN swap the mock for the real `api-client` call (one-line at the service boundary).
4. **Backend second** - Service-Repository.
5. **TDD** both layers (Vitest/RTL front, pytest/httpx back), tests precede impl.
6. **Playwright E2E** - REAL user clicks (never URL shortcuts), against mock then live; produce a Test Execution Report.
7. **Code review approves before merge.**
8. **Branch** `sprint-<N>/<feature>`; merge to `main` only after review.

## Definition of Done gate (a slice is NOT done until all pass)
1. **Mock swapped to real** + verified showing real data. A phase-1 in-memory `*-service` is DEBT, not done. Tag mocks loudly + backlog them.
2. **Backfill existing rows/tenants** - a new column/engine on an entity that already has rows/tenants needs a backfill migration, not just seed-if-absent.
3. **No hardcoded lookup of a tenant-editable key** - keys code depends on must be locked from tenant editing (system rows).
4. **New permission → grant sweep** for already-provisioned tenants (grants compute at provision/seed; else the feature silently 403s / hides).
5. **Verify from the USER's perspective** - real clicks, real data, fresh `rm -rf .next && npm run build`, **375px AND 1280px**, ports **3001** (FE) / **8001** (Foundryx backend; kill any sorento squatting 8001). Tests green ≠ user-verifiable (conftest `create_all` hides broken Alembic migrations - keep revision ids ≤ 32 chars).

## Design mandates (user-issued; non-negotiable)
- **Reuse, don't rebuild** - extend an existing component for a new variant.
- **Foolproof-UI** - the UI is self-evident; NO instructional/how-to copy on screen. Only offer valid options; warn on missing prerequisites; never auto-derive an ambiguous action.
- **Responsive** - every surface usable + non-clipped at 375px AND 1280px; verify both.
- **White-label** - tenant-facing copy never says "Foundryx"; a branded tenant without a logo shows its NAME.
- **Truncated text is always recoverable** - use `ClampedText`/`OverflowPills`, never a bare `truncate`/`line-clamp`.
- **Every dropdown is searchable** - `SearchSelect` (single) / `MultiSelect` (many); no bare shadcn `<Select>`.
- **Resource shell for every list/form** - config-driven `components/platform/{resource-list,resource-form}`; clone Users. No hand-rolled tables. No clickable parent menus (children only). The global Edit toggle gates canvases (read-only by default).
- **No `<style>` tags / no raw CSS** - Metronic/Tailwind utility classes only. Brand source of truth = `css/foundryx-tokens.css` + the TokensStudio JSON.
- **Datetimes** stored UTC-0 (`UTCDateTime` columns, aware-UTC `datetime.now(timezone.utc)`), wire Z-suffixed (`ApiModel`), rendered in the user's tz via `lib/datetime.ts`.
- **Brand spelling is exactly "Foundryx"** - never with a capital X after "Foundry" (the mixed-case variant is banned; CI greps for it). Applies everywhere the brand name appears: docs, UI strings, page titles, comments, metadata. Lowercase `foundryx` in URLs/repo/package/DB names and any all-caps `FOUNDRYX` identifier are unaffected. Known exception: the `documentation/ui_ux/*.TokensStudio.json` filenames (and references to them) predate the rule and keep their on-disk names.
- **No emdash, anywhere in the repo** - never type an em dash (U+2014) or an en dash (U+2013) used as punctuation. Use a plain hyphen: `" - "` (spaced) for sentence-level punctuation, bare `-` for a compact separator. Applies to docs, markdown, code comments, UI strings, seed data. Legitimate hyphens, CLI flags, YAML/frontmatter syntax, and horizontal rules are untouched by this rule.

## Layering (enforced)
- **Frontend:** UI component → custom hook → service → `lib/api-client` → FastAPI. Components NEVER call fetch/axios directly. Path alias `@/` → repo root. Explicit TS interfaces - no `any`.
- **Backend:** Router (HTTP/Pydantic only, no DB/SQL) → Service (business logic) → Repository (SQLAlchemy). Auth via `Depends(get_current_user)`. **Every query tenant-scoped** (tenant from the JWT, never client input). Pydantic v2 camelCase wire (`validation_alias` + `from_attributes`), `ApiModel` base for datetime schemas.

## Code-review hard-fail rules (auto-reject)
DB query / raw SQL in a router · a React component calling axios/fetch directly · `any` types · raw CSS / injected `<style>` · a module ALTERing core `public` tables · a "done" slice still serving a mock · a new column/engine with no backfill for existing rows/tenants · hardcoded lookup of a tenant-editable key · a new permission with no existing-tenant grant path.

## Module / App-Store governance
- Modules are schema-isolated (`app_<name>` Postgres schema); **never** `DROP`/`ALTER`/`TRUNCATE` core `public` tables.
- Cross-schema refs to core (`tenants`/`statuses`/`products`) = plain indexed columns or sanctioned module→core FK; **cross-module refs = capability soft-refs** (BL-030), never a cross-module DB FK/join.
- Per-module RBAC CSV (`<module>/permissions/permissions.csv`); **grep core for permission-key + `*-service.ts` name collisions BEFORE adding** (`sync_permissions` is delete-by-module on a global unique key).
- Per-module Alembic; modules register into the shared engines (status/rule/template/workflow/form/import/terminology) at install - don't fork an engine.

## Agents-team orchestration (the quality lever as the codebase grows)
Audit-first (Explore → per-AC gap matrix) → coder(s) → tester → reviewer, loop on findings. **Every subagent brief MUST embed this file's Design mandates + DoD gate + hard-fail rules** - a subagent starts with zero project memory; the brief is its only guardrail. Sequential coders on a shared branch when files overlap (parallel same-tree edits race). Tester verifies from the user's perspective + writes an AC-id PASS/FAIL/DEFERRED report.

## Ops quick-reference
- Backend port **8001** (8000 = sorento). Frontend port **3001** (3000 taken). Postgres everywhere (no SQLite). `FERNET_KEY` + `NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8001` + `BACKEND_API_URL=http://localhost:8001` in local env.
- After a frontend change: `rm -rf .next && npm run build` then restart 3001 (kill the stale `next-server` first). After new backend ROUTES: restart uvicorn (or rely on `--reload`). After a new migration: `alembic upgrade head` on the live DB.
- When a page 404s / perms vanish / login shows "Not Found": check WHO owns the port (`lsof -p $(lsof -ti :PORT) | grep cwd`) - a sibling/sorento server may be squatting it.
