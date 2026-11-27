"""Signed result links ``/planner3d/files/{file id}?exp=&sig=`` (contract 3.1).

``"public": true``: no key and no session - the HMAC signature over the file id and
expiry IS the authorisation (``services/signed_files.py``). Served as an attachment
with ``Content-Security-Policy: sandbox`` + ``nosniff``; links expire, so nothing is
cached publicly. HTTP only.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from app.database import get_db

from ..services import gateway_service
from ..services.errors import P3Error

router = APIRouter()


@router.get("/{file_id}")
def get_file(
    file_id: str,
    exp: int = Query(...),
    sig: str = Query(..., max_length=128),
    db: Session = Depends(get_db),
) -> Response:
    try:
        data, mime, name = gateway_service.signed_file(db, file_id, exp, sig)
    except P3Error:
        raise HTTPException(status_code=404, detail="Not found.")
    headers = {
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
        "Cache-Control": "private, max-age=300",
        "Content-Disposition": f'attachment; filename="{name}"',
    }
    return Response(content=data, media_type=mime, headers=headers)
