"""Public respond.io webhook intake for the continuous sync (plan 52, D5/D6).

``POST /omnichannel/migration-hooks/{sync_id}/{secret}`` - the URL secret is
the capability. The body is a HINT: only a respond.io contact id is kept, the
tick re-reads everything from the respond.io API. No respond.io call is made
here. Every authorization failure is the same uniform 404."""
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.database import get_db

from ..services.migration_sync_service import HOOK_MAX_BYTES, SyncNotFound, record_hint

router = APIRouter()


@router.post("/{sync_id}/{secret}")
async def receive_migration_hook(
    sync_id: str, secret: str, request: Request, db: Session = Depends(get_db)
):
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > HOOK_MAX_BYTES:
        raise HTTPException(413, "Payload too large")
    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > HOOK_MAX_BYTES:
            raise HTTPException(413, "Payload too large")
        chunks.append(chunk)
    try:
        # DB + Fernet work runs on a worker thread, never on the event loop.
        outcome = await run_in_threadpool(record_hint, db, sync_id, secret, b"".join(chunks))
    except SyncNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not Found")
    if outcome == "stored":
        return {"ok": True}
    return Response(status_code=status.HTTP_204_NO_CONTENT)
