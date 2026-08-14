"""Review/Approval engine persistence (plan sprint-4/06 Part 2) - pure
SQLAlchemy, ALWAYS tenant-scoped. Every query filters ``tenant_id`` from the
authed context, never client input (multi-tenancy invariant). Stored cross-engine
ids (status ids, bound persona/staff-role ids, actor ids) are resolved
scope/tenant-guarded by the SERVICE - the repo never returns rows for another
tenant.
"""
from typing import List, Optional

from sqlalchemy.orm import Session

from app.models.review import (
    ReviewAssignment,
    ReviewConfiguration,
    ReviewDecision,
    ReviewRole,
    ReviewRoleActor,
)


class ReviewRepository:
    def __init__(self, db: Session):
        self.db = db

    # ---- configurations ----

    def list_configs(self, tenant_id: str) -> List[ReviewConfiguration]:
        return (
            self.db.query(ReviewConfiguration)
            .filter(ReviewConfiguration.tenant_id == tenant_id)
            .order_by(ReviewConfiguration.created_at.asc())
            .all()
        )

    def get_config(self, tenant_id: str, config_id: str) -> Optional[ReviewConfiguration]:
        return (
            self.db.query(ReviewConfiguration)
            .filter(
                ReviewConfiguration.tenant_id == tenant_id,
                ReviewConfiguration.id == config_id,
            )
            .first()
        )

    def add_config(self, config: ReviewConfiguration) -> ReviewConfiguration:
        self.db.add(config)
        self.db.flush()
        return config

    def delete_config(self, config: ReviewConfiguration) -> None:
        # Roles + actors are wiped by the service first (no DB cascade - plain
        # cross-engine ids, not FKs).
        self.db.delete(config)

    # ---- roles ----

    def list_roles(self, tenant_id: str, config_id: str) -> List[ReviewRole]:
        return (
            self.db.query(ReviewRole)
            .filter(
                ReviewRole.tenant_id == tenant_id,
                ReviewRole.review_configuration_id == config_id,
            )
            .order_by(ReviewRole.sort_order.asc(), ReviewRole.key.asc())
            .all()
        )

    def get_role(self, tenant_id: str, role_id: str) -> Optional[ReviewRole]:
        return (
            self.db.query(ReviewRole)
            .filter(ReviewRole.tenant_id == tenant_id, ReviewRole.id == role_id)
            .first()
        )

    def add_role(self, role: ReviewRole) -> ReviewRole:
        self.db.add(role)
        self.db.flush()
        return role

    def delete_role(self, role: ReviewRole) -> None:
        self.db.delete(role)

    def delete_roles_for_config(self, tenant_id: str, config_id: str) -> None:
        role_ids = [
            r.id for r in self.list_roles(tenant_id, config_id)
        ]
        if role_ids:
            self.db.query(ReviewRoleActor).filter(
                ReviewRoleActor.tenant_id == tenant_id,
                ReviewRoleActor.role_id.in_(role_ids),
            ).delete(synchronize_session=False)
        self.db.query(ReviewRole).filter(
            ReviewRole.tenant_id == tenant_id,
            ReviewRole.review_configuration_id == config_id,
        ).delete(synchronize_session=False)

    # ---- role actors ----

    def list_actors(self, tenant_id: str, role_id: str) -> List[ReviewRoleActor]:
        return (
            self.db.query(ReviewRoleActor)
            .filter(
                ReviewRoleActor.tenant_id == tenant_id,
                ReviewRoleActor.role_id == role_id,
            )
            .order_by(ReviewRoleActor.sort_order.asc())
            .all()
        )

    def add_actor(self, actor: ReviewRoleActor) -> ReviewRoleActor:
        self.db.add(actor)
        self.db.flush()
        return actor

    def delete_actors_for_role(self, tenant_id: str, role_id: str) -> None:
        self.db.query(ReviewRoleActor).filter(
            ReviewRoleActor.tenant_id == tenant_id,
            ReviewRoleActor.role_id == role_id,
        ).delete(synchronize_session=False)

    # ---- assignments ----

    def list_assignments_for_revision(
        self, tenant_id: str, config_id: str, group_id: str, revision: int
    ) -> List[ReviewAssignment]:
        return (
            self.db.query(ReviewAssignment)
            .filter(
                ReviewAssignment.tenant_id == tenant_id,
                ReviewAssignment.review_configuration_id == config_id,
                ReviewAssignment.reviewed_submission_group_id == group_id,
                ReviewAssignment.revision_number == revision,
            )
            .order_by(ReviewAssignment.assigned_at.asc())
            .all()
        )

    def list_assignments_for_actor(
        self, tenant_id: str, actor_kind: str, actor_id: str
    ) -> List[ReviewAssignment]:
        """The reviewer's queue (My Reviews) - every assignment for an actor."""
        return (
            self.db.query(ReviewAssignment)
            .filter(
                ReviewAssignment.tenant_id == tenant_id,
                ReviewAssignment.actor_kind == actor_kind,
                ReviewAssignment.actor_id == actor_id,
            )
            .order_by(ReviewAssignment.assigned_at.desc())
            .all()
        )

    def get_assignment(self, tenant_id: str, assignment_id: str) -> Optional[ReviewAssignment]:
        return (
            self.db.query(ReviewAssignment)
            .filter(
                ReviewAssignment.tenant_id == tenant_id,
                ReviewAssignment.id == assignment_id,
            )
            .first()
        )

    def add_assignment(self, assignment: ReviewAssignment) -> ReviewAssignment:
        self.db.add(assignment)
        self.db.flush()
        return assignment

    # ---- decisions ----

    def get_decision(
        self, tenant_id: str, config_id: str, group_id: str, revision: int
    ) -> Optional[ReviewDecision]:
        return (
            self.db.query(ReviewDecision)
            .filter(
                ReviewDecision.tenant_id == tenant_id,
                ReviewDecision.review_configuration_id == config_id,
                ReviewDecision.reviewed_submission_group_id == group_id,
                ReviewDecision.revision_number == revision,
            )
            .first()
        )

    def list_decisions_for_config(
        self, tenant_id: str, config_id: str
    ) -> List[ReviewDecision]:
        return (
            self.db.query(ReviewDecision)
            .filter(
                ReviewDecision.tenant_id == tenant_id,
                ReviewDecision.review_configuration_id == config_id,
            )
            .all()
        )

    def list_groups_for_config(self, tenant_id: str, config_id: str) -> List[str]:
        """Distinct submission-group ids that have at least one assignment under
        the config - the universe a decider's Decisions surface iterates over."""
        rows = (
            self.db.query(ReviewAssignment.reviewed_submission_group_id)
            .filter(
                ReviewAssignment.tenant_id == tenant_id,
                ReviewAssignment.review_configuration_id == config_id,
            )
            .distinct()
            .all()
        )
        return [r[0] for r in rows]

    def add_decision(self, decision: ReviewDecision) -> ReviewDecision:
        self.db.add(decision)
        self.db.flush()
        return decision
