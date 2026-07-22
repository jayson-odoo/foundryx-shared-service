"""Versioned BR artifact template (Bi-D1/Bi-D2, AC-BI-16).

The BR template is a ``form_engine`` block document (``FormDocument``), stored as
immutable versions with a movable ``active`` label — the exact ai_skills shape,
one layer up. A BR STAMPS ``(template_key, version)`` at create; validation and
rendering resolve the STAMPED version's ``doc_json`` (never the current active
one) so a template edit can never reshape an existing BR.

S2 seeds ONLY the platform-tier (``tenant_id = NULL``) template — no tenant fork
logic yet (tenant customization is deferred). Reseed is insert-if-missing so an
operator's edits survive a bootstrap.
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy.orm import Session

from app.form_engine.schemas import FormDocument, validate_form_doc

from ..models import IdeationArtifactTemplate, IdeationArtifactTemplateVersion

BR_TEMPLATE_KEY = "business_requirement"
BR_TEMPLATE_NAME = "Business Requirement"

# Field labels, kept in sync with the schema below.
BR_FIELD_LABELS = {
    "problem_statement": "Problem statement",
    "business_goal": "Business goal",
    "stakeholders": "Stakeholders",
    "success_metric": "Success metric",
    "scope": "Scope",
    "constraints": "Constraints",
}


def br_target_schema() -> FormDocument:
    """The Business-Requirement capture document (Page → Section → Field), a
    valid ``validate_form_doc`` document (AC-BI-16). Fields mirror the intake
    pattern (``_ideation_target_schema``). ``problem_statement`` /
    ``business_goal`` / ``success_metric`` are required (the spine of a BR);
    ``stakeholders`` / ``scope`` / ``constraints`` are optional — a grill may
    leave a field blank rather than invent it (partial emit is success, D13)."""
    return FormDocument.model_validate(
        {
            "schemaVersion": 1,
            "pages": [
                {
                    "id": "page-br",
                    "title": "Business Requirement",
                    "sections": [
                        {
                            "id": "sec-br",
                            "title": "Requirement",
                            "fields": [
                                {
                                    "id": "f-problem-statement",
                                    "type": "textarea",
                                    "key": "problem_statement",
                                    "label": BR_FIELD_LABELS["problem_statement"],
                                    "required": True,
                                },
                                {
                                    "id": "f-business-goal",
                                    "type": "textarea",
                                    "key": "business_goal",
                                    "label": BR_FIELD_LABELS["business_goal"],
                                    "required": True,
                                },
                                {
                                    "id": "f-stakeholders",
                                    "type": "textarea",
                                    "key": "stakeholders",
                                    "label": BR_FIELD_LABELS["stakeholders"],
                                    "required": False,
                                },
                                {
                                    "id": "f-success-metric",
                                    "type": "textarea",
                                    "key": "success_metric",
                                    "label": BR_FIELD_LABELS["success_metric"],
                                    "required": True,
                                },
                                {
                                    "id": "f-scope",
                                    "type": "textarea",
                                    "key": "scope",
                                    "label": BR_FIELD_LABELS["scope"],
                                    "required": False,
                                },
                                {
                                    "id": "f-constraints",
                                    "type": "textarea",
                                    "key": "constraints",
                                    "label": BR_FIELD_LABELS["constraints"],
                                    "required": False,
                                },
                            ],
                        }
                    ],
                }
            ],
        }
    )


def seed_br_template(db: Session) -> None:
    """Idempotent global seed of the platform-tier BR template + its v1 version.

    Insert-if-missing (an operator's edits survive a reseed): if the platform
    template already exists this is a no-op. The doc is validated with
    ``validate_form_doc`` before persisting (a broken seed doc would be a
    programming error — fail loudly). Bi-D2: only the platform (NULL) tier."""
    existing = (
        db.query(IdeationArtifactTemplate)
        .filter(
            IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
            IdeationArtifactTemplate.tenant_id.is_(None),
        )
        .first()
    )
    if existing is not None:
        return

    doc = br_target_schema()
    problems = validate_form_doc(doc)
    if problems:
        raise ValueError(f"Seed BR template doc is invalid: {problems}")

    template = IdeationArtifactTemplate(
        tenant_id=None,
        template_key=BR_TEMPLATE_KEY,
        name=BR_TEMPLATE_NAME,
        description="The default Business Requirement capture template.",
        is_system=True,
    )
    db.add(template)
    db.flush()
    version = IdeationArtifactTemplateVersion(
        template_id=template.id,
        tenant_id=None,
        version=1,
        doc_json=doc.model_dump(mode="json"),
        created_by=None,
    )
    db.add(version)
    db.flush()
    template.active_version_id = version.id
    db.flush()


def resolve_active_template(
    db: Session, tenant_id: Optional[str]
) -> Optional[IdeationArtifactTemplate]:
    """The active BR template for a tenant. S2 has no tenant fork, so this
    resolves the platform-tier (NULL) row; a tenant-tier row (future) would win.
    Returns None only if the seed never ran."""
    tenant_row = (
        db.query(IdeationArtifactTemplate)
        .filter(
            IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
            IdeationArtifactTemplate.tenant_id == tenant_id,
        )
        .first()
        if tenant_id is not None
        else None
    )
    if tenant_row is not None:
        return tenant_row
    return (
        db.query(IdeationArtifactTemplate)
        .filter(
            IdeationArtifactTemplate.template_key == BR_TEMPLATE_KEY,
            IdeationArtifactTemplate.tenant_id.is_(None),
        )
        .first()
    )


def active_version_number(
    template: IdeationArtifactTemplate, db: Session
) -> Optional[int]:
    """The version int of a template's active label (the number a new BR stamps)."""
    if not template.active_version_id:
        return None
    row = (
        db.query(IdeationArtifactTemplateVersion)
        .filter(IdeationArtifactTemplateVersion.id == template.active_version_id)
        .first()
    )
    return row.version if row else None


def get_stamped_version(
    db: Session, template_key: str, template_version: int, tenant_id: Optional[str]
) -> Optional[IdeationArtifactTemplateVersion]:
    """The IMMUTABLE version row a BR stamped — resolved by (key, version) within
    the tenant's resolved tier (falls back to the platform tier). Rendering +
    validation read THIS, never the current active version (AC-BI-16)."""
    template = resolve_active_template(db, tenant_id)
    if template is None or template.template_key != template_key:
        # Fall back to any template of that key visible to the tenant (own or
        # platform tier) — the stamp is authoritative, not the active pointer.
        template = (
            db.query(IdeationArtifactTemplate)
            .filter(
                IdeationArtifactTemplate.template_key == template_key,
                IdeationArtifactTemplate.tenant_id.in_(
                    [t for t in (tenant_id, None) if t is not None] + [None]
                ),
            )
            .first()
        )
    if template is None:
        return None
    return (
        db.query(IdeationArtifactTemplateVersion)
        .filter(
            IdeationArtifactTemplateVersion.template_id == template.id,
            IdeationArtifactTemplateVersion.version == template_version,
        )
        .first()
    )


def get_stamped_doc(
    db: Session, template_key: str, template_version: int, tenant_id: Optional[str]
) -> Optional[dict]:
    """The stamped version's ``doc_json`` (for validation + FE rendering)."""
    version = get_stamped_version(db, template_key, template_version, tenant_id)
    return dict(version.doc_json) if version and version.doc_json else None
