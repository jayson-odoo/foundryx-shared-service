# Sprint 2 · Plan 03 — Tenant Branding & Theming Foundation

**Branch:** `sprint-2/03-tenant-branding`
**Closes/advances:** new white-label foundation (multi-tenant SaaS requirement — each tenant brands its own deployment surface). Ties forward to BL-038 (email branding adopts these assets later).
**Defers (new backlog items):** BL-066 per-tenant email branding adoption of these assets (supersedes part of BL-038), BL-067 SVG sanitization hardening, BL-068 branding on custom domains.

---

## Context

FoundryX EMS is multi-tenant SaaS; tenants need their own identity on the surfaces their users see: sign-in page, browser tab, app header, and the system color theme. Today everything is hardcoded FoundryX (orange `#FF5A00`, `AuthBrandPanel` defaults, static favicon). The foundation must scale: many tenants, each with distinct light+dark themes, served from one deployment.

### Locked design decisions (from grilling)

1. **Stored theme format = curated flat JSON.** One document, `light` + `dark` sections, **whitelisted variable names only** (all Layer-1 `--foundryx-*` primitives: primary family, greys, status colors, light/dark surfaces), values = valid CSS colors only. Backend validates names against the whitelist and color syntax; anything else → 422. Partial overrides allowed — only changed vars are stored and emitted; everything else falls through to `foundryx-tokens.css` defaults.
2. **Two edit methods over the SAME stored JSON:** (a) download template (current effective values pre-filled) → modify → upload; (b) in-app per-variable color pickers, grouped by section (Brand, Greys, Status, Surfaces). Both write the same `tokens_json`.
3. **Injection = backend-generated CSS + `<link>`.** Public endpoint `GET /public/branding/{slug}/theme.css` renders `:root { ... }` + `.dark { ... }` from stored JSON (overridden vars only). Next root layout (server component) derives slug from host (`lib/tenant.ts deriveTenantSlug`) and emits the `<link>` **after** `foundryx-tokens.css` so tenant values win. ETag + `Cache-Control` + `?v={version}` busting. Render-blocking link = no flash of FoundryX orange.
4. **Asset set:** logo (used in 3 places: sign-in brand panel, app header top-left, browser-tab fallback), **optional favicon** (square; falls back to logo — wide wordmarks are unreadable at 16px), **optional brand-panel illustration**, slogan (plain text). Empty slogan = nothing rendered (no FoundryX fallback on a branded tenant).
5. **Storage = lift `StorageService` to core.** Move `modules/omnichannel/services/storage.py` → `app/services/storage.py`; omnichannel imports via a thin re-export (module code otherwise untouched). Branding saves under `MEDIA_ROOT/branding/{tenant_id}/`; same `STORAGE_BACKEND=local|s3` contract.
6. **Data model = `tenant_branding` 1:1** (no two-tier fork machinery): `tenant_id` PK/FK, `slogan`, `logo_path`, `favicon_path`, `illustration_path`, `tokens_json` JSONB, `version` int (bumped on every save — busts CSS + asset URLs), timestamps. No row = pure FoundryX defaults.
7. **Edit surfaces — BOTH in this plan:** tenant `/settings/branding` (new core perms `branding.read`/`branding.manage`, CSV rows, auto-granted to tenant Admin) AND operator console tenant-detail **Branding tab** (new platform key `tenants.manage_branding`, follows the `tenants.manage_modules` granular precedent).
8. **Browser tab:** title = **tenant name** (no separate product-name field), favicon = uploaded icon; via Next `generateMetadata` reading host → public branding endpoint. Default tenant / no branding = "FoundryX EMS".
9. **Unknown slug on every public branding endpoint → 200 with FoundryX defaults**, never 404 — no tenant-enumeration signal, sign-in page always renders.
10. **Platform tenant keeps hardcoded FoundryX branding** (the console IS the product).

---

## Data model (core `public`, Alembic migration)

### `tenant_branding` (new)
- `tenant_id` String PK, FK → `tenants.id` (1:1, cascade delete)
- `slogan` String nullable
- `logo_path` String nullable, `favicon_path` String nullable, `illustration_path` String nullable
- `tokens_json` JSONB nullable — `{"light": {"primary": "#0050FF", ...}, "dark": {...}}`, whitelisted keys only
- `version` Integer not null default 1 — incremented on every mutation
- `created_at` / `updated_at` (tz-aware UTC — plan 05 convention)

## Token whitelist (single source)

`app/branding/token_whitelist.py` — the canonical ordered list of variable names (mirrors Layer-1 primitives in `css/foundryx-tokens.css`), each with: key (e.g. `primary-active`), CSS var name (`--foundryx-primary-active`), group (`brand|grey|status|surface`), label. Frontend picker groups + template generation + backend validation all derive from this one list (exposed via `GET /branding/template`). Add a themeable var = add one entry.

## Backend

### Public (no auth — consumed pre-login + by `<link>`/`<img>`/metadata)
- `GET /public/branding/{slug}` → JSON `{tenantName, slogan, logoUrl, faviconUrl, illustrationUrl, version}` (URLs absolute, version-stamped). Unknown slug → FoundryX defaults.
- `GET /public/branding/{slug}/theme.css` → generated CSS, `text/css`, ETag, `Cache-Control: public, max-age=31536000` (immutable per `?v=`). No row / no tokens → empty stylesheet 200.
- `GET /public/branding/{slug}/asset/{kind}` (`logo|favicon|illustration`) → file via core StorageService, correct content-type, inline disposition.

### Tenant-side (gated `branding.read` / `branding.manage`)
- `GET /branding` → own row (effective values + which vars overridden)
- `PUT /branding` → slogan + tokens_json (validated against whitelist + color syntax; 422 on unknown key/bad color); bumps `version`
- `POST /branding/assets/{kind}` (multipart) / `DELETE /branding/assets/{kind}` — upload caps: logo/illustration PNG/JPG/SVG/WebP ≤2MB; favicon PNG/ICO ≤512KB; content-type sniffed not trusted
- `GET /branding/template` → downloadable JSON template, current effective values pre-filled

### Operator (gated `require_platform_permission("tenants.manage_branding")`)
- Same five operations at `/platform/tenants/{id}/branding[...]` — one `BrandingService` behind both route sets (the AppStoreService precedent).

### Layering
`api/v1/branding.py` + `api/v1/platform_tenants.py` additions → `services/branding_service.py` (validation, CSS generation, version bump) → `repositories/branding_repository.py`. CSS generation is pure-function (`tokens_json → css text`) — unit-testable.

## Frontend

- **Root layout** (`app/layout.tsx`, server): derive slug from host → fetch `GET /public/branding/{slug}` (cached per request) → emit theme `<link>`; `generateMetadata` → title = tenant name, icon = favicon URL. Failure → FoundryX defaults (never block render).
- **Sign-in**: `AuthBrandPanel` already takes `tagline`/`logoSrc`/`illustrationSrc` props — wire from a small `useBranding()` hook (public service). Branded tenant + no illustration → clean panel (logo + slogan only).
- **Header top-left**: replace hardcoded logo with branding logo (fallback FoundryX).
- **`/settings/branding` page** (tenant) + **console Branding tab** (operator, same components): asset upload cards (preview + remove), slogan input, theme editor — grouped color pickers (whitelist-driven, shows default vs overridden, per-var reset), Download template / Upload JSON buttons, **live preview** of sign-in panel + header strip so contrast problems are visible before save.
- Layering per standard: components → `use-branding` hooks → `branding-service` (mock first, then real) → api-client.

## Phases (methodology)

- **Phase A (frontend, mock):** branding settings page + console tab + pickers + template down/upload + live preview + sign-in/header/tab wiring, `branding-service.mock.ts` tunable states. Vitest: whitelist grouping, picker→JSON mapping, upload validation messages.
- **Phase B (backend):** TDD — token validation (whitelist/color/422 cases), CSS generation snapshots, asset upload caps + content-type sniff, version bump, public-endpoint defaults on unknown slug, perms enforcement (tenant vs platform), StorageService lift (omnichannel tests stay green). Alembic migration. Swap mock → real.
- **Phase C (E2E, real clicks):** provision dedicated timestamped tenant (operator API setup) → sign in → upload logo/favicon → set slogan → change primary via picker → save → sign out → sign-in page shows tenant logo/slogan/color on `<slug>.localhost:3001` → tab title/favicon assertions → template download/upload roundtrip → operator edits via console tab. Test Execution Report per §6.

## Test notes
- Unknown-slug behavior asserted explicitly (defaults, 200).
- Spec mutates only its own dedicated tenant — never `default` (suite is fullyParallel).
- SVG upload accepted but served with `Content-Type: image/svg+xml` via `<img>` only (no inline embedding); full sanitization = BL-067.
