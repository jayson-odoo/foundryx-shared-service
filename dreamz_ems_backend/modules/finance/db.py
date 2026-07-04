"""Finance module DB foundation (sprint-4/05, Cluster D / R3-1) — schema-isolated
metadata (``app_finance``).

The finance vertical (invoices now; payments / sales-orders / settlement extend
it in Cluster F) is its OWN module so it can be consumed by BOTH the EMS
registration stream (ticket → invoice) and the CRM quotation stream — born here
rather than re-homed later (the plan-08 churn lesson). Cross-schema refs to core
(``tenants``/``statuses``) and cross-module refs (bill-to Client = app_crm,
project = app_ems) are PLAIN indexed columns / capability soft-refs (BL-030).
Intra-``app_finance`` FKs are kept.
"""
from sqlalchemy.orm import declarative_base

FINANCE_SCHEMA = "app_finance"

FinanceBase = declarative_base()
FinanceBase.metadata.schema = FINANCE_SCHEMA
