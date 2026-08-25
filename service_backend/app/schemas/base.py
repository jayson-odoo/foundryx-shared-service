"""ApiModel - shared wire-schema base (plan sprint-2/05, BL-012).

ONE place that guarantees every datetime leaves the API as Z-suffixed UTC
ISO-8601, whatever a field is named. Columns are aware-UTC (UTCDateTime)
so pydantic would already emit `Z`; this serializer is the defensive net
for any naive value that sneaks through a computed field.

Every schema with a datetime field inherits this instead of BaseModel.

Caveat: the wildcard serializer sees TOP-LEVEL field values only. A nested
ApiModel re-applies it, but a `List[datetime]` / `Dict[..., datetime]`
field would bypass the net (aware-UTC values still emit `Z` via pydantic;
only NAIVE nested values could leak offset-less). No such field exists
today - if you add one, give it its own field_serializer.
"""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, SerializerFunctionWrapHandler, field_serializer


class ApiModel(BaseModel):
    @field_serializer("*", mode="wrap", when_used="json")
    def _serialize_datetimes_utc_z(
        self, value: Any, handler: SerializerFunctionWrapHandler
    ) -> Any:
        if isinstance(value, datetime):
            aware = (
                value.replace(tzinfo=timezone.utc)  # naive = UTC by convention
                if value.tzinfo is None
                else value.astimezone(timezone.utc)
            )
            return aware.isoformat().replace("+00:00", "Z")
        return handler(value)
