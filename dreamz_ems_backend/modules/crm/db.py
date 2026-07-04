"""CRM module DB foundation (sprint-4/08) — schema-isolated metadata (``app_crm``).

The commercial CRM vertical (clients, leads, quotations) split out of EMS so it
installs independently of events. Separate declarative base keeps its tables out
of core's ``Base.metadata``. Cross-schema refs to core (``tenants``, ``statuses``)
and to the core catalog (``products``) are PLAIN indexed columns, NOT DB FKs
(BL-030) — integrity for product-in-quotation is enforced by the catalog
reference-guard + service validation. Cross-module refs to EMS (``projects``) are
soft-refs resolved via capability. Intra-``app_crm`` FKs are kept.
"""
from sqlalchemy.orm import declarative_base

CRM_SCHEMA = "app_crm"

CrmBase = declarative_base()
CrmBase.metadata.schema = CRM_SCHEMA
