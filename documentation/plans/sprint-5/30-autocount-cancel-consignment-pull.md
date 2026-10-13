# 30 - AutoCount cancel / consignment pull - plan

Lane AC-CANCEL-PULL. Contract: `30-autocount-cancel-consignment-pull-acceptance-criteria.md`. Engine reference:
`documentation/engineering/autocount-doc-feeds.md` section 12. CRM side: lane AC-CANCEL-CRM (#1623, contract 2.8).

## Design

1. **Source.** Four `sql_db` document presets on the SO/PO pattern:
   - `XS`/`XSDTL`, `XP`/`XPDTL`, `Consignment`/`ConsignmentDTL`, `ConsignmentReturn`/`ConsignmentReturnDTL`;
   - `LastModified` cursor, `DocDate` floor, `DocKey` key;
   - the SO pseudo-line cut;
   - `FromDocType`/`FromDocNo`/`FromDocDtlKey` on every line.

   Schema facts were read live, read-only, by the crew on 2026-10-13.
2. **Mapping layer.** Typed canonical models (`CanonicalLinkedDocument*`) give the Mapping tab its catalog, the
   required-field gate and named mapping errors. They never reach the wire.
3. **Wire.** The DO/GRN doc-feed shape the CRM already ingests:
   - body `{companyCode, book, records}`, each record the SQL header row (PascalCase) plus `Details`;
   - `source_ref` = `{book}:{XS|XP|CG|CR}:{DocKey}`;
   - `book` = the company's own DO (else GRN) feed book;
   - deletions through `delete_doc_keys`.
4. **Gate.** Contract >= 2.8 with the entity's name advertised. `auto_push` and `approve()` refuse the logging-sink
   fallback (`CONTRACT_GATE`, rows stay STAGED).
5. **Frontend.** Only the entity lists (`AC_SQL_DB_ENTITY_TYPES`, `isDocumentEntity`) and the mock presets.

## Not in this lane

- Mocha (API-only).
- A per-book TLS 1.0 connection option (separate lane).
- Filtering `DtlType='P'` package-parent lines.
- A per-entity allow-list of wire columns (deny-list of the ESB's own columns today, matching the DO/GRN
  feed's verbatim records).
