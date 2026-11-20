# 31 - AutoCount Consignment TransferedQty (CRM contract 2.9) - plan

Lane AC-CONSIGN-PULL, partner of sorento-crm#1654 (AC-CONSIGN-CRM). Contract:
`31-autocount-consignment-transferred-qty-acceptance-criteria.md`. Engine reference:
`documentation/engineering/autocount-doc-feeds.md` section 12.1.

## Design

1. **Scope.** The only additive wire field is `Details[].TransferedQty`. The header `DebtorCode`/`DebtorName`/`SalesAgent`
   and the line `UnitPrice`/`SubTotal`/`UOM` have been in the 2.8 shape since #122.
2. **Preset.** The consignment builders gain `transferred=True`: `d.TransferedQty` on the lines, and a `TransferedSum`
   aggregate on the header `OUTER APPLY` and the fingerprint sweep (a transfer may not bump `LastModified`).
   `TransferedSum` is ESB-internal. The other three linked presets are byte-identical.
3. **Gate.** `CanonicalLinkedDocument.CONTRACT_GATED_LINE_COLUMNS` (consignment `{"TransferedQty": 2.9}`) is checked
   against `SorentoSink.advertised_contract_version`, which `sink_for_company` sets from the probe its 2.8 gate already
   makes. Unknown = stripped (fail closed). Every delivery path (auto_push, approve, preview, dry run) builds its sink
   through `sink_for_company`.
4. **Mapping layer.** `CanonicalConsignmentLine.qty_transferred` (optional); `LINKED_DOCUMENT_LINE_MODELS` per entity.
5. **Backfill.** `backfill_consignment_transferred_qty`, from module Alembic `0030_autocount_consign_xfer` and from
   `update_tenant` gated `< 0.16.0`.
   - Trigger: a task whose stored header is the frozen #122 text.
   - Rewrites every stored query that is still a #122 text.
   - Lists `TransferedQty` (and enables its row) only when the line query now selects it.
   - A customised header is left alone with a WARNING.
   - Tenant-scoped company lookup.
6. **Effect.** Every consignment re-stages once after deploy (`TransferedSum` joins the row hash). Below 2.9 that
   re-push is the unchanged 2.8 record.

## Follow-ups (not this lane)

- Contract versions are compared as floats (`2.10` < `2.9`). This is pre-existing for every gate and is already logged
  as BL-SS-289 (`documentation/backlogs/backlog.md`).
- The mapping simulate preview always shows the 2.8 shape. This is fail-closed by design.
