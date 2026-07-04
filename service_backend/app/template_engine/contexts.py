"""Template contexts — code-side registry (plan 07 D11).

Mirrors ``STATUS_ENTITIES`` / fact-source registration: a context defines
WHERE a template renders — its merge-fact vocabulary (with samples for
preview/test-send), the rule-engine fact sources usable in visibility
conditions, and the facts a template MUST consume to be saveable (D7 safety
rail: a reset-password template without {{resetLink}} is a broken product
flow, not a style choice).

Modules register their contexts at install and ship platform-tier default
templates; core registers the auth/account/status contexts below.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Sequence

from app.lazy_registry import lazy_once


@dataclass(frozen=True)
class ContextFact:
    key: str
    label: str
    sample: str


@dataclass(frozen=True)
class ListFact:
    """A list fact — bound by a table/repeater `source` (F2 document surface).

    ``item_facts`` are the row sub-fields (the ``row.*`` vocabulary for the
    iterator body); ``sample`` is a list of row dicts used by preview/render
    when no real binding exists yet (domain binding lands with the consumer).
    """

    key: str
    label: str
    item_facts: Sequence[ContextFact] = field(default_factory=tuple)
    sample: Sequence[Dict[str, str]] = field(default_factory=tuple)


@dataclass(frozen=True)
class TemplateContext:
    key: str
    label: str
    # Rule-engine fact sources for block visibility conditions (D8).
    fact_sources: Sequence[str] = field(default_factory=tuple)
    # Merge-field vocabulary (chips + preview samples).
    facts: Sequence[ContextFact] = field(default_factory=tuple)
    # List facts bindable by table/repeater blocks (document surface, F2).
    list_facts: Sequence[ListFact] = field(default_factory=tuple)
    # Facts that MUST appear in doc/subject (save-time 422 — D7).
    required_facts: Sequence[str] = field(default_factory=tuple)
    # Registering module — delisted with it (core = "core").
    module: str = "core"

    def sample_facts(self) -> Dict[str, str]:
        return {f.key: f.sample for f in self.facts}

    def list_fact(self, key: str) -> "ListFact | None":
        for lf in self.list_facts:
            if lf.key == key:
                return lf
        return None


_CONTEXTS: Dict[str, TemplateContext] = {}


def register_context(context: TemplateContext) -> None:
    """Idempotent — modules re-register on every bootstrap."""
    _CONTEXTS[context.key] = context


def deregister_module_contexts(module: str) -> None:
    for key in [k for k, c in _CONTEXTS.items() if c.module == module]:
        del _CONTEXTS[key]


def get_context(key: str) -> TemplateContext | None:
    ensure_core_contexts()
    return _CONTEXTS.get(key)


def list_contexts() -> List[TemplateContext]:
    ensure_core_contexts()
    return sorted(_CONTEXTS.values(), key=lambda c: c.label)


_RECIPIENT_FACTS = (
    ContextFact("recipient.firstName", "Recipient first name", "Alex"),
    ContextFact("recipient.name", "Recipient full name", "Alex Tan"),
    ContextFact("recipient.email", "Recipient email", "alex@example.com"),
    ContextFact("tenant.name", "Workspace name", "Acme Events"),
)


def _register_core() -> None:
    register_context(
        TemplateContext(
            key="auth.password_reset",
            label="Auth · Password reset",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS
            + (
                ContextFact("resetLink", "Reset link", "https://acme.example.com/change-password?token=sample"),
                ContextFact("expiresInMinutes", "Link expiry (minutes)", "60"),
            ),
            required_facts=("resetLink",),
        )
    )
    register_context(
        TemplateContext(
            key="auth.invite",
            label="Auth · User invitation",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS
            + (
                ContextFact("inviteLink", "Invitation link", "https://acme.example.com/change-password?token=sample"),
                ContextFact("expiresInDays", "Link expiry (days)", "7"),
            ),
            required_facts=("inviteLink",),
        )
    )
    register_context(
        TemplateContext(
            key="auth.verification",
            label="Auth · Email verification",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS
            + (
                ContextFact("verifyLink", "Verification link", "https://acme.example.com/verify-email?token=sample"),
            ),
            required_facts=("verifyLink",),
        )
    )
    register_context(
        TemplateContext(
            key="account.email_change_approve",
            label="Account · Email change — approve (old mailbox)",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS
            + (
                ContextFact("newEmail", "Requested new email (masked)", "a***@example.com"),
                ContextFact("approveLink", "Approve link", "https://acme.example.com/approve-email-change?token=sample"),
            ),
            required_facts=("approveLink",),
        )
    )
    register_context(
        TemplateContext(
            key="account.email_change_verify",
            label="Account · Email change — verify (new mailbox)",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS
            + (
                ContextFact("verifyLink", "Verify link", "https://acme.example.com/verify-email-change?token=sample"),
            ),
            required_facts=("verifyLink",),
        )
    )
    register_context(
        TemplateContext(
            key="account.email_change_notice",
            label="Account · Email change — notice (both mailboxes)",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS
            + (
                ContextFact("oldEmail", "Previous email", "old@example.com"),
                ContextFact("newEmail", "New email", "new@example.com"),
            ),
            required_facts=(),
        )
    )
    register_context(
        TemplateContext(
            key="status.notification",
            label="Status engine · Transition notification",
            fact_sources=("actor",),
            facts=(
                ContextFact("recordLabel", "Record label", "Acme Events"),
                ContextFact("fromStatus", "From status", "Active"),
                ContextFact("toStatus", "To status", "Suspended"),
                ContextFact("actorName", "Actor name", "Jordan Lee"),
                ContextFact("entityLabel", "Entity", "Tenant"),
                ContextFact("tenant.name", "Workspace name", "Acme Events"),
            ),
            required_facts=(),
        )
    )
    register_context(
        TemplateContext(
            key="template.test",
            label="Template · Test send",
            fact_sources=("recipient",),
            facts=_RECIPIENT_FACTS,
            required_facts=(),
        )
    )
    # F2 document surface — sample context so the PDF designer is exercisable
    # ahead of the real invoice entity (Cluster F registers the bound context).
    register_context(
        TemplateContext(
            key="document.invoice_preview",
            label="Document · Invoice (sample)",
            fact_sources=(),
            facts=(
                ContextFact("companyName", "Your company name", "Acme Events"),
                ContextFact("recipientName", "Bill-to name", "Jordan Lee"),
                ContextFact("invoiceNumber", "Invoice number", "INV-1042"),
                ContextFact("invoiceDate", "Invoice date", "12 Jun 2026"),
                ContextFact("subtotal", "Subtotal", "$1,400.00"),
                ContextFact("tax", "Tax", "$84.00"),
                ContextFact("total", "Total", "$1,484.00"),
            ),
            list_facts=(
                ListFact(
                    key="lineItems",
                    label="Line items",
                    item_facts=(
                        ContextFact("description", "Description", "Booth rental"),
                        ContextFact("qty", "Qty", "1"),
                        ContextFact("amount", "Amount", "$500.00"),
                    ),
                    sample=(
                        {"description": "Booth rental", "qty": "1", "amount": "$500.00"},
                        {"description": "Catering", "qty": "3", "amount": "$900.00"},
                    ),
                ),
            ),
            required_facts=("invoiceNumber",),
        )
    )

    # F2 slice 2 — fixed-canvas (badge) sample context so the canvas designer is
    # exercisable ahead of the real attendee entity (Cluster H binds the real
    # context). Scalar facts only; ticketCode drives a QR element.
    register_context(
        TemplateContext(
            key="badge.preview",
            label="Badge · Attendee (sample)",
            fact_sources=(),
            facts=(
                ContextFact("attendeeName", "Attendee name", "Alex Tan"),
                ContextFact("role", "Role", "Speaker"),
                ContextFact("company", "Company", "Acme Events"),
                ContextFact("ticketCode", "Ticket code (QR)", "TKT-7F3A91"),
            ),
            required_facts=("attendeeName",),
        )
    )

    # Visibility conditions over the RECIPIENT need a rule-engine source —
    # register it beside the contexts (core fact sources live in
    # app/rule_engine/registry; this one is template-engine-owned).
    from app.models.user import User
    from app.rule_engine.registry import infer_facts, register_fact_source

    register_fact_source(
        "recipient",
        "Recipient",
        infer_facts(User, ["email", "name", "status"], prefix="recipient"),
    )


ensure_core_contexts = lazy_once(_register_core)
