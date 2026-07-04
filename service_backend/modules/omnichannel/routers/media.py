"""Serve local-disk media (dev StorageService adapter). S3 deployments serve
straight from the bucket/CDN — this router only backs STORAGE_BACKEND=local.
"""
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.config import settings

router = APIRouter()


@router.get("/{path:path}")
def serve_media(path: str) -> FileResponse:
    root = Path(settings.media_root).resolve()
    target = (root / path).resolve()
    # Path-traversal guard: target must be INSIDE media_root. is_relative_to is
    # robust where str.startswith is not — a sibling like /srv/media-x shares
    # the "/srv/media" string prefix but is not under /srv/media.
    if not target.is_relative_to(root) or not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(target)
