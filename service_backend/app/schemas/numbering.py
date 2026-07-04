"""Numbering wire schemas (sprint-4/07). camelCase via ApiModel."""
from typing import List, Optional

from pydantic import ConfigDict, Field, field_validator

from app.numbering.registry import RESET_PERIODS

MAX_PREFIX_LEN = 24
MAX_FORMAT_LEN = 120

from app.schemas.base import ApiModel


class NumberCatalogItem(ApiModel):
    """One registered NumberSequenceDef + its current override + live next-val
    (for the current period) — drives the settings list."""

    model_config = ConfigDict(from_attributes=True)

    docType: str
    label: str
    module: str
    defaultPrefix: str
    defaultFormat: str
    defaultReset: str
    # Present only when the tenant has overridden this doc type.
    overridePrefix: Optional[str] = None
    overrideFormat: Optional[str] = None
    overrideReset: Optional[str] = None
    # The resolved (override-or-default) effective values.
    prefix: str
    formatPattern: str
    reset: str
    # The next running number that will be handed out for the current period.
    nextVal: int
    # A live sample of the next number that would be generated.
    sample: str


class NumberFormatSetRequest(ApiModel):
    """Upsert a tenant override (AC-07-07). Reset is whitelisted."""

    prefix: str = Field(default="", max_length=MAX_PREFIX_LEN)
    formatPattern: str = Field(min_length=1, max_length=MAX_FORMAT_LEN)
    reset: str

    @field_validator("reset")
    @classmethod
    def _valid_reset(cls, v: str) -> str:
        if v not in RESET_PERIODS:
            raise ValueError(f"reset must be one of {RESET_PERIODS}")
        return v

    @field_validator("formatPattern")
    @classmethod
    def _format_has_running(cls, v: str) -> str:
        # The format MUST contain the running counter token {N…} or every
        # generated number collides — foolproof-UI guard at the boundary.
        if "{N" not in v:
            raise ValueError("format must contain a running-number token like {NNNN}")
        return v


class NumberNextValRequest(ApiModel):
    """Set the next running value for the CURRENT period (AC-07-07)."""

    nextVal: int = Field(ge=1)


class ListResponse(ApiModel):
    items: List[NumberCatalogItem]
