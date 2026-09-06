"""respond.io migration - S1 owns ``MigrationPreflightService`` (the
read-only preflight, AC-MIG-14). S2 adds ``MigrationService`` (phase
orchestration, cursor writes, cooperative abort, dry-run gate, mapping hash,
report assembly, plan §2.1) to this SAME file - kept together because S2's
service reuses this one's connection/workspace resolution helpers.
"""
import logging
from typing import Any, Dict, List, Optional

from cryptography.fernet import InvalidToken
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.models.connection import Connection
from app.secrets import decrypt_secret

from ..models import Channel
from ..repositories.migration_connection_repository import MigrationConnectionRepository
from ..respondio.channel_map import target_channel_type_for
from ..respondio.client import RespondIoClient, RespondIoError
from ..respondio.shapes import Contact, CustomField, SpaceChannel, SpaceUser
from ..schemas import (
    MigrationPreflight,
    MigrationSourceChannel,
    MigrationSourceField,
    MigrationSourceTeam,
    MigrationSourceUser,
    MigrationTargetChannel,
    MigrationTargetStage,
    WorkspaceItem,
)
from .lifecycle_service import stages_for_workspace
from .workspace_service import WorkspaceNotFound, WorkspaceService

logger = logging.getLogger(__name__)

RESPONDIO_PROVIDER = "respondio"

# A workspace with more contacts than this skips the rest of the preflight's
# distinct-lifecycle pass and reports a warning instead of walking the whole
# contact base on every "New migration" screen load - the pass is read-only
# and resumes no cursor of its own, so an unbounded walk here (unlike the real
# S2 contacts phase, which IS resumable) would make preflight itself the slow
# path on a two-year workspace. Far more than enough contacts to observe
# every DISTINCT lifecycle label a workspace actually uses in practice.
_MAX_LIFECYCLE_SCAN_CONTACTS = 2000


def _decrypt_or_none(ciphertext: str) -> Optional[Dict[str, str]]:
    if not ciphertext:
        return {}
    try:
        return decrypt_secret(ciphertext)
    except InvalidToken:
        return None


class MigrationPreflightService:
    def __init__(self, db: Session, *, client_factory=None):
        self.db = db
        self.connections = MigrationConnectionRepository(db)
        # Resolved at CALL time (never bound as a default-argument value,
        # which would capture the original classmethod at import time and
        # ignore a later `monkeypatch.setattr(migration_service,
        # "RespondIoClient", ...)`) - a test can swap the module-level
        # `RespondIoClient` name wholesale and this still picks it up.
        self._client_factory = client_factory or RespondIoClient.from_connection

    def preflight(self, tenant_id: str, connection_id: str, workspace_id: str) -> MigrationPreflight:
        connection = self._connection(tenant_id, connection_id)
        workspace = self._workspace(tenant_id, workspace_id)
        target_channels = self._target_channels(tenant_id, workspace.id)
        target_stages = self._target_stages(tenant_id, workspace.id)

        config = connection.config_json or {}
        space_label = str(config.get("spaceLabel") or "")
        warnings: List[str] = []

        credentials = _decrypt_or_none(connection.credentials_json)
        if credentials is None:
            warnings.append(
                "This connection's stored credentials can no longer be decrypted - "
                "re-enter the access token and save before running preflight again."
            )
            return self._unavailable(space_label, target_channels, target_stages, warnings)

        client = self._client_factory(config, credentials)

        try:
            raw_channels = client.list_space_channels()
        except RespondIoError as exc:
            warnings.append(self._api_unavailable_message(exc))
            return self._unavailable(space_label, target_channels, target_stages, warnings)

        channels = [
            MigrationSourceChannel(id=str(c.id), name=c.name, source=c.source)
            for c in (SpaceChannel(**row) for row in raw_channels)
        ]
        self._warn_no_compatible_target(channels, target_channels, warnings)

        try:
            raw_users = [SpaceUser(**row) for row in client.list_space_users()]
        except RespondIoError as exc:
            warnings.append(f"Could not read space users: {exc.message}")
            raw_users = []
        users = [
            MigrationSourceUser(
                id=str(u.id),
                firstName=u.firstName,
                lastName=u.lastName or "",
                email=u.email,
                role=u.role or "",
                teamId=str(u.team.id) if u.team else None,
                teamName=u.team.name if u.team else None,
            )
            for u in raw_users
        ]
        teams_by_id: Dict[str, MigrationSourceTeam] = {}
        for u in raw_users:
            if u.team is not None:
                teams_by_id.setdefault(str(u.team.id), MigrationSourceTeam(id=str(u.team.id), name=u.team.name))
        teams = sorted(teams_by_id.values(), key=lambda t: t.name.lower())

        try:
            raw_fields = [CustomField(**row) for row in client.list_custom_fields()]
        except RespondIoError as exc:
            warnings.append(f"Could not read custom fields: {exc.message}")
            raw_fields = []
        fields = [
            MigrationSourceField(id=str(f.id), name=f.name, dataType=f.dataType)
            for f in raw_fields
        ]

        lifecycles = self._distinct_lifecycles(client, config, warnings)

        return MigrationPreflight(
            apiAvailable=True,
            spaceLabel=space_label,
            channels=channels,
            users=users,
            teams=teams,
            fields=fields,
            lifecycles=lifecycles,
            targetChannels=target_channels,
            targetStages=target_stages,
            warnings=warnings,
        )

    # ── helpers ──────────────────────────────────────────────────────────

    def _connection(self, tenant_id: str, connection_id: str) -> Connection:
        connection = self.connections.get_for_provider(tenant_id, connection_id, RESPONDIO_PROVIDER)
        if connection is None:
            # Uniform 404 for a missing OR foreign-tenant id (AC-MIG-52) -
            # never distinguish "doesn't exist" from "isn't yours".
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Connection not found.")
        return connection

    def _workspace(self, tenant_id: str, workspace_id: str) -> WorkspaceItem:
        try:
            return WorkspaceService(self.db).get(workspace_id, tenant_id)
        except WorkspaceNotFound as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Workspace not found.") from exc

    def _target_channels(self, tenant_id: str, workspace_id: str) -> List[MigrationTargetChannel]:
        rows = (
            self.db.query(Channel)
            .filter(
                Channel.tenant_id == tenant_id,
                Channel.workspace_id == workspace_id,
                Channel.is_trashed.is_(False),
            )
            .order_by(Channel.name.asc())
            .all()
        )
        return [
            MigrationTargetChannel(id=c.id, name=c.name, channelType=c.channel_type)
            for c in rows
        ]

    def _target_stages(self, tenant_id: str, workspace_id: str) -> List[MigrationTargetStage]:
        return [
            MigrationTargetStage(statusId=s.id, label=s.label)
            for s in stages_for_workspace(self.db, tenant_id, workspace_id)
        ]

    def _unavailable(
        self,
        space_label: str,
        target_channels: List[MigrationTargetChannel],
        target_stages: List[MigrationTargetStage],
        warnings: List[str],
    ) -> MigrationPreflight:
        return MigrationPreflight(
            apiAvailable=False,
            spaceLabel=space_label,
            channels=[],
            users=[],
            teams=[],
            fields=[],
            lifecycles=[],
            targetChannels=target_channels,
            targetStages=target_stages,
            warnings=warnings,
        )

    @staticmethod
    def _api_unavailable_message(exc: RespondIoError) -> str:
        if exc.status_code == 401:
            return "respond.io rejected this access token."
        if exc.status_code == 403:
            return (
                "This workspace's respond.io plan does not include the Developer "
                "API (Growth plan or above required) - use the CSV import path instead."
            )
        return f"Could not reach respond.io ({exc.message})."

    @staticmethod
    def _warn_no_compatible_target(
        channels: List[MigrationSourceChannel],
        target_channels: List[MigrationTargetChannel],
        warnings: List[str],
    ) -> None:
        target_types = {c.channelType for c in target_channels}
        for c in channels:
            mapped = target_channel_type_for(c.source)
            if mapped is None or mapped not in target_types:
                warnings.append(
                    f'No connected channel in the target workspace matches source '
                    f'channel "{c.name}" ({c.source}) - it will be skipped.'
                )

    def _distinct_lifecycles(
        self, client: RespondIoClient, config: Dict[str, Any], warnings: List[str]
    ) -> List[str]:
        timezone = str(config.get("timezone") or "")
        seen: Dict[str, None] = {}
        try:
            for contact_index, row in enumerate(client.list_contacts(timezone=timezone)):
                if contact_index >= _MAX_LIFECYCLE_SCAN_CONTACTS:
                    warnings.append(
                        "Lifecycle preview stopped early after scanning the first "
                        f"{_MAX_LIFECYCLE_SCAN_CONTACTS} contacts - unmapped labels "
                        "found on a later contact are still allowed and reported as a "
                        "blocker on that contact's dry run."
                    )
                    break
                contact = Contact(**row)
                if contact.lifecycle:
                    seen.setdefault(contact.lifecycle, None)
        except RespondIoError as exc:
            warnings.append(f"Could not preview source lifecycle labels: {exc.message}")
            return []
        return sorted(seen.keys())
