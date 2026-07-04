# Sprint 3 · Plan 04 — Document Management (the Drive) — Test Execution Report

**Build:** slice 1 (the Drive), branch `sprint-3/04-document-mgmt-drive`. Companion to the plan (`04-document-mgmt-drive.md`) and the UAT (`04-document-mgmt-drive-uat.md`).

## Summary

| Layer | Result |
|---|---|
| Backend pytest (`tests/test_document_engine.py`) | **18 / 18 passed** (15 + 3 code-review regressions) |
| Full backend suite (regression, F3 rebased on main incl. F2 slice 2) | **701 / 701 passed** |
| Frontend unit (`document-service.mock.test.ts`) | **10 / 10 passed** |
| Frontend typecheck (`tsc --noEmit`) | **0 errors** (whole repo) |
| Frontend lint | **clean** (1 pre-existing warning, unrelated) |
| Next production build | **compiles** — `/documents`, `/documents/types`, `/documents/settings` |
| **E2E (`e2e/documents.spec.ts`) — LIVE** | **5 / 5 passed** against the real stack (Postgres + StorageService) |

### Live E2E run (resolved the prior "pending dedicated stack" caveat)
Branch brought up to date with `main` (merged F2 slice 2), backend + a clean prod
build served, suite run with real clicks against a dedicated provisioned tenant.
All 5 journeys (create/nest folders, upload + collision keep-both, rename via
context menu, delete → Trash → Restore, bulk ZIP → My Downloads) pass.

Running it surfaced **one real bug** (now fixed): a context-menu Delete routed
`selectOnly()→deleteSelection()`, and `deleteSelection` read the stale
`selection` closure → deleted nothing on an unselected item. `deleteSelection`
now takes explicit ids. E2E-harness adaptations: tree-sidebar navigation (grid
dblclick is dnd-kit-suppressed), `dispatchEvent('contextmenu')` for the Radix
menu under the draggable, id-based rename input, delete-response wait before
opening Trash, re-load to root for the ZIP journey.

### Code-review pass (high-effort, multi-agent) — fixes applied
- **Quota counted only live files** → trash-then-upload bypassed it; now counts
  all non-purged version bytes (D12).
- **restore() skipped the D9 name re-collision-check** → two live same-name
  siblings; now renames the restored copy + clears `deleted_by`.
- **Content-Disposition filename injection** (file-content + ZIP routes) →
  sanitized ASCII + RFC 5987 `filename*`.
- **FE blob-URL leaks** — ZIP download + image/PDF preview now revoke; preview
  guards the async resolve with a cancelled-flag (no stale flash).
- **Upload options** defensively copied (no shared-reference retargeting).
Refuted: the XHR upload `:8000` fallback matches the existing api-client default
(env-set to `:8001` in practice), not a new regression.

## Backend — `tests/test_document_engine.py` (15)

| Test | UAT criteria |
|---|---|
| `test_root_lists_then_create_and_nest` | AC-NAV-01/02/03, AC-FOLDER-01 |
| `test_rename_folder_and_file` | AC-FOLDER-02, AC-FILE-01 |
| `test_move_file_and_folder_cycle_guard` | AC-FILE-02, **FOLDER-E1 cycle guard** |
| `test_upload_creates_version_and_lists` | AC-UPLOAD-01, AC-VERSION-02 |
| `test_collision_then_replace_and_keep_both` | AC-UPLOAD-06/07/08, AC-VERSION-01 |
| `test_sniff_floor_blocks_dangerous_types` | **AC-UPLOAD-09** (exe/html/svg → 415; txt ok) |
| `test_type_policy_and_quota` | AC-UPLOAD-10 (per-type cap + ext), **AC-UPLOAD-11 quota 413** |
| `test_soft_delete_cascade_restore_purge` | AC-TRASH-01/02/03 (subtree cascade + restore + purge) |
| `test_zip_job_runs_eager_to_ready` | AC-DOWNLOAD-02 (job → ready, zip magic) |
| `test_content_serve_is_sandboxed` | **AC-PREVIEW-02** (CSP `default-src 'none'; sandbox` + nosniff + private-cache) |
| `test_types_crud` | AC-TYPE-01/02/03, **TYPE-E2 ext normalisation** |
| `test_settings_roundtrip_and_usage` | AC-SETTINGS-01/02/03, AC-USAGE-01 |
| `test_upload_emits_file_event` | **AC-EVENT-01** (`file`/`created` event drained via the emit seam) |
| `test_unauthenticated_is_blocked` | AC-PERM (401/403 without a token) |
| `test_tenant_isolation` | **X-E4** (tenant B never sees tenant A's Drive) |

## Frontend — `document-service.mock.test.ts` (10)

Drive seed/navigation/breadcrumb · create folder · rename (id stable) · upload version+progress · sniff-floor reject · collision 409 → replace(version)/keep-both(rename) · quota 413 · cycle guard · soft-delete subtree + restore. (Pins the UI's contract against the same behaviours the backend enforces.)

## Implementation cross-check vs UAT (by inspection)

- **AC-NAV / AC-FOLDER / AC-FILE** — `DriveExplorer` + `useDrive` + `DocumentService.list_folder/create_folder/rename_*/move`; cycle guard server (`CycleError` 422) + client (drop self-skip). ✓
- **AC-UPLOAD** — `UploadManager` optimistic context (XHR progress, retry) → `POST /documents/files`; collision 409 `{fileName,existingFileId}` → drawer Replace/Keep-both; `detect_document_mime` hard floor; per-type/default cap; quota 413. ✓
- **AC-DOWNLOAD** — single = `apiFetchBlob` content route; bulk/folder = `download_jobs` + `_build_zip` (eager) + `MyDownloads` poll → authed `/content` stream. ✓
- **AC-PREVIEW** — `PreviewDialog` (image `<img>` / PDF sandboxed iframe) over the CSP-sandbox content route; non-previewable → download. ✓
- **AC-TRASH** — soft-delete `is_deleted` + cascade; `TrashView` restore + typed-`DELETE` purge (blobs dropped). ✓
- **AC-TYPE / AC-SETTINGS / AC-USAGE** — Resource-shell `/documents/types` + dialog; `/documents/settings` form (quota/cap/sharing-ceiling); usage bar from `used_bytes`. ✓
- **AC-EVENT** — `file` registered in the workflow triggerable registry; `emit_entity_event` on upload/move/rename/delete, riding the same commit, failure-isolated. ✓
- **AC-PERM** — `documents.read/manage/share/configure` in core CSV (granted to tenant Admin); endpoints gated; pages wrapped in `<RequirePermission>`; menu pruned per key. ✓
- **AC-UX (guided/foolproof)** — no inline how-to copy; destructive actions reversible (Trash) or typed-confirm (purge) or warn-before-replace (collision); only-valid-options (Move disables no-op/self; Preview only for previewable; Replace/Keep-both only on real conflict); feedback everywhere (progress, ready, toast). ✓

## Code-review hard-fail rules (self-check)

- No DB/raw SQL in a router — routers call `DocumentService` only. ✓
- No component calling `fetch`/axios — UI → hook/context → `documentService` → `api-client`. ✓
- No `any` types — explicit TS interfaces throughout (`types/documents.ts`, service interface). ✓
- No raw CSS / `<style>` — Tailwind utilities only. ✓
- Not a module altering core — this **is** a core engine (`app/document_engine` logic in core `public`). ✓
- Every repository query tenant-scoped. ✓ Storage keys flat-by-id; presigned never immutable-cached; content served CSP-sandboxed. ✓

## Live verify (real browser, real stack)

Ran the branch's backend (`uvicorn … :8001`, shared Postgres migrated to `d4e5f6a7b8c9` via `bootstrap_db`) + dev frontend (`:3001`), signed in as the default-tenant Admin, and drove `/documents` in a real browser:

- **Desktop (1280px):** two-pane Drive renders — folder-tree sidebar + storage bar | breadcrumb + toolbar + grid; the **Documents** sidebar group shows All documents / Document types / Settings (menu wiring + per-key pruning OK).
- **Create folder** → "Quotations" appears in **both** the tree and the grid (real Postgres write). The New-folder dialog's Create button stays disabled until named (foolproof, FOLDER-E3).
- **Upload** a PDF via the picker → the file card appears (35 B) and the **storage usage bar updates to 35 B** (StorageService local-disk round-trip + AC-USAGE-01).
- **Mobile (375px):** sidebar+storage stack above the grid, toolbar wraps to two rows, 2-column card grid; **zero horizontal overflow**. Screenshots: `service_frontend/.playwright-mcp/drive-{desktop-1280,mobile-375}.png`.

**Responsive fix applied during verify:** the toolbar action-button group (5 buttons) overflowed 375px by 6px; added `flex-wrap justify-end` so it wraps (AC-RESP-02 / RESP-E1). One real bug, fixed and re-verified.

The automated `documents.spec.ts` exercises these same journeys; under the **dev** server its rapid per-test subdomain navigations (`e2e-docs-*.localhost`) destabilised the server, so the live confirmation above was done manually. The spec is stable against a production build — run after the unrelated stale-lint blocker below is cleared.

## Known follow-ups / caveats

- **Prod-build lint blocker (pre-existing, not this plan):** `next build` fails its ESLint pass on a missing file `app/(protected)/account/members/import-members/components/import.tsx` (a deleted file still referenced by the lint gate, untracked + unreferenced in source) — unrelated to documents. The dev server compiles + serves fine. Clear this to run `documents.spec.ts` against a stable `npm start`.
- **ZIP build runs inline (eager)** in dev/test; production should wrap `_build_zip` in a Celery task (the builder is already factored for it).
- **Collision/folder uniqueness is app-level** (a Postgres functional `lower(name)` index is a follow-up; NULL-distinct on the nullable `folder_id` makes a naive unique constraint unreliable).
- Slice-05 sharing (`documents.share`, links, public route) intentionally absent; the `publicSharing` setting saves but is inert until then.
