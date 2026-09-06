"""Contacts-module list service (plan 26 S1, D-A2-12) - composes tenant +
workspace scope, a saved segment ANDed with any ad-hoc filter, a whitelisted
sort, pagination, then maps through the ONE `ConversationService._thread_items`
mapper and decorates `channels[]` from a single batched query (AC-CTM-14..19,
23). Separate from `list_threads` (the Inbox) on purpose - different search
semantics (never message bodies) and a different query vocabulary."""
from typing import List, Optional, Tuple

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.schemas.filters import FilterGroup
from app.services.filter_translator import FilterError, translate_filter

from ..models import Contact
from ..phone import digits_only
from ..repositories.contact_repository import ContactRepository
from ..schemas import ContactChannelRef, ContactListItem
from .contact_filters import CONTACT_FILTER_COLUMNS, CONTACT_SORT_COLUMNS, build_special
from .contact_segment_service import ContactSegmentService
from .conversation_service import ConversationService

DEFAULT_PAGE_SIZE = 50


def _and_groups(a: Optional[FilterGroup], b: Optional[FilterGroup]) -> Optional[FilterGroup]:
    if a is not None and b is not None:
        return FilterGroup(kind="group", combinator="and", rules=[a, b])
    return a if a is not None else b


def _search_clause(term: str):
    like = f"%{term}%"
    full_name = func.coalesce(Contact.first_name, "") + " " + func.coalesce(Contact.last_name, "")
    clauses = [full_name.ilike(like), Contact.email.ilike(like)]
    digits = digits_only(term)
    if digits:
        clauses.append(Contact.phone_digits.ilike(f"%{digits}%"))
    return or_(*clauses)


class ContactListService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = ContactRepository(db)
        self.conv = ConversationService(db)
        self.segments = ContactSegmentService(db)

    def _build_query(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        search: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
        segment_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
    ):
        """The ONE filter/segment/sort query builder shared by `.list()` (page +
        `_decorate`) and `.query_for_export()` (plan 26 S3, D-A2-6a - the
        export handler streams raw `Contact` rows through THIS same builder,
        never `_decorate`, which pays for a thread/message join per row).
        Raises `SegmentNotFound`/`FilterError` exactly like `.list()` did."""
        segment_tree: Optional[FilterGroup] = None
        if segment_id:
            # Raises SegmentNotFound for a foreign/missing id - uniform 404
            # (AC-CTM-21), never leaks whether the id exists elsewhere.
            segment_tree = self.segments.tree_for(segment_id, workspace_id, tenant_id)

        combined = _and_groups(segment_tree, filter_group)
        special = build_special(self.db, tenant_id, workspace_id)
        clause = translate_filter(combined, CONTACT_FILTER_COLUMNS, special)

        if sort_by is not None and sort_by not in CONTACT_SORT_COLUMNS:
            raise FilterError(f"field not sortable: {sort_by}")

        q = self.db.query(Contact).filter(
            Contact.tenant_id == tenant_id, Contact.workspace_id == workspace_id
        )
        if search and search.strip():
            q = q.filter(_search_clause(search.strip()))
        if clause is not None:
            q = q.filter(clause)

        if sort_by:
            column = CONTACT_SORT_COLUMNS[sort_by]
            q = q.order_by(column.desc() if sort_dir == "desc" else column.asc())
        else:
            # AC-CTM-14 default: lastMessageAt desc nulls last, then createdAt desc.
            q = q.order_by(Contact.last_message_at.desc().nullslast(), Contact.created_at.desc())
        q = q.order_by(Contact.id.asc())  # stable tiebreak (deterministic paging)
        return q

    def list(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        search: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
        segment_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
        page: int = 0,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Tuple[List[ContactListItem], int]:
        """Raises `SegmentNotFound` (router -> 404) and `FilterError` (router
        -> 422, unknown field / unknown sort key / nesting too deep)."""
        q = self._build_query(
            tenant_id, workspace_id, search=search, filter_group=filter_group,
            segment_id=segment_id, sort_by=sort_by, sort_dir=sort_dir,
        )
        total = q.count()
        rows = q.offset(page * page_size).limit(page_size).all()
        items = self._decorate(rows, tenant_id)
        return items, total

    def query_for_export(
        self,
        tenant_id: str,
        workspace_id: str,
        *,
        ids: Optional[List[str]] = None,
        search: Optional[str] = None,
        filter_group: Optional[FilterGroup] = None,
        segment_id: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "desc",
    ):
        """Unpaginated `Contact` query for the export job (D-A2-6a, AC-CTM-42).
        An explicit `ids` selection WINS over search/filter/segment/sort (the
        frontend contract, `ContactExportRequest`'s own docstring) - a bulk
        "export just these rows" must never be silently narrowed by whatever
        list state happened to be on screen when it was chosen."""
        if ids:
            return (
                self.db.query(Contact)
                .filter(
                    Contact.tenant_id == tenant_id,
                    Contact.workspace_id == workspace_id,
                    Contact.id.in_(ids),
                )
                .order_by(Contact.id.asc())
            )
        return self._build_query(
            tenant_id, workspace_id, search=search, filter_group=filter_group,
            segment_id=segment_id, sort_by=sort_by, sort_dir=sort_dir,
        )

    def _decorate(self, rows: List[Contact], tenant_id: str) -> List[ContactListItem]:
        if not rows:
            return []
        thread_items = self.conv._thread_items(rows, tenant_id)
        channels_map = self.repo.channels_for_contacts([c.id for c in rows], tenant_id)
        out: List[ContactListItem] = []
        for t in thread_items:
            data = t.model_dump()
            data["channels"] = [ContactChannelRef(**c) for c in channels_map.get(t.id, [])]
            out.append(ContactListItem(**data))
        return out
