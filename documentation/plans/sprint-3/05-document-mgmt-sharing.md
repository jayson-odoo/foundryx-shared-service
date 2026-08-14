# Sprint 3 · Plan 05 - Document Sharing (share links + entity-link seam - slice 2)

**Branch:** `sprint-3/05-document-mgmt-sharing` (slice 2; builds on `sprint-3/04-document-mgmt-drive`)
**Advances:** F3 (roadmap `sprint-3/00-foundation-gaps-roadmap.md`) - BRD R9. The differentiator sorento never built: shareable links with access control + the polymorphic entity-attach seam future clusters consume.
**Spawns:** BL-101 (wire `file_links` to Cluster B quotation attach), BL-102 (`file.shared` workflow trigger), BL-103 (share-link analytics / view counts), BL-104 (download-as-PDF watermark on public view), BL-105 (notify-on-access / access request flow).
**Depends on:** **everything in slice 04** (folders/files/versions, StorageService keys, sniff floor, CSP-sandbox serve route, `document_settings`), the **public pre-auth route precedent** (`/public/branding/{slug}`, `/public/forms/{tenant_slug}/{form_slug}` - sprint-2/03, sprint-3/02), throttle store + scope buckets (`THROTTLE_SCOPE_*`, sprint-1/10 + sprint-3/02 `THROTTLE_SCOPE_FORM_PUBLIC`), honeypot pattern (sprint-3/02), `app/uploads.py detect_mime` capped-read sniff, polymorphic target-validation discipline (sprint-2/01 cross-tenant-leak lesson), Resource shell + `ConfirmActionDialog`, `deriveTenantSlug` (frontend), workflow triggerable registry + `emit_entity_event`.

---

## Context

Slice 04 shipped the Drive (capture, organize, version, navigate). This slice makes files **leave the tenant boundary safely** - the one thing sorento's resource-management never did - and lands the **entity-attach seam** that turns the Drive into a hub the EMS clusters plug into.

Two distinct features, one plan:
1. **Share links** - generate a link to a file or folder, control who can open it (internal tenant users / named users / anonymous public) and what they can do (view+download / edit), bounded by a tenant policy ceiling, with optional expiry + password. Public links are the security-heavy surface (pre-auth, anonymous write when `public+edit`) - they reuse every public-endpoint hardening pattern the platform already proved (branding/forms public routes, throttle scopes, honeypot, sniff floor, CSP-sandbox serving).
2. **Entity-link seam** - the polymorphic `file_links(entity_type, entity_id, file_id)` table + link/unlink/list API. Built here as a tested-in-isolation seam; **wired to its first real consumer (quotation document attach) at Cluster B (BL-101)** - no domain entity exists to link to yet.

**Net demo at end of slice 05:** on a file in the Drive, open Share → pick a tier (Internal / Specific users / Public), pick capability (View / Edit), set optional expiry + password → copy the link. Open an **internal** link as another tenant user (works), as a logged-out browser (blocked). Set tenant policy `public_sharing = view`, generate a **public** link, open it logged-out on the tenant subdomain → see a clean branded view + download (sandboxed), no app chrome. Flip policy to `edit`, generate a **public+edit** folder link → a logged-out visitor uploads a file into the shared folder (throttled, honeypotted, sniff-gated, quota-checked, audited as `share:{token}`), and it appears live in the owner's Drive. Revoke the link → the page 404s. On `/documents/shares`, an admin sees every active link and bulk-revokes.

---

## Locked design decisions (from grilling)

1. **D1 - Share target = file OR folder.** A share points at one file or one folder. **Folder share = recursive subtree, live-follow** (D4) - Google-Drive behavior. `target_kind` discriminates.

2. **D2 - Three tiers.** `tier ∈ {internal, user, public}`:
   - **internal** - any authenticated user of the OWNING tenant (the `/auth/me` tenant must match the share's tenant). "Internal = everyone onboarded to the system" (user phrasing).
   - **user** - only named tenant users (`file_share_users` join). Still authenticated tenant members; a non-listed tenant user is denied.
   - **public** - anonymous, anyone with the link (pre-auth). The security-heavy tier.

3. **D3 - Capability = view | edit.** `capability ∈ {view, edit}`.
   - **view** = open inline (preview) + download. The only capability for read-sharing.
   - **edit (file)** = replace content → **appends a `file_versions` row** (slice-04 versioning; never destroys bytes - so even anonymous edit is reversible by the owner).
   - **edit (folder)** = upload new files into the shared subtree (+ rename within it). Move/delete via a link = **not** in v1 (too destructive for a capability link).

4. **D4 - Folder share is LIVE-FOLLOW (dynamic, resolved at serve time).** A link to folder X grants access to X's **current** subtree - files/subfolders added later auto-appear. Access check **walks ancestry**: a file is reachable through a link iff the link targets the file directly, OR any ancestor folder of the file is the link's target (and not soft-deleted along the path). Revoke = delete/disable the share row. No snapshot/manifest table.

5. **D5 - Tenant policy ceiling governs the PUBLIC tier only.** `document_settings.public_sharing ∈ {off, view, edit}` (default **off**, from slice 04):
   - `off` → the Public option is **hidden/disabled** in the Share dialog; existing public links are **disabled** (resolve → 404) until re-enabled. internal/user unaffected.
   - `view` → public links cap at **view** (the Edit radio is disabled for the Public tier).
   - `edit` → public links may be view **or** edit.
   - **internal + user tiers are always available** (authenticated tenant members - low risk). The ceiling clamps per-link choices server-side too (never trust the client): creating/serving a public link above the ceiling = 403.

6. **D6 - Public-edit (anonymous write) hard bounds (system invariants, non-negotiable).** When a `public + edit` link is exercised by an anonymous visitor:
   - **Own throttle bucket** `THROTTLE_SCOPE_DOC_SHARE` - never shares the login or form-public bucket.
   - **Sniff-gated** uploads (the slice-04 magic-byte hard floor; block exe/html/svg) + the target folder's/tenant's type+size policy + **quota** (413).
   - **Per-link guardrails**: `max_uploads` + `max_total_mb` on the share row (defaults sane) - caps abuse independent of tenant quota.
   - **Honeypot** field on the public upload form (sprint-3/02 pattern) → non-empty = 204, store nothing.
   - **Audited**: every anonymous write records `actor = "share:{token}"` (no User) via the BL-084 audit seam; emits the `file` event with that synthetic actor.
   - **Creator gate**: only a user holding **`documents.share`** can mint a link, and **only `public+edit` requires the creator additionally hold `documents.manage`** (you can't hand out write access you don't have).
   - Served through the CSP-sandbox route; presigned never immutable-cached.

7. **D7 - Token = unguessable capability.** `token` = a high-entropy URL-safe secret (plaintext-capability convention, sprint-1/10 reset-token precedent - stored hashed is overkill for a revocable share secret; store as-is, indexed, but treat as a bearer capability). Optional `password_hash` (bcrypt) gates open - prompt page on the public route; failed attempts pump the share throttle bucket. Optional `expires_at` (closed → 404, same uniform not-found as unknown token - **no enumeration**).

8. **D8 - Data model (core `public`):**
   - **`file_shares`** - `id`, `tenant_id`, `target_kind` (`file|folder`), `target_id`, `token` (unique, indexed), `tier` (`internal|user|public`), `capability` (`view|edit`), `expires_at` (nullable), `password_hash` (nullable), `max_uploads` (nullable, public+edit), `max_total_mb` (nullable), `is_disabled` (revoke flag - soft, keeps audit trail), `created_by`, `created_at`, `updated_at`.
   - **`file_share_users`** - `share_id` (FK), `user_id` (FK) - the `tier=user` allow-list. **Polymorphic-discipline check**: `user_id` validated to belong to the share's tenant at save (422 otherwise), tenant-scoped at resolve (the sprint-2/01 cross-tenant-leak rule - never resolve a stored id unscoped).
   - **`file_links`** - `id`, `tenant_id`, `entity_type` (string), `entity_id` (string), `file_id` (FK), `created_by`, `created_at`. **The deferred seam from slice 04.** Link row lives Drive-side, points OUT by string (no FK to domain modules, no import). Same polymorphic save-validate + scoped-resolve discipline. **Untested against a real consumer until BL-101 (Cluster B).**

9. **D9 - Public route reuses the proven precedent.** `app/api/v1/documents.py public_router` (no auth):
   - `GET /public/documents/{token}` → resolves the share (active? not expired? not disabled? policy-ceiling honored?) → returns a **state envelope** (`open | password_required | closed`) + (when open) the file metadata OR the folder subtree listing (live-walked). Unknown/expired/disabled/over-ceiling = **uniform 404** (no enumeration - branding/forms precedent).
   - `POST /public/documents/{token}/unlock` (password) → throttled.
   - `GET /public/documents/{token}/file/{file_id}` → streams/serves a reachable file through the **CSP-sandbox route** (ancestry-checked against the share). Single-file share ⇒ `file_id` must equal the target.
   - `POST /public/documents/{token}/upload` (public+edit only) → honeypot + throttle + sniff + quota + per-link caps → store into the shared folder, append version on collision-replace.
   - **Tenant slug rides in neither path nor subdomain** - the token is globally unique and self-identifies the tenant (simpler than forms, which needed a per-tenant slug). The public page derives branding from the resolved tenant for a white-labeled view.

10. **D10 - `file.shared` workflow trigger = BL-102 (deferred).** Slice 04 already made `file` triggerable (free `entity.created/updated/deleted`). A dedicated `file.shared` trigger (payload: tier/capability/target) is additive and low-demand - deferred so this slice stays focused on the sharing + seam surface. (Anonymous uploads via a public+edit link still fire the normal `file.created` event.)

11. **D11 - UI.**
   - **Share dialog** (on a file/folder in the custom Drive, gated `documents.share`): tier SearchSelect (Public option disabled + annotated when `public_sharing=off`), capability radio (Edit disabled when ceiling=view or no `documents.manage`), `tier=user` → MultiSelect of tenant users, optional expiry (date) + password + (public+edit) max-uploads/max-mb, **Copy link**. Lists this target's existing links with Revoke.
   - **`/documents/shares`** (Resource shell, gated `documents.share` - oversight): every active link across the tenant (target, tier, capability, creator, expiry, created), row + bulk **Revoke** (typed-confirm for bulk via `ConfirmActionDialog`). The admin kill-switch.
   - **Public page** `app/(public)/public/documents/[token]/` (literal `public/` segment - the route-group-collision lesson from sprint-3/02): white-labeled (tenant branding), minimal chrome. File share → preview + Download. Folder share → a read-only Drive-lite tree/grid (+ upload affordance when public+edit). Password gate page when required. Friendly closed/expired message (200 state, not a raw 404 page) when the token resolved but the link is closed. Responsive (≤375px) - house mandate.
   - **Policy** lives on the slice-04 `/documents/settings` form: the `public_sharing` enum (off/view/edit) + (this slice) default per-link expiry / max-upload defaults.

12. **D12 - Permissions.** `documents.share` (declared in slice 04) is **enforced here**: mint/revoke links. `public+edit` minting additionally requires `documents.manage`. Public endpoints are perm-free (token is the capability). `/documents/shares` oversight gated `documents.share`.

---

## Slice 05 scope (this plan)

In: `file_shares` + `file_share_users` + `file_links`; share CRUD (mint/list/revoke) for file+folder × 3 tiers × view/edit, bounded by `document_settings.public_sharing` ceiling; optional expiry + password + per-link upload caps; public pre-auth route (resolve/state-envelope/unlock/serve-file/upload) with uniform-404, honeypot, own throttle bucket, sniff floor, quota, CSP-sandbox serving, `actor=share:{token}` audit; folder live-follow ancestry-walk access check; Share dialog + `/documents/shares` Resource page + public `(public)/public/documents/[token]` page; `documents.share` enforcement; the `file_links` polymorphic seam + link/unlink/list API (validated, tenant-scoped, **isolation-tested only**).

Out (→ backlog): wire `file_links` to Cluster B quotation attach (BL-101 - first real consumer), `file.shared` trigger (BL-102), share analytics/view-counts (BL-103), public-view watermark (BL-104), notify-on-access / access-request (BL-105).

---

## Build order (house methodology)

**Phase A - Frontend-first (mock).** Extend `documentService` with share methods; build the Share dialog (tier/capability/users/expiry/password/caps, ceiling-aware disabling, copy-link), the `/documents/shares` Resource page, and the public `(public)/public/documents/[token]` page (file view, folder tree-lite, password gate, closed state, upload affordance) - all white-labeled, all states tuned on the mock. Verify desktop + mobile, internal vs public chrome.

**Phase B - Backend.** `file_shares`/`file_share_users`/`file_links` models + migration (`import app.models.utc_datetime`), share service (mint with ceiling+perm gates, revoke, resolve), public router (state envelope, unlock, ancestry-walked serve, guarded upload), `THROTTLE_SCOPE_DOC_SHARE` wiring, `file_links` link/unlink/list, audit-seam `actor=share:{token}`. Swap mock → real.

**Phase C - TDD + E2E + review.** Backend pytest: ceiling clamp (create+serve over-ceiling → 403), uniform-404 on unknown/expired/disabled, password gate + throttle, folder live-follow ancestry reachability (added file becomes reachable; sibling outside subtree not), public+edit honeypot-drop + sniff-reject + quota-413 + per-link cap, anonymous-write audit actor + version append, `file_share_users` cross-tenant save-reject + scoped resolve, `file_links` tenant isolation, revoke kills access. Frontend Vitest: share dialog ceiling/capability gating, public page state envelope. Playwright `e2e/documents-sharing.spec.ts` (real clicks: mint internal link → open as other user (ok) / logged-out (blocked); set policy=view → public link → logged-out view+download; policy=edit → public+edit folder → logged-out upload appears; revoke → 404). Test Execution Report `05-document-mgmt-sharing-test-report.md`. Review → merge.

---

## Security checklist (public surface - must all hold before merge)
- Unknown / expired / disabled / over-ceiling token → **uniform 404** (no enumeration).
- Tenant policy ceiling clamped **server-side** at both mint and every serve.
- Anonymous writes: own throttle bucket, honeypot, sniff hard-floor, tenant quota + per-link caps, audited `actor=share:{token}`, never an auth User.
- Stored `user_id` (share allow-list) + `file_links` ids validated to the share's tenant at save AND tenant-scoped at resolve (polymorphic-leak discipline).
- Files served only through the CSP-sandbox route; presigned URLs never immutable-cached; ancestry-checked against the share on every fetch.
- `public+edit` mint requires `documents.manage` (can't grant write you lack).
