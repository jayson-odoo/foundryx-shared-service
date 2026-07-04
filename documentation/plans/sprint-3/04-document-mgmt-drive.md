# Sprint 3 · Plan 04 — Resource & Document Management (the Drive — slice 1)

**Branch:** `sprint-3/04-document-mgmt-drive` (slice 1) → `sprint-3/05-document-mgmt-sharing` (slice 2)
**Advances:** F3 (roadmap `sprint-3/00-foundation-gaps-roadmap.md`) — BRD R9 (resource/document management). **Consumed by** R7 quotation attachments (Cluster B), R21 invoice supporting docs (Cluster F), e-Perolehan PO upload. **Two vertical slices**: 04 = the Drive (folders/files/versions, upload + bulk-zip download, move/rename/trash, preview, types, quota, custom UI, `file` triggerable); 05 = share links (3 tiers, tenant policy ceiling, public pre-auth route, file+folder live-follow, view+edit + anonymous-write guards) + the polymorphic entity-link seam.
**Spawns:** BL-094 (per-folder restricted ACL), BL-095 (ZIP-expand bulk import — recreate folder tree), BL-096 (office-doc inline preview — converter daemon), BL-097 (restore-previous-version UI), BL-098 (blob prune / auto-purge Trash after N days), BL-099 (antivirus scan on upload), BL-100 (widen sniff allow-list), BL-101 (entity-link wiring — lands with Cluster B), BL-102 (`file.shared` workflow trigger — slice 05).
**Depends on:** `StorageService` / `storage_for_tenant` + per-connection key convention (sprint-2/06), `app/uploads.py detect_mime` capped-read sniff (sprint-2/04/06), Resource shell + `ConfirmActionDialog` typed-confirm (sprint-1/02/08), dnd-kit + `useHistory` (sprint-2/07/10), SearchSelect/MultiSelect/StatusBadge/ClampedText, workflow triggerable-entity registry + `emit_entity_event` bus (sprint-2/08–10), Celery (omnichannel/workflow, eager in dev), tenant settings-row precedent (`workflow_settings`).

---

## Context

The platform has the **bytes layer** (StorageService: tenant→platform→local resolution, per-connection keys, sniff-gated uploads, CSP-sandbox serving, presigned-never-immutable-cached). What's missing is the **entity layer on top**: a Google-Drive-class repository — a navigable folder tree, files with version history, upload/download/move/rename/trash, preview, and (slice 05) shareable links with access control.

Reference baseline: sorento_crm's `resource-management` (attachments + self-nested directories + attachment-types + polymorphic entity links + an n8n linkage log; decoupled upload-activity + my-downloads drawers). We keep its good bones (decoupled drawers, soft-delete + Trash, optional attachment-types, polymorphic link seam) and fix its gaps: **no share links, coarse binary access, ugly UI, no real versioning, n8n-coupled linkage**. foundryx has no n8n — uploads are direct multipart → FastAPI → StorageService, completing in the request — so sorento's async "processing/linked" lifecycle collapses to a simpler one.

**Net demo at end of slice 04:** open `/documents`, see the tenant's shared Drive (folder tree + file grid + breadcrumb), create nested folders, drag-drop upload 20 files at once (non-blocking activity drawer with per-file progress + retry), get warned on a same-name collision (Replace → new version / Keep both), rename + drag-move files between folders, preview an image/PDF inline, multi-select a folder → "Download as ZIP" lands in the My Downloads drawer when ready, delete a folder → it + its subtree go to Trash → Restore brings them back, configure an attachment-type and a tenant storage quota (usage bar reflects it), and watch a workflow with an `entity.created` trigger on `file` fire when a file lands.

### Engine is PLATFORM CORE, not an App Store module
Settled in the grill (user initially leaned module, for the revenue-product angle). Decisive reason: **classify by graph shape.** omnichannel is a *leaf* — nothing references it — so it is safely a module. Documents is a *hub* — complaint, quotation, invoice, PO all attach to it. A hub as a module forces a web of **module→module dependencies** (a consuming module would FK/soft-link into another module's schema, and depend on it being installed — install-order + uninstall-dangling hell). Governance only blesses **FK into core `public`**. Hubs therefore belong in core, exactly like the status/rule/template/workflow/form engines.

**Monetization without modules:** permissions are intra-tenant RBAC (tenant Admin auto-grants every core key — can't make a tenant *pay*); the only built cross-tenant entitlement lever is App-Store install-state, and real billing is BL-036. So a core feature is free-to-all until BL-036. The right lever for a core hub is a **per-tenant entitlement** (seeded by the `storage_quota_mb` knob here, generalized by BL-036) — NOT abusing module-install. Net: `app/document_engine/` + core `public` tables + core permissions CSV.

---

## Locked design decisions (from grilling)

1. **D1 — Core hub.** `app/document_engine/` (mirrors `template_engine/`/`form_engine/`), tables in `public`, perms in core `permissions.csv`, present for every tenant always. StorageService stays core (bytes); this is the entity layer (folders/files/shares/UI) on top.

2. **D2 — One shared tenant Drive.** A single org-wide folder tree per tenant. All files are org assets (quotations, invoices, POs) — no per-user "My Drive" silo, no ownership-transfer-on-offboarding. Visibility = RBAC perms (slice 04) + share-link tiers (slice 05). **Per-folder restricted ACL = BL-094.** Every query tenant-scoped (house invariant).

3. **D3 — Entity-linking is a deferred seam.** Domain entities (F4 clusters) don't exist yet — nothing to attach files *to*. Slice 04 ships the Drive only. The polymorphic **`file_links(entity_type, entity_id, file_id)`** table + link/unlink API land in slice 05 as a seam (the link row lives Drive-side, points OUT by string — no FK, no module→module import), **wired to a real consumer at Cluster B (BL-101)**. Same polymorphic discipline as `notification_recipients.target_id` (sprint-2/01 cross-tenant-leak lesson): validate target tenant at save, tenant-scope at resolve.

4. **D4 — Data model (core `public`):**
   - **`folders`** — `id`, `tenant_id`, `parent_id` (self-FK, NULL = root), `name`, `is_deleted`, `deleted_at`, `deleted_by`, `created_by`, `created_at`, `updated_at`. Self-nested tree. Move = reparent; **cycle-guarded** (can't move a folder into its own descendant). Unique `(tenant_id, parent_id, lower(name))` among non-deleted for collision detection.
   - **`files`** — `id`, `tenant_id`, `folder_id` (NULL = Drive root), `name`, `current_version_id` (FK file_versions), `attachment_type_id` (FK, nullable), `is_deleted`, `deleted_at`, `deleted_by`, `created_by`, `created_at`, `updated_at`. **Identity (id) + name stable** — rename/move/replace never break a ref. Collision unique scope `(tenant_id, folder_id, lower(name))` among non-deleted.
   - **`file_versions`** — `id`, `file_id` (FK), `storage_key`, `size_bytes`, `mime` (the **sniffed** mime, not declared), `uploaded_by`, `created_at`. Replace / edit-via-link / re-upload **append** a version; `files.current_version_id` moves to the latest. Old blobs retained (prune = BL-098). Restore-previous = BL-097.
   - **`attachment_types`** — `id`, `tenant_id`, `name`, `allowed_exts` (JSON), `max_mb`, `description`, `created_at`. **Optional** categorization (D7). Seed defaults: Document / Image / Spreadsheet. Managed on a Resource-shell page.
   - **`document_settings`** — `tenant_id` PK, `public_sharing` enum `off|view|edit` (default `off`, **slice 05**), `default_max_file_mb` (untyped-upload cap), `storage_quota_mb` (NULL = unlimited). `JSON(none_as_null=True)` where applicable. `workflow_settings`-row precedent.
   - **`download_jobs`** — `id`, `tenant_id`, `user_id`, `kind` (`zip`), `status` (`pending|processing|ready|failed`), `filename`, `zip_storage_key` (nullable until ready), `error`, `created_at`, `ready_at`. Per-user async ZIP feed.
   - **(slice 05)** `file_shares`, `file_share_users`, `file_links` — defined in plan 05.

5. **D5 — Versioning, not overwrite.** Same-name upload → **409 `{existingFileId}`** → dialog **Replace** (append a new version to the existing file) or **Keep both** (auto-rename `name (1)`, `name (2)`, …). Replace never destroys bytes (anonymous share-edit in slice 05 can't irreversibly nuke content). This is the file-edit semantics too: "edit a file" = append a version.

6. **D6 — Upload = client-session optimistic drawer, no server feed.** A global `UploadManagerContext` (sorento pattern, simplified) holds the queue + per-file progress via **XHR `upload.onprogress`**; uploads continue while the user navigates the Drive (non-blocking), with retry-on-fail. **No `upload_activity` table** — each multipart completes in its own request, so the file is in the tree immediately; the drawer is transient progress UI (cleared on refresh). Drops sorento's n8n `processing/linked` states entirely. Statuses: `queued → uploading → done | failed`.

7. **D7 — attachment_type optional + hard sniff floor.** Type is optional on upload (categorization + per-type `allowed_exts`/`max_mb` *when set*). **Untyped** uploads are bounded by `document_settings.default_max_file_mb`. **Underneath everything**, a non-overridable **system magic-byte floor** (`app/uploads.py detect_mime`, capped read so an oversize body is never buffered) sniffs the real type and **always blocks executables / html / SVG** regardless of tenant type config — a tenant can't configure a stored-XSS hole (branding-asset SVG-XSS lesson, sprint-2/03). The sniffed mime is what's stored on the version. Allow-list v1 = images, PDF, MS-Office + OpenDocument, text/csv, zip. Widen = BL-100.

8. **D8 — Download: direct single + async ZIP bulk.** Single file = direct (stream / presigned URL, no job). Multi-select or whole-folder = server builds a ZIP **async via a Celery task** (eager-inline in dev/test) → `download_jobs` row → **My Downloads drawer** polls status every 4s → Ready → click fetches a **fresh** signed URL (presigned → never immutable-cached; serve `private, max-age=300`). `MyDownloadsContext` (sorento pattern) owns the feed + badge + intelligent poll-stop.

9. **D9 — Soft-delete + Trash + restore + purge.** Delete a file/folder → `is_deleted` + `deleted_at/by`; hidden from the tree, shown in a Trash view. Restore puts it back (re-collision-checks the name). Deleting a folder **cascades** soft-delete to its subtree. **Permanent purge** from Trash drops blobs (all versions) + rows, **typed-confirm** via the shared `ConfirmActionDialog` contract. Auto-purge after N days = BL-098.

10. **D10 — Preview: images + PDF inline, rest download.** `image/*` + `application/pdf` render inline via the existing **CSP-sandbox serve route** (`Content-Security-Policy: sandbox` + `nosniff` + private-cache; presigned never immutable-cached — reuse branding/form-file hardening). All other types show a type icon + Download. Office-doc inline preview (needs a LibreOffice/Gotenberg converter) = BL-096.

11. **D11 — Storage key convention.** Via `storage_for_tenant(db, tenant_id)` → key **`documents/{file_id}/{version_id}`** (flat by id, NOT by folder path — so rename/move never touch blobs; the key carries its writing connection per the sprint-2/06 `conn:<id>:<raw>` rule). **Quarantine order**: create the `files` row + `file_versions` row first (need the ids for the key), sniff the bytes BEFORE store, store after the rows exist (a validation failure leaves no orphan blob — form-engine upload lesson). ZIP outputs key `downloads/{job_id}.zip`.

12. **D12 — Per-tenant storage quota (monetization lever).** `document_settings.storage_quota_mb` (NULL = unlimited, default). Upload checks `sum(non-purged version bytes) + new` ≤ quota → **413** over limit. Usage bar in the Drive header. This is the seed of the BL-036 entitlement story — a billing tier sets the quota.

13. **D13 — `file` registered triggerable; emits workflow events.** Register `file` (and optionally `folder`) in the workflow **triggerable-entity registry** (`entities.py`) — gives `entity.created / updated / deleted` triggers for free (e.g. *file lands in /Contracts → notify legal*), no new `TriggerDef`. Upload/move/rename/delete emit via `emit_entity_event` (after-commit drain on a fresh session; **fully failure-isolated** — a broken workflow can never 500 an upload). Record facts `_json_safe`-coerced. A dedicated **`file.shared` trigger = BL-102** (slice 05). No status engine on files (not everything needs a state machine).

14. **D14 — UI: custom Drive surface + Resource shell for the flat bits.** A tree+grid is not a flat table — the Drive (`/documents`) is a **custom two-pane surface**: folder-tree sidebar + file grid/list main, breadcrumb, drag-to-move, right-click context menu, multi-select + bulk actions, usage bar (App-Store-storefront precedent for a non-Resource surface). It **reuses primitives**: SearchSelect, MultiSelect, StatusBadge, `ConfirmActionDialog`, dnd-kit, ClampedText, the action registry, `useHistory` (for in-session move undo — optional). The flat entities ride the **Resource shell**: `/documents/types` (attachment_types CRUD) and `/documents/shares` (slice 05 — active-links oversight/revocation). Settings (`/documents/settings`: quota, default cap, share policy) = a simple form. Responsive: tree collapses to a drawer on mobile (≤375px), grid reflows (house mandate).

15. **D15 — Permissions: 4 keys.** `documents.read` (browse/preview/download), `documents.manage` (upload/rename/move/delete/restore/folders), `documents.share` (create/revoke share links — separate because public sharing is higher-trust; slice 05), `documents.configure` (attachment_types + document_settings — admin). Core CSV, all seeded to tenant Admin. Implied-read auto-applies. Drive browse/preview/download endpoints gated `documents.read`; mutations `documents.manage`.

---

## Slice 04 scope (this plan)

In: folders (nested, move, cycle-guard), files + version history, optional attachment_types, document_settings (quota + default cap; `public_sharing` column added but unused until 05), upload (client drawer, collision→replace/keep-both, sniff floor, quota), single download + async ZIP bulk (My Downloads drawer), rename/move, soft-delete + Trash + restore + purge, images+PDF inline preview, custom Drive UI + `/documents/types` Resource page + `/documents/settings` form, `file` triggerable + event emits, `documents.read/manage/configure` perms (+ `documents.share` key declared, enforced in 05).

Out (→ slice 05): share links (tiers/policy/public route/file+folder live-follow/view+edit/guards), `file_links` polymorphic seam + link API, `file.shared` trigger.
Out (→ backlog): per-folder ACL (BL-094), ZIP-expand import (BL-095), office preview (BL-096), restore-previous-version (BL-097), blob-prune/auto-purge (BL-098), AV scan (BL-099), widen sniff list (BL-100), entity-link wiring at Cluster B (BL-101).

---

## Build order (house methodology)

**Phase A — Frontend-first (mock service).** `documentService.{ts,mock,real}` behind the service layer; build the custom Drive two-pane (tree + grid + breadcrumb + context menu + multi-select), the `UploadManagerContext` + activity drawer (XHR progress, retry), the `MyDownloadsContext` + drawer, the collision dialog, the Trash view, the inline preview (sandboxed `<img>`/iframe), `/documents/types` (Resource shell), `/documents/settings` (quota/cap form). Tune all states against the mock. Verify desktop (~1280px) AND mobile (~375px).

**Phase B — Backend (Service-Repository).** `app/document_engine/` (schemas, models, repository, service), `app/api/v1/documents.py` (Drive CRUD + upload multipart + download + bulk-zip job + trash/restore/purge + types + settings + sandboxed serve route), Celery ZIP task, Alembic migration (remember `import app.models.utc_datetime` for UTCDateTime cols), `file` triggerable registration + emits, core permissions CSV rows. Swap mock → real at the service boundary (one-line).

**Phase C — TDD + E2E + review.** Backend pytest (folder tree + cycle-guard, versioning + collision replace/keep-both, sniff floor reject exe/html/svg, quota 413, soft-delete cascade + restore + purge, ZIP job, sandboxed serve headers, `file` event emit + failure-isolation, tenant-scope isolation). Frontend Vitest (drive tree, upload context progress/retry, collision dialog, downloads context poll). Playwright `e2e/documents.spec.ts` (real clicks: create folders → bulk upload → collision → rename/move → preview → ZIP download → trash/restore). Test Execution Report `04-document-mgmt-drive-test-report.md`. Code-review approval → merge.

---

## Open / confirm before code
- Folder-tree depth: soft cap + breadcrumb collapse for deep paths (sorento gap) — UI-only, no hard limit.
- ZIP task transport: Celery task (eager in dev) vs a lifespan daemon thread like the email dispatcher — lean Celery (workflow precedent), confirm in Phase B.
