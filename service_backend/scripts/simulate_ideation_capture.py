"""End-to-end SIMULATION of the ideation Conversational-Intake capture flow.

Drives the REAL ``create_idea`` state machine (via the FastAPI TestClient, the same
transport sorento's brain uses) across a multi-turn WhatsApp-style conversation and
prints a transcript for each turn: the USER message (+ the brain-extracted
``fields`` / ``remove`` / ``confirm`` it stands in for), then the RETURNED
``status``, ``captured``, ``missing`` and ``reply_text``.

This is a demonstration of D-CONFIRM (a fully-complete intake still returns
``review`` until an explicit confirm) - it does NOT change any feature code and it
runs entirely on an in-memory SQLite copy of the module stack (no live Postgres,
no LLM).

Run:  cd service_backend && .venv/bin/python scripts/simulate_ideation_capture.py
"""
from __future__ import annotations

import os
import sys

# Make ``app`` / ``modules`` / ``tests`` importable when run as a bare script.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import func

# Importing tests.conftest neutralises live Meta/SMTP/Celery config for the
# process (same as the pytest run), so the omnichannel adapter runs in DEV mode.
import tests.conftest as conftest  # noqa: F401  (side-effect: settings blanking)
from app.database import Base, get_db
from app.main import app
from app.models import DEFAULT_TENANT_ID, Role, User, UserStatus
from app.models.status import Status
from app.seed import (
    seed_default_tenant,
    seed_permissions,
    seed_platform_admin,
    seed_platform_tenant,
    seed_statuses,
    seed_tenant_transitions,
    tenant_admin_grant,
)
from app.security import hash_password

ACTIVE_EMAIL = conftest.ACTIVE_EMAIL
ACTIVE_PASSWORD = conftest.ACTIVE_PASSWORD
PRODUCT_DOMAIN_BASE = "https://fe-sorento.foundryx.my"


# ── build an in-memory session factory with omnichannel + ideation installed ──


def build_session_factory():
    """Mirror ``tests.conftest.ideation_session_factory`` for a standalone run."""
    from modules.ideation.db import IDEATION_SCHEMA, IdeationBase
    from modules.omnichannel.db import OMNI_SCHEMA, OmniBase

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    ).execution_options(
        schema_translate_map={OMNI_SCHEMA: "omni", IDEATION_SCHEMA: "ideation"}
    )
    with engine.connect() as conn:
        conn.exec_driver_sql("ATTACH ':memory:' AS omni")
        conn.exec_driver_sql("ATTACH ':memory:' AS ideation")
        conn.commit()
    Base.metadata.create_all(bind=engine)
    OmniBase.metadata.create_all(bind=engine)
    IdeationBase.metadata.create_all(bind=engine)
    Factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    db = Factory()
    seed_statuses(db)
    seed_tenant_transitions(db)
    seed_default_tenant(db)
    seed_platform_tenant(db)
    seed_permissions(db)
    seed_platform_admin(db)
    from app.template_engine.seed_templates import seed_platform_templates

    seed_platform_templates(db)

    admin_role = Role(
        tenant_id=DEFAULT_TENANT_ID,
        name="Admin",
        description="Full system access",
        is_system=True,
    )
    admin_role.permissions = tenant_admin_grant(db, DEFAULT_TENANT_ID)
    db.add(admin_role)
    db.flush()

    demo = User(
        tenant_id=DEFAULT_TENANT_ID,
        email=ACTIVE_EMAIL,
        password=hash_password(ACTIVE_PASSWORD),
        name="Demo User",
        status=UserStatus.ACTIVE.value,
        email_verified_at=func.now(),
    )
    demo.roles = [admin_role]
    db.add(demo)
    db.commit()

    from app.module_loader import bootstrap_modules
    from app.services.app_store_service import AppStoreService

    bootstrap_modules(engine=engine, db=db)
    store = AppStoreService(db)
    store.install(DEFAULT_TENANT_ID, "omnichannel")
    store.install(DEFAULT_TENANT_ID, "ideation")
    db.close()
    return Factory


# ── seed helpers (maintainer + brain-side setup) ──────────────────────────────


def default_workspace_id(db) -> str:
    from modules.omnichannel.models import Workspace

    ws = (
        db.query(Workspace)
        .filter(Workspace.tenant_id == DEFAULT_TENANT_ID, Workspace.is_default.is_(True))
        .first()
    )
    assert ws is not None, "omnichannel default workspace not seeded"
    return ws.id


def make_contact(factory) -> str:
    from modules.omnichannel.models import Contact

    db = factory()
    try:
        c = Contact(
            tenant_id=DEFAULT_TENANT_ID,
            workspace_id=default_workspace_id(db),
            first_name="Jayson",
            last_name="Tan",
            phone="+60123456789",
        )
        db.add(c)
        db.commit()
        return c.id
    finally:
        db.close()


def mint_workspace_key(factory) -> str:
    from modules.omnichannel.services.api_key_service import ApiKeyService

    db = factory()
    try:
        _row, full_key = ApiKeyService(db).mint(
            DEFAULT_TENANT_ID, default_workspace_id(db), "intake", None
        )
        return full_key
    finally:
        db.close()


def idea_status_key(factory, idea_id: str) -> str:
    from modules.ideation.models import Idea

    db = factory()
    try:
        idea = db.query(Idea).filter(Idea.id == idea_id).first()
        assert idea is not None, "idea not found"
        st = db.query(Status).filter(Status.id == idea.status_id).first()
        return st.key
    finally:
        db.close()


# ── transcript rendering ──────────────────────────────────────────────────────

LINES: list[str] = []


def emit(text: str = "") -> None:
    print(text)
    LINES.append(text)


def render_turn(n, title, user_msg, extracted, resp, db_status=None):
    emit(f"### Turn {n} - {title}")
    emit("")
    emit(f"**User (WhatsApp):** {user_msg}")
    emit(f"**Brain-extracted →** {extracted}")
    emit("")
    emit("```json")
    emit(f'status  : {resp["status"]}')
    emit(f'captured: {resp["captured"]}')
    emit(f'missing : {resp["missing"]}')
    if "link" in resp:
        emit(f'link    : {resp["link"]}')
    if "duplicate_of" in resp:
        emit(f'duplicate_of: {resp["duplicate_of"]}')
    emit("```")
    emit("")
    emit("**Bot reply:**")
    emit("```")
    for ln in resp["reply_text"].splitlines():
        emit(ln)
    emit("```")
    if db_status is not None:
        emit(f"*DB check → Idea.status = `{db_status}`*")
    emit("")
    emit("---")
    emit("")


# ── the driver ────────────────────────────────────────────────────────────────


def main() -> int:
    factory = build_session_factory()

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    failures: list[str] = []

    try:
        with TestClient(app) as client:
            # Maintainer logs in (user JWT) to create the product + delivery base.
            tok = client.post(
                "/auth/login",
                json={"email": ACTIVE_EMAIL, "password": ACTIVE_PASSWORD},
            ).json()["access_token"]
            uh = {"Authorization": f"Bearer {tok}"}

            product_id = client.post(
                "/products", headers=uh, json={"name": "Sorento CRM", "kind": "software"}
            ).json()["id"]
            r = client.put(
                f"/ideation/products/{product_id}/delivery",
                headers=uh,
                json={"productDomainBase": PRODUCT_DOMAIN_BASE},
            )
            assert r.status_code == 200, r.text

            contact_id = make_contact(factory)
            key = mint_workspace_key(factory)
            kh = {"Authorization": f"Bearer {key}"}  # brain server-to-server key

            def call(**body):
                payload = {
                    "product_id": product_id,
                    "submitter_contact_id": contact_id,
                }
                payload.update(body)
                res = client.post(
                    "/ideation/intake/create-idea", headers=kh, json=payload
                )
                assert res.status_code == 200, res.text
                return res.json()

            def expect(cond, msg):
                if not cond:
                    failures.append(msg)
                    emit(f"!! ASSERTION FAILED: {msg}")

            emit("# Ideation Capture - end-to-end simulation transcript")
            emit("")
            emit(
                "Deterministic Conversational-Intake (NO LLM). Product **Sorento CRM** "
                f"(`{product_id}`), domain base `{PRODUCT_DOMAIN_BASE}`. The brain "
                "extracts structured `fields`/`remove`/`confirm`; this module merges "
                "them against the schema, computes captured/missing and echoes a "
                "templated reply. Required fields: **problem, module, who, impact**."
            )
            emit("")
            emit("---")
            emit("")

            # ── MAIN CONVERSATION ─────────────────────────────────────────────
            emit("## Conversation A - build → confirm (7 turns)")
            emit("")

            # Turn 1 - incomplete (only the problem, seeded from message_text).
            msg1 = "I wish the CRM reminded me before a DO's SLA breaches"
            r1 = call(message_text=msg1)
            draft_id = r1["draft_id"]
            render_turn(1, "INCOMPLETE (problem only)", msg1,
                        "fields={} (problem seeded from message)", r1)
            expect(r1["status"] == "collecting", "T1 status should be collecting")
            expect("problem" in r1["captured"], "T1 should capture problem")
            expect(set(r1["missing"]) == {"module", "who", "impact"},
                   "T1 missing should be module/who/impact")

            # Turn 2 - supplies SOME missing (module).
            msg2 = "It's about the Orders module"
            r2 = call(message_text=msg2, draft_id=draft_id, fields={"module": "Orders"})
            render_turn(2, "SOME missing filled (module)", msg2,
                        'fields={"module":"Orders"}', r2)
            expect(r2["status"] == "collecting", "T2 status should be collecting")
            expect(r2["captured"].get("module") == "Orders", "T2 should capture module")
            expect(set(r2["missing"]) == {"who", "impact"},
                   "T2 missing should shrink to who/impact")

            # Turn 3 - supplies the REST → review (does NOT auto-complete).
            msg3 = "It'd help the CS team and save them about 30 minutes a day"
            r3 = call(
                message_text=msg3,
                draft_id=draft_id,
                fields={"who": "The CS team", "impact": "Saves 30 minutes a day"},
            )
            st3 = idea_status_key(factory, draft_id)
            render_turn(3, "REST filled → REVIEW (no auto-complete)", msg3,
                        'fields={"who":"The CS team","impact":"Saves 30 minutes a day"}',
                        r3, db_status=st3)
            expect(r3["status"] == "review", "T3 status should be review")
            expect(r3["missing"] == [], "T3 missing should be empty")
            expect("link" not in r3, "T3 should NOT carry a link (not complete)")
            expect(st3 == "draft", "T3 draft must STAY draft (D-CONFIRM)")

            # Turn 4 - revision: change the team.
            msg4 = "Actually, change the team to Operations"
            r4 = call(message_text=msg4, draft_id=draft_id, fields={"who": "Operations"})
            render_turn(4, "REVISION - change team", msg4,
                        'fields={"who":"Operations"}', r4)
            expect(r4["status"] == "review", "T4 status should stay review")
            expect(r4["captured"].get("who") == "Operations",
                   "T4 should reflect who=Operations")

            # Turn 5 - revision: remove the impact line (required → collecting).
            msg5 = "Actually remove the impact line"
            r5 = call(message_text=msg5, draft_id=draft_id, remove=["impact"])
            render_turn(5, "REVISION - remove impact (required)", msg5,
                        'remove=["impact"]', r5)
            expect(r5["status"] == "collecting",
                   "T5 status should drop to collecting (impact is required)")
            expect("impact" in r5["missing"], "T5 missing should include impact")
            emit(
                "> _`impact` is a REQUIRED field in the intake schema, so removing it "
                "drops the intake back to **collecting** - the confirm gate cannot be "
                "reached until every required field is answered again._"
            )
            emit("")

            # Turn 6 - add more info that merges back in → review.
            msg6 = "Put the impact back - it saves about an hour a day"
            r6 = call(
                message_text=msg6,
                draft_id=draft_id,
                fields={"impact": "Saves an hour a day"},
            )
            render_turn(6, "MERGE more info → REVIEW", msg6,
                        'fields={"impact":"Saves an hour a day"}', r6)
            expect(r6["status"] == "review", "T6 status should be review again")
            expect(r6["captured"].get("impact") == "Saves an hour a day",
                   "T6 should merge the new impact")
            expect(r6["missing"] == [], "T6 missing should be empty")

            # Turn 7 - explicit confirm → complete + link; DB now captured.
            msg7 = "Yes, submit it"
            r7 = call(message_text=msg7, draft_id=draft_id, confirm=True)
            st7 = idea_status_key(factory, draft_id)
            render_turn(7, "EXPLICIT CONFIRM → COMPLETE", msg7,
                        "confirm=true", r7, db_status=st7)
            expected_link = f"{PRODUCT_DOMAIN_BASE}/ideas/{draft_id}"
            expect(r7["status"] == "complete", "T7 status should be complete")
            expect(r7.get("link") == expected_link,
                   f"T7 link should be {expected_link}")
            expect(expected_link in r7["reply_text"],
                   "T7 reply_text should carry the deep link")
            expect(st7 == "captured", "T7 Idea should now be captured in the DB")

            # ── ONE-SHOT CASE ─────────────────────────────────────────────────
            emit("## Conversation B - one-shot complete STILL reviews first")
            emit("")
            msg_os = ("Let me bulk-edit product prices by uploading a spreadsheet "
                      "instead of one row at a time")
            os1 = call(
                message_text=msg_os,
                fields={
                    "module": "Products",
                    "who": "The pricing team",
                    "impact": "Cuts a full afternoon of manual edits each month",
                },
            )
            os_draft = os1["draft_id"]
            os_status = idea_status_key(factory, os_draft)
            render_turn("B1", "ONE-SHOT (all fields on turn 1)", msg_os,
                        'fields={module,who,impact} (problem seeded)', os1,
                        db_status=os_status)
            expect(os1["status"] == "review",
                   "One-shot turn 1 must return review, NOT complete")
            expect("link" not in os1, "One-shot turn 1 must NOT carry a link")
            expect(os_status == "draft", "One-shot draft must stay draft until confirm")
            emit(
                "> _Even though every required field was answered in the very first "
                "message, the intake returns **review** - the D-CONFIRM gate means "
                "nothing is captured without an explicit confirm._"
            )
            emit("")

            # Then confirm it.
            os2 = call(message_text="confirm", draft_id=os_draft, confirm=True)
            os_status2 = idea_status_key(factory, os_draft)
            render_turn("B2", "…then CONFIRM → COMPLETE", "confirm",
                        "confirm=true", os2, db_status=os_status2)
            expect(os2["status"] == "complete", "One-shot confirm should complete")
            expect(os_status2 == "captured",
                   "One-shot Idea should be captured after confirm")

            emit("## Result")
            emit("")
            if failures:
                emit(f"**FAILED** - {len(failures)} assertion(s) did not match:")
                for f in failures:
                    emit(f"- {f}")
            else:
                emit(
                    "**All asserted status transitions matched.** "
                    "collecting → collecting → review → review → collecting → review "
                    "→ complete, plus one-shot review-before-confirm. D-CONFIRM holds."
                )
            emit("")
    finally:
        app.dependency_overrides.clear()

    # Save the transcript.
    out_path = (
        "/Users/tehjayson/Documents/foundryx/foundryx-shared-service/"
        "documentation/plans/ideation/ideation-capture-simulation-transcript.md"
    )
    with open(out_path, "w") as fh:
        fh.write("\n".join(LINES) + "\n")
    print(f"\n[transcript saved to {out_path}]")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
