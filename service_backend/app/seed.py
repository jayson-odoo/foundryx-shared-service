"""Idempotent seed: statuses + tenants (default + platform) + permission
catalog + roles + demo users.

Shared by scripts/bootstrap_db.py (canonical) and scripts/init_db.py. Safe to
run repeatedly — every step checks for existing rows first. The permission
catalog is synced from the core + platform CSVs (core = "module zero",
plan 03 §4; platform = operator keys, plan 07 §5).

Grant model (plan 08 §5): a tenant Admin holds the core keys + the keys of
modules INSTALLED for that tenant (AppStoreService grants/revokes on
install/uninstall); the platform tenant's Platform Admin holds the full
catalog including platform keys.
"""
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy.sql import func

from app.models import (
    DEFAULT_TENANT_ID,
    DEFAULT_TENANT_NAME,
    DEFAULT_TENANT_SLUG,
    PLATFORM_TENANT_ID,
    PLATFORM_TENANT_NAME,
    PLATFORM_TENANT_SLUG,
    Role,
    Status,
    StatusTransition,
    Tenant,
    TENANT_ENTITY,
    TENANT_STATUS_ACTIVE,
    TENANT_STATUS_IDS,
    TENANT_STATUS_SEED,
    TENANT_TRANSITION_SEED,
    User,
    UserStatus,
)
from app.repositories.permission_repository import PermissionRepository
from app.security import hash_password
from app.services.permission_service import PLATFORM_MODULE, PermissionService

# (name, description) — all seeded roles are system (protected from deletion).
SEED_ROLES: List[Tuple[str, str]] = [
    ("Admin", "Full system access with all permissions"),
    ("Event Manager", "Plan and run events end to end"),
    ("Coordinator", "Coordinate event logistics and schedules"),
    ("Vendor Manager", "Manage vendors and procurement"),
    ("Finance", "Manage billing, invoicing and financial reports"),
    ("Member", "Standard member access"),
    ("Viewer", "Read-only access to dashboards and reports"),
]

# (email, password, name, [role names]) — all ACTIVE under the default tenant.
SEED_USERS = [
    ("demo@example.com", "demo1234", "Demo User", ["Admin"]),
    ("demo@kt.com", "demo1234", "KT Demo", ["Member"]),
    ("admin@foundryx.com", "admin1234", "Admin User", ["Admin"]),
    ("manager@foundryx.com", "manager1234", "Event Manager", ["Event Manager"]),
    ("staff@foundryx.com", "staff1234", "Event Staff", ["Coordinator", "Member"]),
]

# The operator team's first login (change in prod).
PLATFORM_ADMIN_EMAIL = "platform@example.com"
PLATFORM_ADMIN_PASSWORD = "platform1234"
PLATFORM_ADMIN_NAME = "Platform Operator"
PLATFORM_ADMIN_ROLE = "Platform Admin"


def seed_statuses(db: Session) -> None:
    """Tenant lifecycle system rows — platform defaults (tenant NULL).

    Behavior = trait flags (sprint-2/01 D2); ``category`` stays populated as
    the cosmetic uppercase-key mirror the wire/filters still display. Flags
    are re-asserted on every seed (idempotent backfill for create_all DBs).
    """
    existing = {
        s.id: s for s in db.query(Status).filter(Status.entity_type == TENANT_ENTITY).all()
    }
    for status_id, key, label, color, sort_order, flags in TENANT_STATUS_SEED:
        row = existing.get(status_id)
        if row is None:
            row = Status(
                id=status_id,
                entity_type=TENANT_ENTITY,
                key=key,
                category=key.upper(),
                label=label,
                color=color,
                sort_order=sort_order,
                is_system=True,
                tenant_id=None,
            )
            db.add(row)
        # Trait flags are the machine semantics — always converge them.
        for flag, value in flags.items():
            setattr(row, flag, value)
    db.flush()


def seed_tenant_transitions(db: Session) -> None:
    """Default tenant lifecycle edge graph (sprint-2/01) — platform-owned.

    active→suspended (Suspend), suspended→active (Reactivate),
    active/suspended→archived (Archive), archived→active (Restore —
    sprint-2/02 revision; hard purge stays BL-035, not a transition).
    """
    existing = {
        t.id
        for t in db.query(StatusTransition)
        .filter(StatusTransition.entity_type == TENANT_ENTITY)
        .all()
    }
    for transition_id, from_cat, to_cat, label, sort_order in TENANT_TRANSITION_SEED:
        if transition_id in existing:
            continue
        db.add(
            StatusTransition(
                id=transition_id,
                entity_type=TENANT_ENTITY,
                tenant_id=None,
                from_status_id=TENANT_STATUS_IDS[from_cat],
                to_status_id=TENANT_STATUS_IDS[to_cat],
                label=label,
                sort_order=sort_order,
            )
        )
    db.flush()


def _ensure_tenant(db: Session, tenant_id: str, name: str, slug: str, is_platform: bool) -> None:
    if db.query(Tenant).filter(Tenant.id == tenant_id).first():
        return
    db.add(
        Tenant(
            id=tenant_id,
            name=name,
            slug=slug,
            status_id=TENANT_STATUS_IDS[TENANT_STATUS_ACTIVE],
            is_platform=is_platform,
        )
    )
    db.flush()


def seed_default_tenant(db: Session) -> None:
    _ensure_tenant(db, DEFAULT_TENANT_ID, DEFAULT_TENANT_NAME, DEFAULT_TENANT_SLUG, False)


def seed_platform_tenant(db: Session) -> None:
    _ensure_tenant(db, PLATFORM_TENANT_ID, PLATFORM_TENANT_NAME, PLATFORM_TENANT_SLUG, True)


def seed_permissions(db: Session) -> None:
    """Sync the core + platform permission catalogs from the bundled CSVs."""
    service = PermissionService(db)
    service.sync_core()
    service.sync_platform()


def tenant_admin_grant(db: Session, tenant_id: str):
    """What a tenant Admin holds (plan 08 §5): core keys + keys of modules
    INSTALLED for that tenant. Platform keys stay operator-only (plan 07 §5);
    uninstalled modules' keys are granted by AppStoreService on install."""
    from app.repositories.module_repository import ModuleRepository
    from app.services.permission_service import CORE_MODULE

    allowed_modules = {CORE_MODULE} | ModuleRepository(db).installed_module_names(tenant_id)
    return [
        p
        for p in PermissionRepository(db).list_all()
        if p.module != PLATFORM_MODULE and p.module in allowed_modules
    ]


def seed_tenant_roles(db: Session, tenant_id: str) -> Dict[str, Role]:
    """Seed the standard system roles for ONE tenant (idempotent).

    Reused by provisioning (plan 07 §7) — a new tenant gets the same role set
    the default tenant does, with Admin granted core + installed-module keys
    (a fresh tenant has no modules installed → core only, plan 08 §5).
    """
    existing = {
        r.name: r for r in db.query(Role).filter(Role.tenant_id == tenant_id).all()
    }
    for name, description in SEED_ROLES:
        role = existing.get(name)
        if role is None:
            role = Role(
                tenant_id=tenant_id,
                name=name,
                description=description,
                is_system=True,
            )
            db.add(role)
            existing[name] = role
        else:
            # Backfill on re-seed (e.g. after the RBAC migration added columns).
            if role.description is None:
                role.description = description
            role.is_system = True
    db.flush()

    # Admin holds the core keys + installed-module keys (plan 08 §5).
    existing["Admin"].permissions = tenant_admin_grant(db, tenant_id)
    db.flush()
    return existing


def seed_roles(db: Session) -> Dict[str, Role]:
    return seed_tenant_roles(db, DEFAULT_TENANT_ID)


def sweep_tenant_admin_grants(db: Session) -> None:
    """Re-compute the Admin grant for EVERY non-platform tenant (DoD #4).

    ``seed_roles`` only re-grants DEFAULT, so a new core permission (e.g.
    ``numbering.read/manage``) never reaches the Admin role of tenants
    provisioned BEFORE the slice that added it. This idempotent sweep — run on
    every bootstrap/init, AFTER the permission catalog is synced — closes that
    gap. Platform tenant excluded (its Platform Admin holds the full catalog via
    ``seed_platform_admin``)."""
    tenants = db.query(Tenant).filter(Tenant.is_platform.is_(False)).all()
    for tenant in tenants:
        admin = (
            db.query(Role)
            .filter(Role.tenant_id == tenant.id, Role.name == "Admin")
            .first()
        )
        if admin is None:
            continue
        admin.permissions = tenant_admin_grant(db, tenant.id)
    db.flush()


def seed_platform_admin(db: Session) -> None:
    """Platform Admin role (full catalog incl. platform keys) + operator user."""
    role = (
        db.query(Role)
        .filter(Role.tenant_id == PLATFORM_TENANT_ID, Role.name == PLATFORM_ADMIN_ROLE)
        .first()
    )
    if role is None:
        role = Role(
            tenant_id=PLATFORM_TENANT_ID,
            name=PLATFORM_ADMIN_ROLE,
            description="Operate the platform — tenants, app store, support",
            is_system=True,
        )
        db.add(role)
        db.flush()
    role.permissions = PermissionRepository(db).list_all()
    db.flush()

    if (
        db.query(User)
        .filter(User.email == PLATFORM_ADMIN_EMAIL, User.tenant_id == PLATFORM_TENANT_ID)
        .first()
    ):
        return
    operator = User(
        tenant_id=PLATFORM_TENANT_ID,
        email=PLATFORM_ADMIN_EMAIL,
        password=hash_password(PLATFORM_ADMIN_PASSWORD),
        name=PLATFORM_ADMIN_NAME,
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    operator.roles = [role]
    db.add(operator)
    db.flush()


def seed_users(db: Session, roles_by_name: Dict[str, Role]) -> None:
    for email, password, name, role_names in SEED_USERS:
        if (
            db.query(User)
            .filter(User.email == email, User.tenant_id == DEFAULT_TENANT_ID)
            .first()
        ):
            continue
        user = User(
            tenant_id=DEFAULT_TENANT_ID,
            email=email,
            password=hash_password(password),
            name=name,
            status=UserStatus.ACTIVE.value,
            email_verified_at=func.now(),
        )
        user.roles = [roles_by_name[n] for n in role_names if n in roles_by_name]
        db.add(user)


def seed_platform_smtp_connection(db: Session) -> None:
    """Env-seed the PLATFORM tenant's default SMTP connection (plan 09 D3).

    Zero-touch on-prem: set PLATFORM_SMTP_* and bootstrap upserts the row the
    platform UI later edits. Unset host = no row = dev-log email fallback.
    Credentials refresh from env on every bootstrap (idempotent).
    """
    from app.config import settings
    from app.models.connection import CONNECTION_STATUS_UNVERIFIED, Connection
    from app.secrets import encrypt_secret

    if not settings.platform_smtp_host:
        return
    if not settings.fernet_key:
        # Seeding encrypts with THIS process's ephemeral key; uvicorn is a
        # DIFFERENT process with a different ephemeral key — the dispatcher
        # could never decrypt the password. Refuse loudly instead.
        print(
            "WARNING: PLATFORM_SMTP_HOST is set but FERNET_KEY is not — "
            "skipping the platform SMTP seed (the encrypted password would be "
            "unreadable by the API process). Set a stable FERNET_KEY and re-run."
        )
        return
    config = {
        "host": settings.platform_smtp_host,
        "port": str(settings.platform_smtp_port),
        "security": settings.platform_smtp_security,
        "username": settings.platform_smtp_username,
        "fromEmail": settings.platform_smtp_from_email or settings.platform_smtp_username,
        "fromName": settings.platform_smtp_from_name,
    }
    row = (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.provider == "smtp")
        .first()
    )
    if row is None:
        row = Connection(
            tenant_id=PLATFORM_TENANT_ID,
            provider="smtp",
            type="email",
            name="Platform SMTP",
            status=CONNECTION_STATUS_UNVERIFIED,
        )
        db.add(row)
    row.config_json = config
    row.credentials_json = encrypt_secret({"password": settings.platform_smtp_password})


def seed_platform_storage_connection(db: Session) -> None:
    """Env-seed the PLATFORM tenant's default storage connection (plan 06 D10).

    Mirrors `seed_platform_smtp_connection`: set PLATFORM_STORAGE_* and
    bootstrap upserts the row. Unset provider = no row = local-disk fallback.
    Credentials refresh from env on every bootstrap (idempotent).
    """
    from app.config import settings
    from app.models.connection import CONNECTION_STATUS_UNVERIFIED, Connection
    from app.secrets import encrypt_secret

    provider = settings.platform_storage_provider.strip().lower()
    if not provider:
        return
    if provider not in ("s3", "r2"):
        print(
            f"WARNING: PLATFORM_STORAGE_PROVIDER={provider!r} is not one of s3|r2 — "
            "skipping the platform storage seed."
        )
        return
    if not settings.fernet_key:
        # Same rule as the SMTP seed: an ephemeral key here is unreadable by
        # the API process. Refuse loudly instead.
        print(
            "WARNING: PLATFORM_STORAGE_PROVIDER is set but FERNET_KEY is not — "
            "skipping the platform storage seed (the encrypted credentials "
            "would be unreadable by the API process). Set a stable FERNET_KEY "
            "and re-run."
        )
        return
    config = {
        "bucket": settings.platform_storage_bucket,
        "cdnBaseUrl": settings.platform_storage_cdn_base_url,
    }
    if provider == "s3":
        config["region"] = settings.platform_storage_region
        config["endpointUrl"] = settings.platform_storage_endpoint_url
    else:
        config["accountId"] = settings.platform_storage_account_id
    row = (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.type == "storage")
        .first()
    )
    if row is None:
        row = Connection(
            tenant_id=PLATFORM_TENANT_ID,
            provider=provider,
            type="storage",
            name="Platform storage",
            status=CONNECTION_STATUS_UNVERIFIED,
        )
        db.add(row)
    row.provider = provider
    row.config_json = config
    row.credentials_json = encrypt_secret(
        {
            "accessKeyId": settings.platform_storage_access_key_id,
            "secretAccessKey": settings.platform_storage_secret_access_key,
        }
    )


def seed_all(db: Session) -> None:
    seed_statuses(db)
    seed_tenant_transitions(db)
    seed_default_tenant(db)
    seed_platform_tenant(db)
    seed_permissions(db)
    roles_by_name = seed_roles(db)
    seed_users(db, roles_by_name)
    seed_platform_admin(db)
    # DoD #4: reach Admin roles of tenants provisioned before a new core perm.
    sweep_tenant_admin_grants(db)
    seed_platform_smtp_connection(db)
    seed_platform_storage_connection(db)
    # Template engine (plan 07 D7): platform-tier system email templates.
    from app.template_engine.seed_templates import seed_platform_templates

    seed_platform_templates(db)
    db.commit()
