"""EMS events (projects) routes (sprint-3/11) — instance CRUD + lifecycle
transitions + embedded participants (add-one + graph-driven transitions; bulk
registration rides the Import engine, project-scoped via context)."""
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import require_permission
from app.models.user import User
from modules.ems.schemas import (
    CheckpointIn,
    CheckpointLogListResponse,
    CheckpointLogOut,
    CheckpointOut,
    ExportRequest,
    ListResponse,
    NominateIn,
    NominateOut,
    ParticipantIn,
    ParticipantOut,
    ParticipantPatch,
    ProjectIn,
    ProjectOut,
    ProjectUpdate,
    ScanIn,
    ScanOut,
    TicketOut,
    TicketRowOut,
    TransitionIn,
    VoidRefundOut,
)
from modules.ems.services import (
    CheckpointService,
    ParticipantService,
    ProjectService,
    TicketService,
)

router = APIRouter()


@router.get("", response_model=ListResponse)
def list_projects(
    search: Optional[str] = Query(None),
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    sort_by: Optional[str] = Query(None),
    sort_dir: str = Query("desc"),
    current_user: User = Depends(require_permission("projects.read")),
    db: Session = Depends(get_db),
):
    rows, total = ProjectService(db).list(
        current_user.tenant_id, search=search, page=page, page_size=page_size,
        sort_by=sort_by, sort_dir=sort_dir,
    )
    return ListResponse(
        items=[ProjectOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("/export", response_class=PlainTextResponse)
def export_projects(
    body: ExportRequest,
    current_user: User = Depends(require_permission("projects.read")),
    db: Session = Depends(get_db),
):
    csv_text = ProjectService(db).export_csv(
        current_user.tenant_id, body.columns, ids=body.ids, search=body.search
    )
    return PlainTextResponse(csv_text, media_type="text/csv")


@router.post("", response_model=ProjectOut, status_code=201)
def create_project(
    body: ProjectIn,
    current_user: User = Depends(require_permission("projects.manage")),
    db: Session = Depends(get_db),
):
    return ProjectOut.model_validate(ProjectService(db).create(current_user.tenant_id, body.model_dump()))


@router.get("/{project_id}", response_model=ProjectOut)
def get_project(
    project_id: str,
    current_user: User = Depends(require_permission("projects.read")),
    db: Session = Depends(get_db),
):
    return ProjectOut.model_validate(ProjectService(db).get(current_user.tenant_id, project_id))


@router.patch("/{project_id}", response_model=ProjectOut)
def update_project(
    project_id: str,
    body: ProjectUpdate,
    current_user: User = Depends(require_permission("projects.manage")),
    db: Session = Depends(get_db),
):
    # exclude_unset → only the keys the caller SET (absent = keep, null = clear).
    return ProjectOut.model_validate(
        ProjectService(db).update(
            current_user.tenant_id, project_id, body.model_dump(exclude_unset=True)
        )
    )


@router.post("/{project_id}/transition", response_model=ProjectOut)
def transition_project(
    project_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("projects.manage")),
    db: Session = Depends(get_db),
):
    return ProjectOut.model_validate(
        ProjectService(db).transition(current_user.tenant_id, project_id, body.toStatusId, current_user)
    )


# ── embedded participants ────────────────────────────────────────────────────


@router.get("/{project_id}/participants", response_model=ListResponse)
def list_participants(
    project_id: str,
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("participants.read")),
    db: Session = Depends(get_db),
):
    rows, total = ParticipantService(db).list(
        current_user.tenant_id, project_id, page=page, page_size=page_size
    )
    return ListResponse(
        items=[ParticipantOut.model_validate(r) for r in rows], total=total, page=page, pageSize=page_size
    )


@router.post("/{project_id}/participants", response_model=ParticipantOut, status_code=201)
def add_participant(
    project_id: str,
    body: ParticipantIn,
    current_user: User = Depends(require_permission("participants.manage")),
    db: Session = Depends(get_db),
):
    return ParticipantOut.model_validate(
        ParticipantService(db).add(current_user.tenant_id, project_id, body.model_dump())
    )


@router.patch(
    "/{project_id}/participants/{participant_id}", response_model=ParticipantOut
)
def update_participant(
    project_id: str,
    participant_id: str,
    body: ParticipantPatch,
    current_user: User = Depends(require_permission("participants.manage")),
    db: Session = Depends(get_db),
):
    return ParticipantOut.model_validate(
        ParticipantService(db).update(
            current_user.tenant_id, project_id, participant_id, body.model_dump(exclude_unset=True)
        )
    )


@router.post(
    "/{project_id}/participants/{participant_id}/transition", response_model=ParticipantOut
)
def transition_participant(
    project_id: str,
    participant_id: str,
    body: TransitionIn,
    current_user: User = Depends(require_permission("participants.manage")),
    db: Session = Depends(get_db),
):
    return ParticipantOut.model_validate(
        ParticipantService(db).transition(
            current_user.tenant_id, project_id, participant_id, body.toStatusId, current_user
        )
    )


# ── tickets — nomination / transfer (slice 3) ────────────────────────────────


@router.get("/{project_id}/tickets", response_model=ListResponse)
def list_project_tickets(
    project_id: str,
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    search: Optional[str] = Query(None),
    current_user: User = Depends(require_permission("tickets.read")),
    db: Session = Depends(get_db),
):
    """Event-wide tickets list (BL-120) — backs the admin Tickets tab. Real
    registrations mint these; tenant-scoped + paginated, search on attendee
    name/email."""
    rows, total = TicketService(db).list_for_project(
        current_user.tenant_id, project_id, page=page, page_size=page_size, search=search
    )
    return ListResponse(
        items=[TicketRowOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        pageSize=page_size,
    )


@router.get(
    "/{project_id}/participants/{participant_id}/tickets",
    response_model=list[TicketOut],
)
def list_participant_tickets(
    project_id: str,
    participant_id: str,
    current_user: User = Depends(require_permission("tickets.read")),
    db: Session = Depends(get_db),
):
    return [
        TicketOut.model_validate(t)
        for t in TicketService(db).list_for_participant(
            current_user.tenant_id, project_id, participant_id
        )
    ]


@router.post(
    "/{project_id}/tickets/{ticket_id}/nominate", response_model=NominateOut
)
def nominate_ticket(
    project_id: str,
    ticket_id: str,
    body: NominateIn,
    current_user: User = Depends(require_permission("tickets.manage")),
    db: Session = Depends(get_db),
):
    return NominateOut.model_validate(
        TicketService(db).nominate(
            current_user.tenant_id, ticket_id, body.profileId, current_user
        )
    )


@router.post("/{project_id}/tickets/{ticket_id}/void", response_model=VoidRefundOut)
def void_ticket(
    project_id: str,
    ticket_id: str,
    current_user: User = Depends(require_permission("tickets.manage")),
    db: Session = Depends(get_db),
):
    """Void a ticket (AC-05-TKT-04): kills the QR + releases the RESERVED seat."""
    return VoidRefundOut.model_validate(
        TicketService(db).void(current_user.tenant_id, ticket_id, current_user)
    )


@router.post("/{project_id}/tickets/{ticket_id}/refund", response_model=VoidRefundOut)
def refund_ticket(
    project_id: str,
    ticket_id: str,
    current_user: User = Depends(require_permission("tickets.manage")),
    db: Session = Depends(get_db),
):
    """Refund a ticket (AC-05-TKT-04): kills the QR + releases the seat. Payment
    reversal is Cluster F — this changes the ticket + seat only."""
    return VoidRefundOut.model_validate(
        TicketService(db).refund(current_user.tenant_id, ticket_id, current_user)
    )


# ── checkpoints + scan (event-day preview; full = Cluster H) ─────────────────


@router.get("/{project_id}/checkpoints", response_model=list[CheckpointOut])
def list_checkpoints(
    project_id: str,
    current_user: User = Depends(require_permission("checkpoints.read")),
    db: Session = Depends(get_db),
):
    return [
        CheckpointOut.model_validate(c)
        for c in CheckpointService(db).list(current_user.tenant_id, project_id)
    ]


@router.post("/{project_id}/checkpoints", response_model=CheckpointOut, status_code=201)
def create_checkpoint(
    project_id: str,
    body: CheckpointIn,
    current_user: User = Depends(require_permission("checkpoints.manage")),
    db: Session = Depends(get_db),
):
    return CheckpointOut.model_validate(
        CheckpointService(db).create(current_user.tenant_id, project_id, body.model_dump())
    )


@router.get(
    "/{project_id}/checkpoints/{checkpoint_id}/logs",
    response_model=CheckpointLogListResponse,
)
def list_checkpoint_logs(
    project_id: str,
    checkpoint_id: str,
    page: int = Query(0, ge=0),
    page_size: int = Query(25, ge=1, le=200),
    current_user: User = Depends(require_permission("checkpoints.read")),
    db: Session = Depends(get_db),
):
    rows, total = CheckpointService(db).list_logs(
        current_user.tenant_id, project_id, checkpoint_id, page=page, page_size=page_size
    )
    return CheckpointLogListResponse(
        items=[CheckpointLogOut.model_validate(r) for r in rows],
        total=total,
        page=page,
        pageSize=page_size,
    )


@router.post("/{project_id}/checkpoints/{checkpoint_id}/scan", response_model=ScanOut)
def scan_ticket(
    project_id: str,
    checkpoint_id: str,
    body: ScanIn,
    current_user: User = Depends(require_permission("checkpoints.manage")),
    db: Session = Depends(get_db),
):
    return ScanOut.model_validate(
        TicketService(db).scan(
            current_user.tenant_id, checkpoint_id, body.qrToken, current_user
        )
    )
