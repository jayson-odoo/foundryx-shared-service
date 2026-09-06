"""First-party deferred-action registrations (AC-DLA-38).

Every handler calls an EXISTING service method - never re-implements the
mutation. `register_deferred_actions()` is idempotent (safe to call more than
once - the underlying `register_deferred_action` tolerates re-registering the
SAME def object) and is called from `app/main.py`'s lifespan and
`tests/conftest.py`.

Ten keys, matching the plan's explicit list (AC-DLA-38): the confirm-bearing
site's OWN verb is used where it differs from the plan's shorthand (the
"Delete permanently" action on workflows/forms is a hard delete gated to the
Archived view, so the key is `workflows.delete`/`forms.delete`, not
`.trash` - the plan's prose names were approximate; the registered set is the
one this file actually implements).

Fix round 1 (T5) items 6/7: every handler resolves its acting user via the
entity's OWN tenant-scoped repository (never a bare `db.get(User, id)` -
that's an unscoped lookup of a stored id, the polymorphic-target_id rule),
and every `DeferredActionDef` carries an `exists` check so `park()` 404s a
target that's already gone, plus the handlers whose underlying service call
silently no-ops on a missing id (bulk-shaped `UPDATE ... WHERE id IN (...)`)
assert the record was actually touched before reporting success.
"""
from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action
from app.repositories.user_repository import UserRepository


class DeferredTargetGone(Exception):
    """The record the handler was asked to act on no longer exists - the
    underlying service call would otherwise silently no-op (fix round 1,
    item 7). Raised so `commit_one` marks the row `failed`."""


def _load_actor(db: Session, tenant_id: str, actor_user_id: str):
    """Tenant-scoped resolution of the acting user (audit context only - the
    permission check already happened at park time, this is not a
    re-authorization). Never an unscoped `db.get(User, id)` - a stored id
    must always be resolved tenant-scoped at use time."""
    actor = (
        UserRepository(db).get_by_id(actor_user_id, tenant_id, include_trashed=True)
        if actor_user_id
        else None
    )
    if actor is None:
        raise ValueError("Deferred action actor not found.")
    return actor


def _users_trash(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.user_service import UserService

    if UserRepository(db).get_by_id(entity_id, tenant_id, include_trashed=True) is None:
        raise DeferredTargetGone("User no longer exists.")
    UserService(db).trash([entity_id], tenant_id)


def _users_trash_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return UserRepository(db).get_by_id(entity_id, tenant_id, include_trashed=True) is not None


def _roles_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.role_service import RoleService

    RoleService(db).delete(entity_id, tenant_id)


def _roles_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.role_repository import RoleRepository

    return RoleRepository(db).get_by_id(entity_id, tenant_id) is not None


def _workflows_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.workflow_service import WorkflowService

    WorkflowService(db).remove(entity_id, tenant_id)


def _workflows_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.workflow_repository import WorkflowRepository

    return WorkflowRepository(db).get(entity_id, tenant_id) is not None


def _forms_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.form_service import FormService

    FormService(db).delete(tenant_id, entity_id)


def _forms_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.form_repository import FormRepository

    return FormRepository(db).get_by_id(tenant_id, entity_id) is not None


def _templates_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.template_service import TemplateService

    TemplateService(db).delete(entity_id, tenant_id)


def _templates_reset(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.template_service import TemplateService

    TemplateService(db).reset(entity_id, tenant_id)


def _templates_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.template_repository import TemplateRepository

    return TemplateRepository(db).get_visible(entity_id, tenant_id) is not None


def _connections_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.integration_service import IntegrationService

    IntegrationService(db).delete(tenant_id, entity_id)


def _connections_activate(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.integration_service import IntegrationService

    IntegrationService(db).set_active(tenant_id, entity_id)


def _connections_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.connection_repository import ConnectionRepository

    return ConnectionRepository(db).get(entity_id, tenant_id) is not None


def _ai_agents_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.ai_service import AgentService

    AgentService(db).delete(tenant_id, entity_id)


def _ai_agents_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.ai_repository import AgentRepository

    return AgentRepository(db).get(tenant_id, entity_id) is not None


def _ai_skills_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.ai_service import SkillService

    SkillService(db).delete(tenant_id, entity_id)


def _ai_skills_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.ai_repository import SkillRepository

    return SkillRepository(db).get(tenant_id, entity_id) is not None


def _documents_trash(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.document_service import DocumentService
    from app.repositories.document_repository import DocumentRepository

    actor = _load_actor(db, tenant_id, actor_user_id)
    if DocumentRepository(db).get_file(tenant_id, entity_id) is None:
        raise DeferredTargetGone("File no longer exists.")
    DocumentService(db).delete(tenant_id, [], [entity_id], actor)


def _documents_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.document_repository import DocumentRepository

    file = DocumentRepository(db).get_file(tenant_id, entity_id)
    return file is not None and not file.is_deleted


def _document_shares_revoke(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.share_service import ShareService
    from app.repositories.share_repository import ShareRepository

    if ShareRepository(db).get(tenant_id, entity_id) is None:
        raise DeferredTargetGone("Share no longer exists.")
    ShareService(db).revoke(tenant_id, [entity_id])


def _document_shares_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.share_repository import ShareRepository

    return ShareRepository(db).get(tenant_id, entity_id) is not None


def _products_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.catalog_service import ProductService

    ProductService(db).delete(tenant_id, entity_id)


def _products_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.models.catalog import Product

    return (
        db.query(Product.id)
        .filter(Product.id == entity_id, Product.tenant_id == tenant_id)
        .first()
        is not None
    )


def _tenants_archive(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.tenant_service import TenantService

    # `entity_id` is the TARGET tenant being archived, not the actor's own
    # tenant (a platform action) - the actor is only resolved for audit;
    # `TenantService`'s guard reads the target tenant itself.
    actor = (
        UserRepository(db).get_by_id(actor_user_id, tenant_id, include_trashed=True)
        if actor_user_id
        else None
    )
    TenantService(db).archive(entity_id, actor)


def _tenants_suspend(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.tenant_service import TenantService

    actor = (
        UserRepository(db).get_by_id(actor_user_id, tenant_id, include_trashed=True)
        if actor_user_id
        else None
    )
    TenantService(db).suspend(entity_id, actor)


def _tenants_reactivate(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.tenant_service import TenantService

    actor = (
        UserRepository(db).get_by_id(actor_user_id, tenant_id, include_trashed=True)
        if actor_user_id
        else None
    )
    TenantService(db).reactivate(entity_id, actor)


def _tenants_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.tenant_repository import TenantRepository

    return TenantRepository(db).get_by_id(entity_id) is not None


def _document_types_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.document_service import DocumentService

    DocumentService(db).delete_type(tenant_id, entity_id)


def _document_types_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.repositories.document_repository import DocumentRepository

    return DocumentRepository(db).get_type(tenant_id, entity_id) is not None


def _jobs_abort(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.storage_migration.service import StorageMigrationService

    StorageMigrationService(db).abort(tenant_id, entity_id)


def _jobs_complete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.storage_migration.service import StorageMigrationService

    StorageMigrationService(db).complete(tenant_id, entity_id)


def _jobs_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.jobs.service import JobService

    return JobService(db).get(tenant_id, entity_id) is not None


def _email_outbox_cancel(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.email_log_service import EmailLogService

    EmailLogService(db).cancel(entity_id, tenant_id)


def _email_outbox_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.models.email_outbox import EmailOutbox

    return (
        db.query(EmailOutbox.id)
        .filter(EmailOutbox.id == entity_id, EmailOutbox.tenant_id == tenant_id)
        .first()
        is not None
    )


def _tenant_modules_deactivate(
    db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str
) -> None:
    # T5 fix round 2, S2: Deactivate is fully reversible (Reactivate is one
    # click, data + permission assignments kept) - the storefront's OWN-tenant
    # app-store surface only (the operator console acts cross-tenant, outside
    # the actor's own tenant scope this engine assumes, and stays on the
    # existing immediate confirm path). `entity_id` is the module's `name`
    # (modules have no surrogate id). `AppStoreService.deactivate` already
    # raises loudly (already-inactive/not-installed/has-dependents) - let it
    # propagate so `commit_one` marks the row `failed`, never a silent no-op.
    from app.services.app_store_service import AppStoreService

    AppStoreService(db).deactivate(tenant_id, entity_id)


def _tenant_modules_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from app.models.module import MODULE_STATUS_ACTIVE
    from app.repositories.module_repository import ModuleRepository

    repo = ModuleRepository(db)
    module = repo.get_by_name(entity_id)
    if module is None:
        return False
    state = repo.get_state(tenant_id, module.id)
    return state is not None and state.status == MODULE_STATUS_ACTIVE


USERS_TRASH = DeferredActionDef(
    key="users.trash",
    entity_type="user",
    permission="users.delete",
    window="destructive",
    label="Trash",
    execute=_users_trash,
    exists=_users_trash_exists,
)
ROLES_DELETE = DeferredActionDef(
    key="roles.delete",
    entity_type="role",
    permission="roles.delete",
    window="destructive",
    label="Delete role",
    execute=_roles_delete,
    exists=_roles_exists,
)
WORKFLOWS_DELETE = DeferredActionDef(
    key="workflows.delete",
    entity_type="workflow",
    permission="workflows.manage",
    window="destructive",
    label="Delete permanently",
    execute=_workflows_delete,
    exists=_workflows_exists,
)
FORMS_DELETE = DeferredActionDef(
    key="forms.delete",
    entity_type="form",
    permission="forms.manage",
    window="destructive",
    label="Delete permanently",
    execute=_forms_delete,
    exists=_forms_exists,
)
TEMPLATES_DELETE = DeferredActionDef(
    key="templates.delete",
    entity_type="template",
    permission="templates.manage",
    window="destructive",
    label="Delete",
    execute=_templates_delete,
    exists=_templates_exists,
)
TEMPLATES_RESET = DeferredActionDef(
    key="templates.reset",
    entity_type="template",
    permission="templates.manage",
    window="destructive",
    label="Reset to default",
    execute=_templates_reset,
    exists=_templates_exists,
)
CONNECTIONS_DELETE = DeferredActionDef(
    key="connections.delete",
    entity_type="connection",
    permission="integrations.manage",
    window="destructive",
    label="Disconnect",
    execute=_connections_delete,
    exists=_connections_exists,
)
CONNECTIONS_ACTIVATE = DeferredActionDef(
    key="connections.activate",
    entity_type="connection",
    permission="integrations.manage",
    window="reversible",  # switching the active bucket back is a click away
    label="Set as active",
    execute=_connections_activate,
    exists=_connections_exists,
)
AI_AGENTS_DELETE = DeferredActionDef(
    key="ai_agents.delete",
    entity_type="ai_agent",
    permission="ai_agents.manage",
    window="destructive",
    label="Delete",
    execute=_ai_agents_delete,
    exists=_ai_agents_exists,
)
AI_SKILLS_DELETE = DeferredActionDef(
    key="ai_skills.delete",
    entity_type="ai_skill",
    permission="ai_agents.manage",
    window="destructive",
    label="Delete",
    execute=_ai_skills_delete,
    exists=_ai_skills_exists,
)
DOCUMENTS_TRASH = DeferredActionDef(
    key="documents.trash",
    entity_type="document_file",
    permission="documents.manage",
    window="destructive",
    label="Trash",
    execute=_documents_trash,
    exists=_documents_exists,
)
PRODUCTS_DELETE = DeferredActionDef(
    key="products.delete",
    entity_type="product",
    permission="products.delete",
    window="destructive",
    label="Delete",
    execute=_products_delete,
    exists=_products_exists,
)
DOCUMENT_SHARES_REVOKE = DeferredActionDef(
    key="document_shares.revoke",
    entity_type="document_share",
    permission="documents.share",
    window="destructive",
    label="Revoke",
    execute=_document_shares_revoke,
    exists=_document_shares_exists,
)
TENANTS_ARCHIVE = DeferredActionDef(
    key="tenants.archive",
    entity_type="tenant",
    permission="tenants.archive",
    window="reversible",  # archive is reversible via Restore (D2)
    label="Archive",
    execute=_tenants_archive,
    exists=_tenants_exists,
    platform=True,
)
TENANTS_SUSPEND = DeferredActionDef(
    key="tenants.suspend",
    entity_type="tenant",
    permission="tenants.suspend",
    window="reversible",
    label="Suspend",
    execute=_tenants_suspend,
    exists=_tenants_exists,
    platform=True,
)
TENANTS_REACTIVATE = DeferredActionDef(
    key="tenants.reactivate",
    entity_type="tenant",
    permission="tenants.suspend",
    window="reversible",
    label="Reactivate",
    execute=_tenants_reactivate,
    exists=_tenants_exists,
    platform=True,
)

DOCUMENT_TYPES_DELETE = DeferredActionDef(
    key="document_types.delete",
    entity_type="document_type",
    permission="documents.configure",
    window="destructive",
    label="Delete",
    execute=_document_types_delete,
    exists=_document_types_exists,
)
JOBS_ABORT = DeferredActionDef(
    key="jobs.abort",
    entity_type="background_job",
    permission="integrations.migrate_storage",
    window="reversible",  # "You can retry later" - the copy names its own undo
    label="Abort",
    execute=_jobs_abort,
    exists=_jobs_exists,
)
JOBS_COMPLETE = DeferredActionDef(
    key="jobs.complete",
    entity_type="background_job",
    permission="integrations.migrate_storage",
    window="destructive",  # "This cannot be undone"
    label="Complete anyway",
    execute=_jobs_complete,
    exists=_jobs_exists,
)
EMAIL_OUTBOX_CANCEL = DeferredActionDef(
    key="email_outbox.cancel",
    entity_type="email_outbox",
    permission="emails.manage",
    window="reversible",  # a cancelled email is retryable (D14)
    label="Cancel",
    execute=_email_outbox_cancel,
    exists=_email_outbox_exists,
)
TENANT_MODULES_DEACTIVATE = DeferredActionDef(
    key="tenant_modules.deactivate",
    entity_type="tenant_module",
    permission="app_store.deactivate",
    window="reversible",  # Reactivate is one click (D2)
    label="Deactivate",
    execute=_tenant_modules_deactivate,
    exists=_tenant_modules_exists,
)

_ALL = (
    USERS_TRASH,
    ROLES_DELETE,
    WORKFLOWS_DELETE,
    FORMS_DELETE,
    TEMPLATES_DELETE,
    TEMPLATES_RESET,
    CONNECTIONS_DELETE,
    CONNECTIONS_ACTIVATE,
    AI_AGENTS_DELETE,
    AI_SKILLS_DELETE,
    DOCUMENTS_TRASH,
    PRODUCTS_DELETE,
    DOCUMENT_SHARES_REVOKE,
    TENANTS_ARCHIVE,
    TENANTS_SUSPEND,
    TENANTS_REACTIVATE,
    DOCUMENT_TYPES_DELETE,
    JOBS_ABORT,
    JOBS_COMPLETE,
    EMAIL_OUTBOX_CANCEL,
    TENANT_MODULES_DEACTIVATE,
)


def register_deferred_actions() -> None:
    for action_def in _ALL:
        register_deferred_action(action_def)
