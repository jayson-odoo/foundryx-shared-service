# 15 - AutoCount review UI + field-mapping editor - User Acceptance Criteria

> **Status:** DRAFT - contract for `15-autocount-review-ui-and-mapping.md`
> **Builds on:** slice 14 (masters end-to-end, MERGED-pending-review on `sprint-4/14-autocount-sorento-masters`).
> **Source:** UI eyeball feedback 2026-07-22 (6 items) + grill decisions below.
> **Nature:** UI/UX conformance pass + one new feature (mapping editor). No change to the sync/push
> engine, the canonical contract, or the Sorento sink.

## Why this slice exists

Live eyeball of slice 14 surfaced six issues, five of them violations of the project's own
standing mandates (read-only-until-Edit, Resource-shell for every list, foolproof-UI, no dead
controls) and one genuinely-missing feature (a UI to configure field mappings). None are engine bugs;
all are the surface.

## Grill decisions (2026-07-22)

| # | Decision | Rationale |
|---|----------|-----------|
| G1 | Mapping UI presents **AutoCount field → Sorento field** directly | The operator's mental model. The canonical layer stays as invisible internal transport. |
| G2 | The **Sorento target is a picker of Sorento's ACCEPTED fields** for that entity | Foolproof-UI: you cannot map to a field Sorento would reject (`extra="forbid"`). "Full remap" = free choice of the AutoCount *source* for each valid Sorento target, not the freedom to invent targets. |
| G3 | No-change staged records are **collapsed, not hidden** | Consistency with the preview panel ("N updates with no value change"); hiding would lose the audit that the record was seen. |
| G4 | First-run window is **not offered as editable once superseded** | A dialog you cannot edit is a dead control. Re-widening a spent window is a deliberate, separate "re-fetch history" act. |

---

## Group A - Review has its own menu (list + form)

### AC-15-01 `[FE]` A "Review" entry in the AutoCount sidebar section
**Given** the AutoCount module is active and the user holds `autocount.sync.read`
**When** the sidebar renders
**Then** the AutoCount section lists **Companies** AND **Review**
**And** the entry is tagged with the same permission gate as the review page (menu-filter parity, all menu arrays).

### AC-15-02 `[FE][BE]` Review is a Resource LIST of batches awaiting attention
**Given** sync jobs exist in various states
**When** the operator opens Review
**Then** a config-driven `ResourceList` shows one row per sync batch (job), newest first
**And** it is **server-paginated, searchable and filterable** (status segment at least: Needs review | Done | All)
**And** each row shows: company, entity, status, record count, when
**And** a backend `GET /autocount/jobs` (tenant-scoped, paginated, status filter) backs it - the list
must NOT be an unbounded fetch.

### AC-15-03 `[FE]` A batch row opens the review FORM view
**Given** the Review list
**When** the operator clicks a batch
**Then** it opens the existing review surface (the form/detail view) for that job
**And** the review surface is reachable this way, not only by a hand-typed URL.

---

## Group B - Staged record list on the Resource shell

### AC-15-10 `[FE][BE]` The staged list paginates, filters and searches
**Given** a batch with many staged records (e.g. 172)
**When** the operator reviews it
**Then** the staged records render through the **Resource-shell list** (server pagination, a page-size
control, search by source ref/name, and a filter)
**And** `GET /autocount/jobs/{id}/staged` accepts `page`/`page_size` (mirroring `/runs`) - no
all-rows fetch
**And** the tall full-card-per-record layout is replaced by a scannable list; a record's full diff is
reachable (expand / detail), not forced inline for every row.

### AC-15-11 `[FE]` No-change records are collapsed
**Given** a delta sync staged records whose mapped fields did not change (Image-4 case: AutoCount
`LastModified` advanced but no mapped field differs)
**When** the staged list renders
**Then** the no-change records are **collapsed into a count** ("N records with no field changes"),
expandable, exactly like the dry-run preview panel does
**And** they are never shown as full-height cards that bury the records that DID change.
> These are legitimate no-op re-fetches, not errors - the fix is presentation, not suppression.

---

## Group C - Push target conforms to read-only-until-Edit

### AC-15-20 `[FE]` The push target is read-only until the form is in Edit
**Given** the company detail Overview (a read-by-default Resource form)
**When** the operator views it without editing
**Then** the push target (delivery sink + Sorento connection) renders **read-only** - plain
label/value like the other Overview fields, no bare dropdowns, no always-visible Save
**And** it becomes editable **only** under the form's global Edit toggle, saving through the form's
single save (dirty-guarded), never its own detached Save button.

### AC-15-21 `[FE]` The push target matches the system's form design
**Given** the redesigned push target
**When** it renders in either mode
**Then** it uses the same `FormRow`/field primitives as the rest of the Resource form (no bespoke
out-of-style container)
**And** the sink and connection pickers are searchable `SearchSelect`s (dropdown mandate)
**And** when delivery is Sorento with no connection chosen, a warning is shown (foolproof-UI), and a
Sorento delivery cannot be saved without a connection.

---

## Group D - First-run window is not a dead control

### AC-15-30 `[FE]` Editing the first-run window is only offered when it can take effect
**Given** an entity that has already synced (superseded - has a watermark)
**When** the operator opens its row actions
**Then** a plain "Edit first-run window" that opens a disabled dialog is **not** presented
**And** instead the superseded state is shown as read-only info (the current sync position), with any
re-fetch offered as an explicit, clearly-labelled "re-fetch history" action (which resets the
watermark) - never a Days box that silently does nothing.

### AC-15-31 `[FE]` A not-yet-synced entity can edit the window normally
**Given** an entity with no watermark
**When** the operator edits the first-run window
**Then** the Days field is editable and saves (unchanged from today for the un-superseded case).

---

## Group E - Field-mapping editor (the feature)

### AC-15-40 `[FE][BE]` Each entity's field mappings are viewable in the UI
**Given** a company + entity (e.g. Customer)
**When** the operator opens its mapping configuration
**Then** the current mappings render as a table: **AutoCount source field → (transform) → Sorento
field**
**And** the Sorento field is shown by its Sorento name, the operator never has to know the internal
canonical name
**And** it is reachable from the entity (Entities tab row action or a Mapping tab).

### AC-15-41 `[FE][BE]` The operator can remap the AutoCount source for any Sorento field
**Given** the mapping editor in Edit
**When** the operator changes which AutoCount field feeds a Sorento field (e.g. `Mobile` → phone), or
its transform
**Then** it persists to `ac_field_mapping` via a backend endpoint (per company+entity)
**And** the change is seed-if-absent-safe: it is an operator edit the next `update_tenant` must not
revert (existing contract).

### AC-15-42 `[BE]` The Sorento target picker offers ONLY Sorento's accepted fields
**Given** the mapping editor for an entity
**When** the operator picks a Sorento target field
**Then** the choices are exactly Sorento's accepted fields for that entity (the sink's field set) -
no more (`extra="forbid"` can never be tripped) and each shown once
**And** a mapping to a non-accepted field is rejected server-side (422), not silently dropped.

### AC-15-43 `[BE]` The AutoCount source picker is discoverable, not free-text guessing
**Given** the mapping editor
**When** the operator picks an AutoCount source field
**Then** the known AutoCount fields for that entity are offered (from the observed vendor payload /
declared source fields), with free-entry allowed for an un-listed path (dotted, e.g. `Data.0.X`)
**And** the source path is validated shape-wise before save.

### AC-15-44 `[FE]` Mapping editor is read-only until Edit + foolproof
**Given** the mapping editor
**Then** it follows read-only-until-Edit, searchable dropdowns, and warns (not silently breaks) if a
required Sorento field (e.g. `code`, `name`) has no source mapped - a required Sorento field left
unmapped is exactly the null-record failure the slice-14 live verify caught, and the UI must flag it
before a sync produces a batch that fails.

---

## Out of scope

- No change to the canonical block model, the sink projection contract, or the sync/watermark engine.
- Per-tenant editing of the canonical→Sorento leg beyond choosing among Sorento's accepted fields (G2).
- The Sorento cross-repo work (separate PR).

## Tests

- `[BE]` new `GET /autocount/jobs` (pagination, status filter, tenant scope), staged pagination,
  mapping GET/PUT (accepted-field guard 422, seed-safe), source/target field catalogs.
- `[FE]` Review list config, staged Resource list + no-change collapse, push-target read/edit modes,
  first-run superseded gating, mapping editor render + accepted-target picker + unmapped-required warning.
- `[E2E]` Review via sidebar → list → open batch → preview; edit a mapping and re-sync; push-target edit.
- Live-verify (both viewports) - the mandate that caught the slice-14 issues.
