"""Omnichannel's own deferred (grace-window) action registrations (sprint-4/23,
T5 fix round 1, item 15).

Migrates the module's `confirm:`-gated frontend actions onto the CORE
grace-window engine (D2) - no confirm dialog, a server-side countdown, cancel
while it's open. Registered from `bootstrap.register_engine_entities()`
(mirrors how a module extends the status/rule/workflow engines - never a
fork). Every handler calls an EXISTING service method.

Three of these entities (`wa_template`, `quick_reply`, `api_key`) are owned
by a parent (channel/workspace) but have their OWN globally-unique PK, so
`entity_id` stays the bare row id - the handler resolves the owning parent
from the row itself rather than threading a composite key through the
Resource shell's default `getEntityId = row.id`.
"""
from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action

CHANNELS_MANAGE = "channels.manage"
WA_TEMPLATES_MANAGE = "wa_templates.manage"
WEBHOOKS_MANAGE = "webhooks.manage"
WORKSPACES_MANAGE = "workspaces.manage"
API_KEYS_MANAGE = "api_keys.manage"


# ---- channels --------------------------------------------------------------


def _channel_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .repositories.channel_repository import ChannelRepository

    return ChannelRepository(db).get_by_id(entity_id, tenant_id) is not None


def _channels_disconnect(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.channel_service import ChannelService

    if not _channel_exists(db, tenant_id, entity_id):
        raise ValueError("Channel no longer exists.")
    ChannelService(db).disconnect([entity_id], tenant_id)


def _channels_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.channel_service import ChannelService

    if not _channel_exists(db, tenant_id, entity_id):
        raise ValueError("Channel no longer exists.")
    ChannelService(db).remove([entity_id], tenant_id)


CHANNELS_DISCONNECT = DeferredActionDef(
    key="channels.disconnect",
    entity_type="channel",
    permission=CHANNELS_MANAGE,
    window="destructive",  # matches users.trash's precedent - restorable, still 10s
    label="Disconnect",
    execute=_channels_disconnect,
    exists=_channel_exists,
)
CHANNELS_DELETE = DeferredActionDef(
    key="channels.delete",
    entity_type="channel",
    permission=CHANNELS_MANAGE,
    window="destructive",
    label="Delete permanently",
    execute=_channels_delete,
    exists=_channel_exists,
)


# ---- WhatsApp templates ----------------------------------------------------
#
# `entity_id` is the bare template id - its PK is globally unique, so unlike
# the workspace-scoped entities below this needs no composite key. The
# handler resolves the OWNING channel from the row itself (rather than
# threading `channelId` through the row objects the Resource shell's default
# `getEntityId = row.id` reads) before calling the service, which still wants
# both ids (it needs the channel's credentials for the Meta-side delete).


def _wa_template_row(db: Session, tenant_id: str, entity_id: str):
    from .models import WhatsappTemplate

    return (
        db.query(WhatsappTemplate)
        .filter(WhatsappTemplate.id == entity_id, WhatsappTemplate.tenant_id == tenant_id)
        .first()
    )


def _wa_templates_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _wa_template_row(db, tenant_id, entity_id) is not None


def _wa_templates_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.template_management_service import TemplateManagementService

    row = _wa_template_row(db, tenant_id, entity_id)
    if row is None:
        raise ValueError("Template no longer exists.")
    TemplateManagementService(db).delete(row.channel_id, entity_id, tenant_id)


WA_TEMPLATES_DELETE = DeferredActionDef(
    key="wa_templates.delete",
    entity_type="wa_template",
    permission=WA_TEMPLATES_MANAGE,
    window="destructive",
    label="Delete",
    execute=_wa_templates_delete,
    exists=_wa_templates_exists,
)


# ---- consumer webhook endpoints --------------------------------------------


def _webhook_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import WebhookEndpoint

    return (
        db.query(WebhookEndpoint.id)
        .filter(WebhookEndpoint.id == entity_id, WebhookEndpoint.tenant_id == tenant_id)
        .first()
        is not None
    )


def _webhooks_set_active(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.webhook_service import WebhookService

    WebhookService(db).set_status(tenant_id, entity_id, bool(payload.get("active", False)))


def _webhooks_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.webhook_service import WebhookService

    WebhookService(db).delete(tenant_id, entity_id)


WEBHOOKS_SET_ACTIVE = DeferredActionDef(
    key="webhooks.set_active",
    entity_type="webhook_endpoint",
    permission=WEBHOOKS_MANAGE,
    window="reversible",  # "pause until you re-enable it"
    label="Disable",
    execute=_webhooks_set_active,
    exists=_webhook_exists,
)
WEBHOOKS_DELETE = DeferredActionDef(
    key="webhooks.delete",
    entity_type="webhook_endpoint",
    permission=WEBHOOKS_MANAGE,
    window="destructive",
    label="Delete",
    execute=_webhooks_delete,
    exists=_webhook_exists,
)


# ---- quick replies ----------------------------------------------------------
#
# `entity_id` is the bare quick-reply id (globally unique PK) - the handler
# resolves its owning workspace from the row itself (the service method wants
# both ids for its own tenant+workspace re-check).


def _quick_reply_row(db: Session, tenant_id: str, entity_id: str):
    from .models import QuickReply

    return (
        db.query(QuickReply)
        .filter(QuickReply.id == entity_id, QuickReply.tenant_id == tenant_id)
        .first()
    )


def _quick_replies_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _quick_reply_row(db, tenant_id, entity_id) is not None


def _quick_replies_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.message_service import MessageService

    row = _quick_reply_row(db, tenant_id, entity_id)
    if row is None:
        raise ValueError("Quick reply no longer exists.")
    MessageService(db).delete_quick_reply(entity_id, row.workspace_id, tenant_id)


QUICK_REPLIES_DELETE = DeferredActionDef(
    key="quick_replies.delete",
    entity_type="quick_reply",
    permission=WORKSPACES_MANAGE,  # matches the FE action's own gate
    window="destructive",
    label="Delete",
    execute=_quick_replies_delete,
    exists=_quick_replies_exists,
)


# ---- workspace API keys -----------------------------------------------------
#
# `entity_id` is the bare key id (globally unique PK) - the handler resolves
# its owning workspace from the row itself (the service method wants both
# ids for its own tenant+workspace re-check).


def _api_key_row(db: Session, tenant_id: str, entity_id: str):
    from .models import WorkspaceApiKey

    return (
        db.query(WorkspaceApiKey)
        .filter(WorkspaceApiKey.id == entity_id, WorkspaceApiKey.tenant_id == tenant_id)
        .first()
    )


def _api_key_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _api_key_row(db, tenant_id, entity_id) is not None


def _api_keys_revoke(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.api_key_service import ApiKeyService

    row = _api_key_row(db, tenant_id, entity_id)
    if row is None:
        raise ValueError("API key no longer exists.")
    ApiKeyService(db).revoke(entity_id, tenant_id, row.workspace_id)


API_KEYS_REVOKE = DeferredActionDef(
    key="api_keys.revoke",
    entity_type="api_key",
    permission=API_KEYS_MANAGE,
    window="destructive",  # "cannot be undone - mint a new key"
    label="Revoke",
    execute=_api_keys_revoke,
    exists=_api_key_exists,
)


# ---- workspaces -------------------------------------------------------------


def _workspace_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .repositories.workspace_repository import WorkspaceRepository

    return WorkspaceRepository(db).get_by_id(entity_id, tenant_id) is not None


def _workspaces_trash(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.workspace_service import WorkspaceService

    WorkspaceService(db).trash([entity_id], tenant_id)


WORKSPACES_TRASH = DeferredActionDef(
    key="workspaces.trash",
    entity_type="workspace",
    permission=WORKSPACES_MANAGE,
    window="destructive",
    label="Trash",
    execute=_workspaces_trash,
    exists=_workspace_exists,
)


_ALL = (
    CHANNELS_DISCONNECT,
    CHANNELS_DELETE,
    WA_TEMPLATES_DELETE,
    WEBHOOKS_SET_ACTIVE,
    WEBHOOKS_DELETE,
    QUICK_REPLIES_DELETE,
    API_KEYS_REVOKE,
    WORKSPACES_TRASH,
)


def register_omnichannel_deferred_actions() -> None:
    for action_def in _ALL:
        register_deferred_action(action_def)
