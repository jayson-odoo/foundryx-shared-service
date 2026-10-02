"""BR build write-back (PUBLIC, ``Authorization: Bearer fxb_live_...``): the crew
orchestrator appends Trace entries. Append-only: this router has no update or
delete route, and the key opens nothing else. Tenant comes from the key."""
from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.database import get_db

from ..build_auth import get_build_key
from ..models import BrBuildKey
from ..schemas import BuildEventIn, BuildEventOut
from ..services.build_handoff import BuildHandoffService

router = APIRouter()


@router.post(
    "/{br_id}/events", response_model=BuildEventOut, status_code=status.HTTP_201_CREATED
)
def append_build_event(
    br_id: str,
    body: BuildEventIn,
    key: BrBuildKey = Depends(get_build_key),
    db: Session = Depends(get_db),
) -> BuildEventOut:
    return BuildHandoffService(db).append_event(key, br_id, body)
