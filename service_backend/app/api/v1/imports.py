"""Import engine routes (sprint-3/09, F8). Thin: validate, delegate, shape HTTP.

Import is gated by the ENTITY's write perm (no new per-entity key, D12); the
cross-actor history view needs ``imports.read_all`` (else own jobs only). No DB
logic here (house rule); ImportService owns it.
"""
from typing import Optional

from fastapi import (
    APIRouter,
    Depends,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
)
from fastapi.responses import StreamingResponse
import io
import json

from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import (
    effective_permission_keys,
    get_current_user,
    require_permission,
)
from app.import_engine.registry import get_importer
from app.models.import_job import IMPORT_MODES, MODE_CREATE_ONLY
from app.models.user import User
from app.schemas.base import ApiModel
from app.schemas.import_engine import (
    ImportColumnOut,
    ImportConfigOut,
    ImportJobListResponse,
    ImportJobOut,
    ImportSettingsOut,
    MappingRequest,
)
from app.import_engine.service import ImportService

router = APIRouter()

# Cap a single read so an oversize body is never buffered unbounded (D14). The
# hard cap is re-checked against the tenant's settings inside the service.
_MAX_UPLOAD = 64 * 1024 * 1024


def _require_entity_write(entity_type: str, user: User, db: Session) -> None:
    importer = get_importer(entity_type)
    if importer is None:
        raise HTTPException(404, f"No importer for '{entity_type}'.")
    # active_modules filter (plan sprint-3/10 D2): a module's importer is hidden
    # for a tenant without that module active.
    from app.module_platform.active import active_modules, is_visible

    if not is_visible(importer.module, active_modules(db, user.tenant_id)):
        raise HTTPException(404, f"No importer for '{entity_type}'.")
    perm = importer.write_permission
    if perm and perm not in effective_permission_keys(user):
        raise HTTPException(403, f"Missing permission: {perm}")


def _job_out(job, *, include_errors: bool = True) -> ImportJobOut:
    out = ImportJobOut.model_validate(job)
    out.hasErrorFile = bool(job.error_report_key) and not job.files_purged
    if not include_errors:
        out.errors = None
    return out


@router.get("/config/{entity_type}", response_model=ImportConfigOut)
def get_config(
    entity_type: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_entity_write(entity_type, current_user, db)
    importer = get_importer(entity_type)
    cols = []
    for c in importer.columns:
        opts = c.options if isinstance(c.options, list) else None
        cols.append(
            ImportColumnOut(
                key=c.key,
                label=c.label,
                type=c.type,
                required=c.required,
                unique=c.unique,
                options=opts,
                hasResolver=c.resolver is not None,
            )
        )
    return ImportConfigOut(
        entityType=entity_type,
        label=importer.label,
        columns=cols,
        modes=list(IMPORT_MODES),
        contextKeys=list(importer.context_keys),
    )


@router.get("/template/{entity_type}")
def get_template(
    entity_type: str,
    columns: str = Query("", description="comma-separated optional column keys"),
    format: str = Query("xlsx"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_entity_write(entity_type, current_user, db)
    chosen = [c for c in columns.split(",") if c]
    content, mime, ext = ImportService(db).build_template(entity_type, chosen, format)
    return StreamingResponse(
        io.BytesIO(content),
        media_type=mime,
        headers={"Content-Disposition": f'attachment; filename="{entity_type}-import-template.{ext}"'},
    )


class ImportSettingsRequest(ApiModel):
    maxRows: Optional[int] = None
    maxFileMb: Optional[int] = None


# NOTE: defined BEFORE /{job_id} so "settings" isn't swallowed as a job id.
@router.get("/settings", response_model=ImportSettingsOut)
def get_import_settings(
    current_user: User = Depends(require_permission("imports.read_all")),
    db: Session = Depends(get_db),
):
    return ImportSettingsOut(**ImportService(db).get_settings(current_user.tenant_id))


@router.put("/settings", response_model=ImportSettingsOut)
def set_import_settings(
    body: ImportSettingsRequest,
    current_user: User = Depends(require_permission("imports.read_all")),
    db: Session = Depends(get_db),
):
    return ImportSettingsOut(
        **ImportService(db).set_settings(current_user.tenant_id, body.maxRows, body.maxFileMb)
    )


@router.post("", response_model=dict, status_code=201)
async def create_import(
    file: UploadFile,
    entityType: str = Form(...),
    mode: str = Form(MODE_CREATE_ONLY),
    abortOnInvalid: bool = Form(False),
    triggerAutomations: bool = Form(False),
    context: Optional[str] = Form(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_entity_write(entityType, current_user, db)
    content = await file.read(_MAX_UPLOAD + 1)
    if len(content) > _MAX_UPLOAD:
        raise HTTPException(413, "File too large.")
    ctx = json.loads(context) if context else None
    ext_hint = (file.filename or "").rsplit(".", 1)[-1].lower() if file.filename else ""
    job = ImportService(db).create_job(
        tenant_id=current_user.tenant_id,
        actor_user_id=current_user.id,
        entity_type=entityType,
        mode=mode,
        abort_on_invalid=abortOnInvalid,
        trigger_automations=triggerAutomations,
        context=ctx,
        content=content,
        ext_hint=ext_hint,
    )
    return {"jobId": job.id}


@router.get("/{job_id}/preview", response_model=dict)
def preview(
    job_id: str,
    sheet: Optional[str] = Query(None),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = ImportService(db).get_job(current_user.tenant_id, job_id)
    _require_entity_write(job.entity_type, current_user, db)
    return ImportService(db).preview(current_user.tenant_id, job_id, sheet)


@router.put("/{job_id}/mapping", response_model=ImportJobOut)
def set_mapping(
    job_id: str,
    body: MappingRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = ImportService(db).get_job(current_user.tenant_id, job_id)
    _require_entity_write(job.entity_type, current_user, db)
    job = ImportService(db).set_mapping(
        current_user.tenant_id, job_id, body.mapping, body.sheetName, context=body.context
    )
    return _job_out(job)


class CommitRequest(ApiModel):
    abortOnInvalid: Optional[bool] = None
    triggerAutomations: Optional[bool] = None
    context: Optional[dict] = None


@router.post("/{job_id}/commit", response_model=ImportJobOut)
def commit(
    job_id: str,
    body: Optional[CommitRequest] = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = ImportService(db).get_job(current_user.tenant_id, job_id)
    _require_entity_write(job.entity_type, current_user, db)
    opts = body or CommitRequest()
    job = ImportService(db).commit_job(
        current_user.tenant_id,
        job_id,
        abort_on_invalid=opts.abortOnInvalid,
        trigger_automations=opts.triggerAutomations,
        context=opts.context,
    )
    return _job_out(job)


@router.get("/{job_id}/errors-file")
def errors_file(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    content, filename = ImportService(db).error_file(current_user.tenant_id, job_id)
    return StreamingResponse(
        io.BytesIO(content),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{job_id}", response_model=ImportJobOut)
def get_job(
    job_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    job = ImportService(db).get_job(current_user.tenant_id, job_id)
    return _job_out(job)


@router.get("", response_model=ImportJobListResponse)
def list_jobs(
    entityType: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    # Own jobs only unless imports.read_all (cross-actor history, D12).
    actor = None if "imports.read_all" in effective_permission_keys(current_user) else current_user.id
    rows, total = ImportService(db).list_jobs(
        current_user.tenant_id,
        actor_user_id=actor,
        entity_type=entityType,
        status=status,
        page=page,
        page_size=page_size,
    )
    return ImportJobListResponse(
        items=[_job_out(r, include_errors=False) for r in rows],
        total=total,
        page=page,
        pageSize=page_size,
    )
