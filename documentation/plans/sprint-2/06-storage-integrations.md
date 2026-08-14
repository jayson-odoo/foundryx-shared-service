# Sprint 2 · Plan 06 - Storage Integrations (S3/R2 + CDN), Avatar Upload, Integrations Resource Shell, Session Freshness

**Branch:** `sprint-2/06-storage-integrations`
**Closes/advances:** BL-007 (avatar upload + blob storage), session permission freshness (new - no prior BL), integrations page → Resource design language, "Workspace Settings" → "Settings" rename + dead-menu prune. NOT in scope: BL-014 (stays in plan 05, already started).
**Depends on:** plan 09 (sprint-1 - connections framework, provider registry), plan 03 (sprint-2 - StorageService in core, upload sniff-gate patterns), plan 04 (sprint-2 - `/account` page, `use-session-email-sync` drift pattern).

---

## Locked design decisions (from grilling)

1. **D1 - Storage = connection-driven everywhere (full replacement).** `StorageService` resolution mirrors email: tenant's storage connection → platform tenant's connection → local-disk fallback (zero-config dev). ALL consumers ride it: branding assets, omnichannel media, new avatars. Tenants can BYO bucket.
   - **Backend identity lives in the storage key**: keys written through a connection get prefix `conn:<connection_id>:<key>` so reads resolve through the connection that WROTE them - switching connections never breaks existing assets (they strand in the old bucket but stay resolvable while the row exists; re-upload migration = BL-077). Unprefixed legacy keys resolve via local disk, exactly as today.
2. **D2 - Two provider cards, one adapter.** Registry entries `s3` ("Amazon S3 / S3-compatible") and `r2` ("Cloudflare R2"), both thin `fields()` wrappers over ONE `S3CompatibleAdapter` (boto3). S3 card: region + optional endpoint URL (blank = AWS; MinIO/Wasabi fit here). R2 card: Account ID (endpoint derived `https://<account>.r2.cloudflarestorage.com`, region pinned `auto`) - deriving kills paste-error tickets. `type="storage"` (enum already in the provider contract).
3. **D3 - CDN = optional `cdnBaseUrl` config field** on both providers (not a separate integration). Public asset URLs: CDN set → `{cdnBaseUrl}/{key}` (edge-cached); unset → presigned URL (time-limited, generated per request). Private assets (future) → always presigned. Targeted test ("Verify storage") = upload probe object → fetch back (via CDN URL when set) → compare bytes → delete probe.
4. **D4 - DB stores storage KEYS, never final URLs** (presigned URLs expire - max 7d SigV4). `users.avatar` migrates URL→key semantics; URL resolution happens per response in the serializer (CDN URL = string concat; presign = local HMAC, no network - cheap on 100-row lists). `?v=` version cache-busting carries over from branding.
5. **D5 - Avatar package (BL-007):**
   - Surfaces: `/account` profile card (self, perm-free self-scope) + user ResourceForm (admin sets others, rides `users.update`). ONE shared upload component.
   - Formats: png/jpg/webp ≤2MB, **sniff-first** magic-byte gate (branding convention). **NO SVG** (XSS surface; avatars render everywhere).
   - Client-side square crop dialog + canvas downscale to 512×512 before upload - no backend image-processing dep; backend validates + stores only.
   - Remove-avatar action → initials; old blob deleted best-effort AFTER commit (branding convention).
6. **D6 - Integrations page = full Resource shell, wizard dies.** `ResourceList` of connections (Name, Provider, Type, StatusBadge verified/unverified/error, Last tested, Last error via ClampedText, Created; server-side sort/filter/search; `view_key`; actions registry: Test, Disconnect). Create = new-record `ResourceForm`: provider SearchSelect → provider `fields()` schema renders dynamically → Save (status UNVERIFIED until first successful test). Edit = read-mode + global Edit toggle; secrets write-only (blank = keep) + eye toggles. "Test connection" / targeted test = form actions. `integration-connect-wizard/` component deleted; BL-045 re-pointed (omnichannel channel connect converges on the ResourceForm flow instead of a wizard shell).
7. **D7 - One ACTIVE connection per `type` per tenant.** Connecting a second storage provider while one exists = 409 "disconnect X first" (service-level + DB partial unique index). Keeps `StorageService` resolution deterministic - no "default connection" picker. Email de-facto already behaves this way.
8. **D8 - Session permission freshness = probe-on-mount, update-on-drift.** Generalize plan 04's `use-session-email-sync` → `use-session-sync`, mounted in the **protected layout**: every hard page load probes `/auth/me` once, calls NextAuth `update()` ONLY on drift (bare update-on-mount loops the layout - plan 04 lesson). Syncs `permissions[]`, roles, email, name, avatar, isPlatformTenant. Backend was never stale (per-request DB resolution) - this closes the UX gap: refresh page = fresh perms, no re-login. The page-specific email-sync hook folds into this.
9. **D9 - Menu: "Workspace Settings" → "Settings"** (plain - "tenant" is platform vocabulary, leaks the SaaS abstraction into white-label UI; routes already `/settings/*`, zero route churn). Omnichannel "Workspaces" keeps its name (different concept - messaging workspaces). Prune the four dead User-Management entries (Permissions, Account, Logs, Settings - Metronic demo residue, routes don't exist).
10. **D10 - Platform default + env retirement.** Bootstrap seeds a platform-tenant storage connection from `PLATFORM_STORAGE_*` env when present (refuses loudly if `FERNET_KEY` unset - SMTP-seed rule). `STORAGE_BACKEND=local|s3` selection DIES; `media_root` stays (local adapter). Existing `S3Storage` refactors INTO the shared adapter - one S3 code path total.

## Work items

### Backend
- `S3CompatibleAdapter` (boto3): put/save/resolve/delete + presign + CDN-URL building; providers `s3` + `r2` registered (`app/integrations/`), `fields()` schemas incl. `cdnBaseUrl`; `test()` = HEAD bucket; targeted test = probe-object round-trip.
- `StorageService` resolution: connection-aware factory (`conn:` key-prefix routing, tenant→platform→local chain); retire `STORAGE_BACKEND`.
- One-per-type guard: service 409 + partial unique index `uq_connections_tenant_type_active` (Alembic).
- Avatar endpoints: `POST/DELETE /me/avatar` (self, perm-free) + avatar on `PATCH /users/{id}` path (admin, `users.update`); sniff-gate; `users.avatar` key semantics + serializer URL resolution + `?v=`; Alembic migration.
- Connections list endpoint grows Resource-shell contract (pagination/sort/filter via `filter_translator` whitelist, export).
- `PLATFORM_STORAGE_*` bootstrap seeding.

### Frontend
- Integrations: `useConnectionsListConfig()` + `useConnectionForm()` (dynamic provider-driven fields), `<ResourceList>`/`<ResourceForm>` wiring; delete card grid + wizard.
- Avatar: shared `AvatarUpload` component (crop dialog + canvas downscale), mounted on `/account` profile card + user form; header/user-list rendering of resolved URLs.
- `use-session-sync` in protected layout (replaces `use-session-email-sync`).
- `menu.config.tsx`: rename, prune dead entries.

### Phases
- **Phase A (frontend-first, mock service):** integrations Resource list+form against mock connections service; AvatarUpload + crop on `/account` + user form (mock upload); menu rename/prune; Vitest (configs, crop logic, `use-session-sync` drift/no-drift - loop regression test).
- **Phase B (backend, TDD):** adapter (stubbed boto3 - no network, no moto), resolution chain, one-per-type 409, legacy unprefixed keys, secrets blank-keep, avatar sniff-gate + migration, platform seeding; swap mocks for real services.
- **Phase C (E2E + report):** (1) integrations journey - create S3 connection (fake creds → UNVERIFIED, Test shows honest error), edit blank-keep, disconnect; (2) avatar journey - upload → crop → save → renders in header + users list (local fallback, no bucket); (3) one-per-type 409 surfaced; (4) permission freshness - revoke perm on role, refresh, menu entry + page gone (**dedicated provisioned tenant** - default-tenant Admin mutation breaks parallel specs; timestamped names); (5) "Settings" rename + dead entries gone. **Manual pre-merge:** real R2 bucket + custom-domain CDN round-trip, noted in the test report (omnichannel real-WhatsApp posture).

### Risk notes
- Presign requires credentials decrypt per resolve - keep adapter instances cached per connection id (version-bust on update).
- `put()` (omnichannel contract: returns PUBLIC URL) under S3: returned URL must be CDN-or-presigned at SEND time; long-lived message media older than presign TTL needs re-resolution at read - verify the inbox reads media via `resolve()`, not stored URLs, before flipping omnichannel onto connections.
- Wizard deletion: grep for `integration-connect-wizard` imports (tests included) - plan 09's vitest spec dies with it, replaced by form-config tests.
- One Postgres serves all worktrees: run migrations only from the branch being served; plan 05 is in flight in the main checkout - `git status` before any branch op, work this plan from a worktree if 05 is dirty.
