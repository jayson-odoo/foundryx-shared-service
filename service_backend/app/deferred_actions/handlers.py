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
"""
from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action
from app.models.user import User


def _load_actor(db: Session, actor_user_id: str) -> User:
    """Look up the acting user by id for an existing service call that wants
    a `User` (audit context only - the permission check already happened at
    park time, this is not a re-authorization)."""
    actor = db.get(User, actor_user_id) if actor_user_id else None
    if actor is None:
        raise ValueError("Deferred action actor not found.")
    return actor


def _users_trash(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.user_service import UserService

    UserService(db).trash([entity_id], tenant_id)


def _roles_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.role_service import RoleService

    RoleService(db).delete(entity_id, tenant_id)


def _workflows_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.workflow_service import WorkflowService

    WorkflowService(db).remove(entity_id, tenant_id)


def _forms_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.form_service import FormService

    FormService(db).delete(tenant_id, entity_id)


def _templates_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.template_service import TemplateService

    TemplateService(db).delete(entity_id, tenant_id)


def _templates_reset(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.template_service import TemplateService

    TemplateService(db).reset(entity_id, tenant_id)


def _connections_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.integration_service import IntegrationService

    IntegrationService(db).delete(tenant_id, entity_id)


def _connections_activate(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.integration_service import IntegrationService

    IntegrationService(db).set_active(tenant_id, entity_id)


def _ai_agents_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.ai_service import AgentService

    AgentService(db).delete(tenant_id, entity_id)


def _ai_skills_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.ai_service import SkillService

    SkillService(db).delete(tenant_id, entity_id)


def _documents_trash(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.document_service import DocumentService

    actor = _load_actor(db, actor_user_id)
    DocumentService(db).delete(tenant_id, [], [entity_id], actor)


def _document_shares_revoke(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.share_service import ShareService

    ShareService(db).revoke(tenant_id, [entity_id])


def _products_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.catalog_service import ProductService

    ProductService(db).delete(tenant_id, entity_id)


def _tenants_archive(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.tenant_service import TenantService

    actor = db.get(User, actor_user_id) if actor_user_id else None
    # `entity_id` is the TARGET tenant being archived, not the actor's own
    # tenant (a platform action) - `tenant_id` (park scope) is the actor's own.
    TenantService(db).archive(entity_id, actor)


def _tenants_suspend(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.tenant_service import TenantService

    actor = db.get(User, actor_user_id) if actor_user_id else None
    TenantService(db).suspend(entity_id, actor)


def _tenants_reactivate(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.services.tenant_service import TenantService

    actor = db.get(User, actor_user_id) if actor_user_id else None
    TenantService(db).reactivate(entity_id, actor)


USERS_TRASH = DeferredActionDef(
    key="users.trash",
    entity_type="user",
    permission="users.delete",
    window="destructive",
    label="Trash",
    execute=_users_trash,
)
ROLES_DELETE = DeferredActionDef(
    key="roles.delete",
    entity_type="role",
    permission="roles.delete",
    window="destructive",
    label="Delete role",
    execute=_roles_delete,
)
WORKFLOWS_DELETE = DeferredActionDef(
    key="workflows.delete",
    entity_type="workflow",
    permission="workflows.manage",
    window="destructive",
    label="Delete permanently",
    execute=_workflows_delete,
)
FORMS_DELETE = DeferredActionDef(
    key="forms.delete",
    entity_type="form",
    permission="forms.manage",
    window="destructive",
    label="Delete permanently",
    execute=_forms_delete,
)
TEMPLATES_DELETE = DeferredActionDef(
    key="templates.delete",
    entity_type="template",
    permission="templates.manage",
    window="destructive",
    label="Delete",
    execute=_templates_delete,
)
TEMPLATES_RESET = DeferredActionDef(
    key="templates.reset",
    entity_type="template",
    permission="templates.manage",
    window="destructive",
    label="Reset to default",
    execute=_templates_reset,
)
CONNECTIONS_DELETE = DeferredActionDef(
    key="connections.delete",
    entity_type="connection",
    permission="integrations.manage",
    window="destructive",
    label="Disconnect",
    execute=_connections_delete,
)
CONNECTIONS_ACTIVATE = DeferredActionDef(
    key="connections.activate",
    entity_type="connection",
    permission="integrations.manage",
    window="reversible",  # switching the active bucket back is a click away
    label="Set as active",
    execute=_connections_activate,
)
AI_AGENTS_DELETE = DeferredActionDef(
    key="ai_agents.delete",
    entity_type="ai_agent",
    permission="ai_agents.manage",
    window="destructive",
    label="Delete",
    execute=_ai_agents_delete,
)
AI_SKILLS_DELETE = DeferredActionDef(
    key="ai_skills.delete",
    entity_type="ai_skill",
    permission="ai_agents.manage",
    window="destructive",
    label="Delete",
    execute=_ai_skills_delete,
)
DOCUMENTS_TRASH = DeferredActionDef(
    key="documents.trash",
    entity_type="document_file",
    permission="documents.manage",
    window="destructive",
    label="Trash",
    execute=_documents_trash,
)
PRODUCTS_DELETE = DeferredActionDef(
    key="products.delete",
    entity_type="product",
    permission="products.delete",
    window="destructive",
    label="Delete",
    execute=_products_delete,
)
DOCUMENT_SHARES_REVOKE = DeferredActionDef(
    key="document_shares.revoke",
    entity_type="document_share",
    permission="documents.share",
    window="destructive",
    label="Revoke",
    execute=_document_shares_revoke,
)
TENANTS_ARCHIVE = DeferredActionDef(
    key="tenants.archive",
    entity_type="tenant",
    permission="tenants.archive",
    window="reversible",  # archive is reversible via Restore (D2)
    label="Archive",
    execute=_tenants_archive,
    platform=True,
)
TENANTS_SUSPEND = DeferredActionDef(
    key="tenants.suspend",
    entity_type="tenant",
    permission="tenants.suspend",
    window="reversible",
    label="Suspend",
    execute=_tenants_suspend,
    platform=True,
)
TENANTS_REACTIVATE = DeferredActionDef(
    key="tenants.reactivate",
    entity_type="tenant",
    permission="tenants.suspend",
    window="reversible",
    label="Reactivate",
    execute=_tenants_reactivate,
    platform=True,
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
)


def register_deferred_actions() -> None:
    for action_def in _ALL:
        register_deferred_action(action_def)
