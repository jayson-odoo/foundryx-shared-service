"""Idea portal (lane IDEA-PORTAL) - the signed-in Canny-style portal.

Plan + contract: ``documentation/plans/sprint-5/idea-portal/``
(``acceptance-criteria.md`` AC-P-xx, ``behaviour-card.md`` Q1..Q5).

WHO (owner ruling 13 Oct: sign-in required, no anonymous voting/commenting).
Every portal request carries a PORTAL token: a JWT signed with a key DERIVED
from ``settings.jwt_secret`` (HMAC, own label) - so a portal token can never
authenticate a staff endpoint (core ``decode_access_token`` uses the raw
secret) and a core JWT can never authenticate the portal. Three exchanges mint
one, each tenant-bound by its own credential (never client input):

- ``staff``   - a shared-service user (core login) holding ``ideation.ideas.view``;
- ``crm``     - a Sorento CRM user arriving through the ideation embed SSO (the
                embed token's ``sub``/``name``/``phone``/product scope);
- ``contact`` - a WhatsApp submitter: the chatbot link's ``status_token`` PLUS
                the last 4 digits of the submitter contact's WhatsApp number
                (Q1 option b). Throttled per link + per IP; uniform 401.

Every resolve re-checks liveness (tenant sign-in, ideation module ACTIVE, the
user / contact / embed connection still exists), so suspending a tenant or
disabling the module kills live portal sessions on the next request.

WHAT (visibility, AC-P-10/11): tenant-scoped; never draft (``is_initial``),
``is_test`` or merged children (a merged child's page resolves to its
survivor, scoped by the child's own tenant); ``portal_hidden`` ideas only for
staff and their own submitter; a product-scoped embed connection sees only its
product. Off-ramp statuses (``is_archived`` and not mapped) are left out of the
roadmap and only listed with ``includeClosed``.

Roadmap columns (Q2) are a code default keyed on the PLATFORM status keys (a
tenant fork copies keys verbatim); a status outside the map that is neither
initial nor archived gets its OWN column at its sort position, so nothing ever
disappears when a tenant adds a status.
"""
import hashlib
import hmac
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from jose import JWTError, jwt
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.config import settings
from app.models.catalog import Product
from app.models.status import Status
from app.models.tenant import Tenant
from app.models.user import User
from modules.omnichannel.models import Contact
from modules.omnichannel.phone import digits_only

from ..models import (
    Idea,
    IdeaActivity,
    IdeaComment,
    IdeaCommentLike,
    IdeaStatusEvent,
    IdeaVote,
)
from .comments import AUTHOR_EMBED, AUTHOR_USER, CommentViewer, IdeaCommentService
from .ownership import SubmitterIdentity, owned_filter, owned_ids
from .public_status import PublicIdeaStatusService, project_first_name
from .statuses import IDEA_ENTITY

PORTAL_TYP = "idea_portal"
PORTAL_AUD = "ideation-portal"
PORTAL_TTL = timedelta(days=30)

KIND_STAFF = "staff"
KIND_CRM = "crm"
KIND_CONTACT = "contact"
ROLE_BY_KIND = {KIND_STAFF: "Staff", KIND_CRM: "Member", KIND_CONTACT: "Dealer"}

# Portal comments by a WhatsApp contact (``IdeaComment.author_kind``).
AUTHOR_CONTACT = "contact"
ROLE_BY_AUTHOR_KIND = {AUTHOR_USER: "Staff", AUTHOR_EMBED: "Member", AUTHOR_CONTACT: "Dealer"}

VIEW_PERMISSION = "ideation.ideas.view"

# (column key, title, colour, platform status keys) - Q2.
DEFAULT_COLUMNS: Tuple[Tuple[str, str, str, Tuple[str, ...]], ...] = (
    ("under_review", "Under review", "blue", ("captured", "triaged")),
    ("planned", "Planned", "violet", ("linked",)),
    ("in_progress", "In progress", "amber", ("building",)),
    ("complete", "Complete", "green", ("delivered", "closed")),
)
_KEY_TO_COLUMN = {k: col for col, _t, _c, keys in DEFAULT_COLUMNS for k in keys}
CLOSED_COLUMN = "closed"
CHANGELOG_STATUS_KEYS = ("delivered",)

# IDEA-CORE fields (owner ruling 13 Oct). Read defensively: a column once
# IDEA-CORE ships it, else the captured_json answer, else null.
CORE_FIELDS = (
    ("desiredOutcome", "desired_outcome"),
    ("useCases", "use_cases"),
    ("currentWorkaround", "current_workaround"),
)

MAX_PAGE_SIZE = 100


class PortalError(Exception):
    """A typed refusal - the router emits ``{error:{code,message}}``."""

    def __init__(self, status_code: int, code: str, message: str, retry_after: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retry_after = retry_after


def _unauthorized() -> PortalError:
    return PortalError(401, "unauthorized", "Sign in to continue.")


def _not_found() -> PortalError:
    return PortalError(404, "not_found", "Idea not found.")


LINK_REJECTED = PortalError(401, "link_rejected", "That number does not match this link.")


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── principal + token ─────────────────────────────────────────────────────────


@dataclass
class PortalPrincipal:
    tenant_id: str
    kind: str
    subject: str
    name: Optional[str] = None
    product_id: Optional[str] = None
    phone: Optional[str] = None
    connection_id: Optional[str] = None

    @property
    def role(self) -> str:
        return ROLE_BY_KIND[self.kind]

    @property
    def is_staff(self) -> bool:
        return self.kind == KIND_STAFF

    @property
    def voter_id(self) -> str:
        """One namespace per kind. Staff = the bare user id and crm =
        ``embed-user:<sub>`` - the SAME ids the operator board and the embed
        iframe already vote with, so a person's vote is one vote everywhere."""
        if self.kind == KIND_STAFF:
            return self.subject
        if self.kind == KIND_CRM:
            return f"embed-user:{self.subject}"
        return f"contact:{self.subject}"

    @property
    def identity(self) -> SubmitterIdentity:
        return SubmitterIdentity(
            crm_user_id=self.subject if self.kind == KIND_CRM else None, phone=self.phone
        )

    @property
    def comment_kind(self) -> str:
        return {KIND_STAFF: AUTHOR_USER, KIND_CRM: AUTHOR_EMBED}.get(self.kind, AUTHOR_CONTACT)

    @property
    def viewer(self) -> CommentViewer:
        return CommentViewer(kind=self.comment_kind, id=self.voter_id, can_moderate=self.is_staff)


def _signing_key() -> str:
    return hmac.new(
        settings.jwt_secret.encode("utf-8"), b"ideation-portal-token-v1", hashlib.sha256
    ).hexdigest()


def mint_portal_token(p: PortalPrincipal, extra: Optional[Dict[str, Any]] = None) -> str:
    now = _now()
    claims: Dict[str, Any] = dict(extra or {})
    claims.update({
        "typ": PORTAL_TYP,
        "aud": PORTAL_AUD,
        "tenant_id": p.tenant_id,
        "kind": p.kind,
        "sub": p.subject,
        "pid": p.product_id,
        "cid": p.connection_id,
        "iat": int(now.timestamp()),
        "exp": int((now + PORTAL_TTL).timestamp()),
    })
    return jwt.encode(claims, _signing_key(), algorithm="HS256")


first_name = project_first_name


def _module_active(db: Session, tenant_id: str) -> bool:
    from app.repositories.module_repository import ModuleRepository

    return ModuleRepository(db).is_active(tenant_id, "ideation")


def _tenant_ok(db: Session, tenant_id: str) -> bool:
    tenant = db.query(Tenant).filter(Tenant.id == tenant_id).first()
    return tenant is not None and tenant.signin_allowed and _module_active(db, tenant_id)


def _staff_user(db: Session, tenant_id: str, user_id: str) -> Optional[User]:
    from app.dependencies import effective_permission_keys
    from app.models.user import UserStatus
    from app.repositories.user_repository import UserRepository

    user = UserRepository(db).get_by_id(user_id, tenant_id)
    if user is None or user.status != UserStatus.ACTIVE.value:
        return None
    if VIEW_PERMISSION not in effective_permission_keys(user):
        return None
    return user


def _contact(db: Session, tenant_id: str, contact_id: str) -> Optional[Contact]:
    return (
        db.query(Contact)
        .filter(Contact.id == contact_id, Contact.tenant_id == tenant_id)
        .first()
    )


def resolve_portal_token(db: Session, token: str) -> PortalPrincipal:
    try:
        claims = jwt.decode(token, _signing_key(), algorithms=["HS256"], audience=PORTAL_AUD)
    except JWTError:
        raise _unauthorized()
    if claims.get("typ") != PORTAL_TYP:
        raise _unauthorized()
    tenant_id, kind, sub = claims.get("tenant_id"), claims.get("kind"), claims.get("sub")
    if not tenant_id or not sub or kind not in ROLE_BY_KIND:
        raise _unauthorized()
    if not _tenant_ok(db, tenant_id):
        raise _unauthorized()

    p = PortalPrincipal(tenant_id=tenant_id, kind=kind, subject=sub, product_id=claims.get("pid"))
    if kind == KIND_STAFF:
        user = _staff_user(db, tenant_id, sub)
        if user is None:
            raise _unauthorized()
        p.name = first_name(user.name) or "Staff"
    elif kind == KIND_CONTACT:
        contact = _contact(db, tenant_id, sub)
        if contact is None:
            raise _unauthorized()
        p.phone = contact.phone
        p.name = first_name(contact.first_name) or "Dealer"
    else:
        from ..models import EmbedConnection

        conn = (
            db.query(EmbedConnection)
            .filter(
                EmbedConnection.connection_id == claims.get("cid"),
                EmbedConnection.tenant_id == tenant_id,
            )
            .first()
        )
        if conn is None or not conn.is_active:
            raise _unauthorized()
        p.connection_id = conn.connection_id
        p.product_id = conn.product_id
        # The CRM user's name/phone ride the token (signed by us at exchange).
        p.name = claims.get("nm") or "Member"
        p.phone = claims.get("ph")
    return p


# ── sessions ──────────────────────────────────────────────────────────────────


def _session_out(p: PortalPrincipal, extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"token": mint_portal_token(p, extra), "principal": principal_out(p)}


def principal_out(p: PortalPrincipal) -> Dict[str, Any]:
    return {"kind": p.kind, "name": p.name, "role": p.role, "productId": p.product_id}


def session_for_staff(db: Session, user: User) -> Dict[str, Any]:
    if not _tenant_ok(db, user.tenant_id):
        raise PortalError(403, "module_inactive", "Ideas are not available.")
    if _staff_user(db, user.tenant_id, user.id) is None:
        raise PortalError(403, "forbidden", "You do not have access to ideas.")
    p = PortalPrincipal(
        tenant_id=user.tenant_id, kind=KIND_STAFF, subject=user.id, name=first_name(user.name) or "Staff"
    )
    return _session_out(p)


def session_for_embed(db: Session, embed_token: str) -> Dict[str, Any]:
    from .embed import IdeationEmbedError, resolve_embed_token

    try:
        ep = resolve_embed_token(db, embed_token)
    except IdeationEmbedError:
        raise _unauthorized()
    sub = (ep.sub or "").strip()
    if not sub or not _tenant_ok(db, ep.tenant_id):
        raise _unauthorized()
    name = first_name(ep.name) or "Member"
    p = PortalPrincipal(
        tenant_id=ep.tenant_id,
        kind=KIND_CRM,
        subject=sub,
        name=name,
        product_id=ep.product_id,
        phone=ep.phone,
        connection_id=ep.connection_id,
    )
    return _session_out(p, extra={"nm": name, "ph": ep.phone})


def session_for_link(db: Session, *, token: str, last4: str, ip: str) -> Dict[str, Any]:
    """Q1 (b): the chatbot link token + the last 4 digits of the submitter
    contact's WhatsApp number. Every non-servable case is the SAME 401 so the
    response never tells a draft from a wrong number from an unknown link."""
    from app.services.throttle import Throttled, ThrottleService

    throttle = ThrottleService(db)
    token_key = hashlib.sha256((token or "").encode("utf-8")).hexdigest()
    try:
        throttle.enforce_idea_portal_link(ip=ip, token_key=token_key)
    except Throttled as exc:
        raise PortalError(
            429, "too_many_attempts", "Too many attempts. Try again later.", exc.retry_after_seconds
        )

    idea = PublicIdeaStatusService(db).resolve_idea(token)
    contact = (
        _contact(db, idea.tenant_id, idea.submitter_contact_id)
        if idea is not None and idea.submitter_contact_id
        else None
    )
    digits = digits_only(contact.phone) if contact is not None else ""
    ok = (
        contact is not None
        and len(digits) >= 4
        and hmac.compare_digest(digits[-4:], last4)
        and _tenant_ok(db, idea.tenant_id)
    )
    if not ok:
        throttle.record_idea_portal_link_failure(ip=ip, token_key=token_key)
        raise LINK_REJECTED
    throttle.reset_idea_portal_link(token_key=token_key)
    p = PortalPrincipal(
        tenant_id=idea.tenant_id,
        kind=KIND_CONTACT,
        subject=contact.id,
        name=first_name(contact.first_name) or "Dealer",
        phone=contact.phone,
    )
    out = _session_out(p)
    # The idea the link addressed - the survivor for a merged child.
    out["ideaId"] = idea.merged_into_id or idea.id
    return out


# ── status map ────────────────────────────────────────────────────────────────


@dataclass
class _Column:
    key: str
    title: str
    color: str
    position: float
    status_ids: Set[str] = field(default_factory=set)


@dataclass
class _StatusMap:
    by_id: Dict[str, Status]
    columns: List[_Column]  # roadmap columns, ordered
    column_of: Dict[str, str]  # status id -> column key
    initial_ids: Set[str]
    offramp_ids: Set[str]

    def column(self, status_id: str) -> Optional[str]:
        if status_id in self.column_of:
            return self.column_of[status_id]
        if status_id in self.offramp_ids:
            return CLOSED_COLUMN
        return None


def _status_map(db: Session, tenant_id: str) -> _StatusMap:
    rows = (
        db.query(Status)
        .filter(
            Status.entity_type == IDEA_ENTITY,
            or_(Status.tenant_id == tenant_id, Status.tenant_id.is_(None)),
        )
        .all()
    )
    by_id = {r.id: r for r in rows}
    columns: Dict[str, _Column] = {}
    for i, (key, title, color, _keys) in enumerate(DEFAULT_COLUMNS):
        columns[key] = _Column(key=key, title=title, color=color, position=float("inf"))
    column_of: Dict[str, str] = {}
    initial_ids: Set[str] = set()
    offramp_ids: Set[str] = set()
    for r in rows:
        if r.is_initial:
            initial_ids.add(r.id)
            continue
        col = _KEY_TO_COLUMN.get(r.key)
        if col is not None:
            column_of[r.id] = col
            columns[col].status_ids.add(r.id)
            columns[col].position = min(columns[col].position, float(r.sort_order or 0))
        elif r.is_archived:
            offramp_ids.add(r.id)
        else:
            key = f"status:{r.key}"
            if key not in columns:
                columns[key] = _Column(
                    key=key, title=r.label, color=r.color or "gray",
                    position=float(r.sort_order or 0) + 0.5,
                )
            columns[key].status_ids.add(r.id)
            column_of[r.id] = key
    # A default column with no status row anywhere keeps its seed order.
    for i, (key, *_rest) in enumerate(DEFAULT_COLUMNS):
        if columns[key].position == float("inf"):
            columns[key].position = float(i + 2)
    ordered = sorted(columns.values(), key=lambda c: c.position)
    return _StatusMap(by_id, ordered, column_of, initial_ids, offramp_ids)


# ── the service ───────────────────────────────────────────────────────────────


class IdeaPortalService:
    def __init__(self, db: Session, principal: PortalPrincipal):
        self.db = db
        self.p = principal
        self._smap: Optional[_StatusMap] = None

    @property
    def smap(self) -> _StatusMap:
        if self._smap is None:
            self._smap = _status_map(self.db, self.p.tenant_id)
        return self._smap

    # ---- visibility -------------------------------------------------------

    def _visible(self, q=None, *, include_closed: bool = False):
        p = self.p
        q = q if q is not None else self.db.query(Idea)
        q = q.filter(
            Idea.tenant_id == p.tenant_id,
            Idea.is_test.is_(False),
            Idea.merged_into_id.is_(None),
        )
        allowed = set(self.smap.column_of)
        if include_closed:
            allowed |= self.smap.offramp_ids
        q = q.filter(Idea.status_id.in_(allowed or {"-"}))
        if p.product_id:
            q = q.filter(Idea.product_id == p.product_id)
        if not p.is_staff:
            owned = owned_filter(self.db, self.db.query(Idea.id), p.tenant_id, p.identity)
            q = q.filter(or_(Idea.portal_hidden.is_(False), Idea.id.in_(owned.subquery())))
        return q

    def _resolve(self, idea_id: str, *, follow_merge: bool) -> Idea:
        """A visible idea by id, or 404. ``follow_merge``: a merged child
        resolves to its survivor (scoped by the child's own tenant); without
        it a merged child is a 409 (writes always target the survivor)."""
        row = (
            self.db.query(Idea)
            .filter(Idea.id == idea_id, Idea.tenant_id == self.p.tenant_id, Idea.is_test.is_(False))
            .first()
        )
        if row is None:
            raise _not_found()
        if row.merged_into_id:
            if not follow_merge:
                raise PortalError(409, "merged", "This idea was merged into another idea.")
            idea_id = row.merged_into_id
        idea = self._visible(include_closed=True).filter(Idea.id == idea_id).first()
        if idea is None:
            raise _not_found()
        return idea

    # ---- cards ------------------------------------------------------------

    def _cards(self, ideas: Sequence[Idea]) -> List[Dict[str, Any]]:
        ids = [i.id for i in ideas]
        if not ids:
            return []
        counts = dict(
            self.db.query(IdeaComment.idea_id, func.count(IdeaComment.id))
            .filter(
                IdeaComment.idea_id.in_(ids),
                IdeaComment.tenant_id == self.p.tenant_id,
                IdeaComment.deleted_at.is_(None),
            )
            .group_by(IdeaComment.idea_id)
            .all()
        )
        voted = {
            r[0]
            for r in self.db.query(IdeaVote.idea_id)
            .filter(
                IdeaVote.idea_id.in_(ids),
                IdeaVote.voter_id == self.p.voter_id,
                IdeaVote.dir == "up",
            )
            .all()
        }
        mine = owned_ids(self.db, self.p.tenant_id, ids, self.p.identity)
        products = self._product_names({i.product_id for i in ideas})
        out = []
        for i in ideas:
            st = self.smap.by_id.get(i.status_id)
            out.append(
                {
                    "id": i.id,
                    "ideaNumber": i.idea_number,
                    "title": (i.title or i.problem or "").strip(),
                    "upvotes": i.upvotes or 0,
                    "commentCount": counts.get(i.id, 0),
                    "isMine": i.id in mine,
                    "myVote": i.id in voted,
                    "column": self.smap.column(i.status_id),
                    "statusLabel": st.label if st else None,
                    "statusColor": st.color if st else None,
                    "productName": products.get(i.product_id),
                    "submittedAt": i.created_at,
                }
            )
        return out

    def _product_names(self, ids: Iterable[str]) -> Dict[str, str]:
        ids = [i for i in ids if i]
        if not ids:
            return {}
        rows = (
            self.db.query(Product.id, Product.name)
            .filter(Product.id.in_(ids), Product.tenant_id == self.p.tenant_id)
            .all()
        )
        return dict(rows)

    def _mine_filter(self, q):
        return owned_filter(self.db, q, self.p.tenant_id, self.p.identity)

    # ---- roadmap / feedback / changelog ------------------------------------

    def roadmap(self, *, product_id: Optional[str] = None, mine: bool = False) -> Dict[str, Any]:
        q = self._visible()
        if product_id:
            q = q.filter(Idea.product_id == product_id)
        if mine:
            q = self._mine_filter(q)
        ideas = q.order_by(Idea.upvotes.desc(), Idea.created_at.desc(), Idea.id.asc()).all()
        cards = self._cards(ideas)
        columns = []
        for col in self.smap.columns:
            columns.append(
                {
                    "key": col.key,
                    "title": col.title,
                    "color": col.color,
                    "ideas": [c for c in cards if c["column"] == col.key],
                }
            )
        return {"columns": columns}

    def list(
        self,
        *,
        q: Optional[str] = None,
        columns: Optional[List[str]] = None,
        sort: str = "top",
        mine: bool = False,
        product_id: Optional[str] = None,
        include_closed: bool = False,
        page: int = 1,
        page_size: int = 25,
    ) -> Dict[str, Any]:
        query = self._visible(include_closed=include_closed)
        if product_id:
            query = query.filter(Idea.product_id == product_id)
        if mine:
            query = self._mine_filter(query)
        if q and q.strip():
            like = f"%{q.strip().lower()}%"
            query = query.filter(
                or_(func.lower(func.coalesce(Idea.title, "")).like(like), func.lower(Idea.problem).like(like))
            )
        if columns:
            wanted: Set[str] = set()
            for key in columns:
                if key == CLOSED_COLUMN:
                    wanted |= self.smap.offramp_ids
                for col in self.smap.columns:
                    if col.key == key:
                        wanted |= col.status_ids
            query = query.filter(Idea.status_id.in_(wanted or {"-"}))
        total = query.count()
        if sort == "new":
            query = query.order_by(Idea.created_at.desc(), Idea.id.desc())
        else:
            query = query.order_by(Idea.upvotes.desc(), Idea.created_at.desc(), Idea.id.asc())
        rows = query.offset((page - 1) * page_size).limit(page_size).all()
        return {"items": self._cards(rows), "total": total, "page": page, "pageSize": page_size}

    def changelog(self) -> Dict[str, Any]:
        delivered = {
            sid for sid, st in self.smap.by_id.items() if st.key in CHANGELOG_STATUS_KEYS
        }
        ideas = self._visible().filter(Idea.status_id.in_(delivered or {"-"})).all()
        ids = [i.id for i in ideas]
        last_move = dict(
            self.db.query(IdeaActivity.idea_id, func.max(IdeaActivity.created_at))
            .filter(IdeaActivity.idea_id.in_(ids or ["-"]), IdeaActivity.tenant_id == self.p.tenant_id)
            .group_by(IdeaActivity.idea_id)
            .all()
        )
        cards = self._cards(ideas)
        for c, i in zip(cards, ideas):
            c["deliveredAt"] = last_move.get(i.id) or i.updated_at or i.created_at
        cards.sort(key=lambda c: c["deliveredAt"], reverse=True)
        return {"items": cards}

    # ---- idea page ---------------------------------------------------------

    def _core_field(self, idea: Idea, attr: str) -> Optional[str]:
        value = getattr(idea, attr, None)
        if not value:
            value = (idea.captured_json or {}).get(attr)
        return value or None

    def _timeline(self, idea: Idea) -> List[Dict[str, Any]]:
        current = self.smap.column(idea.status_id)
        cols = self.smap.columns
        idx = next((i for i, c in enumerate(cols) if c.key == current), None)
        if idx is None:
            st = self.smap.by_id.get(idea.status_id)
            steps = [{"key": cols[0].key, "label": cols[0].title, "color": cols[0].color, "state": "done"}] if cols else []
            steps.append({"key": CLOSED_COLUMN, "label": st.label if st else "Closed", "color": (st.color if st and st.color else "gray"), "state": "current"})
            return steps
        return [
            {
                "key": c.key,
                "label": c.title,
                "color": c.color,
                "state": "done" if i < idx else "current" if i == idx else "upcoming",
            }
            for i, c in enumerate(cols)
        ]

    def detail(self, idea_id: str) -> Dict[str, Any]:
        idea = self._resolve(idea_id, follow_merge=True)
        card = self._cards([idea])[0]
        out = {
            **card,
            "problem": idea.problem,
            "submitterFirstName": PublicIdeaStatusService(self.db)._first_name(idea),
            "timeline": self._timeline(idea),
            "portalHidden": bool(idea.portal_hidden) if self.p.is_staff else None,
        }
        for wire, attr in CORE_FIELDS:
            out[wire] = self._core_field(idea, attr)
        return out

    def set_hidden(self, idea_id: str, hidden: bool) -> Dict[str, Any]:
        """Q5: staff hide/show an idea on the portal."""
        if not self.p.is_staff:
            raise PortalError(403, "forbidden", "Only staff can change this.")
        idea = self._resolve(idea_id, follow_merge=False)
        idea.portal_hidden = bool(hidden)
        self.db.commit()
        return self.detail(idea.id)

    # ---- votes -------------------------------------------------------------

    def vote(self, idea_id: str) -> Dict[str, Any]:
        from .actions import IdeaActionService

        idea = self._resolve(idea_id, follow_merge=False)
        existing = (
            self.db.query(IdeaVote)
            .filter(IdeaVote.idea_id == idea.id, IdeaVote.voter_id == self.p.voter_id)
            .first()
        )
        if existing is not None and existing.dir == "up":
            self.db.delete(existing)
        elif existing is not None:
            existing.dir = "up"
            existing.voter_name, existing.voter_role = self.p.name, self.p.role
        else:
            self.db.add(
                IdeaVote(
                    tenant_id=idea.tenant_id,
                    idea_id=idea.id,
                    voter_id=self.p.voter_id,
                    dir="up",
                    voter_name=self.p.name,
                    voter_role=self.p.role,
                    created_at=_now(),
                )
            )
        self.db.flush()
        IdeaActionService(self.db)._recount(idea)
        self.db.commit()
        self.db.refresh(idea)
        voted = existing is None or existing.dir != "up"
        return {"id": idea.id, "upvotes": idea.upvotes or 0, "myVote": voted}

    @staticmethod
    def _role_for_voter(voter_id: str, stored: Optional[str]) -> str:
        if stored:
            return stored
        if voter_id.startswith("contact:"):
            return "Dealer"
        if voter_id.startswith("embed"):
            return "Member"
        return "Staff"

    def voters(self, idea_id: str) -> List[Dict[str, Any]]:
        idea = self._resolve(idea_id, follow_merge=True)
        rows = (
            self.db.query(IdeaVote)
            .filter(IdeaVote.idea_id == idea.id, IdeaVote.tenant_id == idea.tenant_id, IdeaVote.dir == "up")
            .order_by(IdeaVote.created_at.desc(), IdeaVote.id.asc())
            .all()
        )
        # Votes cast outside the portal carry no name: staff ids resolve to the
        # user's first name (tenant-scoped), the rest show their role only.
        staff_ids = [r.voter_id for r in rows if not r.voter_name and ":" not in r.voter_id]
        names = {}
        if staff_ids:
            names = {
                u.id: first_name(u.name)
                for u in self.db.query(User).filter(User.id.in_(staff_ids), User.tenant_id == idea.tenant_id)
            }
        return [
            {
                "name": first_name(r.voter_name) if r.voter_name else names.get(r.voter_id),
                "role": self._role_for_voter(r.voter_id, r.voter_role),
                "isMe": r.voter_id == self.p.voter_id,
            }
            for r in rows
        ]

    # ---- comments ----------------------------------------------------------

    def _comment_rows(self, idea: Idea) -> List[Dict[str, Any]]:
        rows = IdeaCommentService(self.db).list(
            idea.tenant_id, idea.id, self.p.viewer, project_names=True
        )
        ids = [r.id for r in rows]
        counts = dict(
            self.db.query(IdeaCommentLike.comment_id, func.count(IdeaCommentLike.id))
            .filter(IdeaCommentLike.comment_id.in_(ids or ["-"]), IdeaCommentLike.tenant_id == idea.tenant_id)
            .group_by(IdeaCommentLike.comment_id)
            .all()
        )
        liked = {
            r[0]
            for r in self.db.query(IdeaCommentLike.comment_id)
            .filter(IdeaCommentLike.comment_id.in_(ids or ["-"]), IdeaCommentLike.liker_id == self.p.voter_id)
            .all()
        }
        out = []
        for r in rows:
            d = r.model_dump()
            d["authorRole"] = ROLE_BY_AUTHOR_KIND.get(r.authorKind, "Member")
            d["likeCount"] = counts.get(r.id, 0)
            d["likedByMe"] = r.id in liked
            out.append(d)
        return out

    def comments(self, idea_id: str) -> List[Dict[str, Any]]:
        return self._comment_rows(self._resolve(idea_id, follow_merge=True))

    def add_comment(self, idea_id: str, *, body: str, parent_id: Optional[str]) -> Dict[str, Any]:
        from app.services.throttle import Throttled, ThrottleService

        idea = self._resolve(idea_id, follow_merge=False)
        throttle = ThrottleService(self.db)
        key = hashlib.sha256(f"{self.p.tenant_id}:{self.p.voter_id}".encode("utf-8")).hexdigest()
        try:
            throttle.enforce_idea_portal_comment(principal_key=key)
        except Throttled as exc:
            raise PortalError(429, "too_many_comments", "Too many comments. Try again later.", exc.retry_after_seconds)
        created = IdeaCommentService(self.db).create(
            idea.tenant_id,
            idea.id,
            body=body,
            parent_id=parent_id,
            author_kind=self.p.comment_kind,
            author_id=self.p.voter_id,
            author_name=self.p.name,
            viewer=self.p.viewer,
        )
        throttle.record_idea_portal_comment(principal_key=key)
        d = created.model_dump()
        d.update(authorRole=self.p.role, likeCount=0, likedByMe=False)
        return d

    def delete_comment(self, idea_id: str, comment_id: str) -> None:
        idea = self._resolve(idea_id, follow_merge=True)
        IdeaCommentService(self.db).delete(
            idea.tenant_id, idea.id, comment_id, viewer=self.p.viewer, can_comment=True
        )

    def toggle_like(self, idea_id: str, comment_id: str) -> Dict[str, Any]:
        idea = self._resolve(idea_id, follow_merge=True)
        comment = (
            self.db.query(IdeaComment)
            .filter(
                IdeaComment.id == comment_id,
                IdeaComment.idea_id == idea.id,
                IdeaComment.tenant_id == idea.tenant_id,
                IdeaComment.deleted_at.is_(None),
            )
            .first()
        )
        if comment is None:
            raise PortalError(404, "not_found", "Comment not found.")
        existing = (
            self.db.query(IdeaCommentLike)
            .filter(IdeaCommentLike.comment_id == comment.id, IdeaCommentLike.liker_id == self.p.voter_id)
            .first()
        )
        if existing is not None:
            self.db.delete(existing)
        else:
            self.db.add(
                IdeaCommentLike(
                    tenant_id=idea.tenant_id,
                    idea_id=idea.id,
                    comment_id=comment.id,
                    liker_id=self.p.voter_id,
                    liker_name=self.p.name,
                    created_at=_now(),
                )
            )
        self.db.commit()
        count = (
            self.db.query(func.count(IdeaCommentLike.id))
            .filter(IdeaCommentLike.comment_id == comment.id)
            .scalar()
        )
        return {"likeCount": int(count or 0), "likedByMe": existing is None}

    # ---- activity ----------------------------------------------------------

    def activity(self, idea_id: str, *, order: str = "desc") -> List[Dict[str, Any]]:
        idea = self._resolve(idea_id, follow_merge=True)
        events: List[Tuple[datetime, int, Dict[str, Any]]] = []
        events.append(
            (
                idea.created_at,
                0,
                {
                    "kind": "submitted",
                    "at": idea.created_at,
                    "by": PublicIdeaStatusService(self.db)._first_name(idea),
                    "source": idea.source,
                },
            )
        )
        for a in (
            self.db.query(IdeaActivity)
            .filter(IdeaActivity.idea_id == idea.id, IdeaActivity.tenant_id == idea.tenant_id)
            .all()
        ):
            events.append(
                (a.created_at, 1, {"kind": a.kind, "at": a.created_at, "fromLabel": a.from_label, "toLabel": a.to_label, "toColor": a.to_color})
            )
        comments = self._comment_rows(idea)
        replies: Dict[str, List[Dict[str, Any]]] = {}
        for c in comments:
            if c["parentId"]:
                replies.setdefault(c["parentId"], []).append(c)
        for c in comments:
            if not c["parentId"]:
                events.append((c["createdAt"], 1, {"kind": "comment", "at": c["createdAt"], "comment": c, "replies": replies.get(c["id"], [])}))
        # Upvotes grouped per UTC day (newest vote of the day as its time).
        by_day: Dict[str, List[IdeaVote]] = {}
        for v in (
            self.db.query(IdeaVote)
            .filter(IdeaVote.idea_id == idea.id, IdeaVote.tenant_id == idea.tenant_id, IdeaVote.dir == "up")
            .all()
        ):
            by_day.setdefault(v.created_at.astimezone(timezone.utc).date().isoformat(), []).append(v)
        for day, votes in by_day.items():
            at = max(v.created_at for v in votes)
            names = [first_name(v.voter_name) for v in votes if v.voter_name]
            events.append((at, 1, {"kind": "upvotes", "at": at, "day": day, "count": len(votes), "names": [n for n in names if n][:3]}))
        live = {c["id"]: c for c in comments if not c["isDeleted"]}
        for like in (
            self.db.query(IdeaCommentLike)
            .filter(IdeaCommentLike.idea_id == idea.id, IdeaCommentLike.tenant_id == idea.tenant_id)
            .all()
        ):
            if like.comment_id in live:
                events.append(
                    (like.created_at, 1, {"kind": "comment_like", "at": like.created_at, "by": first_name(like.liker_name), "commentId": like.comment_id})
                )

        def _key(e):
            at = e[0]
            if at is not None and at.tzinfo is None:
                at = at.replace(tzinfo=timezone.utc)
            return (at or datetime.min.replace(tzinfo=timezone.utc), e[1])

        events.sort(key=_key, reverse=(order != "asc"))
        return [e[2] for e in events]

    # ---- products + submit -------------------------------------------------

    def products(self) -> List[Dict[str, Any]]:
        q = self.db.query(Product).filter(
            Product.tenant_id == self.p.tenant_id,
            Product.kind == "software",
            Product.is_deleted.is_(False),
            Product.is_active.is_(True),
        )
        if self.p.product_id:
            q = q.filter(Product.id == self.p.product_id)
        return [{"id": r.id, "name": r.name} for r in q.order_by(Product.name.asc()).all()]

    def submit(
        self,
        *,
        title: str,
        problem: str,
        product_id: Optional[str],
        desired_outcome: Optional[str] = None,
        use_cases: Optional[str] = None,
        current_workaround: Optional[str] = None,
    ) -> Dict[str, Any]:
        from .actions import IdeaActionService
        from .numbering import mint_idea_identity

        p = self.p
        product_id = p.product_id or product_id
        if not product_id or product_id not in {x["id"] for x in self.products()}:
            raise PortalError(422, "invalid_product", "Choose a product.")
        actor = _staff_user(self.db, p.tenant_id, p.subject) if p.is_staff else None
        out = IdeaActionService(self.db).create_operator(
            p.tenant_id,
            product_id=product_id,
            problem=problem,
            source="portal",
            actor=actor,
            submitter_crm_user_id=p.subject if p.kind == KIND_CRM else None,
            submitter_name=p.name if p.kind == KIND_CRM else None,
        )
        idea = self.db.query(Idea).filter(Idea.id == out.id, Idea.tenant_id == p.tenant_id).first()
        idea.title = title.strip()
        if p.kind == KIND_CONTACT:
            idea.submitter_contact_id = p.subject
            idea.submitter_name = None
        captured = dict(idea.captured_json or {})
        for value, attr in (
            (desired_outcome, "desired_outcome"),
            (use_cases, "use_cases"),
            (current_workaround, "current_workaround"),
        ):
            value = (value or "").strip() or None
            if value:
                captured[attr] = value
                if hasattr(Idea, attr):
                    setattr(idea, attr, value)
        idea.captured_json = captured
        mint_idea_identity(self.db, idea)
        self.db.commit()
        return self.detail(idea.id)


# ── activity log writers ──────────────────────────────────────────────────────


def record_status_activity(
    db: Session,
    *,
    tenant_id: str,
    idea_id: str,
    from_label: Optional[str],
    to_label: Optional[str],
    to_color: Optional[str] = None,
) -> None:
    db.add(
        IdeaActivity(
            tenant_id=tenant_id,
            idea_id=idea_id,
            kind="status_changed",
            from_label=from_label,
            to_label=to_label,
            to_color=to_color,
            created_at=_now(),
        )
    )
    db.flush()


def on_domain_event(db: Session, ev: Dict[str, Any]) -> None:
    """Bus subscriber: one ``idea_activity`` row per idea status move, for
    EVERY idea (the requester feed only keeps rows for requesters with a
    phone). The bus runs it on its own post-commit session and isolates a
    failure, so it can never break the triggering request."""
    if ev.get("entity_type") != IDEA_ENTITY or ev.get("action") != "status_changed":
        return
    tenant_id, idea_id = ev.get("tenant_id"), ev.get("record_id")
    extra = ev.get("extra") or {}
    from_id = extra.get("from_status_id")
    if not tenant_id or not idea_id or not from_id:
        return
    scope = or_(Status.tenant_id == tenant_id, Status.tenant_id.is_(None))
    from_status = db.query(Status).filter(Status.id == from_id, scope).first()
    if from_status is None or from_status.is_initial:
        return  # draft -> captured is the "submitted" entry, not a move
    exists = db.query(Idea.id).filter(Idea.id == idea_id, Idea.tenant_id == tenant_id).first()
    if exists is None:
        return
    to_status = None
    to_id = extra.get("to_status_id")
    if to_id:
        to_status = db.query(Status).filter(Status.id == to_id, scope).first()
    record_status_activity(
        db,
        tenant_id=tenant_id,
        idea_id=idea_id,
        from_label=from_status.label,
        to_label=extra.get("to_status_label") or (to_status.label if to_status else None),
        to_color=to_status.color if to_status else None,
    )
    db.commit()


def bus_subscriber(db: Session, ev: Dict[str, Any]) -> None:
    """Stable-identity proxy (see ``status_events.bus_subscriber``)."""
    on_domain_event(db, ev)


def backfill_activity_from_status_events(db: Session) -> int:
    """ORM twin of migration 0017's backfill (unit-tested; the migration runs
    the same INSERT..SELECT in SQL). Idempotent via ``source_event_id``."""
    done = {r[0] for r in db.query(IdeaActivity.source_event_id).filter(IdeaActivity.source_event_id.isnot(None))}
    added = 0
    for e in db.query(IdeaStatusEvent).filter(IdeaStatusEvent.kind == "status_changed").all():
        if e.id in done:
            continue
        payload = e.payload_json or {}
        db.add(
            IdeaActivity(
                id=f"ise:{e.id}",
                tenant_id=e.tenant_id,
                idea_id=e.idea_id,
                kind="status_changed",
                from_label=payload.get("from_status_label"),
                to_label=payload.get("status_label"),
                source_event_id=e.id,
                created_at=e.created_at,
            )
        )
        added += 1
    db.flush()
    return added
