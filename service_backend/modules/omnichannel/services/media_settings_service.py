"""Per-workspace media caps (plan 12 §Locked D12, AC-12-12/23).

Resolution: the workspace's own ``omnichannel_settings`` row → the tenant default
(``workspace_id IS NULL``) → Meta's hard ceiling. Every configured value is
CLAMPED to ``min(configured, Meta ceiling)`` at resolve time so a stored value
can never exceed Meta's hard cap. Accepted mimes are fixed (not tenant-editable).
"""
from typing import Dict, Optional

from sqlalchemy.orm import Session

from ..models import OmnichannelSettings
from .media_pipeline import ACCEPTED_MIMES, META_CEILINGS

# Column suffix per media kind (image/video/audio/voice map — voice shares audio).
_COL_FOR_KIND = {
    "IMAGE": "image_max_bytes",
    "VIDEO": "video_max_bytes",
    "AUDIO": "audio_max_bytes",
    "VOICE": "audio_max_bytes",
    "DOCUMENT": "document_max_bytes",
    "STICKER": "sticker_max_bytes",
}


class MediaSettingsService:
    def __init__(self, db: Session):
        self.db = db

    def _row(self, tenant_id: str, workspace_id: Optional[str]) -> Optional[OmnichannelSettings]:
        return (
            self.db.query(OmnichannelSettings)
            .filter(
                OmnichannelSettings.tenant_id == tenant_id,
                OmnichannelSettings.workspace_id == workspace_id,
            )
            .first()
        )

    def _resolve_row(self, tenant_id: str, workspace_id: Optional[str]) -> Optional[OmnichannelSettings]:
        row = self._row(tenant_id, workspace_id) if workspace_id else None
        if row is not None:
            return row
        return self._row(tenant_id, None)  # tenant default

    def max_bytes_for(self, tenant_id: str, workspace_id: Optional[str], kind: str) -> int:
        """Effective cap for ``kind`` = min(configured, Meta ceiling)."""
        kind = (kind or "").upper()
        ceiling = META_CEILINGS.get(kind, 0)
        row = self._resolve_row(tenant_id, workspace_id)
        configured = getattr(row, _COL_FOR_KIND.get(kind, ""), None) if row else None
        if configured is None:
            return ceiling
        return min(int(configured), ceiling)

    def effective(self, tenant_id: str, workspace_id: Optional[str]) -> Dict[str, dict]:
        """The resolved caps + accepted mimes per kind (for the settings UI)."""
        out: Dict[str, dict] = {}
        for kind in META_CEILINGS:
            out[kind] = {
                "maxBytes": self.max_bytes_for(tenant_id, workspace_id, kind),
                "ceilingBytes": META_CEILINGS[kind],
                "acceptedMimes": sorted(ACCEPTED_MIMES[kind]),
            }
        return out

    def get_overrides(self, tenant_id: str, workspace_id: Optional[str]) -> Dict[str, Optional[int]]:
        row = self._row(tenant_id, workspace_id)
        return {
            "imageMaxBytes": row.image_max_bytes if row else None,
            "videoMaxBytes": row.video_max_bytes if row else None,
            "audioMaxBytes": row.audio_max_bytes if row else None,
            "documentMaxBytes": row.document_max_bytes if row else None,
            "stickerMaxBytes": row.sticker_max_bytes if row else None,
        }

    def set_overrides(
        self, tenant_id: str, workspace_id: Optional[str], overrides: Dict[str, Optional[int]]
    ) -> Dict[str, Optional[int]]:
        """Upsert per-type overrides. Values are stored as-is (clamped at read),
        None clears the override. Idempotent."""
        row = self._row(tenant_id, workspace_id)
        if row is None:
            row = OmnichannelSettings(tenant_id=tenant_id, workspace_id=workspace_id)
            self.db.add(row)
        for wire_key, col in (
            ("imageMaxBytes", "image_max_bytes"),
            ("videoMaxBytes", "video_max_bytes"),
            ("audioMaxBytes", "audio_max_bytes"),
            ("documentMaxBytes", "document_max_bytes"),
            ("stickerMaxBytes", "sticker_max_bytes"),
        ):
            if wire_key in overrides:
                val = overrides[wire_key]
                setattr(row, col, int(val) if val is not None else None)
        self.db.commit()
        self.db.refresh(row)
        return self.get_overrides(tenant_id, workspace_id)
