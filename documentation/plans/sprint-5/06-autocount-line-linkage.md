# 06 - AutoCount document line linkage (PO/SPO line -> SO line, SPO line -> PO line)

UAC: `06-autocount-line-linkage-acceptance-criteria.md` (the contract; this file is the design
that fulfils it). Lane `sprint-5/06-autocount-line-linkage`, worktree `.claude/worktrees/s35`
off `origin/main` 23ad4cc4 (module 0.7.0, module Alembic head 0017).

## 1. Why

Sorento's order-inquiry reservation ranks candidate PO / SPO lines by location only. It wants
to prefer the PO line raised FOR the inquiry's sales order, and to print the source PO beside
every SPO reservation. The feed carries neither today: `CanonicalPurchaseOrderLine.from_so_numbers`
exists on `main` (addendum section 4, "engine-derived from `FromSODocList`") but nothing
populates it, and the shared PO/SPO line query selects no linkage column at all.

Live AED_SORENTO facts (2026-09-08 probe, read-only): the stock AutoCount "Transfer from S/O"
writes `PODTL.FromSODtlKey` (+ `FromSODocList`) on 20,802 of 37,692 PO lines since 2025;
`UDF_SOList` is never used; the ICB inter-company plugin UDFs are on 19 lines all-time. SPO
lines (`PO.UDF_ShipOrder='T'`, `SPO-` numbered) carry `FromDocType='PO'` + `FromDocDtlKey`
on 106,283 lines, resolving to the source PO line and header. So line-level resolution is real
for both directions, and this is a code slice, not a process rule.

Wire shape frozen with the Sorento owner (see the UAC header). Division of labour, in the
owner's words: we pass the key and the number, Sorento links.

## 2. Design

### 2.1 Operator-mappable inputs, engine-minted refs (grill 2026-09-08, user's choice)

The user chose operator-mappable line fields over fixed column names. The ref FORMAT is the
ESB's convention (`{database}:{DocKey}:{DtlKey}`, the same composition the line's own
`source_ref` gets in `MappingEngine.map_document`), so the operator maps the raw AutoCount
keys and the engine mints the ref - exactly how `source_ref` already works:

| Wire field (contract 2.2) | Built from | How |
|---|---|---|
| `from_so_line_ref` | input `from_so_doc_key` + `from_so_line_key` | engine: `f"{database}:{doc_key}:{line_key}"`, None if either missing |
| `from_so_numbers` | operator row, transform `string_list` | mapped directly (`FromSODocList`) |
| `from_so_external` | input `from_so_external_db/_doc_key/_doc_no/_line_key` | engine: object when `_db` set, else None |
| `from_po_line_ref` | input `from_po_doc_key` + `from_po_line_key` | engine, same rule |
| `from_po_number` | operator row, transform `string` | mapped directly (`FromPODocNo`) |
| `product_code` | already mapped (`ItemCode`) | unchanged |

Input fields are canonical model fields that never reach `SINK_FIELDS` / `FALLBACK_FIELDS`;
wire fields join `FALLBACK_FIELDS` (contract major >= 2). Line `sink_payload` drops a linkage
key whose value is None / empty (the `container_number` rule: absent = leave alone).

Where it lives: `canonical/documents.py` (fields, `FromSoExternal` model, payload rule);
`mapping.py` (`string_list` transform; minting block in the per-line loop of `map_document`,
right after `_apply` and beside the `line_ref_prefix` composition; save-time transform pairing
for the new targets alongside `LINE_FIELD_REF_TRANSFORMS`); `mapping_catalog.py` (line
targets for PO + SPO only; parity pin rewritten per AC-06-10).

### 2.2 Presets (`presets.py`)

`_PO_LINE_QUERY` (shared PO/SPO) gains the SO / source-PO joins and seven columns (AC-06-12).
`_PO_HEADER_QUERY`'s `OUTER APPLY` and `_PO_FINGERPRINT_QUERY` gain four aggregates
(`LinkedSOCount`, `FromSOKeySum`, `LinkedPOCount`, `FromPOKeySum`, AC-06-13): a link added,
removed or re-pointed changes a header aggregate, so change detection (`result_columns` hash)
and the fingerprint sweep both see it without any line-level watermark. Six preset line rows
per PO / SPO preset (AC-06-14). No UDF column in preset text: `UDF_ICB_*` is a Sorento-book
customisation, documented as an operator addition mapped to `from_so_external_*` (AC-06-24).

### 2.3 Backfill (`backfill.py`, module Alembic 0018, `update_tenant`, manifest 0.8.0)

Mirror of `backfill_shipping_order_container_number` (0016): per existing PO / SPO task, add
the six rows when absent; rewrite byte-identical old `query` / `lineQuery` /
`fingerprintQuery` (own-company substitution only) to the new text and append the four
aggregate names to `result_columns`; customised text -> warning + rows still added; SO tasks
untouched; schema-tolerant (AC-06-16..19). Appending to `result_columns` re-hashes every
header in the task's window on the next reconcile, which is the one-time re-stage that ships
the linkage for documents Sorento already holds.

### 2.4 Backfill window (grill: since 2023-09-01)

`fromDate` is task config; the migration does not touch it. Runbook, after Sorento 2.2 is
live and the ESB is deployed: on the PO and the SPO task set fromDate `2023-09-01`, run
reconcile (bulk document load, plan 03: 2000 headers / run) until the run reports 0 re-staged,
then restore the previous fromDate. Recorded in the test report with counts.

### 2.5 Frontend

The Mapping tab renders whatever the backend line catalog returns; the only FE code is the
transform picker entry `string_list` + the formula type map + the mock service catalogs
(AC-06-21), verified by vitest and one recorded agent-browser run (AC-06-22).

### 2.6 Sorento contract 2.2 (deploy order)

Sorento adds the four names to `CanonicalPurchaseOrderLine` / `CanonicalShippingOrderLine`
and to `fields_added.purchase_orders|shipping_orders` on `GET /api/v1/external/contract`.
The ESB deploy waits for that (AC-06-23); the ESB-side gate stays "contract major >= 2" (the
per-connection `sorentoContractVersion`), no new gate.

## 3. Files

Backend (`service_backend/modules/autocount/`): `canonical/documents.py`, `mapping.py`,
`mapping_catalog.py`, `presets.py`, `backfill.py`, `bootstrap.py` (update_tenant hook),
`alembic/versions/0018_autocount_line_linkage.py`, `manifest.json`.
Tests (`service_backend/tests/`): new `test_autocount_line_linkage.py` (groups A-D), edits to
`test_autocount_spo_container_catalog.py` (parity pin), `test_autocount_documents.py` (golden
unchanged pins).
Frontend: `app/(protected)/autocount/components/autocount-meta.ts`, `lib/autocount-formula.ts`,
`services/autocount-service.mock.ts`, one vitest file.
Docs: `documentation/plans/sprint-5/02-autocount-document-mapping-sorento-addendum.md`
(section 4 + change log), `documentation/plans/sprint-4/22-autocount-db-etl-autocount-sql.md`
(sections 3, 4, AED_SORENTO ICB note), this plan's test report + `06-evidence/`.

## 4. Slices and order

| # | Slice | Proves | ACs |
|---|---|---|---|
| S0 | FE mock: transform entry + mock catalogs + vitest | picker shape before the backend exists | 21 |
| S1 | transform, canonical fields, payload gate, catalog, minting, presets (TDD) | a mapped line mints refs and the wire is right | 01-15 |
| S2 | backfill helper + 0018 + update_tenant + manifest | existing tasks pick it up | 16-20 |
| S3 | docs + agent-browser run + live tunnel proof + report | DoD | 22-27 |

Coder on Sonnet per slice (`isolation` = the s35 worktree, already created); tester writes
the red tests for S1/S2 before the coder; reviewer on Opus before merge; `/codex-review` on
the S1 diff (engine change).

## 5. Risks and answers

- **Sorento rejects the re-staged family** if 2.2 is not live first - deploy order is an AC,
  not a note (AC-06-23). Same guard that bit `container_number`.
- **A customised prod line query never gets the columns** - the backfill warns naming the
  config id; the operator pastes the new preset text from the SQL pack (documented).
- **`SUM(FromSODtlKey)` overflow** - bigint keys ~4.5e7 x <= a few hundred lines: far inside
  bigint. A swap of two keys between lines leaves the sum unchanged but the count and every
  other aggregate too; the line's own payload is re-fetched on any header change anyway.
- **List cap** - Sorento caps `from_so_numbers` at 50; the transform caps and warns.
- **Location** - untouched. The "no location" rows Sorento saw are their own missing
  warehouse (BRW-TERA, retired; owner ruled leave blank).

## 6. Backlog

- BL-SS-(next): `UDF_ICB_*` cross-book linkage as a preset option per company (today an
  operator addition; 19 lines all-time in AED_SORENTO).
- BL-SS-(next): SPO lines typed by hand (11,144 all-time carry no `FromDocDtlKey`) - a
  process rule on the AutoCount side, nothing the feed can recover.

## 7. Decision log

| # | Decision | Why |
|---|---|---|
| D1 | Operator-mappable inputs, engine-minted refs | user's choice at the grill; ref format stays the ESB's, like `source_ref` |
| D2 | Wire fields in `FALLBACK_FIELDS`, no new gate | same contract-major gate as every 2.x field |
| D3 | Omit None / empty linkage keys | `container_number` precedent; Sorento treats absent as leave alone |
| D4 | Header aggregates + fingerprint carry the link keys | link changes re-stage without a line watermark; also the one-time backfill trigger via `result_columns` |
| D5 | No UDF column in preset text | per-company UDFs break other books (ETL Demo Co, AED_VSOFT); catalog still offers the targets |
| D6 | `from_so_external` only when `_db` set | a key that does not resolve in this book never sits in a same-book ref field (Sorento owner's rule) |
| D7 | Backfill from 2023-09-01 by fromDate, operator-driven | user's choice; fromDate is task config, not migration state |
| D8 | No FOC fields | probe C: FOCQty NULL on every zero-qty row; not the mechanism |
| D9 | No Location change | probe E: 0 NULL locations fleet-wide; defect was Sorento's warehouse master |
