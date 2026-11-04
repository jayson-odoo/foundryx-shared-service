"""Vendor paths of the AutoCount hapi wrapper used by write-back (plan 55 section 2)."""

from __future__ import annotations

EDIT_PO_PATH = "/EditPurchaseOrderbydockey"
NEW_PO_PATH = "/NewPurchaseOrder"
NEW_SO_PATH = "/NewSalesOrder"
PO_BY_DOC_DATE_PATH = "/purchaseorderbydocdate"
SO_BY_DOC_DATE_PATH = "/salesorderbydocdate"
PO_BY_LAST_MODIFIED_PATH = "/purchaseorderbyLastModified"
SO_BY_LAST_MODIFIED_PATH = "/salesorderbyLastModified"

# Job id of staged rows the write flows themselves create (any other job id = a sync's rows).
STAGING_JOB_ID = "write-back"
