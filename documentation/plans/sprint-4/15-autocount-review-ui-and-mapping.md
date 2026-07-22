# 15 — AutoCount review UI + field-mapping editor

> **Contract:** `15-autocount-review-ui-and-mapping-acceptance-criteria.md` (governs).
> **Builds on:** slice 14. Branch continues on `sprint-4/14-autocount-sorento-masters` (same feature;
> merge as one) OR a child branch `sprint-4/15-autocount-review-ui` if 14 merges first.
> **Nature:** surface-only. The engine, canonical contract and Sorento sink are untouched.

## 1. Shape of the work

Six eyeball issues → five workstreams. Backend adds are small and additive (a jobs list, staged
pagination, mapping read/write); the weight is frontend conformance to the Resource shell + the
read-only-until-Edit mandate, plus one new editor.

## 2. Backend (additive, thin)

- **`GET /autocount/jobs`** (`autocount.sync.read`): tenant-scoped, paginated (`page`/`page_size`
  like `/companies/{id}/runs`), `status` filter (`needs_review|done|all`), optional `entityType`.
  Returns company, entity, status, counts, timestamps. Backs the Review list (AC-15-02). Reads
  `background_jobs` where `type='autocount_sync'` — no new table.
- **Staged pagination**: `GET /autocount/jobs/{id}/staged` gains `page`/`page_size` + a
  `changed`-only filter option; response carries `total` + the no-change count so the FE can render
  the collapsed summary without fetching them all (AC-15-10/11). The service already computes the
  per-record diff — surface `hasChanges` per row.
- **Mapping read/write** (`autocount.companies.manage`):
  - `GET /autocount/companies/{id}/entities/{entityType}/mapping` → current `ac_field_mapping` rows
    projected as `{sourcePath, transform, sorentoField}` (canonical name mapped to its Sorento label
    via the sink's field set) + the two catalogs: **acFields** (known AutoCount source fields for the
    entity) and **sorentoFields** (Sorento's accepted fields = the sink `SINK_FIELDS`, with
    required-ness).
  - `PUT .../mapping` → replace the entity's mapping rows transactionally. **Guard**: every
    `sorentoField` must be in the accepted set (else 422, AC-15-42); `sourcePath` shape-validated
    (AC-15-43). Writing is an operator edit — the existing seed-if-absent contract already protects
    it from `update_tenant` (AC-15-41).
  - Catalog sources: `sorentoFields` from `CanonicalSupplier/Customer.SINK_FIELDS` + a
    required-fields marker (`code`,`name`); `acFields` from the entity's observed vendor payload keys
    (a declared list per entity in `mapping.py`, extended from the default mapping's source paths).
- Naming: reuse `autocount.sync.read` / `autocount.companies.manage` — **no new permission**, so no
  grant sweep.

## 3. Frontend

### A. Review menu + list + form (AC-15-01..03)
- Add **Review** to the AutoCount sidebar section in ALL menu arrays (`MENU_SIDEBAR`, `MENU_MEGA`,
  `MENU_MEGA_MOBILE`), gated `autocount.sync.read` (menu-filter parity).
- New route `app/(protected)/autocount/review/page.tsx` = a `ResourceList` (config-driven) over
  `GET /autocount/jobs`: columns company/entity/status/records/when, status **segments** (Needs
  review | Done | All), search, server pagination. `rowHref` → the existing
  `/autocount/review/[jobId]` detail (which becomes the "form" view). Clone the Users list shape.
- The existing `[jobId]` review page is the detail/form — unchanged except it now has a real list
  parent (breadcrumb + back to the list).

### B. Staged list on the Resource shell (AC-15-10/11)
- Replace the hand-rolled `StagedRecordCard` stack in `review-view.tsx` with a Resource-shell list
  (or an embedded list like the omnichannel Templates tab): paginated, searchable, `hasChanges`
  filter. Row = source ref + name + status + a "changed / no change" marker; expanding a row (or a
  detail drawer) shows the full `RecordDiff`.
- No-change rows collapse into a single "N records with no field changes" summary line (reuse the
  preview panel's partition pattern).

### C. Push target into Edit view (AC-15-20/21)
- Fold `sink-target-card.tsx` into the company Overview **Resource form**: render read-only
  label/value by default (Delivery: Sorento · Connection: <name>), editable only under the form's
  global Edit toggle, saved via the form's single PATCH (`/sink-target` already exists) with the
  form's dirty-guard. Delete the detached Save button + bespoke container. Use `FormRow` +
  `SearchSelect`. Warn + block Sorento-without-connection.

### D. First-run window not-dead (AC-15-30/31)
- In `use-entities-list-config` / the row actions: when `watermarkAt` is set (superseded), replace
  the "Edit first-run window" item with read-only info (show the sync position) and, if we offer
  re-fetch, a distinct **"Re-fetch history"** action that resets the watermark (explicit, confirmed).
  Keep the editable Days dialog only for un-superseded entities (`entity-lookback-dialog.tsx`
  unchanged for that path).

### E. Mapping editor (AC-15-40..44)
- New surface reachable from the Entities tab (row action "Configure mapping" or a Mapping tab on a
  company-entity detail). A table editor: rows of **AutoCount source `SearchSelect`** →
  **transform `SearchSelect`** → **Sorento field `SearchSelect` (accepted set only)**; add/remove
  rows; read-only until Edit; saved via `PUT .../mapping`.
- Foolproof: a required Sorento field (`code`,`name`) with no source mapped shows a warning before
  save; the Sorento picker lists only accepted fields; source picker lists known AC fields + allows a
  dotted custom path.
- Service trio + hook, types in `types/autocount.ts`. No `any`.

## 4. Build order

1. Backend endpoints (jobs list, staged pagination + `hasChanges`, mapping GET/PUT + catalogs) + tests.
2. FE conformance fixes C, D (small, high-value, unblock the read-only-until-Edit complaint) + B.
3. FE Review menu+list+form (A).
4. FE mapping editor (E) — the feature.
5. Live-verify all at 375 + 1280 against the running stack (the mandate that caught slice-14's gaps),
   E2E spec, test report.

## 5. Definition of Done

The recurring-gap gate applies. Specifically for this pass:
- Every new list is the **Resource shell**, never hand-rolled (the exact complaint here).
- Every editable surface is **read-only until Edit** (the push-target complaint).
- No **dead controls** (the first-run-window complaint) — a control that cannot act is not shown.
- Foolproof mapping: only valid Sorento targets offered; unmapped-required flagged before it becomes
  a failed sync (the null-record failure live-verify caught in slice 14).
- Verified end-to-end with real data at both viewports on a freshly rebuilt frontend.

## 6. Notes / risks

- `acFields` catalog: v1 can seed from the default mappings' source paths + the known
  Creditor/Debtor top-level + `Data.0.*` keys observed live; a fuller "introspect the vendor payload"
  is a follow-up, not this slice.
- The Review list reads `background_jobs` directly (typed `autocount_sync`); keep it tenant-scoped.
- Keep the canonical→Sorento leg fixed (G2). The editor never exposes a target outside `SINK_FIELDS`.
