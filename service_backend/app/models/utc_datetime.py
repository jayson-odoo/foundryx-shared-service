"""UTCDateTime - THE datetime column type (plan sprint-2/05, BL-012).

Postgres stores `timestamptz`; values ALWAYS read back as aware-UTC
datetimes, on every engine:

- bind: naive input is UTC by convention (legacy callers), aware input is
  converted to UTC - the stored instant is never ambiguous;
- result: SQLite (tests) drops the offset, so the result processor
  re-attaches UTC. Postgres already returns aware values.

Never declare a model column as plain `DateTime` again - naive values
poison comparisons (`TypeError: can't compare offset-naive and
offset-aware datetimes`) and serialize without an offset on the wire.
"""
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)

    def process_result_value(self, value: Optional[datetime], dialect) -> Optional[datetime]:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
