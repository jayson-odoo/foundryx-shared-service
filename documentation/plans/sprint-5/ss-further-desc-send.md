# SS-FURTHER-DESC-SEND - raw FurtherDescription on SO + PO lines

Lane: SS-FURTHER-DESC-SEND (partner of the CRM lane RTF-FURTHER-DESC-RENDER, sorento-crm #2766).

## Rulings (crew, 25 Nov)
- New line key `further_description_rtf` on SO AND PO lines: raw bytes, no strip. Sent only when the CRM
  advertises contract >= 2.16. `line_remark` unchanged.
- No bulk re-push mode: the CRM re-pull calls the SS single-document read per document, and that read must
  return `Details[].FurtherDescription` raw for sales orders and purchase orders.
- No change to Link PO writes (PR #354).

## Design
- `mapping.py`: transform `raw_text` (blank -> None, else the stored text unchanged). It is the only
  transform allowed onto `further_description_rtf`.
- `canonical/documents.py`: field on `CanonicalSalesOrderLine` / `CanonicalPurchaseOrderLine` (v2 fallback),
  popped by `sink_payload` unless `advertises_further_desc_rtf` (>= 2.16). Cap `FURTHER_DESC_RTF_MAX_BYTES`
  = 2 MiB UTF-8 (largest seen on db3 is about 1.2 MB). Over the cap it is null plus a warning, never cut.
- `presets.py`: SO adds a second `FurtherDescription` row. PO has its own line query
  (`_PO_ONLY_LINE_QUERY` = shared PO/SPO text + `d.FurtherDescription`) plus the row. SPO is unchanged.
- `backfill.backfill_further_desc_fields`, module Alembic 0050, `update_tenant` < 0.24.0 (manifest 0.24.0).
- B6 read (`PrimitiveService.read_doc`): for SO, `line_notes.attach_so_notes` overlays each row's stored
  FurtherDescription from `SODTL` through the company's line-notes source (one read-only SELECT, keyed by
  DocKey + DocNo). Unknown is no key (the `_unread`/`_legacy` markers are stripped by `public_doc`). PO and SPO
  already get it from `NotesReader`. Writes never call it.

## Expected duration
Not applicable: the bulk re-send was dropped. The CRM re-pull cost is one B6 read per document: one vendor GET
plus one read-only SQL SELECT.

## Tests
`service_backend/tests/test_autocount_further_desc_send.py` (46). Red on main @3f627be6 (collection error:
the contract constants did not exist).
