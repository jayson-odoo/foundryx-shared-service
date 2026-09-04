# CLAUDE.md

> **Read `PRINCIPLES.md` FIRST.** It is the slim, always-true contract: methodology order, design mandates, layering, Definition-of-Done gate, code-review hard-fail rules. **It governs on conflict.** This file is the INDEX: what the repo is, how to run it, the standing conventions, and one pointer per engine into `documentation/engineering/` where the detailed rules live. Read an engine doc on demand when your plan names it. `AGENTS.md` is the real file; `CLAUDE.md` is a symlink to it.

## What this is (shared-service fork)

**Foundryx Shared Service Platform** - a central, multi-tenant **service host** forked from Foundryx EMS. The platform provides the shared spine (auth, RBAC, tenants, users, the App-Store "Services" catalog, and the core engines: status, rule, template, workflow, form, import, terminology, document, numbering) and each installable **Service** (module) plugs into it. Services today: `omnichannel` (WhatsApp-as-a-service, respond.io-style public gateway + consumer webhooks) and `autocount` (AutoCount ERP -> Sorento CRM ESB: API or direct-DB source, mapping engine, Sorento sink). The EMS domain (events / CRM / finance / profiles) is **stripped** - `documentation/engineering/ems-module-historical.md` is reference only, but every engineering rule it illustrates still applies.

Two independently-runnable apps + governing docs:
- `service_frontend/` - Next.js 15 (App Router), React 19, Tailwind 4, Metronic v9.2.7 demo1.
- `service_backend/` - FastAPI + SQLAlchemy + Pydantic v2; owns auth and all domain data. Modules under `service_backend/modules/<name>/`.
- `documentation/development_process/` - governance + orchestration guides; `documentation/plans/sprint-<N>/` - UAC + plan per feature; `documentation/backlogs/backlog.md` - the single deferred-work register; `documentation/engineering/` - the per-engine reference (moved out of this file 2026-09-05).

## Commands

### Backend (`service_backend/`, port 8001)
```bash
python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
python -m scripts.bootstrap_db                 # role+db -> alembic upgrade head -> seed (canonical; use for ANY schema change)
python -m scripts.init_db                      # quick create_all + seed (NEVER adds a column to an existing table)
uvicorn app.main:app --reload --port 8001      # docs at :8001/docs
python -m pytest -q                            # pytest + httpx; conftest = in-memory sqlite create_all (migrations INVISIBLE to it)
```
- **DB = Postgres everywhere** (native, no Docker): `DATABASE_URL=postgresql://foundryx:foundryx@localhost:5432/foundryx_service`. Module schemas (`app_<name>`) need Postgres. Core migrations = `alembic/` (`alembic revision --autogenerate -m ...` then `upgrade head`); module migrations = `modules/<name>/alembic/` (Postgres-only orchestrator `run_module_migrations`).
- Port 8001 is deliberate (8000 = sorento_crm). Redis native (`REDIS_URL`), Celery with `CELERY_TASK_ALWAYS_EAGER=true` in local `.env` (tasks inline, no worker). Local `.env` MUST carry `FERNET_KEY` (unset = ephemeral key = stored credentials undecryptable after restart).
- Demo logins: `demo@example.com`/`demo1234` at `localhost:3001` (tenant `default`); operator `platform@example.com`/`platform1234` at `platform.localhost:3001`.
- Backend python from the repo root = the absolute `service_backend/.venv/bin/python` (`source activate` silently no-ops from the root).

### Frontend (`service_frontend/`, port 3001)
```bash
npm install --force        # React 19 peer deps
npm run dev                # :3001 (3000 is taken)
npm run build && npm start # prod build; after ANY change: rm -rf .next && npm run build before live-verifying
npm run lint && npm test   # eslint; vitest (RTL)
npm run test:e2e           # playwright, real clicks, against the live stack (backend up + seeded)
```
- `.env.local`: `NEXT_PUBLIC_BACKEND_API_URL=http://localhost:8001`, `BACKEND_API_URL=http://localhost:8001`, `NEXTAUTH_URL=http://localhost:3001` (defaults point at 8000 = wrong backend). `NEXT_PUBLIC_*` are baked at BUILD time.
- Real auth only (no mock mode). Vitest config `vitest.config.mts`.

## Architecture in one screen (details: `documentation/engineering/`)

- **Multi-tenant SaaS, shared DB + `tenant_id` row scoping.** Tenant = subdomain slug (`acme.localhost:3001`; bare host = `default`). **Every repository query is tenant-scoped; the tenant comes from the JWT, never from client input. Every stored user/role/record/connection id is resolved WITH `tenant_id` at use time** (the polymorphic-target_id rule - a real cross-tenant leak taught it, twice). Platform tenant (`slug platform`, `is_platform`) hosts operators; `require_platform_permission` = permission AND platform membership. -> `auth-tenancy-rbac.md`
- **FastAPI owns auth; NextAuth is only the session carrier.** `POST /auth/login {email,password,tenantSlug?}` -> JWT (`tenant_id` + `roles[]`, NOT permissions). `get_current_user` re-resolves the user per request and re-checks tenant lifecycle. Backend 401 = token invalid (api-client signs out); permission problems are 403 - keep it that way. -> `auth-tenancy-rbac.md`
- **RBAC: flat `<resource>.<action>` keys from per-module `permissions.csv`** (add a permission = add a CSV row), grants per role, `require_permission("key")` resolved fresh per request, no superuser bypass. Frontend `useCan()` / `<RequirePermission>` = UX only. **A new permission does not reach existing tenants' Admin role** - ship a grant sweep. Module keys must not collide with core keys (`sync_permissions` is delete-by-module on a GLOBAL unique key). -> `auth-tenancy-rbac.md`
- **Layering (enforced).** Backend: Router (HTTP + Pydantic only) -> Service -> Repository (pure SQLAlchemy). Frontend: UI component -> custom hook -> `services/<x>-service.{ts,mock.ts,real.ts}` -> `lib/api-client` -> FastAPI; components never fetch. Wire = camelCase (`Field(validation_alias="snake")` + `from_attributes`); datetime-bearing schemas inherit `ApiModel` (Z-suffixed). -> `frontend-and-design-system.md`
- **Resource shell = every list/form** (`components/platform/{resource-list,resource-form,...}`, config-driven; Users is the reference implementation). Every dropdown = `SearchSelect`/`MultiSelect`; truncation = `ClampedText`; status = `StatusBadge`; one action registry per entity. Card view, N-way segments, typed-confirm dialogs, dirty-guard AlertDialog are shell features - extend the shell, never hand-roll. -> `frontend-and-design-system.md`
- **Datetime: UTC everywhere.** `UTCDateTime` columns only, aware-UTC in memory (`datetime.now(timezone.utc)`), `lib/datetime.ts` + `useDatetime()` on the frontend (never `new Date(iso)` on a backend timestamp). -> `datetime-timezone.md`
- **Design system:** Foundryx tokens (`css/foundryx-tokens.css`, primary orange `#FF5A00`), Poppins + Inter, Metronic utilities only - **no `<style>` tags, no raw CSS**. Tenant branding is white-label: tenant-facing UI never says "Foundryx". -> `frontend-and-design-system.md`, `tenant-branding.md`
- **Integrations & storage are connection-driven** (`connections` table, Fernet `credentials_json`, provider registry `app/integrations/`; email = outbox always; storage keys `conn:<id>:<raw>`; `background_jobs` for any new async job). -> `integrations-email.md`, `storage-and-background-jobs.md`
- **Module platform:** manifest-driven loader, per-tenant install lifecycle, per-module schema + Alembic, capability registry for cross-module calls, `active_modules` filter on every catalog. Modules never alter core `public` tables. -> `module-platform-and-app-store.md`

## Engine index (`documentation/engineering/<file>`)

| Engine / area | File | One-line contract |
|---|---|---|
| Status & state machine | `status-engine.md` | ONE executor `status_machine.transition`; behaviour = boolean trait flags, never `category`; two-tier defaults; scoped graphs; every status change goes through it |
| Rule engine | `rule-engine.md` | JSON condition trees evaluated in memory, fail closed; whitelisted fact sources; `JSON(none_as_null=True)` always |
| Template engine | `template-engine.md` | Block-document email templates; own `{{ }}` micro-renderer (NEVER Jinja/eval on tenant content); MJML via `mrml`; two-tier |
| Workflow engine | `workflow-engine.md` | Triggers -> actions DAG, Celery/eager executor, flat run-context, CRUD event bus (after-commit drain on a FRESH session), loop guard; dispatch must never break the triggering request |
| Form engine | `form-engine.md` | Builder + renderer + server validator; hidden fields dropped never 422; scoped status graphs; sniff-gated uploads; field-type checklist |
| Import engine | `import-engine.md` | Per-entity `ImporterDef`, two-phase Test -> Import, set-based, id-only matching, export/import symmetry |
| Terminology | `terminology-engine.md` | Per-tenant display labels over immutable keys; one cached endpoint, not the JWT |
| Tenant branding | `tenant-branding.md` | Curated token diff + assets; sniff-first uploads; asset route served with CSP sandbox |
| Account security | `account-security.md` | Dual-confirmation email change; one commit per ceremony step |
| Integrations & email | `integrations-email.md` | Provider contract, outbox dispatcher, connection wizard/shell |
| Storage & jobs | `storage-and-background-jobs.md` | Connection-driven storage, key registry, A->B migration, centralized `background_jobs`, migration lessons |
| Auth / tenancy / RBAC | `auth-tenancy-rbac.md` | Login contract, throttle, forgot-password, impersonation invariants |
| Frontend + design | `frontend-and-design-system.md` | Resource shell contract, canvas-editor interaction principles, foolproof-UI, responsive |
| Module platform / App Store | `module-platform-and-app-store.md` | Manifest, loader, lifecycle, capabilities, soft refs, per-module Alembic |
| Omnichannel Service | `omnichannel-service.md` | WhatsApp BSP, WABA tabs, public gateway (guide IS the contract), signed media URLs, AI workflow nodes |
| AutoCount Service | `documentation/plans/sprint-4/22-autocount-db-etl.md`, `sprint-5/01-*`, `sprint-5/02-*` | ERP -> Sorento ESB: `ac_company` (API or `sql_database` source), entity tasks, mapping engine + formula builder, `SorentoSink` (`X-API-Key`, `companyCode`), Sorento addendum = the cross-repo contract |
| EMS (historical) | `ems-module-historical.md` | Reference only |
| Process lessons | `process-lessons.md` | E2E rig/isolation/residue, wrong-build, port ownership, worktrees, alembic gotchas, agent-team lessons |

## Standing conventions (the ones that bite; PRINCIPLES.md has the mandates)

- **Foolproof-UI:** no instructional/hint copy on screen; only offer options that will work; warn on missing prerequisites; never auto-derive an ambiguous action. Editable names must not masquerade as types.
- **Responsive:** every surface verified at ~375px AND ~1280px before "done".
- **Every dropdown searchable** (`SearchSelect`/`MultiSelect`); long catalogs collapse + search; side panels scroll internally; floating menus clamp to the viewport.
- **Contracts are part of the diff:** a wire change to a public gateway (`Rio*`, `api_v1.py`, canonical sink payloads) without the matching guide/addendum change is an automatic review finding. Never justify a breaking change with "only external clients consume it".
- **Tenant-editable keys are a code contract:** never hardcode-lookup a status key a tenant can rename; lock system rows or resolve by flags.
- **New column/engine on an existing entity needs a BACKFILL**, not seed-if-absent. `create_all` never ALTERs; deploy with `bootstrap_db`. A new module table does not appear on a legacy `create_all` local DB by itself.
- **Migrations:** revision id <= 32 chars, single head, check ALL existing ids (some files use `revision: str =`), data migrations on a frozen `sa.table`, never commit Alembic's own connection mid-run, verify on live Postgres (the suite cannot see migrations).
- **JSON columns `JSON(none_as_null=True)`;** SQLAlchemy misses in-place JSON mutation - reassign a fresh dict.
- **Anti-SSTI house line:** substitution-only renderers and hand-written parsers; never eval/Jinja on tenant-authored content. Tenant-authored storage keys are sanitised (`..`, absolute, `~`, NUL).
- **Uploads are sniff-first** (magic bytes gate AND stored type), capped reads, served with CSP sandbox + nosniff; presigned URLs never immutable-cached.
- **Dropdown/action menus:** `onSelect` must `preventDefault` AND `setOpen(false)`.
- **contentEditable** never paired with React-managed children; the sync effect is the single writer.
- **No em/en dashes anywhere** (CI lint: `git grep -I -n $'\xe2\x80\x94'`). Brand spelling "Foundryx".
- **Lint gates the prod build:** no statement-position ternaries, no unused imports, `Array.from` for Set spreads.

## Development methodology (summary; full order + gates in `PRINCIPLES.md`, detail in `process-lessons.md`)

Grill -> **UAC first** (`<NN>-<feature>-acceptance-criteria.md`) -> plan (`<NN>-<feature>.md`) -> plan review (`lavish-axi` markup, mandatory) -> frontend-first against a `PHASE 1 MOCK` -> backend test-FIRST (tester's red tests, then coder) -> Playwright E2E with real clicks + AC-keyed test report -> code review (hard-fail rules + DoD gate) -> merge. Branch per feature `sprint-<N>/<feature>`. Run `/feature` (`.claude/skills/feature/SKILL.md`) - it drives the order and names the executor per step.

### Code-review hard-fail rules
DB queries / raw SQL in a router; a component calling fetch/axios; `any`; raw CSS / `<style>`; a module altering core `public` tables; a "done" slice still bound to a mock; a new column/engine with no backfill; hardcoded lookup of a tenant-editable key; a new permission with no grant path for existing tenants; em/en dashes.

### Definition of Done
(1) mock swapped to real and live-verified with real data; (2) backfill for existing rows/tenants; (3) no hardcoded editable key; (4) permission grant sweep; (5) verified from the user's perspective with real clicks at 375px AND 1280px on a fresh build against correctly-owned ports (3001 FE, 8001 BE). Tests passing is not user-verifiable.

### Branching, worktrees, concurrent plans
- Park a branch with a `wip(...)` commit before switching plans; finish it from a git worktree at `.claude/worktrees/<name>`: symlink backend `.env`/`.venv` + frontend `.env.local` in; **`node_modules` is installed per worktree, NEVER symlinked** (a coder's `rm -rf node_modules/` through the symlink wiped the main install); isolated ports :8002/:3002.
- **The user codes concurrently in the main checkout:** `git status` immediately before any merge/rebase/checkout; ask before touching in-flight user edits.
- Servers track the checked-out code: after a branch switch restart/rebuild the moved side. One Postgres serves every worktree: never reseed from a stale branch while another branch's feature is under test.
- Port ownership is the #1 time sink: `lsof -p $(lsof -ti :3001) | grep cwd`; `pkill -9 -f next-server` before a clean `npm start`.

### Subagent crew v2 (standing rule, 2026-09-05)
Seats live in `.claude/agents/`: `coder`, `tester`, `reviewer`, `security-reviewer`, `planner`, `guide-writer`, `triage`; `/feature` names the executor per step; a `general-purpose` agent doing one of these jobs is a process violation (agent types load at session start - after adding/porting seats, start a fresh session via `/handoff` + `/clear` + `/resume-handoff`). Rules: **tester writes the red tests BEFORE the coder** (from the UAC + the Phase 1 contract block + the captain's test list); **one coder per lane, continued via message, never respawned**; **reviewer + security-reviewer + tester browser-verify run in PARALLEL once per lane**, reviewer runs a **kill test**; plan review = `lavish-axi` markup + grill. Models: execution on Sonnet, review + planner on Opus; escalate a single spawn with `model`, never by editing agent files; never spawn on Fable. Every brief carries the DoD gate + hard-fail rules (a subagent starts with zero project memory). Browser verification = **`agent-browser` CLI, headless** - Playwright MCP is retired for verification (the `e2e/*.spec.ts` suite stays the E2E step).

### Agents-team orchestration (what works)
Audit before building (per-AC gap matrix); sequential coders on a shared branch when files overlap; tester verifies from the USER's perspective (real clicks, real data, fresh build) and writes the AC-id-keyed PASS/FAIL/DEFERRED report; reviewer re-checks the recurring-gap gate, not only correctness.

## Agent skills and routing

- Issue tracker: GitHub Issues for `jayson-odoo/foundryx-shared-service` (`docs/agents/issue-tracker.md`); triage labels `docs/agents/triage-labels.md`; domain docs `CONTEXT.md` + `documentation/adr/` (`docs/agents/domain.md`).
- UI build: `ui-ux-pro-max` (after the Resource shell); UI review: `web-design-guidelines`; tokens: `tailwind-design-system` (brand source of truth stays `css/foundryx-tokens.css`); React/Next: `vercel-react-best-practices`, `vercel-composition-patterns`, `next-best-practices`. Idle for this stack: `better-auth-best-practices`, React Native skills; `supabase-postgres-best-practices` = generic Postgres advice only.
- Cross-model review: `.claude/skills/codex-review/SKILL.md`. Session continuity: `/handoff` then `/resume-handoff`.

## Maintaining this file

Keep this file an INDEX: what every session needs on every task. Engine detail goes into `documentation/engineering/<topic>.md` (update it in the same change as the code); a new engine = one new doc + one row in the index above. Do not repeat what the codebase shows; point at the authoritative file or command. Prefer rewriting or pruning over appending. No em/en dashes.
