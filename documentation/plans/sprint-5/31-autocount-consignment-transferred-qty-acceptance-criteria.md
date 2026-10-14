# 31 - AutoCount Consignment TransferedQty (CRM contract 2.9) - acceptance criteria

Lane: follow-up to AC-CANCEL-PULL (#122). CRM side: AC-CONSIGN-CRM (sorento-crm#1654).

The `consignment` entity (AutoCount `Consignment` / `ConsignmentDTL`) gains one additive line field on the wire,
`Details[].TransferedQty` (consigned quantity already transferred out of the consignment). It is sent only when the
CRM advertises contract >= 2.9; below that the 2.8 shape is sent unchanged. `DebtorCode`, `DebtorName`,
`SalesAgent` (header) and `UnitPrice`, `SubTotal`, `UOM` (lines) are already in the 2.8 shape since #122.

- **AC-31-01 [BE][T]** The `AutoCount Consignment` preset line query selects `d.TransferedQty AS TransferedQty`,
  and the header and fingerprint queries carry a `TransferedSum` aggregate. A transfer that does not bump the
  header `LastModified` therefore still moves the header hash and the fingerprint. The other three linked
  presets are unchanged.
- **AC-31-02 [BE][T]** Given the consumer advertises contract >= 2.9, each consignment record's `Details[]`
  carries `TransferedQty` (a JSON number). Given < 2.9, or an unknown contract, the key is absent and the record
  is byte-identical to the 2.8 shape. `TransferedSum` never reaches the wire.
- **AC-31-03 [BE][T]** The mapping layer gains an optional line field `qty_transferred` (TransferedQty) in the
  consignment preset. It is not required.
- **AC-31-04 [BE][T]** Backfill for existing consignment tasks (deploy migration + `update_tenant`):
  - a task whose stored header, line and fingerprint queries are byte-identical to the #122 preset text (with
    `{database}` substituted) is rewritten to the new text;
  - `TransferedSum` is appended to `result_columns` and `TransferedQty` to `line_result_columns`;
  - the `TransferedQty -> qty_transferred` line mapping row is added when absent;
  - a customised query is left untouched, with a WARNING;
  - it is idempotent.
