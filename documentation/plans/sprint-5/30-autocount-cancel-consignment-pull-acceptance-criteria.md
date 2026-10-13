# 30 - AutoCount cancel / consignment pull - acceptance criteria (DRAFT)

Lane AC-CANCEL-PULL. Status: draft, filled in as the slice lands.

Scope: the `sql_db` source pulls four more AutoCount document types for the SORENTO book
(Cancel SO `XS/XSDTL`, Cancel PO `XP/XPDTL`, Consignment `Consignment/ConsignmentDTL`,
Consignment Return `ConsignmentReturn/ConsignmentReturnDTL`) and pushes them to the CRM,
gated on CRM contract 2.8.
