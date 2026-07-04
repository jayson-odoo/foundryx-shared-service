"""View-preferences schema (per-user column order/width/visibility) + the
profile-level preferences doc (timezone, plan sprint-2/05)."""
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel, field_validator

from app.schemas.base import ApiModel


class ViewPreferenceData(BaseModel):
    order: List[str] = []
    widths: Dict[str, float] = {}
    hidden: List[str] = []


class ProfilePreferences(ApiModel):
    """PATCH /me/preferences — user-level display preferences. `timezone` is
    an IANA name (validated against the host tz database); null clears it
    (= render in the browser tz)."""

    timezone: Optional[str] = None

    @field_validator("timezone")
    @classmethod
    def _known_iana_zone(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        try:
            ZoneInfo(value)
        except Exception:
            raise ValueError(f"Unknown timezone: {value!r} (use an IANA name).")
        return value
