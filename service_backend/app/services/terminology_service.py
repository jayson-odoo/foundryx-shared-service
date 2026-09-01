"""Terminology service (sprint-3/08) - resolve-merged / catalog / set / reset.

Resolution (D6): code defaults overlaid with the tenant's override rows. The
merged map is the client-cache source; the catalog drives the settings page.
Unknown-key writes 422 (must be registered, D2).
"""
from typing import List

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.module_platform.active import active_modules, is_visible
from app.repositories.terminology_repository import TerminologyRepository
from app.schemas.terminology import TermCatalogItem, TermLabels
from app.terminology.registry import is_registered, list_terms


class TerminologyService:
    def __init__(self, db: Session):
        self.db = db
        self.repo = TerminologyRepository(db)

    def _visible_terms(self, tenant_id: str):
        """Only core + active-module terms (plan sprint-3/10 D2 active_modules)."""
        active = active_modules(self.db, tenant_id)
        return [t for t in list_terms() if is_visible(t.module, active)]

    def merged_map(self, tenant_id: str) -> dict:
        """{key: {singular, plural}} = defaults ⊕ tenant overrides (D6),
        filtered to core + the tenant's active modules (D2)."""
        overrides = self.repo.list_for_tenant(tenant_id)
        result: dict = {}
        for term in self._visible_terms(tenant_id):
            ov = overrides.get(term.key)
            result[term.key] = TermLabels(
                singular=ov.singular if ov else term.default_singular,
                plural=ov.plural if ov else term.default_plural,
            )
        return result

    def catalog(self, tenant_id: str) -> List[TermCatalogItem]:
        overrides = self.repo.list_for_tenant(tenant_id)
        items: List[TermCatalogItem] = []
        for term in self._visible_terms(tenant_id):
            ov = overrides.get(term.key)
            items.append(
                TermCatalogItem(
                    key=term.key,
                    module=term.module,
                    group=term.group,
                    description=term.description,
                    defaultSingular=term.default_singular,
                    defaultPlural=term.default_plural,
                    overrideSingular=ov.singular if ov else None,
                    overridePlural=ov.plural if ov else None,
                    singular=ov.singular if ov else term.default_singular,
                    plural=ov.plural if ov else term.default_plural,
                )
            )
        return items

    def _require_registered(self, entity_key: str) -> None:
        if not is_registered(entity_key):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Unknown terminology key: {entity_key}",
            )

    def set_term(
        self,
        tenant_id: str,
        entity_key: str,
        singular: str,
        plural: str,
        actor_id: str,
    ) -> TermLabels:
        self._require_registered(entity_key)
        self.repo.upsert(tenant_id, entity_key, singular, plural, actor_id)
        self.db.commit()
        return TermLabels(singular=singular, plural=plural)

    def reset_term(self, tenant_id: str, entity_key: str) -> None:
        self._require_registered(entity_key)
        self.repo.delete(tenant_id, entity_key)
        self.db.commit()
