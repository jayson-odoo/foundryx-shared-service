"""Lead Capture module DB foundation - schema-isolated metadata
(``app_lead_capture``). A separate declarative base keeps these tables out of
core's ``Base.metadata``. Mirrors ``modules/connector/db.py``."""

from __future__ import annotations
from sqlalchemy.orm import declarative_base

LEAD_CAPTURE_SCHEMA = "app_lead_capture"

LeadCaptureBase = declarative_base()
LeadCaptureBase.metadata.schema = LEAD_CAPTURE_SCHEMA
