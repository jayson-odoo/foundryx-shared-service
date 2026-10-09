"""Housekeeping for the connector (wired into the beat by S5)."""
from datetime import datetime

from sqlalchemy.orm import Session


def prune(db: Session, now: datetime) -> None:  # filled by S4/S5 (idle expiry, call_log retention)
    return None
