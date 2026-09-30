"""BR "Send to build" hand-off (plan ideation-br-send-to-build D2/D6/D7/D10).

``readiness`` computes ``canSend`` + ``blockers`` (the SAME completeness check
Promote uses), ``send`` files ONE GitHub ``crew-intake`` issue and moves the BR
to ``sent_to_build`` through the status engine, ``detail_build`` is the Trace
tab's read model.

Idempotency (D7): a ``br_builds`` row (UNIQUE per BR) is inserted in state
``creating`` and COMMITTED before GitHub is called; refs + ``sent`` + the status
move + the ``sent`` event land in ONE transaction afterwards. A leftover
``creating`` row (a request died) is resolved by a marker search before any
create. Every query is tenant-scoped; stored ids resolve WITH ``tenant_id``.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import httpx
from cryptography.fernet import InvalidToken
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.catalog import Product
from app.models.user import User
from app.repositories.connection_repository import ConnectionRepository
from app.repositories.status_repository import StatusRepository
from app.repositories.status_transition_repository import StatusTransitionRepository
from app.secrets import decrypt_secret
from app.services import status_machine
from app.services.status_machine import (
    TransitionConditionsNotMet,
    TransitionForbidden,
    TransitionNotAllowed,
)

from ..github_client import GitHubClient, GitHubError
from ..models import (
    BrBuild,
    BrBuildKey,
    BrBuildEvent,
    BusinessRequirement,
    Idea,
    IdeaBusinessRequirement,
    ProductDelivery,
)
from ..schemas import BuildEventIn, BuildEventOut, BuildOut, SentByOut
from .br_templates import get_stamped_doc
from .issue_body import render_issue_body
from .statuses import BR_ENTITY, BR_SEND_EDGE_PREFIX, BR_STATUS_IDS

# Test seam: the httpx transport GitHub calls ride (None = the real network).
DEFAULT_TRANSPORT: Optional[httpx.BaseTransport] = None

LABEL = "crew-intake"
LABEL_COLOR = "ff5a00"
GITHUB_PROVIDER = "github"
GITHUB_CONNECTION_TYPE = "scm"

DELIVERED_EDGE_ID = "br-tr-build-delivered"
BLOCKER_TEST = "Test requirements cannot be sent to build"
BLOCKER_GITHUB = "Connect GitHub in Settings > Integrations"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _github_http_error(repo: str, exc: GitHubError) -> HTTPException:
    """The precise 502 for a GitHub failure (never carries the token)."""
    if exc.status_code in (401, 403):
        return HTTPException(502, "GitHub rejected the token")
    if exc.status_code == 404:
        return HTTPException(
            502, f"Repository {repo} not found or the token cannot see it"
        )
    if exc.status_code is None:
        return HTTPException(502, "GitHub is unreachable")
    return HTTPException(502, f"GitHub returned an error ({exc.status_code})")


class BuildHandoffService:
    def __init__(self, db: Session):
        self.db = db

    # ── lookups (all tenant-scoped) ───────────────────────────────────────
    def _brs(self):
        from .business_requirements import BusinessRequirementService

        return BusinessRequirementService(self.db)

    def _row(self, tenant_id: str, br_id: str) -> Optional[BrBuild]:
        return (
            self.db.query(BrBuild)
            .filter(
                BrBuild.business_requirement_id == br_id,
                BrBuild.tenant_id == tenant_id,
            )
            .first()
        )

    def _product(self, tenant_id: str, product_id: str) -> Optional[Product]:
        return (
            self.db.query(Product)
            .filter(Product.id == product_id, Product.tenant_id == tenant_id)
            .first()
        )

    def _build_repo(self, tenant_id: str, product_id: str) -> Optional[str]:
        row = (
            self.db.query(ProductDelivery)
            .filter(
                ProductDelivery.product_id == product_id,
                ProductDelivery.tenant_id == tenant_id,
            )
            .first()
        )
        return (row.build_repo or None) if row else None

    def _connection(self, tenant_id: str):
        conn = ConnectionRepository(self.db).get_by_type(
            tenant_id, GITHUB_CONNECTION_TYPE
        )
        if conn is None or conn.provider != GITHUB_PROVIDER:
            return None
        return conn

    def _send_edge_available(self, tenant_id: str, br: BusinessRequirement) -> bool:
        tier = StatusRepository(self.db).resolve_tier(BR_ENTITY, tenant_id)
        edge = StatusTransitionRepository(self.db).find_edge(
            br.status_id, BR_STATUS_IDS["sent_to_build"], tier
        )
        return edge is not None and edge.id.startswith(BR_SEND_EDGE_PREFIX)

    def _user_name(self, tenant_id: str, user_id: Optional[str]) -> Optional[str]:
        if not user_id:
            return None
        user = (
            self.db.query(User)
            .filter(User.id == user_id, User.tenant_id == tenant_id)
            .first()
        )
        return user.name if user else None

    # ── readiness ─────────────────────────────────────────────────────────
    def _blockers(self, tenant_id: str, br: BusinessRequirement) -> List[str]:
        blockers: List[str] = []
        if br.is_test:
            blockers.append(BLOCKER_TEST)
        try:
            _errors, missing = self._brs().missing_required(br)
            if missing:
                blockers.append("Missing: " + ", ".join(missing))
        except HTTPException as exc:  # stamped template version unresolvable
            blockers.append(str(exc.detail))
        if not self._build_repo(tenant_id, br.product_id):
            product = self._product(tenant_id, br.product_id)
            blockers.append(
                f"Set the build repository on the product {product.name if product else ''}".strip()
            )
        if self._connection(tenant_id) is None:
            blockers.append(BLOCKER_GITHUB)
        return blockers

    def readiness(
        self, tenant_id: str, br: BusinessRequirement
    ) -> Tuple[bool, List[str]]:
        """``(canSend, blockers)``. A BR whose status has no send edge (already
        sent, delivered, archived...) is not sendable and carries no blockers."""
        if not self._send_edge_available(tenant_id, br):
            return False, []
        blockers = self._blockers(tenant_id, br)
        return (not blockers), blockers

    # ── read model ────────────────────────────────────────────────────────
    def detail_build(self, tenant_id: str, br: BusinessRequirement) -> BuildOut:
        can_send, blockers = self.readiness(tenant_id, br)
        row = self._row(tenant_id, br.id)
        events = (
            self.db.query(BrBuildEvent)
            .filter(
                BrBuildEvent.business_requirement_id == br.id,
                BrBuildEvent.tenant_id == tenant_id,
            )
            .order_by(BrBuildEvent.seq)
            .all()
        )
        names: Dict[str, Optional[str]] = {}
        out_events: List[BuildEventOut] = []
        for e in events:
            if e.actor_user_id and e.actor_user_id not in names:
                names[e.actor_user_id] = self._user_name(tenant_id, e.actor_user_id)
            out_events.append(
                BuildEventOut(
                    id=e.id,
                    seq=e.seq,
                    kind=e.kind,
                    stage=e.stage,
                    message=e.message,
                    prUrl=e.pr_url,
                    handtestUrl=e.handtest_url,
                    status=e.status,
                    statusMoved=bool(e.status_moved),
                    actorName=names.get(e.actor_user_id) if e.actor_user_id else None,
                    createdAt=e.created_at,
                )
            )
        pr_url = next((e.prUrl for e in reversed(out_events) if e.prUrl), None)
        handtest = next((e.handtestUrl for e in reversed(out_events) if e.handtestUrl), None)
        sent_by = None
        if row is not None and row.sent_by:
            name = self._user_name(tenant_id, row.sent_by)
            if name is not None:
                sent_by = SentByOut(id=row.sent_by, name=name)
        return BuildOut(
            canSend=can_send,
            blockers=blockers,
            repo=row.repo if row is not None else self._build_repo(tenant_id, br.product_id),
            issueUrl=row.issue_url if row is not None else None,
            issueNumber=row.issue_number if row is not None else None,
            state=row.state if row is not None else "none",
            sentAt=row.sent_at if row is not None else None,
            sentBy=sent_by,
            stage=out_events[-1].stage if out_events else None,
            prUrl=pr_url,
            handtestUrl=handtest,
            events=out_events,
        )

    # ── send ──────────────────────────────────────────────────────────────
    def _issue_body(self, tenant_id: str, br: BusinessRequirement) -> str:
        from app.ai import get_grill_definition, GrillEngine
        from app.config import settings

        from .grill import GRILL_DEFINITION_KEY

        doc = get_stamped_doc(self.db, br.template_key, br.template_version, tenant_id) or {}
        idea_ids = [
            r.idea_id
            for r in self.db.query(IdeaBusinessRequirement.idea_id).filter(
                IdeaBusinessRequirement.business_requirement_id == br.id,
                IdeaBusinessRequirement.tenant_id == tenant_id,
            )
        ]
        ideas = []
        if idea_ids:
            for idea in (
                self.db.query(Idea)
                .filter(Idea.id.in_(idea_ids), Idea.tenant_id == tenant_id)
                .order_by(Idea.created_at.asc(), Idea.id.asc())
            ):
                ideas.append(
                    {
                        "number": idea.idea_number or "",
                        "title": idea.title or idea.problem or "",
                        "up": idea.upvotes,
                        "down": idea.downvotes,
                    }
                )
        definition = get_grill_definition(GRILL_DEFINITION_KEY)
        messages: List[Dict[str, str]] = []
        if definition is not None:
            state = GrillEngine(self.db).state(definition, tenant_id, br.id)
            messages = [
                {"role": m["role"], "content": m["content"]} for m in state.messages
            ]
        base = settings.frontend_url.rstrip("/")
        return render_issue_body(
            doc,
            dict(br.answers_json or {}),
            ideas,
            messages,
            f"{base}/ideation/business-requirements/{br.id}",
            br.id,
            br.product_id,
        )

    def _client(self, tenant_id: str) -> GitHubClient:
        conn = self._connection(tenant_id)
        if conn is None:
            raise HTTPException(
                422, detail={"message": BLOCKER_GITHUB, "blockers": [BLOCKER_GITHUB]}
            )
        try:
            token = str(decrypt_secret(conn.credentials_json).get("token", ""))
        except InvalidToken as exc:
            raise HTTPException(
                502, "The stored GitHub token cannot be read. Save the connection again."
            ) from exc
        return GitHubClient(token, transport=DEFAULT_TRANSPORT)

    def send(self, tenant_id: str, br_id: str, actor: User):
        """Send the BR to build (idempotent). Returns the refreshed detail."""
        brs = self._brs()
        br = brs._br_or_404(tenant_id, br_id)
        row = self._row(tenant_id, br.id)
        can_edge = self._send_edge_available(tenant_id, br)

        # Already sent (status past the send edges): return it, no GitHub call.
        if row is not None and row.state != "creating" and not can_edge:
            return brs.get(tenant_id, br.id)

        can_send, blockers = self.readiness(tenant_id, br)
        if not can_send:
            message = blockers[0] if blockers else "This requirement cannot be sent to build."
            raise HTTPException(422, detail={"message": message, "blockers": blockers})

        repo = self._build_repo(tenant_id, br.product_id) or ""
        client = self._client(tenant_id)

        # D10: re-send after "Back to ready" = a comment on the SAME issue.
        if row is not None and row.state != "creating" and row.issue_number:
            try:
                client.create_comment(
                    row.repo,
                    row.issue_number,
                    f"Re-sent to build {_now().isoformat(timespec='seconds')}",
                )
            except GitHubError as exc:
                raise _github_http_error(row.repo, exc) from exc
            self._finalize(tenant_id, br, row, actor, issue=None)
            return brs.get(tenant_id, br.id)

        recovering = row is not None
        if row is None:
            row = BrBuild(
                tenant_id=tenant_id,
                business_requirement_id=br.id,
                repo=repo,
                state="creating",
            )
            self.db.add(row)
            try:
                self.db.commit()
            except IntegrityError as exc:
                self.db.rollback()
                raise HTTPException(409, "This requirement is already being sent to build.") from exc

        try:
            issue = None
            if recovering:
                issue = client.search_issue_by_marker(repo, f"br-id: {br.id}")
            if issue is None:
                client.ensure_label(repo, LABEL, LABEL_COLOR)
                issue = client.create_issue(
                    repo, br.title or "Untitled", self._issue_body(tenant_id, br), [LABEL]
                )
        except GitHubError as exc:
            self._drop_row(row)
            raise _github_http_error(repo, exc) from exc

        self._finalize(tenant_id, br, row, actor, issue=issue)
        return brs.get(tenant_id, br.id)

    def _drop_row(self, row: BrBuild) -> None:
        self.db.rollback()
        self.db.delete(self.db.merge(row))
        self.db.commit()

    def _finalize(
        self,
        tenant_id: str,
        br: BusinessRequirement,
        row: BrBuild,
        actor: User,
        *,
        issue: Optional[dict],
    ) -> None:
        """Refs + state, the engine status move and the ``sent`` event in ONE
        transaction. The engine is the only status writer (notifications and the
        workflow event ride it); the Send edges are fired here, the one
        sanctioned caller (the generic move refuses them)."""
        if issue is not None:
            row.issue_number = issue["number"]
            row.issue_url = issue["html_url"]
            row.issue_node_id = issue.get("node_id")
        row.state = "sent"
        row.sent_by = actor.id
        row.sent_at = _now()
        self.db.add(row)
        try:
            status_machine.transition(
                self.db,
                BR_ENTITY,
                br,
                BR_STATUS_IDS["sent_to_build"],
                actor=actor,
                tenant_id=tenant_id,
                commit=False,
            )
        except TransitionForbidden as exc:
            self.db.rollback()
            raise HTTPException(403, exc.message) from exc
        except (TransitionNotAllowed, TransitionConditionsNotMet) as exc:
            self.db.rollback()
            raise HTTPException(409, exc.message) from exc
        self.db.add(
            BrBuildEvent(
                tenant_id=tenant_id,
                business_requirement_id=br.id,
                kind="sent",
                stage="Sent",
                message=f"Sent to build by {actor.name}",
                actor_user_id=actor.id,
                status_moved=True,
            )
        )
        self.db.commit()

    # ── write-back (crew -> Trace) ────────────────────────────────────────
    def append_event(
        self, key: BrBuildKey, br_id: str, payload: BuildEventIn
    ) -> BuildEventOut:
        """Append one Trace entry. 404 (one body) unless the BR is in the key's
        tenant AND has a build row. ``merged``/``released`` move the BR to
        ``delivered`` through the engine (no actor) in the same transaction when
        the edge is available from its current status; otherwise the entry is
        stored with ``statusMoved=False``. Never raises for a refused move."""
        tenant_id = key.tenant_id
        br = (
            self.db.query(BusinessRequirement)
            .filter(
                BusinessRequirement.id == br_id,
                BusinessRequirement.tenant_id == tenant_id,
            )
            .first()
        )
        row = self._row(tenant_id, br_id) if br is not None else None
        if br is None or row is None:
            raise HTTPException(404, "Not found.")

        moved = False
        if payload.status in ("merged", "released"):
            tier = StatusRepository(self.db).resolve_tier(BR_ENTITY, tenant_id)
            delivered = BR_STATUS_IDS["delivered"]
            edge = StatusTransitionRepository(self.db).find_edge(
                br.status_id, delivered, tier
            )
            if edge is not None and edge.id == DELIVERED_EDGE_ID:
                try:
                    status_machine.transition(
                        self.db,
                        BR_ENTITY,
                        br,
                        delivered,
                        actor=None,
                        tenant_id=tenant_id,
                        commit=False,
                    )
                    row.state = "delivered"
                    moved = True
                except (
                    TransitionForbidden,
                    TransitionNotAllowed,
                    TransitionConditionsNotMet,
                ):
                    self.db.rollback()
                    br = self.db.get(BusinessRequirement, br_id)
                    row = self._row(tenant_id, br_id)
        event = BrBuildEvent(
            tenant_id=tenant_id,
            business_requirement_id=br_id,
            kind="crew",
            stage=payload.stage,
            message=payload.message,
            pr_url=payload.prUrl,
            handtest_url=payload.handtestUrl,
            status=payload.status,
            key_id=key.id,
            status_moved=moved,
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return BuildEventOut(
            id=event.id,
            seq=event.seq,
            kind=event.kind,
            stage=event.stage,
            message=event.message,
            prUrl=event.pr_url,
            handtestUrl=event.handtest_url,
            status=event.status,
            statusMoved=moved,
            actorName=None,
            createdAt=event.created_at,
        )
