"""The ONE shared report fixture (plan 30, roadmap A9) - reproduces EXACTLY
the UAC's "Seeded report fixture" table
(`30-omnichannel-dashboard-reports-acceptance-criteria.md`): 3 users, 8
threads, 13 messages, and every `conversation_events` row the table lists
(25 rows by literal count - the plan/brief text says "24"; the coder's
handoff report flags this as an off-by-one in the prose, the table itself is
authoritative and is what this fixture reproduces byte-for-byte).

Every `test_omnichannel_reports*.py` test imports `seed_report_fixture` so
every numeric AC (S1's dashboard AND S2's seven reports) asserts against ONE
source of truth, never a per-test hand copy. Report timezone for every
numeric AC is `Asia/Kuala_Lumpur`; range `from=2026-03-01&to=2026-03-07`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict

from sqlalchemy.orm import Session
from sqlalchemy.sql import func as sa_func

from app.models import DEFAULT_TENANT_ID, User, UserStatus
from app.security import hash_password

from modules.omnichannel.models import (
    Channel,
    CloseReason,
    Contact,
    ConversationEvent,
    ConversationMessage,
    WorkspaceMember,
)
from modules.omnichannel.schemas import WorkspaceCreate
from modules.omnichannel.security import encrypt_credentials
from modules.omnichannel.services import statuses as thread_statuses
from modules.omnichannel.services.lifecycle_service import stages_for_workspace
from modules.omnichannel.services.workspace_service import WorkspaceService

_REASON_KEYS = {
    "General Inquiry": "general",
    "Sales Inquiry": "sales",
    "Payment Issue": "payment",
    "Others": "others",
}


@dataclass
class FixtureIds:
    tenant_id: str
    workspace_id: str
    channel_id: str
    users: Dict[str, str] = field(default_factory=dict)  # "ann"|"ben"|"cara" -> user id
    contacts: Dict[str, str] = field(default_factory=dict)  # "C1".."C8" -> contact id
    close_reasons: Dict[str, str] = field(default_factory=dict)  # "general"|"sales"|"payment"|"others"
    lifecycle: Dict[str, str] = field(default_factory=dict)  # "new_lead"|"hot_lead"|... -> status id
    thread_statuses: Dict[str, str] = field(default_factory=dict)  # "OPEN"|"SNOOZED"|"CLOSED" -> id


def _dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _make_user(db: Session, tenant_id: str, email: str, name: str) -> str:
    user = User(
        tenant_id=tenant_id,
        email=email,
        password=hash_password("pw12345678"),
        name=name,
        status=UserStatus.ACTIVE.value,
        email_verified_at=sa_func.now(),
    )
    db.add(user)
    db.flush()
    return user.id


def seed_report_fixture(
    db: Session, tenant_id: str = DEFAULT_TENANT_ID, *, workspace_name: str = "Report Fixture"
) -> FixtureIds:
    """Creates its OWN dedicated workspace (never reuses the tenant's default
    workspace, so this fixture's numbers never depend on test order/residue
    from other tests in the same tenant). Commits once at the end."""
    thread_statuses.ensure_statuses(db, tenant_id)

    ws_item = WorkspaceService(db).create(WorkspaceCreate(name=workspace_name), tenant_id)
    workspace_id = ws_item.id

    channel = Channel(
        tenant_id=tenant_id,
        workspace_id=workspace_id,
        channel_type="WHATSAPP",
        name="WhatsApp Demo",
        credentials_json=encrypt_credentials({"dev": True}),
        phone_number_id=f"pn-report-{workspace_id[:8]}",
        display_phone_number="+60 11-111 1111",
        is_active=True,
        status_id=thread_statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
    )
    db.add(channel)
    db.flush()

    ids = FixtureIds(tenant_id=tenant_id, workspace_id=workspace_id, channel_id=channel.id)

    ids.users["ann"] = _make_user(db, tenant_id, f"ann-{workspace_id[:8]}@fixture.example", "Ann Lee")
    ids.users["ben"] = _make_user(db, tenant_id, f"ben-{workspace_id[:8]}@fixture.example", "Ben Ooi")
    ids.users["cara"] = _make_user(db, tenant_id, f"cara-{workspace_id[:8]}@fixture.example", "Cara Tan")
    for key in ("ann", "ben", "cara"):
        db.add(WorkspaceMember(tenant_id=tenant_id, workspace_id=workspace_id, user_id=ids.users[key]))
    db.flush()

    for status_key in ("OPEN", "SNOOZED", "CLOSED"):
        ids.thread_statuses[status_key] = thread_statuses.status_id_for(db, tenant_id, "THREAD", status_key)

    for reason in (
        db.query(CloseReason)
        .filter(CloseReason.tenant_id == tenant_id, CloseReason.workspace_id == workspace_id)
        .all()
    ):
        ids.close_reasons[_REASON_KEYS[reason.name]] = reason.id

    for stage in stages_for_workspace(db, tenant_id, workspace_id):
        ids.lifecycle[stage.key] = stage.id

    # ── Contacts - final CURRENT STATE (the UAC's "Current state" line) ─────
    # label -> (thread status key, assignee user key or None, lifecycle key)
    contact_specs = {
        "C1": ("CLOSED", None, "new_lead"),
        "C2": ("CLOSED", None, "new_lead"),
        "C3": ("OPEN", "ann", "new_lead"),
        "C4": ("CLOSED", None, "new_lead"),
        "C5": ("CLOSED", None, "hot_lead"),
        "C6": ("OPEN", None, "hot_lead"),
        "C7": ("SNOOZED", None, "payment"),
        "C8": ("CLOSED", None, "customer"),
    }
    for i, (label, (status_key, assignee, lifecycle_key)) in enumerate(contact_specs.items()):
        contact = Contact(
            tenant_id=tenant_id,
            workspace_id=workspace_id,
            first_name="Customer",
            last_name=label,
            phone=f"+601190000{i:02d}",
            phone_digits=f"601190000{i:02d}",
            status_id=ids.thread_statuses[status_key],
            assigned_user_id=ids.users[assignee] if assignee else None,
            lifecycle_status_id=ids.lifecycle[lifecycle_key],
        )
        db.add(contact)
        db.flush()
        ids.contacts[label] = contact.id

    u = ids.users
    c = ids.contacts
    r = ids.close_reasons

    def ev(label: str, event_type: str, at: str, **kw) -> None:
        db.add(
            ConversationEvent(
                tenant_id=tenant_id,
                workspace_id=workspace_id,
                contact_id=c[label],
                event_type=event_type,
                created_at=_dt(at),
                **kw,
            )
        )

    # ── Events - EXACTLY the UAC's "Threads and events" table ────────────────
    ev("C1", "opened", "2026-03-01T02:00:00Z")
    ev("C1", "first_agent_reply", "2026-03-01T02:00:30Z", actor_user_id=u["ann"], payload_json={"responseSeconds": 30})
    ev("C1", "closed", "2026-03-01T03:00:00Z", actor_user_id=u["ann"], close_reason_id=r["general"])

    ev("C2", "opened", "2026-03-01T15:30:00Z")
    ev("C2", "assigned", "2026-03-01T15:40:00Z", actor_user_id=u["ann"], to_value=u["ann"])
    ev("C2", "first_agent_reply", "2026-03-01T15:45:00Z", actor_user_id=u["ben"], payload_json={"responseSeconds": 900})
    ev("C2", "closed", "2026-03-02T02:00:00Z", actor_user_id=u["ben"], close_reason_id=r["sales"])

    ev("C3", "opened", "2026-03-01T16:30:00Z")
    ev("C3", "first_agent_reply", "2026-03-01T16:32:00Z", actor_user_id=u["ann"], payload_json={"responseSeconds": 120})

    ev("C4", "opened", "2026-03-02T01:00:00Z")
    ev("C4", "assigned", "2026-03-02T01:05:00Z", actor_user_id=u["ann"], to_value=u["ben"])
    ev("C4", "first_agent_reply", "2026-03-02T01:07:00Z", actor_user_id=u["ben"], payload_json={"responseSeconds": 420})
    ev("C4", "closed", "2026-03-02T05:00:00Z", actor_user_id=u["ben"], close_reason_id=r["payment"])

    ev("C5", "opened", "2026-03-03T03:00:00Z")
    ev("C5", "closed", "2026-03-03T04:00:00Z", actor_user_id=u["ann"], close_reason_id=r["others"])
    ev("C5", "reopened", "2026-03-04T03:00:00Z")
    ev("C5", "first_agent_reply", "2026-03-04T03:00:20Z", actor_user_id=u["ann"], payload_json={"responseSeconds": 20})
    ev("C5", "closed", "2026-03-04T06:00:00Z", actor_user_id=u["ann"], close_reason_id=r["general"])

    ev("C2", "unassigned", "2026-03-04T08:00:00Z", actor_user_id=u["ben"], from_value=u["ann"])

    ev("C6", "opened", "2026-03-05T02:00:00Z", payload_json={"backfilled": True})
    ev("C6", "comment_added", "2026-03-05T02:05:00Z", actor_user_id=u["ann"])

    ev("C7", "opened", "2026-03-05T16:10:00Z")
    ev("C7", "snoozed", "2026-03-05T17:00:00Z")

    ev("C8", "opened", "2026-02-28T02:00:00Z")
    ev("C8", "closed", "2026-03-06T02:00:00Z", actor_user_id=u["ann"], close_reason_id=r["others"])

    def msg(label: str, sender: str, at: str, sender_id=None) -> None:
        db.add(
            ConversationMessage(
                tenant_id=tenant_id,
                contact_id=c[label],
                channel_id=channel.id,
                sender_type=sender,
                sender_id=sender_id,
                message_type="TEXT",
                body="fixture",
                created_at=_dt(at),
            )
        )

    # ── Messages - EXACTLY the UAC's "Messages" table (13 rows) ──────────────
    msg("C1", "CONTACT", "2026-03-01T02:00:00Z")
    msg("C1", "AGENT", "2026-03-01T02:00:30Z", u["ann"])
    msg("C2", "CONTACT", "2026-03-01T15:30:00Z")
    msg("C2", "AGENT", "2026-03-01T15:45:00Z", u["ben"])
    msg("C3", "CONTACT", "2026-03-01T16:30:00Z")
    msg("C3", "AGENT", "2026-03-01T16:32:00Z", u["ann"])
    msg("C4", "CONTACT", "2026-03-02T01:00:00Z")
    msg("C4", "AGENT", "2026-03-02T01:07:00Z", u["ben"])
    msg("C5", "CONTACT", "2026-03-04T03:00:00Z")
    msg("C5", "AGENT", "2026-03-04T03:00:20Z", u["ann"])
    msg("C6", "CONTACT", "2026-03-05T02:00:00Z")
    msg("C6", "AGENT", "2026-03-05T02:03:00Z", u["ben"])
    msg("C6", "SYSTEM", "2026-03-05T02:05:00Z", u["ann"])

    db.commit()
    return ids
