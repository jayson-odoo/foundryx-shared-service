"""Tenant administration business logic (plan 07 §4/§7/§9).

Owns the rules: slug validation/reservation, the platform-tenant guard, and
provisioning (tenant + seeded roles + first admin user in ONE transaction).
Lifecycle moves go through the STATUS MACHINE (sprint-2/01) - a transition is
only possible along a defined edge of the tenant entity's graph; behavior
binds to status trait flags, never to a category enum.
Routers translate outcomes to HTTP; the repository does the SQL.
"""
import csv
import io
from typing import Dict, List, Optional, Tuple

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.status import Status, TENANT_ENTITY
from app.models.tenant import (
    RESERVED_TENANT_SLUGS,
    Tenant,
    is_valid_tenant_slug,
)
from app.models.user import User, UserStatus
from app.repositories.tenant_repository import TenantRepository
from app.schemas.filters import FilterGroup
from app.security import hash_password
from app.services import status_machine
from app.services.filter_translator import translate_filter
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)

# Whitelisted filter columns for the tenants list (field -> column). The list
# query always joins Status, so the category column is directly filterable.
_TENANT_FILTER_COLUMNS = {
    "tenant": Tenant.name,
    "name": Tenant.name,
    "slug": Tenant.slug,
    "status": Status.category,
    "contactEmail": Tenant.contact_email,
    "created": Tenant.created_at,
}


class TenantServiceError(Exception):
    """Base class for tenant domain errors."""


class TenantNotFound(TenantServiceError):
    pass


class SlugInvalid(TenantServiceError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class SlugTaken(TenantServiceError):
    pass


class DomainTaken(TenantServiceError):
    """custom_domain is unique across tenants (BL-034)."""


class PlatformTenantProtected(TenantServiceError):
    """Lifecycle actions never apply to the platform tenant."""


class InvalidTransition(TenantServiceError):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class AdminEmailTaken(TenantServiceError):
    """Provisioning admin email already exists in the new tenant (race only)."""


class TenantNotArchived(TenantServiceError):
    """Hard delete requires the archived state first (two-step safety)."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class PurgeConfirmMismatch(TenantServiceError):
    """The typed slug confirmation didn't match (same UX as module uninstall)."""


class TenantService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TenantRepository(db)
        # Lifecycle status rows - loaded lazily; read-only paths (list/get/
        # export) never need them, so they shouldn't pay the query.
        self._status_by_key: Optional[Dict[str, Status]] = None

    def _status(self, key: str) -> Status:
        if self._status_by_key is None:
            self._status_by_key = {
                s.key: s
                for s in self.db.query(Status)
                .filter(Status.entity_type == TENANT_ENTITY, Status.tenant_id.is_(None))
                .all()
            }
        if key not in self._status_by_key:
            raise TenantServiceError(
                f"Tenant lifecycle status '{key}' is not seeded - run bootstrap."
            )
        return self._status_by_key[key]

    def _initial_status(self) -> Status:
        """Where new tenants start - the set's is_default flag (D2), with the
        seeded "active" key as a defensive fallback."""
        row = (
            self.db.query(Status)
            .filter(
                Status.entity_type == TENANT_ENTITY,
                Status.tenant_id.is_(None),
                Status.is_default.is_(True),
            )
            .first()
        )
        return row or self._status("active")

    # ---- reads ----

    def list(
        self,
        *,
        page: int = 0,
        page_size: int = 25,
        status_view: str = "active",
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[List[Tenant], int]:
        clause = translate_filter(filter_group, _TENANT_FILTER_COLUMNS)
        return self.repo.paginate(
            page=page,
            page_size=page_size,
            status_view=status_view,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=clause,
        )

    def get(self, tenant_id: str) -> Tenant:
        tenant = self.repo.get_by_id(tenant_id)
        if tenant is None:
            raise TenantNotFound()
        return tenant

    def get_at(
        self,
        index: int,
        *,
        status_view: str = "active",
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> Tuple[Optional[Tenant], int]:
        rows, total = self.list(
            page=max(index, 0),
            page_size=1,
            status_view=status_view,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
        )
        return (rows[0] if rows else None), total

    def user_counts(self, tenant_ids: List[str]) -> Dict[str, int]:
        return self.repo.user_counts(tenant_ids)

    # ---- slug rules (plan 07 §4) ----

    def validate_slug(self, slug: str) -> str:
        slug = slug.strip().lower()
        if not is_valid_tenant_slug(slug):
            raise SlugInvalid(
                "Slug must be lowercase letters/numbers with single hyphens (3-63 chars)."
            )
        if slug in RESERVED_TENANT_SLUGS:
            raise SlugInvalid(f'"{slug}" is a reserved slug.')
        if self.repo.get_by_slug(slug) is not None:
            raise SlugTaken()
        return slug

    # ---- provisioning (plan 07 §7) ----

    def provision(
        self,
        *,
        name: str,
        slug: str,
        contact_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        notes: Optional[str] = None,
        admin_name: str,
        admin_email: str,
        admin_password: str,
    ) -> Tenant:
        """Create tenant + seeded system roles + first admin - ONE transaction.

        Any failure rolls back the whole provision (no half-provisioned
        tenants). Self-signup (BL-032) calls this same path later.
        """
        from app.seed import seed_tenant_roles  # local import: seed imports models

        slug = self.validate_slug(slug)
        try:
            tenant = Tenant(
                name=name,
                slug=slug,
                status_id=self._initial_status().id,
                is_platform=False,
                contact_name=contact_name,
                contact_email=contact_email,
                notes=notes,
            )
            self.repo.add(tenant)

            roles_by_name = seed_tenant_roles(self.db, tenant.id)

            admin = User(
                tenant_id=tenant.id,
                email=admin_email.strip().lower(),
                password=hash_password(admin_password),
                name=admin_name,
                status=UserStatus.ACTIVE.value,
            )
            admin.roles = [roles_by_name["Admin"]]
            self.db.add(admin)
            self.db.flush()

            # Tenant is platform-owned - operator workflows watching tenant
            # creation live in the platform tenant (slice 09).
            from app.models.tenant import PLATFORM_TENANT_ID
            from app.workflow_engine.entity_events import emit_entity_event

            emit_entity_event(self.db, "tenant", "created", tenant, tenant_id=PLATFORM_TENANT_ID)
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise
        self.db.refresh(tenant)
        return tenant

    # ---- updates + lifecycle (plan 07 §4) ----

    def update(
        self,
        tenant_id: str,
        *,
        name: Optional[str] = None,
        contact_name: Optional[str] = None,
        contact_email: Optional[str] = None,
        custom_domain: Optional[str] = None,
        notes: Optional[str] = None,
        fields_set: Optional[set] = None,
    ) -> Tenant:
        tenant = self.get(tenant_id)
        fields_set = fields_set or set()
        if name is not None:
            tenant.name = name
        if "contactName" in fields_set:
            tenant.contact_name = contact_name
        if "contactEmail" in fields_set:
            tenant.contact_email = contact_email
        if "customDomain" in fields_set:
            tenant.custom_domain = custom_domain or None
        if "notes" in fields_set:
            tenant.notes = notes
        try:
            return self.repo.save(tenant)
        except IntegrityError:
            # custom_domain is unique across tenants.
            self.db.rollback()
            raise DomainTaken()

    def _guarded(self, tenant_id: str) -> Tenant:
        tenant = self.get(tenant_id)
        if tenant.is_platform:
            raise PlatformTenantProtected()
        return tenant

    def _transition_to(self, tenant: Tenant, to_status: Status, actor: Optional[User]) -> Tenant:
        """One path for every lifecycle move - the strict edge graph (D4)."""
        try:
            status_machine.transition(
                self.db, TENANT_ENTITY, tenant, to_status.id, actor=actor
            )
        except (
            TransitionNotAllowed,
            TransitionForbidden,
            TransitionConditionsNotMet,
        ) as exc:
            raise InvalidTransition(exc.message)
        self.db.refresh(tenant)
        return tenant

    def transition(self, tenant_id: str, transition_id: str, actor: Optional[User]) -> Tenant:
        """Fire an explicit graph edge (generic transition endpoint)."""
        from app.repositories.status_transition_repository import (
            StatusTransitionRepository,
        )

        tenant = self._guarded(tenant_id)
        edge = StatusTransitionRepository(self.db).get_by_id(transition_id)
        if edge is None or edge.entity_type != TENANT_ENTITY or edge.tenant_id is not None:
            raise InvalidTransition("Unknown transition.")
        try:
            status_machine.transition(
                self.db, TENANT_ENTITY, tenant, edge.to_status_id, actor=actor
            )
        except (
            TransitionNotAllowed,
            TransitionForbidden,
            TransitionConditionsNotMet,
        ) as exc:
            raise InvalidTransition(exc.message)
        self.db.refresh(tenant)
        return tenant

    def available_transitions(self, tenant_id: str, actor: Optional[User]):
        tenant = self.get(tenant_id)
        if tenant.is_platform:
            return []
        return status_machine.available_transitions(
            self.db, TENANT_ENTITY, tenant, actor=actor
        )

    def available_transition_ids(
        self, tenants: List[Tenant], actor: Optional[User]
    ) -> Optional[Dict[str, List[str]]]:
        """Per-record fireable edge ids for list/detail rows (sprint-2/02 D6 -
        rule-blocked actions hide per record). Thin wrapper over the GENERIC
        engine helper (code-review fix: batched, reusable by every adopting
        entity); only the platform-tenant exclusion is tenant-specific."""
        mapping = status_machine.fireable_edge_ids(
            self.db, TENANT_ENTITY, tenants, actor=actor
        )
        if mapping is None:
            return None
        for tenant in tenants:
            if tenant.is_platform:
                mapping[tenant.id] = []
        return mapping

    def purge(self, tenant_id: str, confirm_slug: str) -> None:
        """Hard-delete an ARCHIVED tenant + every row it owns (BL-035).

        Two-step safety: archive first (reversible since sprint-2/02), then
        purge (irreversible, typed-slug confirm - module-uninstall UX).
        Installed modules' ``uninstall_tenant`` hooks wipe their app_* schema
        rows (the certification contract); core rows cascade here. Future
        business data ("transactions") should add its own guard the same way
        modules do - refuse in the hook, the purge aborts atomically.
        """
        tenant = self.get(tenant_id)
        if tenant.is_platform:
            raise PlatformTenantProtected()
        if confirm_slug != tenant.slug:
            raise PurgeConfirmMismatch()
        if not (tenant.status and tenant.status.is_archived):
            raise TenantNotArchived(
                "Only archived tenants can be deleted - archive it first."
            )

        from app.models.impersonation import ImpersonationSession
        from app.models.invite_token import InviteToken
        from app.models.connection import Connection
        from app.models.email_outbox import EmailOutbox
        from app.models.notification_spec import (
            NotificationRecipient as SpecRecipient,
            NotificationSpec,
            notification_spec_transitions,
        )
        from app.models.permission import role_permissions
        from app.models.role import Role, user_roles
        from app.models.status_transition import StatusTransition, transition_roles
        from app.models.view_preference import UserViewPreference
        from app.services.app_store_service import AppStoreService

        db = self.db

        # Modules first - their hooks own the app_* schema rows. ONE teardown
        # definition lives in the store service (code-review fix).
        AppStoreService(db).remove_all_tenant_modules(tenant_id)

        # Core rows, FK-safe order (children → parents).
        user_ids = [
            row[0]
            for row in db.query(User.id).filter(User.tenant_id == tenant_id).all()
        ]
        if user_ids:
            db.query(ImpersonationSession).filter(
                ImpersonationSession.admin_user_id.in_(user_ids)
                | ImpersonationSession.target_user_id.in_(user_ids)
            ).delete(synchronize_session=False)
            db.query(InviteToken).filter(InviteToken.user_id.in_(user_ids)).delete(
                synchronize_session=False
            )
            db.query(UserViewPreference).filter(
                UserViewPreference.user_id.in_(user_ids)
            ).delete(synchronize_session=False)
        db.execute(user_roles.delete().where(user_roles.c.tenant_id == tenant_id))
        db.execute(
            role_permissions.delete().where(role_permissions.c.tenant_id == tenant_id)
        )
        db.query(User).filter(User.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        db.execute(
            transition_roles.delete().where(transition_roles.c.tenant_id == tenant_id)
        )
        db.query(Role).filter(Role.tenant_id == tenant_id).delete(
            synchronize_session=False
        )

        # Status-engine fork (statuses + edges + notification specs).
        spec_ids = [
            row[0]
            for row in db.query(NotificationSpec.id)
            .filter(NotificationSpec.tenant_id == tenant_id)
            .all()
        ]
        if spec_ids:
            db.query(SpecRecipient).filter(SpecRecipient.spec_id.in_(spec_ids)).delete(
                synchronize_session=False
            )
            db.execute(
                notification_spec_transitions.delete().where(
                    notification_spec_transitions.c.spec_id.in_(spec_ids)
                )
            )
            db.query(NotificationSpec).filter(
                NotificationSpec.id.in_(spec_ids)
            ).delete(synchronize_session=False)
        db.query(StatusTransition).filter(
            StatusTransition.tenant_id == tenant_id
        ).delete(synchronize_session=False)
        db.query(Status).filter(Status.tenant_id == tenant_id).delete(
            synchronize_session=False
        )

        db.query(Connection).filter(Connection.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        db.query(EmailOutbox).filter(EmailOutbox.tenant_id == tenant_id).delete(
            synchronize_session=False
        )
        db.delete(tenant)
        db.commit()

    def suspend(self, tenant_id: str, actor: Optional[User] = None) -> Tenant:
        return self._transition_to(self._guarded(tenant_id), self._status("suspended"), actor)

    def reactivate(self, tenant_id: str, actor: Optional[User] = None) -> Tenant:
        return self._transition_to(self._guarded(tenant_id), self._status("active"), actor)

    def archive(self, tenant_id: str, actor: Optional[User] = None) -> Tenant:
        return self._transition_to(self._guarded(tenant_id), self._status("archived"), actor)

    # ---- export ----

    def export_csv(
        self,
        columns: List[str],
        *,
        ids: Optional[List[str]] = None,
        status_view: str = "active",
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
    ) -> str:
        rows, _ = self.list(
            page=0,
            page_size=100_000,
            status_view=status_view,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_group=filter_group,
        )
        if ids:
            id_set = set(ids)
            rows = [t for t in rows if t.id in id_set]
        counts = self.user_counts([t.id for t in rows])

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(columns)
        for tenant in rows:
            writer.writerow(
                [_column_value(tenant, c, counts.get(tenant.id, 0)) for c in columns]
            )
        return buffer.getvalue()


def _column_value(tenant: Tenant, column: str, user_count: int) -> str:
    if column in ("tenant", "name"):
        return tenant.name
    if column == "slug":
        return tenant.slug
    if column == "status":
        # Machine value, matching the JSON API (code-review fix: consumers
        # keying on ACTIVE/SUSPENDED must not see the editable label).
        return tenant.status.category or tenant.status.key.upper()
    if column == "contact":
        return tenant.contact_email or ""
    if column == "users":
        return str(user_count)
    if column == "created":
        return tenant.created_at.isoformat() if tenant.created_at else ""
    return ""
