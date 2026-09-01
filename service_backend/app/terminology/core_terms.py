"""Core relabelable entities (sprint-3/08 seed).

The existing core entities a tenant may reasonably rename, so the mechanism is
demoable day one. Deliberately EXCLUDES ``user``/``permission``/``tenant`` -
relabeling those confuses RBAC/admin. EMS adds ``project``/``profile``/… at
the ``ems`` module's install (plan 11).
"""
from app.terminology.registry import TermDef, register_term

CORE_TERMS = [
    TermDef("form", "Form", "Forms", group="Engines",
            description="A drag-drop form/survey."),
    TermDef("workflow", "Workflow", "Workflows", group="Engines",
            description="An automation (trigger → actions)."),
    TermDef("template", "Template", "Templates", group="Engines",
            description="An email/document template."),
    TermDef("document", "Document", "Documents", group="Content",
            description="A file in the tenant Drive."),
    TermDef("connection", "Integration", "Integrations", group="Settings",
            description="An external-service connection."),
    TermDef("role", "Role", "Roles", group="Access",
            description="A set of permissions assignable to users."),
    TermDef("import", "Import", "Imports", group="Engines",
            description="A bulk-import job."),
    TermDef("submission", "Submission", "Submissions", group="Engines",
            description="A form submission under review/approval."),
    TermDef("review", "Review", "Reviews", group="Engines",
            description="A review/approval of a submission."),
    TermDef("product", "Product", "Products", group="Catalog",
            description="A catalog product/service."),
    TermDef("product_category", "Category", "Categories", group="Catalog",
            description="A product category in the taxonomy tree."),
]


def register_core_terms() -> None:
    for term in CORE_TERMS:
        register_term(term)
