"""Ideation's own deferred (grace-window) action registrations (sprint-4/23,
T5 fix round 1, item 15).

Every one of these replaces a `confirm:`-gated frontend action with the SAME
grace-window contract core entities already use (D2) - no confirm dialog, a
server-side countdown, cancel while it's open. Registered into the CORE
`app.deferred_actions` registry from `bootstrap.register_engine_entities()`
(mirrors how a module extends the status/rule/workflow engines - never a
fork). Every handler calls an EXISTING service method.
"""
from sqlalchemy.orm import Session

from app.deferred_actions.registry import DeferredActionDef, register_deferred_action
from app.repositories.user_repository import UserRepository

MANAGE = "ideation.triage.manage"
BR_MANAGE = "ideation.business_requirements.manage"


def _actor(db: Session, tenant_id: str, actor_user_id: str):
    return UserRepository(db).get_by_id(actor_user_id, tenant_id, include_trashed=True) if actor_user_id else None


# ---- ideas --------------------------------------------------------------


def _idea_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import Idea

    return db.query(Idea.id).filter(Idea.id == entity_id, Idea.tenant_id == tenant_id).first() is not None


def _ideas_archive(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.actions import IdeaActionService

    IdeaActionService(db).set_status(tenant_id, entity_id, "archived", _actor(db, tenant_id, actor_user_id))


def _ideas_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.actions import IdeaActionService

    IdeaActionService(db).delete(tenant_id, entity_id)


IDEAS_ARCHIVE = DeferredActionDef(
    key="ideation_ideas.archive",
    entity_type="ideation_idea",
    permission=MANAGE,
    window="reversible",  # Restore is one click away (D2)
    label="Archive",
    execute=_ideas_archive,
    exists=_idea_exists,
)
IDEAS_DELETE = DeferredActionDef(
    key="ideation_ideas.delete",
    entity_type="ideation_idea",
    permission=MANAGE,
    window="destructive",
    label="Delete",
    execute=_ideas_delete,
    exists=_idea_exists,
)


# ---- business requirements ------------------------------------------------


def _br_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import BusinessRequirement

    return (
        db.query(BusinessRequirement.id)
        .filter(BusinessRequirement.id == entity_id, BusinessRequirement.tenant_id == tenant_id)
        .first()
        is not None
    )


def _br_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.business_requirements import BusinessRequirementService

    BusinessRequirementService(db).delete(tenant_id, entity_id)


BR_DELETE = DeferredActionDef(
    key="ideation_business_requirements.delete",
    entity_type="ideation_business_requirement",
    permission=BR_MANAGE,
    window="destructive",
    label="Delete",
    execute=_br_delete,
    exists=_br_exists,
)


# ---- BR <-> idea link (the "Unlink idea" action, a composite key) ---------

# The unlink target isn't a single BR - it's ONE (br_id, idea_id) link row.
# `entity_id` carries the composite `f"{brId}:{ideaId}"` (park time), unpacked
# at execute/exists time - the grace-window engine's `entity_id` is a bare
# string column, so this is the same "encode a composite key" pattern the
# park caller controls end to end (no new engine column needed for one link).


def _unlink_key(entity_id: str) -> tuple[str, str]:
    br_id, _, idea_id = entity_id.partition(":")
    return br_id, idea_id


def _br_idea_link_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .models import IdeaBusinessRequirement

    br_id, idea_id = _unlink_key(entity_id)
    return (
        db.query(IdeaBusinessRequirement.id)
        .filter(
            IdeaBusinessRequirement.tenant_id == tenant_id,
            IdeaBusinessRequirement.business_requirement_id == br_id,
            IdeaBusinessRequirement.idea_id == idea_id,
        )
        .first()
        is not None
    )


def _br_idea_unlink(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.business_requirements import BusinessRequirementService

    br_id, idea_id = _unlink_key(entity_id)
    BusinessRequirementService(db).unlink_idea(tenant_id, br_id, idea_id)


BR_IDEA_UNLINK = DeferredActionDef(
    key="ideation_business_requirements.unlink_idea",
    entity_type="ideation_br_idea_link",
    permission=BR_MANAGE,
    window="reversible",  # re-linking is a click away
    label="Unlink",
    execute=_br_idea_unlink,
    exists=_br_idea_link_exists,
)


# ---- embed connections -----------------------------------------------------


def _embed_connection_exists(db: Session, tenant_id: str, entity_id: str) -> bool:
    from .services.embed import get_connection

    return get_connection(db, connection_id=entity_id, tenant_id=tenant_id) is not None


def _embed_connection_delete(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.embed import delete_connection

    if not delete_connection(db, connection_id=entity_id, tenant_id=tenant_id):
        raise ValueError("Embed connection no longer exists.")


def _embed_connection_set_active(db: Session, tenant_id: str, entity_id: str, payload: dict, actor_user_id: str) -> None:
    from .services.embed import update_connection_fields

    if update_connection_fields(db, connection_id=entity_id, tenant_id=tenant_id, is_active=bool(payload.get("isActive"))) is None:
        raise ValueError("Embed connection no longer exists.")


EMBED_CONNECTIONS_DELETE = DeferredActionDef(
    key="ideation_embed_connections.delete",
    entity_type="ideation_embed_connection",
    permission=MANAGE,
    window="destructive",
    label="Delete",
    execute=_embed_connection_delete,
    exists=_embed_connection_exists,
)
EMBED_CONNECTIONS_SET_ACTIVE = DeferredActionDef(
    key="ideation_embed_connections.set_active",
    entity_type="ideation_embed_connection",
    permission=MANAGE,
    window="reversible",
    label="Change connection status",
    execute=_embed_connection_set_active,
    exists=_embed_connection_exists,
)

_ALL = (
    IDEAS_ARCHIVE,
    IDEAS_DELETE,
    BR_DELETE,
    BR_IDEA_UNLINK,
    EMBED_CONNECTIONS_DELETE,
    EMBED_CONNECTIONS_SET_ACTIVE,
)


def register_ideation_deferred_actions() -> None:
    for action_def in _ALL:
        register_deferred_action(action_def)
