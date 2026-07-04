"""Import engine wire schemas (sprint-3/09). camelCase via ApiModel."""
from datetime import datetime
from typing import Any, Dict, List, Optional

from pydantic import ConfigDict, Field

from app.schemas.base import ApiModel


class ImportColumnOut(ApiModel):
    key: str
    label: str
    type: str
    required: bool
    unique: bool
    # bounded option values (enum / small reference) → in-xlsx dropdown
    options: Optional[List[Dict[str, str]]] = None
    hasResolver: bool = False


class ImportConfigOut(ApiModel):
    entityType: str
    label: str
    columns: List[ImportColumnOut]
    modes: List[str]
    contextKeys: List[str]


class ImportJobOut(ApiModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    entityType: str = Field(validation_alias="entity_type")
    mode: str
    status: str
    abortOnInvalid: bool = Field(validation_alias="abort_on_invalid")
    triggerAutomations: bool = Field(validation_alias="trigger_automations")
    sheetName: Optional[str] = Field(default=None, validation_alias="sheet_name")
    mapping: Optional[dict] = Field(default=None, validation_alias="mapping_json")
    context: Optional[dict] = Field(default=None, validation_alias="context_json")
    totalRows: int = Field(validation_alias="total_rows")
    validRows: int = Field(validation_alias="valid_rows")
    invalidRows: int = Field(validation_alias="invalid_rows")
    errors: Optional[List[dict]] = Field(default=None, validation_alias="errors_json")
    hasErrorFile: bool = False
    createdIds: Optional[List[str]] = Field(default=None, validation_alias="created_ids")
    updatedIds: Optional[List[str]] = Field(default=None, validation_alias="updated_ids")
    filesPurged: bool = Field(validation_alias="files_purged")
    createdAt: datetime = Field(validation_alias="created_at")
    finishedAt: Optional[datetime] = Field(default=None, validation_alias="finished_at")


class ImportJobListResponse(ApiModel):
    items: List[ImportJobOut]
    total: int
    page: int
    pageSize: int


class MappingRequest(ApiModel):
    mapping: Dict[str, Optional[str]]
    sheetName: Optional[str] = None
    # Job-level context chosen on the import page (e.g. Ticket mode, sprint-4/05);
    # merged into the job's context_json, whitelisted by the importer's keys.
    context: Optional[Dict[str, Any]] = None


class ImportSettingsOut(ApiModel):
    maxRows: int
    maxFileMb: int
    isDefault: bool
