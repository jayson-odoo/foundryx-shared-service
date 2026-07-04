"""TemplateService — two-tier lifecycle + render orchestration (plan 07).

Tier semantics (D6): platform rows (tenant_id NULL) are the defaults every
tenant reads until they fork. A tenant edit of a platform row creates a
TENANT COPY (same key, is_system preserved) — the platform row is never
mutated by tenant callers. The platform tenant maintains the NULL tier
through these same endpoints (its edits write the platform rows directly).
"""

import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import and_, case
from sqlalchemy.orm import Session

from app.models.template import (
    TEMPLATE_TYPE_BADGE,
    TEMPLATE_TYPE_EMAIL,
    Template,
)
from app.models.user import User
from app.repositories.template_repository import TemplateRepository
from app.schemas.filters import FilterGroup
from app.services.filter_translator import translate_filter
from app.template_engine import (
    get_context,
    render_canvas,
    render_document,
    render_email,
    validate_canvas_doc,
    validate_doc,
)
from app.template_engine.renderer import RenderedEmail
from app.workflow_engine.entity_events import emit_entity_event


class TemplateError(Exception):
    """422-class problem (named message)."""


class TemplateNotFound(Exception):
    pass


_FILTER_COLUMNS = {
    "name": Template.name,
    "key": Template.key,
    "subject": Template.subject,
    "context": Template.context,
    "type": Template.type,
}


def _tier_special(condition) -> Optional[Any]:
    """Filter field 'tier' — computed from the tenant_id NULL-ness."""
    if condition.field != "tier":
        return None
    is_default = case((Template.tenant_id.is_(None), "default"), else_="customized")
    if condition.operator == "eq":
        return is_default == condition.value
    if condition.operator == "neq":
        return is_default != condition.value
    if condition.operator == "in" and isinstance(condition.value, list):
        return is_default.in_(condition.value)
    return None


class TemplateService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TemplateRepository(db)

    # ---- reads ----

    def list(
        self,
        tenant_id: str,
        *,
        page: int = 0,
        page_size: int = 25,
        search: Optional[str] = None,
        sort_by: Optional[str] = None,
        sort_dir: str = "asc",
        filter_group: Optional[FilterGroup] = None,
        context: Optional[str] = None,
    ) -> Tuple[List[Template], int]:
        clause = translate_filter(filter_group, _FILTER_COLUMNS, special=_tier_special)
        if context:
            # Picker filter (plan 10 BL-081) — AND a context match onto whatever
            # the caller's filter produced (None-safe).
            ctx_clause = Template.context == context
            clause = ctx_clause if clause is None else and_(clause, ctx_clause)
        return self.repo.paginate(
            tenant_id,
            page=page,
            page_size=page_size,
            search=search,
            sort_by=sort_by,
            sort_dir=sort_dir,
            filter_clause=clause,
        )

    def get_at(
        self,
        index: int,
        tenant_id: str,
        **list_kwargs,
    ) -> Tuple[Optional[Template], int]:
        rows, total = self.list(tenant_id, page=max(index, 0), page_size=1, **list_kwargs)
        return (rows[0] if rows else None), total

    def get(self, template_id: str, tenant_id: str) -> Template:
        row = self.repo.get_visible(template_id, tenant_id)
        if row is None:
            raise TemplateNotFound()
        return row

    def resolve_by_key(self, key: str, tenant_id: str) -> Optional[Template]:
        return self.repo.resolve_by_key(key, tenant_id)

    @staticmethod
    def tier_of(template: Template) -> str:
        return "default" if template.tenant_id is None else "customized"

    # ---- validation helper ----

    def _validated_doc(
        self, raw_doc: Dict[str, Any], subject: str, context_key: str, type_: str = TEMPLATE_TYPE_EMAIL
    ):
        """Type-aware validation gate. Canvas (badge) docs validate through
        ``validate_canvas_doc``; email/document docs through ``validate_doc``."""
        context = get_context(context_key)
        if context is None:
            raise TemplateError(f'Unknown template context "{context_key}".')
        if type_ == TEMPLATE_TYPE_BADGE:
            doc, problems = validate_canvas_doc(
                raw_doc,
                fact_sources=list(context.fact_sources),
                required_facts=list(context.required_facts),
                scalar_facts=[f.key for f in context.facts],
            )
        else:
            doc, problems = validate_doc(
                raw_doc,
                subject,
                fact_sources=list(context.fact_sources),
                required_facts=list(context.required_facts),
                list_facts=context.list_facts,
                scalar_facts=[f.key for f in context.facts],
            )
        if problems:
            raise TemplateError(problems[0])
        return doc

    # ---- writes ----

    def create(
        self,
        tenant_id: str,
        *,
        name: str,
        subject: str,
        context: str,
        doc: Dict[str, Any],
        type_: str = TEMPLATE_TYPE_EMAIL,
    ) -> Template:
        if not name.strip():
            raise TemplateError("Name is required.")
        model = self._validated_doc(doc, subject, context, type_)
        row = Template(
            tenant_id=tenant_id,
            type=type_,
            key=f"custom.{uuid.uuid4().hex[:8]}",
            name=name.strip(),
            context=context,
            subject=subject,
            doc_json=model.model_dump(by_alias=True),
            is_system=False,
        )
        self.repo.add(row)
        self.db.flush()
        emit_entity_event(self.db, "template", "created", row, tenant_id=tenant_id)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(
        self,
        template_id: str,
        tenant_id: str,
        *,
        name: str,
        subject: str,
        doc: Dict[str, Any],
    ) -> Template:
        row = self.get(template_id, tenant_id)
        if not name.strip():
            raise TemplateError("Name is required.")
        model = self._validated_doc(doc, subject, row.context, row.type)

        if row.tenant_id is None and tenant_id is not None:
            # Editing a platform default from a TENANT: FORK (D6). The
            # platform tenant's scope is tenant_id=None (router maps
            # is_platform → None), so operator edits land on the NULL row
            # in place below, never here.
            fork = Template(
                tenant_id=tenant_id,
                type=row.type,
                key=row.key,
                name=name.strip(),
                context=row.context,
                subject=subject,
                doc_json=model.model_dump(by_alias=True),
                is_system=row.is_system,
            )
            self.repo.add(fork)
            self.db.flush()
            emit_entity_event(self.db, "template", "created", fork, tenant_id=tenant_id)
            self.db.commit()
            self.db.refresh(fork)
            return fork

        changes: dict = {}
        if row.name != name.strip():
            changes["name"] = {"from": row.name, "to": name.strip()}
        if row.subject != subject:
            changes["subject"] = {"from": row.subject, "to": subject}
        row.name = name.strip()
        row.subject = subject
        row.doc_json = model.model_dump(by_alias=True)
        emit_entity_event(self.db, "template", "updated", row, tenant_id=tenant_id, changes=changes or None)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, template_id: str, tenant_id: str) -> None:
        row = self.get(template_id, tenant_id)
        if row.is_system:
            raise TemplateError("System templates cannot be deleted — reset them instead.")
        if row.tenant_id != tenant_id:
            raise TemplateError("Only this workspace's own templates can be deleted.")
        emit_entity_event(self.db, "template", "deleted", row, tenant_id=tenant_id)
        self.repo.delete(row)
        self.db.commit()

    def duplicate(self, template_id: str, tenant_id: str) -> Template:
        source = self.get(template_id, tenant_id)
        copy = Template(
            tenant_id=tenant_id,
            type=source.type,
            key=f"custom.{uuid.uuid4().hex[:8]}",
            name=f"{source.name} (copy)",
            context=source.context,
            subject=source.subject,
            doc_json=source.doc_json,
            is_system=False,
        )
        self.repo.add(copy)
        self.db.commit()
        self.db.refresh(copy)
        return copy

    def reset(self, template_id: str, tenant_id: str) -> Template:
        """Drop a tenant fork of a system template → back to the platform row."""
        row = self.get(template_id, tenant_id)
        if not (row.is_system and row.tenant_id == tenant_id):
            raise TemplateError("Only customized system templates reset to the platform default.")
        platform = self.repo.get_platform_row(row.key)
        if platform is None:
            raise TemplateError("No platform default exists for this template.")
        self.repo.delete(row)
        self.db.commit()
        return platform

    # ---- rendering ----

    def preview(
        self,
        tenant_id: str,
        *,
        doc: Dict[str, Any],
        subject: str,
        context: str,
    ) -> RenderedEmail:
        ctx = get_context(context)
        if ctx is None:
            raise TemplateError(f'Unknown template context "{context}".')
        model = self._validated_doc(doc, subject, context)
        temp = Template(
            tenant_id=tenant_id,
            key="__preview__",
            name="Preview",
            context=context,
            subject=subject,
            doc_json=model.model_dump(by_alias=True),
        )
        return render_email(
            self.db, temp, tenant_id, ctx.sample_facts(), mode="preview"
        )

    def _preview_facts(self, ctx) -> Dict[str, Any]:
        """Sample scalars + list-fact samples — the facts a preview renders
        against (the list-fact key carries its sample row dicts so the expand
        pass sees a binding identically to a real one)."""
        facts: Dict[str, Any] = dict(ctx.sample_facts())
        for lf in ctx.list_facts:
            facts[lf.key] = [dict(r) for r in lf.sample]
        return facts

    def _preview_template(self, tenant_id: str, doc: Dict[str, Any], subject: str, context: str):
        """Validate + build a transient document Template + its sample facts."""
        from app.models.template import TEMPLATE_TYPE_DOCUMENT

        ctx = get_context(context)
        if ctx is None:
            raise TemplateError(f'Unknown template context "{context}".')
        model = self._validated_doc(doc, subject, context)
        temp = Template(
            tenant_id=tenant_id,
            type=TEMPLATE_TYPE_DOCUMENT,
            key="__preview__",
            name="Preview",
            context=context,
            subject=subject,
            doc_json=model.model_dump(by_alias=True),
        )
        return temp, self._preview_facts(ctx)

    def preview_pdf(
        self,
        tenant_id: str,
        *,
        doc: Dict[str, Any],
        subject: str,
        context: str,
    ) -> bytes:
        """Render a document-surface doc to PDF bytes with sample facts (D7).

        Same validation + render path as a real send (preview = production
        renderer). The router offloads this CPU-bound call to a threadpool.
        """
        temp, facts = self._preview_template(tenant_id, doc, subject, context)
        return render_document(self.db, temp, tenant_id, facts, mode="preview")

    def preview_doc_html(
        self,
        tenant_id: str,
        *,
        doc: Dict[str, Any],
        subject: str,
        context: str,
    ) -> str:
        """Render the in-app PREVIEW HTML sheet (no WeasyPrint, no browser PDF
        chrome) — same compiler/merge/brand as the PDF download."""
        from app.template_engine.renderer import render_document_html

        temp, facts = self._preview_template(tenant_id, doc, subject, context)
        return render_document_html(self.db, temp, tenant_id, facts, mode="preview")

    # ---- canvas (badge) rendering ----

    def _preview_canvas_template(self, tenant_id: str, doc: Dict[str, Any], subject: str, context: str):
        """Validate (canvas branch) + build a transient badge Template + sample
        scalar facts (canvas docs have no list facts)."""
        ctx = get_context(context)
        if ctx is None:
            raise TemplateError(f'Unknown template context "{context}".')
        model = self._validated_doc(doc, subject, context, TEMPLATE_TYPE_BADGE)
        temp = Template(
            tenant_id=tenant_id,
            type=TEMPLATE_TYPE_BADGE,
            key="__preview__",
            name="Preview",
            context=context,
            subject=subject,
            doc_json=model.model_dump(by_alias=True),
        )
        return temp, dict(ctx.sample_facts())

    def preview_canvas_pdf(
        self, tenant_id: str, *, doc: Dict[str, Any], subject: str, context: str
    ) -> bytes:
        """Render a canvas (badge) doc to PDF bytes with sample facts (D16
        single render). Router offloads this CPU-bound call to a threadpool."""
        temp, facts = self._preview_canvas_template(tenant_id, doc, subject, context)
        return render_canvas(self.db, temp, tenant_id, facts, mode="preview")

    def preview_canvas_html(
        self, tenant_id: str, *, doc: Dict[str, Any], subject: str, context: str
    ) -> str:
        """In-app canvas preview HTML (stacked sheets, no WeasyPrint chrome)."""
        from app.template_engine.renderer import render_canvas_html

        temp, facts = self._preview_canvas_template(tenant_id, doc, subject, context)
        return render_canvas_html(self.db, temp, tenant_id, facts, mode="preview")

    def test_send(self, template_id: str, tenant_id: str, user: User) -> str:
        """Render with sample facts and queue a real mail to the caller."""
        from app.services.email_service import email_service

        row = self.get(template_id, tenant_id)
        ctx = get_context(row.context)
        if ctx is None:
            raise TemplateError(f'Unknown template context "{row.context}".')
        facts = dict(ctx.sample_facts())
        # Real recipient values where we have them — the sample stays for links.
        facts.update(
            {
                "recipient.firstName": (user.name or user.email).split(" ")[0],
                "recipient.name": user.name or user.email,
                "recipient.email": user.email,
            }
        )
        rendered = render_email(
            self.db,
            row,
            tenant_id,
            facts,
            rule_objects={"recipient": user},
        )
        email_service.enqueue_raw(
            self.db,
            tenant_id,
            user.email,
            f"[Test] {rendered.subject}",
            rendered.html,
            rendered.text,
            template_key="template.test",
        )
        return user.email
