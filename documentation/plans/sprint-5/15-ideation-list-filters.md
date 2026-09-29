# 15 - Ideation list filters / sort / columns / vote order, detail upload + status pill, embed promote

UAC: `15-ideation-list-filters-acceptance-criteria.md` (AC-15-01..26). Lane IDEATION-LIST, branch `crew/ideation-list-filters`, base `origin/main` (4b1a4ec3). Reuse-only UI (no new component, no mockup): DataGrid filters/sort/column toggle, `StatusBadge`, `AttachmentDrop` (`useFileUpload`), api-client multipart.

## 1. Findings (why each change is where it is)

- Column toggle is EMPTY because `components/ui/data-grid-column-visibility.tsx:19` and `data-grid-column-header.tsx:243` filter `typeof column.accessorFn !== 'undefined'`; the ideas columns are display columns (`id` + `cell`, no accessor). Fix the shared filter to `column.getCanHide()` only. Beneficiaries (0 accessor keys): ideas list, BR list, BR ideas tab, idea BRs tab, idea merged tab, autocount pull rows.
- Sorting/filtering are MANUAL in the shell (`resource-list.tsx:333-335`); the ideas fetcher is client-side (`use-ideas-list-config.tsx` fetcher -> `select-idea-rows.ts`). So filter + sort live in `selectIdeaRows` (also used by the detail pager: keeps AC-15-09 for free). `services/mock-query.ts:runQuery` sorts as strings; do not reuse its sort for votes/dates; `evalGroup` from it IS reusable for the filter tree.
- Vote model: `idea_votes.dir in (up, down)`, tallies `upvotes` + `downvotes` on `ideas` (models.py:187-188). Net supported -> default order net desc, upvotes desc, createdAt desc.
- Attachments: `idea_attachments` (models.py:247) holds WhatsApp captures with a durable external `url`, `source_msg_id` NOT NULL unique per idea. No upload path exists (`ideation-service.real.ts:30`). Storage precedent: `app/api/v1/documents.py:320` (capped read) + `document_service.upload` (sniff -> `storage_for_tenant().save(key_hint, content, mime)`) + `_serve_blob` (documents.py:112: CSP sandbox, nosniff, private cache, presigned redirect). Key registration: manifest `storage_locations` block (omnichannel precedent `modules/omnichannel/bootstrap.py:78-95`, `register_module_declared_locations`); `bootstrap.py:52` already names the idea-attachment declaration as a placeholder.
- Embed: `EmbedTokenPrincipal` (services/embed.py:65) has no permissions; the embed token payload carries `email` (embed.py:304) but the principal drops it. Operator BR create = `routers/business_requirements.py:63` -> `BusinessRequirementService.create(tenant_id, product_id=, title=, answers=, idea_ids=, actor=)`. `get_current_user` rejects `typ=embed` (dependencies.py:64) so the FE promote (`promote-to-br.ts:43` -> `POST /ideation/business-requirements`) 401s in the iframe.

## 2. Backend slices

### B1 Attachments upload + serve (AC-15-14..19)
- `modules/ideation/models.py` `IdeaAttachment`: add `storage_key = Column(String, nullable=True)`, `mime = Column(String, nullable=True)`, `size_bytes = Column(Integer, nullable=True)`.
- `modules/ideation/alembic/versions/0013_ideation_attachment_upload.py` (revision `0013_ideation_attachment_upload`, down `0012_ideation_merge_rank_events`): Postgres-only `ALTER TABLE "<schema>".idea_attachments ADD COLUMN IF NOT EXISTS storage_key VARCHAR NULL / mime VARCHAR NULL / size_bytes INTEGER NULL` (pattern: 0011).
- `manifest.json`: `"storage_locations": [{"model": "IdeaAttachment", "column": "storage_key", "tenantColumn": "tenant_id"}]`; `bootstrap.register_engine_entities` registers the manifest-declared locations (copy the omnichannel loop). Drift test `tests/test_storage_migration_registry.py` must stay green.
- `schemas.py` `IdeaAttachmentOut`: add `contentPath: Optional[str] = None`; `IdeaReadService._attachments` fills `sizeBytes` and `contentPath = f"/ideation/ideas/{idea_id}/attachments/{id}/content"` when `storage_key` is set (embed callers rewrite the prefix client-side: FE embed service maps `/ideation/ideas/...` -> `/embed/ideas/...`; simpler: the serializer takes an optional `content_prefix` argument, default `/ideation/ideas`, embed routes pass `/embed/ideas`).
- New service `modules/ideation/services/attachments.py`: `IdeaAttachmentService(db).upload(tenant_id, idea_id, filename, content) -> IdeaAttachmentOut` (idea must be in tenant -> 404; sniff via `modules/omnichannel/services/media_pipeline.detect_media_mime` - move/copy that pure function into `app/uploads.py` as `detect_attachment_mime` if importing across modules violates the capability rule; `None` -> 415; empty -> 415; kind from mime prefix; `storage_for_tenant(db, tenant_id).save(f"ideation/ideas/{idea_id}/{attachment_id}", content, mime)`; row: `source_msg_id=f"upload:{attachment_id}"`, `url=""`, `filename`, `mime`, `size_bytes`, `storage_key`) and `content(tenant_id, idea_id, attachment_id) -> (storage_key, mime, filename)` (404 outside tenant/idea).
- `routers/ideas.py`: `POST /{idea_id}/attachments` (`UploadFile`, `require_permission("ideation.triage.manage")`, read cap `25 MB + 1` -> 413) returns 201 `IdeaAttachmentOut`; `GET /{idea_id}/attachments/{attachment_id}/content` (`ideation.ideas.view`) serves via a `_serve_blob`-equivalent (reuse `app/api/v1/documents._serve_blob` if importable without side effects, else copy the 20 lines into the ideation router with the same headers). Router = HTTP only.
- `routers/embed.py`: same two routes under `/embed/ideas/{idea_id}/attachments[...]` with `require_embed_principal` + `_assert_in_scope`.
- Register on `/embed/ideas/{id}` list/detail serializer the `content_prefix="/embed/ideas"`.

### B2 Embed promote (AC-15-20..23)
- `services/embed.py`: `EmbedTokenPrincipal.email: Optional[str] = None`; `resolve_embed_token` sets it from `payload.get("email")`.
- `routers/embed.py`: `POST /embed/ideas/promote` body `EmbedPromoteIn {ideaIds: List[str], title: str = ""}`; steps: `_assert_in_scope` per id; resolve user = `UserRepository(db).get_by_email(principal.email, principal.tenant_id)` when `principal.email`; 403 `ApiError(403, "forbidden", "You do not have permission to promote ideas.")` when no email / no user / key missing from `effective_permission_keys(user)`; product = `principal.product_id` or the ideas' single product (load via the same light query, 422 if mixed - the service also enforces); return `BusinessRequirementService(db).create(tenant_id, product_id=..., title=body.title, idea_ids=body.ideaIds, actor=user)` with 201.
- Operator route untouched.

## 3. Frontend slices

### F1 Shared column toggle (AC-15-04)
- `data-grid-column-visibility.tsx` + `data-grid-column-header.tsx:243`: drop the `accessorFn` predicate, keep `getCanHide()`; label = `meta.headerTitle ?? (typeof header === 'string' ? header : column.id)`. Add `meta.headerTitle` to `ColumnMeta` (types.ts declaration merge) so display columns get a human label; the ideas `col()` helper sets it.

### F2 Ideas list (AC-15-01..11)
- `select-idea-rows.ts`: accept `Pick<ListQuery, 'search' | 'statusView' | 'filter' | 'sort'>`; apply `evalGroup` (from `services/mock-query`) with a `getField` adapter (`status`, `submitter` -> `submitterName`, `channel` -> `source`, `product` -> `productName`, `votes` -> net, `submitted` -> `createdAt`, `problem` -> title ?? problem); sort with typed comparators (numbers for `votes`, `Date.parse` for `submitted`, localeCompare otherwise); DEFAULT (no `sort`) = net desc, upvotes desc, createdAt desc.
- `use-ideas-list-config.tsx`: remove `rowReorder` + `onReorder` usage (keep the handler key in the signature so callers do not change, mark unused); `col()` gets `enableSorting: true`, header `DataGridColumnHeader title=...`, `meta.headerTitle`; new `submitted` column (`useDatetime().formatDate`); Product column only when `mode !== 'embed'`; `filterFields` = Status enum (unique `status` -> `statusLabel` from `ideas`), Submitter enum (unique `submitterName`); `defaultSort: { id: 'votes', desc: true }`; export columns add Submitted. Promote bulk action: in embed mode drop the `permission` gate (backend 403 -> toast), `run` -> shared `promoteIdeasToBr(rows, router, { mode, service })`.
- `ideas-view.tsx`: remove `IdeaClusterSuggestions` mount; remove `onReorder` handler.
- `ideas/page.tsx`: `<PageHeader />` without description.

### F3 Idea detail (AC-15-12..15, 24)
- `use-idea-form.tsx`: `subtitle` = `<StatusBadge status={idea.status} registry={statusRegistryFor(idea)} />` (move `statusRegistryFor` to `components/status-registry.ts` so list + form share it); Promote action: visible in embed too (no `permission` in embed mode), calls the shared promote with runtime; after upload the form reloads the idea (`getIdea`) so the Attachments tab shows the new row.
- `idea-form-fields.tsx`: `DetailsTab` renders the Product row only when `creating`; `AttachmentsTab` gets `onUpload?: (files: File[]) => Promise<void>` and `fetchContent?: (a) => Promise<Blob>`; when `onUpload` is set renders `AttachmentDrop` above the list (upload on drop, then clear), empty state = `No attachments` only; preview: when `a.contentPath` is set, fetch blob via `fetchContent` -> object URL (revoke on close), else today's `a.url`.
- `attachment-drop.tsx`: expose the raw `File` list (`onChange(files: File[])` alongside the metadata or a second `onFiles` prop) - the capture dialog keeps its metadata use.
- `types/ideation.ts`: `IdeaAttachment.contentPath?: string | null`.
- `services/ideation-service.ts`: `IdeaService.uploadAttachment?(id, file): Promise<IdeaAttachment>`, `fetchAttachment?(contentPath): Promise<Blob>`, `promoteToBr?(ideaIds, title?): Promise<{ id: string; title: string; brNumber?: string | null }>`; real: multipart `apiFetch` (`FormData`, api-client skips JSON content-type), `apiFetchBlob(contentPath)`; embed: same on `/embed/ideas/...` + `POST /embed/ideas/promote`.
- `promote-to-br.ts`: `promoteIdeasToBr(ideas, router, { title?, runtime })` - embed runtime -> `runtime.service.promoteToBr` + toast + stay; operator -> unchanged (`businessRequirementService.create` + navigate). 403 -> toast `You do not have permission to promote ideas.`

## 4. Tests (tester writes first, red)
- Vitest: `select-idea-rows.test.ts` (new), `use-ideas-list-config.test.tsx` (extend), `components/ui/data-grid-column-visibility.test.tsx` (new), `use-idea-form.test.tsx` (extend: subtitle badge, no Product row, upload wiring, embed promote), `promote-to-br.test.ts` (extend: embed path), `ideas-view.test.tsx` (no cluster strip).
- Pytest: `tests/test_ideation_attachments_upload.py` (new: 201 + row fields + sniff 415 + 413 cap + serve headers + cross-tenant 404 + embed scope + storage-location registered), `tests/test_ideation_embed_promote.py` (new: 201 with perm, 403 without / no user / no email, 404 out of scope, operator route unchanged, embed token on operator route 401).

## 5. Ops / DoD
- Migration 0013 verified on live Postgres by crew (`bootstrap_db` runs module migrations); crew SQL file `state/migrations/IDEATION-LIST.sql` mirrors it idempotently.
- No new permission (reuses `ideation.triage.manage`, `ideation.ideas.view`, `ideation.business_requirements.manage`) -> no grant sweep.
- No hardcoded status key anywhere (labels from the engine on each idea).
- Product column choice: operator page keeps Product (multi-product page), embed drops it.
- Frontend checks (vitest/eslint/build) run in a scratch worktree, never in the lane worktree while a hand-test copy is up.

## 6. Shipped notes (coder)
- Backend: `IdeaAttachment.storage_key/mime/size_bytes` + migration `0013_ideation_attachment_upload`; `storage_locations` block in the ideation manifest, registered in `register_engine_entities`; `app/uploads.py:detect_attachment_mime` (shared sniff, superset of `detect_upload_mime` with audio/video containers); `services/attachments.py`; routes `POST|GET /ideation/ideas/{id}/attachments[...]` and `/embed/ideas/{id}/attachments[...]`; `POST /embed/ideas/promote` (403 via the standard `ApiError` envelope).
- Product column choice: the operator page keeps Product (all products); the embed drops it (already product-scoped).
- The Submitted cell and the detail Captured row format through `useDatetime()` (user timezone).
- The crew SQL mirror of 0013 lives at `crew/state/migrations/IDEATION-LIST.sql`.
- Security (PR #100): embed promote also requires an active user and a sign-in-allowed tenant; embed-connection create/patch/rotate require both `ideation.triage.manage` and `ideation.business_requirements.manage`; uploads are capped at 20 per idea with cleaned filenames and BOM-safe sniffing.
- Embed action responses (vote/status/patch/merge/create) carry the operator `contentPath` prefix; `ideation-embed-service.fetchAttachment` rewrites `/ideation/ideas/` to `/embed/ideas/` (intentional). `_serve_blob` is imported from `app/api/v1/documents` (shared helper; promoting it to a shared module is backlog).
