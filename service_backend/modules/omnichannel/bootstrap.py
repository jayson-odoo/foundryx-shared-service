"""Omnichannel bootstrap - the App-Store module contract (plan 08 §4).

`install` is GLOBAL and idempotent (schema + tables + permission-catalog sync);
the per-tenant hooks (`install_tenant` / `update_tenant` / `uninstall_tenant`)
are driven by AppStoreService when a tenant installs/updates/uninstalls.
Permission GRANTS are not this module's concern - the store grants/revokes
against the tenant's roles (plan 08 §5).
"""
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.repositories.permission_repository import PermissionRepository
from app.services.permission_service import load_csv
from .db import OMNI_SCHEMA, OmniBase
from .models import Workspace
from .services import statuses

MODULE_NAME = "omnichannel"
MODULE_CSV = Path(__file__).resolve().parent / "permissions" / "permissions.csv"


def _messaging_send(db: Session, tenant_id: str, payload: dict) -> dict:
    """``messaging.send@1`` capability handler (plan sprint-3/10 D5). Tenant-
    scoped seam other modules call via ``resolve_capability`` - full WhatsApp
    outbound wiring lands in the EMS-comms slice (plan 11). Validates payload +
    accepts; never touches another tenant's data."""
    to = (payload or {}).get("to")
    body = (payload or {}).get("body")
    if not to or not body:
        return {"accepted": False, "error": "to + body required"}
    return {"accepted": True, "to": to, "tenantId": tenant_id}


def register_capabilities() -> None:
    """Boot-time capability registration (plan sprint-3/10 D5). Idempotent."""
    from app.module_platform import CapabilityDef, register_capability

    register_capability(
        CapabilityDef(
            key="messaging.send",
            version=1,
            provider_module=MODULE_NAME,
            handler=_messaging_send,
        )
    )


def register_engine_entities() -> None:
    """Boot-time engine registration (plan 11 D9). Idempotent - called by
    ``register_module_boot`` whenever the module is loaded.

    Registers the omnichannel storage-key locations so its media rides the
    generic storage migration automatically (sprint-4/10 AC-10-20):
    ``conversation_messages.media_key`` (inbound/outbound chat media) and
    ``whatsapp_templates.media_sample_key`` (a draft template's media-header
    sample). The declaration is the ``"storage_locations"`` block in
    ``manifest.json`` - the SINGLE source of truth shared with the migration's
    own registration path (``ensure_all_storage_locations``), so the two can
    never drift. Registering the same signatures at app boot is idempotent.
    """
    from app.module_loader import discover_manifests
    from app.storage_migration.core_locations import register_module_declared_locations

    for manifest in discover_manifests():
        if manifest["module_name"] == MODULE_NAME:
            register_module_declared_locations(manifest)
            break

    # Workflow-engine trigger + actions (plan sprint-4/17) - registers into the
    # core registry's dict-backed catalog; idempotent like the rest of this hook.
    from .workflow_nodes import register_omnichannel_workflow_nodes

    register_omnichannel_workflow_nodes()

    # Deferred (grace-window) actions (sprint-4/23, T5 fix round 1, item 15):
    # omnichannel's own confirm:-gated destructive actions register into the
    # CORE grace-window engine here, the same way any other module extends a
    # shared engine (status/rule/workflow) - never a fork.
    from .deferred_actions import register_omnichannel_deferred_actions

    register_omnichannel_deferred_actions()


def create_schema_and_tables(engine: Engine) -> None:
    """Create the module schema (Postgres) + all module tables. Idempotent."""
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{OMNI_SCHEMA}"'))
    OmniBase.metadata.create_all(bind=engine)
    # create_all only adds NEW tables - columns added after plan 04 need an
    # explicit idempotent ALTER for existing deployments (per-module Alembic
    # is the real fix, BL-029).
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            conn.execute(
                text(
                    f'ALTER TABLE "{OMNI_SCHEMA}".contacts '
                    "ADD COLUMN IF NOT EXISTS agent_last_read_at TIMESTAMPTZ"
                )
            )
            # Internal notes are channel-less (plan 05 Phase B).
            conn.execute(
                text(
                    f'ALTER TABLE "{OMNI_SCHEMA}".conversation_messages '
                    "ALTER COLUMN channel_id DROP NOT NULL"
                )
            )
            # WABA config + business-profile mirror (plan 06 §7) - idempotent
            # add for existing deployments (per-module Alembic is BL-029).
            _channel_cols = [
                ("business_account_name", "VARCHAR"),
                ("verified_name", "VARCHAR"),
                ("profile_about", "VARCHAR"),
                ("profile_address", "VARCHAR"),
                ("profile_description", "TEXT"),
                ("profile_email", "VARCHAR"),
                ("profile_vertical", "VARCHAR"),
                ("profile_website_1", "VARCHAR"),
                ("profile_website_2", "VARCHAR"),
                ("profile_picture_url", "VARCHAR"),
                ("profile_synced_at", "TIMESTAMPTZ"),
            ]
            for col, coltype in _channel_cols:
                conn.execute(
                    text(
                        f'ALTER TABLE "{OMNI_SCHEMA}".channels '
                        f"ADD COLUMN IF NOT EXISTS {col} {coltype}"
                    )
                )
            # Rich-media columns (plan 12) - idempotent add for existing deploys.
            _message_cols = [
                ("media_key", "VARCHAR"),
                ("media_mime", "VARCHAR"),
                ("media_filename", "VARCHAR"),
                ("media_size", "INTEGER"),
                # Generic JSON (matches the model's JSON(none_as_null) + the
                # module's other JSON columns + the 0004 migration's sa.JSON()).
                ("payload_json", "JSON"),
            ]
            for col, coltype in _message_cols:
                conn.execute(
                    text(
                        f'ALTER TABLE "{OMNI_SCHEMA}".conversation_messages '
                        f"ADD COLUMN IF NOT EXISTS {col} {coltype}"
                    )
                )
            # Federated-attribution columns (plan 11H Slice 1) - idempotent add.
            conn.execute(
                text(
                    f'ALTER TABLE "{OMNI_SCHEMA}".conversation_messages '
                    "ADD COLUMN IF NOT EXISTS sender_external_agent_id VARCHAR"
                )
            )
            conn.execute(
                text(
                    f'ALTER TABLE "{OMNI_SCHEMA}".contacts '
                    "ADD COLUMN IF NOT EXISTS assigned_external_agent_id VARCHAR"
                )
            )
            # Template management columns (plan 07 §8) - idempotent add.
            _template_cols = [
                ("meta_template_id", "VARCHAR"),
                ("quality", "VARCHAR"),
                ("rejected_reason", "VARCHAR"),
                ("last_synced_at", "TIMESTAMPTZ"),
                ("media_sample_key", "VARCHAR"),
            ]
            for col, coltype in _template_cols:
                conn.execute(
                    text(
                        f'ALTER TABLE "{OMNI_SCHEMA}".whatsapp_templates '
                        f"ADD COLUMN IF NOT EXISTS {col} {coltype}"
                    )
                )
            # phone_number_id → service-wide UNIQUE (plan Slice 3, AC-01-20) for
            # O(1) inbound routing. Reconcile any existing duplicates FIRST (keep
            # the earliest by created_at,id; NULL the losers) then add a partial
            # unique index (nullable rows stay allowed). Idempotent.
            conn.execute(
                text(
                    f'UPDATE "{OMNI_SCHEMA}".channels c SET phone_number_id = NULL '
                    "WHERE c.phone_number_id IS NOT NULL AND c.is_trashed = false AND EXISTS ("
                    f'  SELECT 1 FROM "{OMNI_SCHEMA}".channels c2 '
                    "  WHERE c2.phone_number_id = c.phone_number_id AND c2.is_trashed = false "
                    "    AND (c2.created_at < c.created_at "
                    "         OR (c2.created_at = c.created_at AND c2.id < c.id)))"
                )
            )
            # Drop any pre-existing all-rows index (earlier build) so the scoped
            # (live-only) predicate takes effect - a disconnected channel keeps
            # its phone_number_id and must not block reconnecting the same number.
            conn.execute(text("DROP INDEX IF EXISTS uq_channels_phone_number_id"))
            conn.execute(
                text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS uq_channels_phone_number_id "
                    f'ON "{OMNI_SCHEMA}".channels (phone_number_id) '
                    "WHERE phone_number_id IS NOT NULL AND is_trashed = false"
                )
            )


def install(engine: Engine, db: Session) -> None:
    """Global install (plan 08 §4): schema + tables + permission catalog sync.

    Runs at every bootstrap (idempotent). Per-tenant seeding happens in
    ``install_tenant`` when a tenant actually installs the module.
    """
    create_schema_and_tables(engine)
    PermissionRepository(db).sync(MODULE_NAME, load_csv(MODULE_CSV))


def install_tenant(db: Session, tenant_id: str) -> None:
    """Per-tenant seed: statuses + the default 'General' workspace. Idempotent."""
    statuses.ensure_statuses(db, tenant_id)
    exists = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True))
        .first()
    )
    if exists:
        return
    db.add(
        Workspace(
            tenant_id=tenant_id,
            name="General",
            status_id=statuses.status_id_for(db, tenant_id, "WORKSPACE", "ACTIVE"),
            is_default=True,
            is_trashed=False,
        )
    )
    db.flush()


def update_tenant(db: Session, tenant_id: str, from_version: str) -> None:
    """Per-tenant data migration between provisioned versions (plan 08 D3).

    All of omnichannel is 0.1.0 today - nothing to backfill yet. New seeds /
    backfills land here guarded by ``from_version`` comparisons.
    """


def uninstall_tenant(db: Session, tenant_id: str) -> None:
    """Wipe THIS tenant's rows from every module table (plan 08 §5).

    The module schema and other tenants' rows are untouched - uninstall is
    per-tenant, never global. Reverse dependency order avoids FK violations.
    """
    for table in reversed(OmniBase.metadata.sorted_tables):
        if "tenant_id" in table.c:
            db.execute(table.delete().where(table.c.tenant_id == tenant_id))
    db.flush()


def tenant_has_data(db: Session, tenant_id: str) -> bool:
    """Backfill detection (loader): pre-App-Store installs seeded a default
    workspace per tenant - its presence marks the tenant as already-installed."""
    return (
        db.query(Workspace.id).filter(Workspace.tenant_id == tenant_id).first() is not None
    )


def seed_demo_conversations(db: Session, tenant_id: str) -> None:
    """DEV-ONLY demo inbox dataset (mirrors the Phase A mock): five threads in
    distinct states + templates + quick replies, attached to a dev-credentialed
    "Demo WhatsApp" channel so outbound sends hit the adapter's stub, never the
    real Graph API. Idempotent (keys on the fixed contact ids). Called by the
    dev seed scripts only - never in prod bootstrap.
    """
    from datetime import datetime, timedelta, timezone

    from .models import Channel, Contact, ContactChannelIdentity, ConversationMessage, QuickReply, WhatsappTemplate
    from .security import encrypt_credentials

    if db.query(Contact).filter(Contact.id == "cnt-001").first():
        return

    now = datetime.now(timezone.utc)
    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == tenant_id, Workspace.is_default.is_(True))
        .first()
    )
    if ws is None:
        return

    channel = db.query(Channel).filter(Channel.id == "chn-demo").first()
    if channel is None:
        channel = Channel(
            id="chn-demo",
            tenant_id=tenant_id,
            workspace_id=ws.id,
            channel_type="WHATSAPP",
            name="Demo WhatsApp (sandbox)",
            credentials_json=encrypt_credentials({"dev": True}),
            waba_id="waba-demo",
            phone_number_id="pn-demo",
            display_phone_number="+60 11-111 1111",
            is_active=True,
            status_id=statuses.status_id_for(db, tenant_id, "CHANNEL", "ACTIVE"),
        )
        db.add(channel)
        db.flush()

    open_id = statuses.status_id_for(db, tenant_id, "THREAD", "OPEN")
    snoozed_id = statuses.status_id_for(db, tenant_id, "THREAD", "SNOOZED")
    closed_id = statuses.status_id_for(db, tenant_id, "THREAD", "CLOSED")

    def hours(n):
        return now - timedelta(hours=n)

    threads = [
        # (id, name, phone, status_id, priority, csw_expires, last_in, msgs)
        ("cnt-001", ("Sarah", "Chen"), "+60 12-345 6789", open_id, "HIGH", now + timedelta(hours=20), [
            ("CONTACT", "Hi! I booked the Grand Ballroom for Friday.", 4.7, None),
            ("AGENT", "Hi Sarah! Yes, I can see your booking - Friday 7pm, 120 pax.", 4.5, "READ"),
            ("SYSTEM", "VIP client - handle with priority. Decision maker is Sarah.", 4.4, None),
            ("CONTACT", "Great. One more thing -", 4.0, None),
            ("CONTACT", "Can I change my booking to Saturday?", 0.17, None),
            ("AGENT", "Checking availability now, give me a minute 🙏", 0.13, "DELIVERED"),
            ("AGENT", "Saturday 7pm is free - shall I move it?", 0.1, "SENT"),
        ]),
        ("cnt-002", ("Marcus", "Wong"), "+60 16-888 2211", open_id, "MEDIUM", hours(3), [
            ("CONTACT", "Confirming Friday 3pm site visit.", 28, None),
            ("AGENT", "Confirmed! See you at the lobby.", 27.5, "READ"),
            ("CONTACT", "Thanks, see you then!", 27, None),
        ]),
        ("cnt-003", ("Priya", "Raj"), "+60 17-202 0303", open_id, "URGENT", now + timedelta(hours=22), [
            ("CONTACT", "Is the venue wheelchair accessible?", 0.5, None),
        ]),
        ("cnt-004", ("Daniel", "Lee"), "+60 11-555 7788", snoozed_id, "LOW", now + timedelta(hours=2), [
            ("CONTACT", "Any update on the quotation?", 22, None),
            ("AGENT", "Finance is reviewing - I will revert by Thursday.", 21.5, "READ"),
            ("CONTACT", "No rush - next week is fine.", 21, None),
        ]),
        ("cnt-005", ("Aisha", "Abdullah"), "+60 19-444 9090", closed_id, "MEDIUM", hours(40), [
            ("CONTACT", "Received the invoice, paying today.", 64, None),
            ("AGENT", "Payment received - booking confirmed! 🎉", 63.5, "READ"),
            ("CONTACT", "Perfect, thank you so much!", 63, None),
        ]),
    ]

    for cid, (first, last), phone, status_id, priority, csw, msgs in threads:
        last_at = None
        last_in = None
        contact = Contact(
            id=cid,
            tenant_id=tenant_id,
            workspace_id=ws.id,
            first_name=first,
            last_name=last,
            phone=phone,
            status_id=status_id,
            priority=priority,
            csw_expires_at=csw,
        )
        db.add(contact)
        db.flush()
        digits = "".join(c for c in phone if c.isdigit())
        db.add(
            ContactChannelIdentity(
                tenant_id=tenant_id,
                contact_id=cid,
                channel_id=channel.id,
                external_user_id=digits,
                profile_name=f"{first} {last}",
            )
        )
        for i, (sender, body, hours_ago, delivery) in enumerate(msgs):
            created = now - timedelta(hours=hours_ago)
            db.add(
                ConversationMessage(
                    tenant_id=tenant_id,
                    contact_id=cid,
                    channel_id=channel.id if sender != "SYSTEM" else None,
                    sender_type=sender,
                    message_type="TEXT",
                    body=body,
                    external_message_id=f"wamid.demo-{cid}-{i}" if sender != "SYSTEM" else None,
                    delivery_status=delivery,
                    created_at=created,
                )
            )
            last_at = created
            if sender == "CONTACT":
                last_in = created
        contact.last_message_at = last_at
        contact.last_incoming_message_at = last_in
        # cnt-001/cnt-003 unread (agent never opened); others read.
        if cid not in ("cnt-001", "cnt-003"):
            contact.agent_last_read_at = now

    db.add_all([
        WhatsappTemplate(
            id="tpl-001", tenant_id=tenant_id, channel_id=channel.id,
            name="booking_update", language="en", category="UTILITY", status="APPROVED",
            components_json=[{"type": "BODY", "text": "Hi {{1}}, there is an update on your booking: {{2}}. Reply to this message to continue the conversation."}],
        ),
        WhatsappTemplate(
            id="tpl-002", tenant_id=tenant_id, channel_id=channel.id,
            name="payment_reminder", language="en", category="UTILITY", status="APPROVED",
            components_json=[{"type": "BODY", "text": "Hi {{1}}, a friendly reminder that invoice {{2}} is due on {{3}}."}],
        ),
        WhatsappTemplate(
            id="tpl-003", tenant_id=tenant_id, channel_id=channel.id,
            name="promo_blast", language="en", category="MARKETING", status="PENDING",
            components_json=[{"type": "BODY", "text": "Big news {{1}}! Our new venue is open."}],
        ),
        QuickReply(tenant_id=tenant_id, workspace_id=ws.id, shortcut="/hi", body="Hi! Thanks for reaching out to Foundryx Events - how can I help?"),
        QuickReply(tenant_id=tenant_id, workspace_id=ws.id, shortcut="/hours", body="Our office hours are Mon-Fri 9am-6pm (MYT)."),
        QuickReply(tenant_id=tenant_id, workspace_id=ws.id, shortcut="/payment", body="You can pay via bank transfer or card - the link is in your invoice email."),
    ])
    db.commit()
