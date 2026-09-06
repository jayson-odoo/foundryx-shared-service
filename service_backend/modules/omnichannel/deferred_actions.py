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
SEGMENTS_MANAGE = "segments.manage"
CONVERSATIONS_READ = "conversations.read"
CLOSE_REASONS_MANAGE = "close_reasons.manage"


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
    module="omnichannel",
    entity_type="channel",
    permission=CHANNELS_MANAGE,
    window="destructive",  # matches users.trash's precedent - restorable, still 10s
    label="Disconnect",
    execute=_channels_disconnect,
    exists=_channel_exists,
)
CHANNELS_DELETE = DeferredActionDef(
    key="channels.delete",
    module="omnichannel",
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
    module="omnichannel",
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
    module="omnichannel",
    entity_type="webhook_endpoint",
    permission=WEBHOOKS_MANAGE,
    window="reversible",  # "pause until you re-enable it"
    label="Disable",
    execute=_webhooks_set_active,
    exists=_webhook_exists,
)
WEBHOOKS_DELETE = DeferredActionDef(
    key="webhooks.delete",
    module="omnichannel",
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
    module="omnichannel",
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
    module="omnichannel",
    entity_type="api_key",
    permission=API_KEYS_MANAGE,
    window="destructive",  # "cannot be undone - mint a new key"
    label="Revoke",
    execute=_api_keys_revoke,
    exists=_api_key_exists,
)


# ---- contact segments (plan 26, review round 1 - Blocker 2) ---------------
#
# `entity_id` is the bare segment id (globally unique PK) - the handler
# resolves its owning workspace from the row itself, mirroring the
# `wa_template`/`quick_reply`/`api_key` entities above.


def _contact_segment_row(db: Session, tenant_id: str, entity_id: str):
    from .models import ContactSegment

    return (
        db.query(ContactSegment)
        .filter(ContactSegment.id == entity_id, ContactSegment.tenant_id == tenant_id)
        .first()
    )


def _contact_segments_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _contact_segment_row(db, tenant_id, entity_id) is not None


def _contact_segments_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.contact_segment_service import ContactSegmentService

    row = _contact_segment_row(db, tenant_id, entity_id)
    if row is None:
        raise ValueError("Segment no longer exists.")
    ContactSegmentService(db).delete(entity_id, row.workspace_id, tenant_id)


CONTACT_SEGMENTS_DELETE = DeferredActionDef(
    key="contact_segments.delete",
    module="omnichannel",
    entity_type="contact_segment",
    permission=SEGMENTS_MANAGE,
    window="destructive",
    label="Delete",
    execute=_contact_segments_delete,
    exists=_contact_segments_exists,
)


# ---- workspaces -------------------------------------------------------------


def _workspace_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .repositories.workspace_repository import WorkspaceRepository

    return WorkspaceRepository(db).get_by_id(entity_id, tenant_id) is not None


def _workspaces_trash(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.workspace_service import WorkspaceService

    # T5 fix round 2, S3: `WorkspaceService.trash` is bulk-shaped (`get_many`
    # loop) and silently no-ops on a missing id - matches `_channels_disconnect`
    # /`_channels_delete` above and `app/deferred_actions/handlers.py`'s
    # `_users_trash` guard. A workspace deleted between park and commit must
    # fail the commit loudly, never report `committed` for a row that was
    # never touched.
    if not _workspace_exists(db, tenant_id, entity_id):
        raise ValueError("Workspace no longer exists.")
    WorkspaceService(db).trash([entity_id], tenant_id)


WORKSPACES_TRASH = DeferredActionDef(
    key="workspaces.trash",
    module="omnichannel",
    entity_type="workspace",
    permission=WORKSPACES_MANAGE,
    window="destructive",
    label="Trash",
    execute=_workspaces_trash,
    exists=_workspace_exists,
)


# ---- close reasons (plan 27 A3, review round 1 follow-up) -----------------
#
# `entity_id` is the bare reason id (globally unique PK). `park()` gates on
# `conversations.read` only (every user with the row menu at all holds it);
# the router's OWN endpoint additionally requires `close_reasons.manage` (a
# reason offers Delete only while `usesCount == 0` per D-A3-13, so the
# in-use 409 stays a defense-in-depth check, not the primary UX gate).


def _close_reason_row(db: Session, tenant_id: str, entity_id: str):
    from .models import CloseReason

    return (
        db.query(CloseReason)
        .filter(CloseReason.id == entity_id, CloseReason.tenant_id == tenant_id)
        .first()
    )


def _close_reasons_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _close_reason_row(db, tenant_id, entity_id) is not None


def _close_reasons_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.close_reason_service import CloseReasonInUse, CloseReasonService

    row = _close_reason_row(db, tenant_id, entity_id)
    if row is None:
        raise ValueError("Close reason no longer exists.")
    try:
        CloseReasonService(db).delete(entity_id, row.workspace_id, tenant_id)
    except CloseReasonInUse as exc:
        raise ValueError(
            "This close reason is still referenced by closed conversations - deactivate it instead."
        ) from exc


CLOSE_REASONS_DELETE = DeferredActionDef(
    key="close_reasons.delete",
    module="omnichannel",
    entity_type="close_reason",
    permission=CLOSE_REASONS_MANAGE,
    window="destructive",
    label="Delete",
    execute=_close_reasons_delete,
    exists=_close_reasons_exists,
)


# ---- saved inbox views (plan 27 A3, review round 1 follow-up) --------------
#
# `entity_id` is the bare view id (globally unique PK). AC-IVE-19: an OWNER
# may delete their own, non-shared view with only `conversations.read`;
# deleting a SHARED view or someone else's additionally needs
# `inbox_views.manage`. `park()` only checks ONE static permission key
# (`DeferredActionDef.permission`), so this registers the WIDER
# `conversations.read` floor and re-checks the narrower rule INSIDE the
# handler (mirrors the router's own `_requires_manage`) - a countdown can
# start for anyone who can see the row, but only an authorized actor's
# commit actually deletes it; an unauthorized commit fails loudly (the
# park-time `exists` check cannot see WHO parked it).


def _inbox_view_row(db: Session, tenant_id: str, entity_id: str):
    from .models import InboxView

    return (
        db.query(InboxView)
        .filter(InboxView.id == entity_id, InboxView.tenant_id == tenant_id)
        .first()
    )


def _inbox_views_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    return _inbox_view_row(db, tenant_id, entity_id) is not None


def _inbox_views_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from app.dependencies import effective_permission_keys
    from app.models.user import User

    from .services.inbox_view_service import InboxViewService

    row = _inbox_view_row(db, tenant_id, entity_id)
    if row is None:
        raise ValueError("View no longer exists.")
    # Round-3 codex triage B9 (closes the round-2 finding documented below) -
    # authorize as the EFFECTIVE user, per the house impersonation rule
    # (`get_current_user`/`require_permission` semantics: effective user for
    # authorization + "me"-ownership, real actor only for attribution).
    # `PendingActionService.park` now stamps `_effectiveUserId` into the
    # stored payload at park time (it is a full `User` there); `actor_user_id`
    # (`PendingAction.requested_by_id`) stays the REAL actor for audit only -
    # never used for this authorization check.
    #
    # Old finding (round 2), now resolved by the payload stamp: a
    # cross-tenant impersonator (a platform admin impersonating INTO this
    # tenant) resolved to `actor is None` when keyed off `requested_by_id`
    # (the real actor's row lives in another tenant) even when the person who
    # clicked Delete was the impersonated owner acting on their OWN view -
    # `requires_manage` fell back to True and the commit 409'd "Missing
    # permission" for an action the effective user was always allowed to take.
    effective_user_id = (payload or {}).get("_effectiveUserId") or actor_user_id
    actor = db.query(User).filter(User.id == effective_user_id, User.tenant_id == tenant_id).first()
    requires_manage = row.is_shared or actor is None or row.owner_user_id != actor.id
    if requires_manage and (actor is None or "inbox_views.manage" not in effective_permission_keys(actor)):
        raise ValueError("Missing permission: inbox_views.manage")
    InboxViewService(db).delete(entity_id, row.workspace_id, tenant_id)


INBOX_VIEWS_DELETE = DeferredActionDef(
    key="inbox_views.delete",
    module="omnichannel",
    entity_type="inbox_view",
    permission=CONVERSATIONS_READ,
    window="destructive",
    label="Delete",
    execute=_inbox_views_delete,
    exists=_inbox_views_exists,
)


_ALL = (
    CHANNELS_DISCONNECT,
    CHANNELS_DELETE,
    WA_TEMPLATES_DELETE,
    WEBHOOKS_SET_ACTIVE,
    WEBHOOKS_DELETE,
    QUICK_REPLIES_DELETE,
    API_KEYS_REVOKE,
    CONTACT_SEGMENTS_DELETE,
    WORKSPACES_TRASH,
    CLOSE_REASONS_DELETE,
    INBOX_VIEWS_DELETE,
)


def register_omnichannel_deferred_actions() -> None:
    for action_def in _ALL:
        register_deferred_action(action_def)
