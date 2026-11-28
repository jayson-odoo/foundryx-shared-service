"""Dashboards module DB foundation - schema-isolated metadata (``app_dashboards``).
A separate declarative base keeps these tables out of core's ``Base.metadata``.
Mirrors ``modules/planner3d/db.py``."""

from __future__ import annotations
from sqlalchemy.orm import declarative_base

DASHBOARDS_SCHEMA = "app_dashboards"

DashboardsBase = declarative_base()
DashboardsBase.metadata.schema = DASHBOARDS_SCHEMA
