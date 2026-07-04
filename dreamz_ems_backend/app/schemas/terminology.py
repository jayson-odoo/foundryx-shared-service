"""Terminology wire schemas (sprint-3/08). camelCase via ApiModel."""
from typing import Dict, Optional

from pydantic import ConfigDict, Field, field_validator

from app.schemas.base import ApiModel

# Display labels are short; cap to keep menus/titles sane.
MAX_LABEL_LEN = 60


class TermLabels(ApiModel):
    singular: str
    plural: str


class TermSetRequest(ApiModel):
    """Both forms required + non-blank (D3 — no auto-pluralize)."""

    singular: str = Field(min_length=1, max_length=MAX_LABEL_LEN)
    plural: str = Field(min_length=1, max_length=MAX_LABEL_LEN)

    @field_validator("singular", "plural")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class TermCatalogItem(ApiModel):
    """One registered TermDef + its current override (drives the settings page)."""

    model_config = ConfigDict(from_attributes=True)

    key: str
    module: str
    group: Optional[str] = None
    description: Optional[str] = None
    defaultSingular: str
    defaultPlural: str
    # Present only when the tenant has overridden this key.
    overrideSingular: Optional[str] = None
    overridePlural: Optional[str] = None
    # The resolved (override-or-default) labels for convenience.
    singular: str
    plural: str


# The merged map GET /terminology returns: {key: {singular, plural}}.
TerminologyMap = Dict[str, TermLabels]
