"""Planner 3D module DB foundation - schema-isolated metadata (``app_planner3d``).
A separate declarative base keeps these tables out of core's ``Base.metadata``.
Mirrors ``modules/lead_capture/db.py``."""

from __future__ import annotations
from sqlalchemy.orm import declarative_base

PLANNER3D_SCHEMA = "app_planner3d"

Planner3dBase = declarative_base()
Planner3dBase.metadata.schema = PLANNER3D_SCHEMA
