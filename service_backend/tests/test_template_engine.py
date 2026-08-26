"""Template engine tests (plan sprint-2/07) - merge security, compiler,
conditional pruning, validate_doc 422 matrix, two-tier fork/reset, system
guards, engine-rendered system mails, notification template path, email log
retry/cancel semantics, retention, permission gates."""

from datetime import timedelta

from app.models.email_outbox import (
    OUTBOX_CANCELLED,
    OUTBOX_FAILED,
    OUTBOX_PENDING,
    OUTBOX_SENT,
    EmailOutbox,
)
from app.models.template import Template
from app.template_engine.compiler import BrandValues, compile_document, document_text
from app.template_engine.merge import collect_tokens, render_tokens, render_url
from app.template_engine.renderer import _prune
from app.template_engine.schemas import TemplateDocumentModel, validate_doc
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, PLATFORM_EMAIL, PLATFORM_PASSWORD


def _login(client, email, password, tenant_slug=None):
    payload = {"email": email, "password": password}
    if tenant_slug is not None:
        payload["tenantSlug"] = tenant_slug
    return client.post("/auth/login", json=payload)


def _headers(res) -> dict:
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _demo_headers(client):
    return _headers(_login(client, ACTIVE_EMAIL, ACTIVE_PASSWORD))


def _platform_headers(client):
    return _headers(_login(client, PLATFORM_EMAIL, PLATFORM_PASSWORD, "platform"))


def _doc(blocks, conditions=None):
    return {
        "schemaVersion": 1,
        "sections": [
            {
                "id": "sec_1",
                "layout": "100",
                "background": "#FFFFFF",
                "padding": {"top": 16, "bottom": 16, "left": 24, "right": 24},
                "conditionsJson": conditions,
                "columns": [{"id": "col_1", "blocks": blocks}],
            }
        ],
    }


def _button(href="{{resetLink}}", label="Reset"):
    return {
        "id": "blk_btn",
        "type": "button",
        "label": label,
        "href": href,
        "align": "left",
        "backgroundColor": None,
        "textColor": None,
        "borderRadius": 6,
    }


# ---------------------------------------------------------------------------
# Merge renderer (D5)
# ---------------------------------------------------------------------------


class TestMerge:
    def test_substitutes_dotted_paths(self):
        assert render_tokens("Hi {{user.name}}!", {"user.name": "Alex"}) == "Hi Alex!"

    def test_html_escapes_values(self):
        out = render_tokens("Hi {{n}}", {"n": "<script>alert(1)</script>"})
        assert "<script>" not in out and "&lt;script&gt;" in out

    def test_missing_fact_send_vs_preview(self):
        assert render_tokens("A{{x}}B", {}, mode="send") == "AB"
        assert "x" in render_tokens("A{{x}}B", {}, mode="preview")

    def test_no_expression_evaluation(self):
        # Jinja-style probes are unknown facts (blanked) or non-tokens (verbatim).
        assert render_tokens("{{__class__.__init__}}", {}, mode="send") == ""
        assert render_tokens("{{ 7 * 7 }}", {}, mode="send") == "{{ 7 * 7 }}"
        assert render_tokens("{{n|upper}}", {"n": "x"}, mode="send") == "{{n|upper}}"

    def test_url_validation_blocks_javascript(self):
        assert render_url("javascript:alert(1)", {}) == "#"
        assert render_url("{{link}}", {"link": "javascript:alert(1)"}) == "#"
        assert render_url("{{link}}", {"link": "https://ok.example/x"}) == "https://ok.example/x"

    def test_collect_tokens(self):
        assert collect_tokens("{{a.b}} and {{c}}", "{{c}}") == {"a.b", "c"}


# ---------------------------------------------------------------------------
# Compiler (D9)
# ---------------------------------------------------------------------------


class TestRenderEmailDoc:
    def test_renders_a_raw_doc_branded(self, session_factory):
        # Plan 10 follow-up - per-use template copy renders branded from a doc.
        from app.template_engine import render_email_doc
        from tests.conftest import DEFAULT_TENANT_ID

        db = session_factory()
        doc, problems = validate_doc(
            _doc(
                [
                    {"id": "h", "type": "brandHeader", "overrides": None},
                    {"id": "t", "type": "heading", "text": "{{recordLabel}} is now {{toStatus}}", "level": 2, "align": "left"},
                ]
            ),
            "{{recordLabel}} moved to {{toStatus}}",
            fact_sources=[],
            required_facts=[],
        )
        assert problems == []
        rendered = render_email_doc(
            db,
            doc_json=doc.model_dump(by_alias=True),
            subject="{{recordLabel}} moved to {{toStatus}}",
            context="status.notification",
            tenant_id=DEFAULT_TENANT_ID,
            facts={"recordLabel": "Acme", "toStatus": "Active"},
        )
        assert rendered.subject == "Acme moved to Active"
        assert "Acme is now Active" in rendered.html
        # Brand header compiled (a table-based email, not the raw heading text).
        assert "<table" in rendered.html.lower()


class TestCompiler:
    def test_compiles_every_block_type(self):
        doc, problems = validate_doc(
            _doc(
                [
                    {"id": "b1", "type": "heading", "text": "Hi {{recipient.firstName}}", "level": 2, "align": "left"},
                    {"id": "b2", "type": "text", "html": "Body <b>bold</b>", "align": "left"},
                    {"id": "b3", "type": "image", "src": "https://img.example/x.png", "alt": "x", "width": 240, "align": "center", "href": None, "storageKey": None},
                    _button(),
                    {"id": "b5", "type": "divider", "color": "#EEE", "thickness": 1},
                    {"id": "b6", "type": "spacer", "height": 24},
                    {"id": "b7", "type": "socialLinks", "links": [{"platform": "facebook", "href": "https://fb.example/a"}], "align": "center", "iconSize": 24},
                    {"id": "b8", "type": "brandHeader", "overrides": None},
                    {"id": "b9", "type": "brandFooter", "overrides": None},
                    {"id": "b10", "type": "customHtml", "html": "<b>raw ok</b>"},
                ]
            ),
            "S",
            fact_sources=["recipient"],
            required_facts=["resetLink"],
        )
        assert problems == []
        brand = BrandValues(tenant_name="Acme", footer_text="Acme · KL")
        html = compile_document(
            doc, brand, {"recipient.firstName": "Alex", "resetLink": "https://l.example/r"}
        )
        assert "<table" in html
        assert "Alex" in html
        assert "https://l.example/r" in html
        assert "raw ok" in html
        assert "Acme · KL" in html

    def test_text_sibling_derived(self):
        doc, _ = validate_doc(
            _doc(
                [
                    {"id": "b1", "type": "heading", "text": "Hello {{n}}", "level": 2, "align": "left"},
                    _button("{{resetLink}}"),
                ]
            ),
            "S",
            fact_sources=[],
            required_facts=[],
        )
        text = document_text(doc, BrandValues(), {"n": "Alex", "resetLink": "https://l.example/r"})
        assert "Hello Alex" in text
        assert "https://l.example/r" in text

    def test_brand_button_inherits_primary(self):
        doc, _ = validate_doc(_doc([_button()]), "S", fact_sources=[], required_facts=[])
        html = compile_document(doc, BrandValues(primary_color="#123456"), {"resetLink": "https://x.example"})
        assert "#123456" in html


# ---------------------------------------------------------------------------
# validate_doc 422 matrix
# ---------------------------------------------------------------------------


class TestValidateDoc:
    def test_unknown_block_type_rejected(self):
        _, problems = validate_doc(
            _doc([{"id": "b", "type": "carousel"}]), "S", fact_sources=[], required_facts=[]
        )
        assert problems

    def test_required_fact_missing(self):
        _, problems = validate_doc(
            _doc([{"id": "b", "type": "text", "html": "no link", "align": "left"}]),
            "Subject",
            fact_sources=[],
            required_facts=["resetLink"],
        )
        assert any("resetLink" in p for p in problems)

    def test_required_fact_in_subject_counts(self):
        _, problems = validate_doc(
            _doc([{"id": "b", "type": "text", "html": "x", "align": "left"}]),
            "Use {{resetLink}}",
            fact_sources=[],
            required_facts=["resetLink"],
        )
        assert problems == []

    def test_custom_html_sanitized(self):
        doc, problems = validate_doc(
            _doc([{"id": "b", "type": "customHtml", "html": '<script>x</script><img src=x onerror=alert(1)><b>ok</b>'}]),
            "S",
            fact_sources=[],
            required_facts=[],
        )
        assert problems == []
        cleaned = doc.sections[0].columns[0].blocks[0].html
        assert "<script>" not in cleaned and "onerror" not in cleaned and "<b>ok</b>" in cleaned

    def test_text_html_sanitized(self):
        doc, _ = validate_doc(
            _doc([{"id": "b", "type": "text", "html": '<a href="x" onclick="evil()">l</a>', "align": "left"}]),
            "S",
            fact_sources=[],
            required_facts=[],
        )
        assert "onclick" not in doc.sections[0].columns[0].blocks[0].html

    def test_bad_conditions_rejected(self):
        bad = {"kind": "group", "combinator": "and", "rules": [
            {"kind": "condition", "fact": "nope.nope", "operator": "eq", "valueKind": "literal", "value": "x"}
        ]}
        _, problems = validate_doc(
            _doc([{"id": "b", "type": "text", "html": "x", "align": "left", "conditionsJson": bad}]),
            "S",
            fact_sources=["recipient"],
            required_facts=[],
        )
        assert any("visibility" in p for p in problems)

    def test_layout_column_mismatch(self):
        raw = _doc([])
        raw["sections"][0]["layout"] = "50/50"  # one column declared
        _, problems = validate_doc(raw, "S", fact_sources=[], required_facts=[])
        assert any("columns" in p for p in problems)


# ---------------------------------------------------------------------------
# Conditional pruning (D8)
# ---------------------------------------------------------------------------


class TestPruning:
    def _conditioned_doc(self):
        cond = {"kind": "group", "combinator": "and", "rules": [
            {"kind": "condition", "fact": "recipient.email", "operator": "contains", "valueKind": "literal", "value": "@vip."}
        ]}
        doc, problems = validate_doc(
            _doc([
                {"id": "always", "type": "text", "html": "always", "align": "left"},
                {"id": "vip", "type": "text", "html": "vip only", "align": "left", "conditionsJson": cond},
            ]),
            "S",
            fact_sources=["recipient"],
            required_facts=[],
        )
        assert problems == []
        return doc

    def test_block_pruned_when_condition_fails(self):
        doc = self._conditioned_doc()
        pruned = _prune(doc, {"recipient.email": "x@plain.example"})
        ids = [b.id for _s, _c, b in pruned.iter_blocks()]
        assert ids == ["always"]

    def test_block_kept_when_condition_passes(self):
        doc = self._conditioned_doc()
        pruned = _prune(doc, {"recipient.email": "x@vip.example"})
        ids = [b.id for _s, _c, b in pruned.iter_blocks()]
        assert ids == ["always", "vip"]

    def test_missing_fact_fails_closed(self):
        doc = self._conditioned_doc()
        pruned = _prune(doc, {})
        assert [b.id for _s, _c, b in pruned.iter_blocks()] == ["always"]


# ---------------------------------------------------------------------------
# API - two-tier lifecycle
# ---------------------------------------------------------------------------


class TestTemplatesApi:
    def test_list_shows_seeded_system_templates_default_tier(self, client):
        headers = _demo_headers(client)
        res = client.get("/templates", headers=headers, params={"page_size": 50})
        assert res.status_code == 200, res.text
        rows = res.json()["data"]
        keys = {r["key"] for r in rows}
        assert "auth.password_reset" in keys
        assert all(r["tier"] == "default" and r["isSystem"] for r in rows)

    def test_permission_gate(self, client):
        res = client.get("/templates")
        assert res.status_code in (401, 403)

    def test_status_notification_starter_template_seeded(self, client):
        # BL-081 - a platform-tier starter template backs the notification picker.
        headers = _demo_headers(client)
        res = client.get(
            "/templates", headers=headers, params={"context": "status.notification"}
        )
        assert res.status_code == 200, res.text
        names = {r["name"] for r in res.json()["data"]}
        assert "Status change notification" in names

    def test_context_filter_narrows_the_picker(self, client):
        # BL-081 - the ?context= param backs the notification template picker.
        headers = _demo_headers(client)
        rows = client.get("/templates", headers=headers, params={"page_size": 200}).json()["data"]
        a_context = rows[0]["context"]
        filtered = client.get(
            "/templates", headers=headers, params={"context": a_context, "page_size": 200}
        )
        assert filtered.status_code == 200, filtered.text
        got = filtered.json()["data"]
        assert got and all(r["context"] == a_context for r in got)
        # A context with no templates returns an empty page, never an error.
        empty = client.get(
            "/templates", headers=headers, params={"context": "no.such.context"}
        )
        assert empty.status_code == 200 and empty.json()["data"] == []

    def test_fork_on_edit_then_reset(self, client):
        headers = _demo_headers(client)
        rows = client.get("/templates", headers=headers, params={"page_size": 50}).json()["data"]
        target = next(r for r in rows if r["key"] == "auth.password_reset")
        detail = client.get(f"/templates/{target['id']}", headers=headers).json()

        res = client.patch(
            f"/templates/{target['id']}",
            headers=headers,
            json={"name": "My reset", "subject": detail["subject"], "doc": detail["doc"]},
        )
        assert res.status_code == 200, res.text
        fork = res.json()
        assert fork["tier"] == "customized"
        assert fork["id"] != target["id"]  # fork = new tenant row
        assert fork["isSystem"] is True

        # List now shows the FORK, not the platform row (shadowed).
        rows2 = client.get("/templates", headers=headers, params={"page_size": 50}).json()["data"]
        mine = next(r for r in rows2 if r["key"] == "auth.password_reset")
        assert mine["id"] == fork["id"] and mine["name"] == "My reset"

        # Reset drops the fork → platform default visible again.
        res = client.post(f"/templates/{fork['id']}/reset", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["tier"] == "default"

    def test_required_fact_gate_on_save(self, client):
        headers = _demo_headers(client)
        rows = client.get("/templates", headers=headers, params={"page_size": 50}).json()["data"]
        target = next(r for r in rows if r["key"] == "auth.password_reset")
        res = client.patch(
            f"/templates/{target['id']}",
            headers=headers,
            json={"name": "Broken", "subject": "no link", "doc": _doc([])},
        )
        assert res.status_code == 422
        assert "resetLink" in res.json()["detail"]

    def test_system_delete_blocked_duplicate_deletable(self, client):
        headers = _demo_headers(client)
        rows = client.get("/templates", headers=headers, params={"page_size": 50}).json()["data"]
        target = next(r for r in rows if r["key"] == "auth.invite")
        assert client.delete(f"/templates/{target['id']}", headers=headers).status_code == 422

        copy = client.post(f"/templates/{target['id']}/duplicate", headers=headers).json()
        assert copy["isSystem"] is False and copy["tier"] == "customized"
        assert client.delete(f"/templates/{copy['id']}", headers=headers).status_code == 204

    def test_create_custom_template(self, client):
        headers = _demo_headers(client)
        res = client.post(
            "/templates",
            headers=headers,
            json={
                "name": "Campaign",
                "subject": "Hello {{recipient.firstName}}",
                "context": "template.test",
                "doc": _doc([{"id": "b", "type": "text", "html": "hi", "align": "left"}]),
            },
        )
        assert res.status_code == 201, res.text
        assert res.json()["tier"] == "customized"

    def test_unknown_context_422(self, client):
        headers = _demo_headers(client)
        res = client.post(
            "/templates",
            headers=headers,
            json={"name": "X", "subject": "s", "context": "nope.nope", "doc": _doc([])},
        )
        assert res.status_code == 422

    def test_preview_renders_sample_facts(self, client):
        headers = _demo_headers(client)
        res = client.post(
            "/templates/preview",
            headers=headers,
            json={
                "subject": "Reset for {{recipient.firstName}}",
                "context": "auth.password_reset",
                "doc": _doc([_button()]),
            },
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert "Alex" in body["subject"]
        assert "change-password?token=sample" in body["html"]

    def test_platform_tenant_edits_null_tier_in_place(self, client):
        operator = _platform_headers(client)
        rows = client.get("/templates", headers=operator, params={"page_size": 50}).json()["data"]
        target = next(r for r in rows if r["key"] == "auth.verification")
        detail = client.get(f"/templates/{target['id']}", headers=operator).json()
        res = client.patch(
            f"/templates/{target['id']}",
            headers=operator,
            json={"name": "Verify (default)", "subject": detail["subject"], "doc": detail["doc"]},
        )
        assert res.status_code == 200, res.text
        updated = res.json()
        assert updated["id"] == target["id"]  # in place - no fork
        assert updated["tier"] == "default"

    def test_contexts_endpoint(self, client):
        headers = _demo_headers(client)
        res = client.get("/templates/contexts", headers=headers)
        assert res.status_code == 200
        keys = {c["key"] for c in res.json()}
        assert "auth.password_reset" in keys
        reset = next(c for c in res.json() if c["key"] == "auth.password_reset")
        assert "resetLink" in reset["requiredFacts"]


# ---------------------------------------------------------------------------
# System mails render through the engine (D7)
# ---------------------------------------------------------------------------


class TestEngineSystemMails:
    def test_forgot_password_outbox_row_is_engine_rendered(self, client, session_factory):
        res = client.post(
            "/auth/forgot-password", json={"email": ACTIVE_EMAIL, "tenantSlug": "default"}
        )
        assert res.status_code == 200
        db = session_factory()
        try:
            row = (
                db.query(EmailOutbox)
                .filter(EmailOutbox.template_key == "auth.password_reset")
                .order_by(EmailOutbox.created_at.desc())
                .first()
            )
            assert row is not None, "engine key expected on the outbox row"
            assert "<table" in row.html_body  # mrml output, not the Jinja file
            assert "change-password?token=" in row.html_body
            assert row.text_body  # derived sibling present
        finally:
            db.close()

    def test_test_send_queues_to_caller(self, client, session_factory):
        headers = _demo_headers(client)
        rows = client.get("/templates", headers=headers, params={"page_size": 50}).json()["data"]
        target = next(r for r in rows if r["key"] == "auth.invite")
        res = client.post(f"/templates/{target['id']}/test-send", headers=headers)
        assert res.status_code == 200, res.text
        assert res.json()["toEmail"] == ACTIVE_EMAIL
        db = session_factory()
        try:
            row = (
                db.query(EmailOutbox)
                .filter(EmailOutbox.template_key == "template.test")
                .first()
            )
            assert row is not None and row.to_email == ACTIVE_EMAIL
            assert row.subject.startswith("[Test]")
        finally:
            db.close()


# ---------------------------------------------------------------------------
# Email log (D14)
# ---------------------------------------------------------------------------


def _seed_outbox(db, tenant_id, status, **extra):
    from datetime import datetime, timezone

    row = EmailOutbox(
        tenant_id=tenant_id,
        to_email=extra.get("to_email", "user@example.com"),
        subject=extra.get("subject", "Subject"),
        html_body="<html><body>hi</body></html>",
        text_body="hi",
        template_key=extra.get("template_key", "auth.invite"),
        status=status,
        attempts=extra.get("attempts", 0),
        next_attempt_at=datetime.now(timezone.utc),
        last_error=extra.get("last_error"),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


class TestEmailLog:
    DEFAULT_TENANT = "00000000-0000-0000-0000-000000000001"

    def test_list_segments_and_detail(self, client, session_factory):
        db = session_factory()
        failed_id = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_FAILED, attempts=3, last_error="SMTP boom").id
        _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_SENT)
        db.close()
        headers = _demo_headers(client)

        res = client.get("/emails", headers=headers, params={"segment": "failed"})
        assert res.status_code == 200
        data = res.json()["data"]
        assert data and all(r["status"] == "FAILED" for r in data)

        detail = client.get(f"/emails/{failed_id}", headers=headers)
        assert detail.status_code == 200
        body = detail.json()
        assert body["lastError"] == "SMTP boom"
        assert "<html" in body["htmlBody"]

    def test_tenant_scoping(self, client, session_factory):
        db = session_factory()
        foreign_id = _seed_outbox(db, "some-other-tenant", OUTBOX_FAILED).id
        db.close()
        headers = _demo_headers(client)
        assert client.get(f"/emails/{foreign_id}", headers=headers).status_code == 404

    def test_retry_failed_preserves_attempts(self, client, session_factory):
        db = session_factory()
        row_id = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_FAILED, attempts=3).id
        db.close()
        headers = _demo_headers(client)
        res = client.post(f"/emails/{row_id}/retry", headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "PENDING" and body["attempts"] == 3

    def test_retry_sent_rejected(self, client, session_factory):
        db = session_factory()
        row_id = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_SENT).id
        db.close()
        headers = _demo_headers(client)
        assert client.post(f"/emails/{row_id}/retry", headers=headers).status_code == 422

    def test_cancel_pending_then_retry(self, client, session_factory):
        db = session_factory()
        row_id = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_PENDING).id
        db.close()
        headers = _demo_headers(client)

        res = client.post(f"/emails/{row_id}/cancel", headers=headers)
        assert res.status_code == 200 and res.json()["status"] == "CANCELLED"

        res = client.post(f"/emails/{row_id}/retry", headers=headers)
        assert res.status_code == 200 and res.json()["status"] == "PENDING"

    def test_cancel_claimed_row_conflicts(self, client, session_factory):
        db = session_factory()
        row_id = _seed_outbox(db, self.DEFAULT_TENANT, "sending").id
        db.close()
        headers = _demo_headers(client)
        assert client.post(f"/emails/{row_id}/cancel", headers=headers).status_code == 409

    def test_manage_permission_gate(self, client, session_factory):
        db = session_factory()
        row_id = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_FAILED).id
        db.close()
        assert client.post(f"/emails/{row_id}/retry").status_code in (401, 403)

    def test_retention_prunes_terminal_rows(self, session_factory):
        from app.services.email_dispatcher import prune_sent

        db = session_factory()
        old = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_CANCELLED)
        fresh = _seed_outbox(db, self.DEFAULT_TENANT, OUTBOX_FAILED)
        old_id, fresh_id = old.id, fresh.id
        # Age the cancelled row past the window.
        from datetime import datetime, timezone

        old.created_at = datetime.now(timezone.utc) - timedelta(days=400)
        db.commit()
        deleted = prune_sent(db)
        db.expire_all()
        assert deleted >= 1
        assert db.query(EmailOutbox).filter(EmailOutbox.id == old_id).first() is None
        assert db.query(EmailOutbox).filter(EmailOutbox.id == fresh_id).first() is not None
        db.close()


# ---------------------------------------------------------------------------
# Notification spec template reference (D10)
# ---------------------------------------------------------------------------


class TestNotificationTemplateRef:
    def test_dispatch_renders_referenced_template(self, session_factory):
        from app.models.notification_spec import (
            CHANNEL_EMAIL,
            TARGET_USER,
            NotificationRecipient,
            NotificationSpec,
        )
        from app.models.user import User
        from app.services.notification_dispatch import dispatch_specs

        db = session_factory()
        try:
            tenant_id = TestEmailLog.DEFAULT_TENANT
            user = db.query(User).filter(User.email == ACTIVE_EMAIL).first()
            template = (
                db.query(Template)
                .filter(Template.key == "account.email_change_notice", Template.tenant_id.is_(None))
                .first()
            )
            spec = NotificationSpec(
                tenant_id=tenant_id,
                channel=CHANNEL_EMAIL,
                template_subject="inline subject",
                template_body="inline body",
                template_id=template.id,
            )
            spec.recipients = [
                NotificationRecipient(target_type=TARGET_USER, target_id=user.id)
            ]
            db.add(spec)
            db.flush()

            count = dispatch_specs(
                db,
                [spec],
                record=None,
                actor=user,
                tenant_id=tenant_id,
                context={"oldEmail": "a@x.com", "newEmail": "b@x.com", "recipient.firstName": "Demo"},
            )
            db.commit()
            assert count == 1
            row = (
                db.query(EmailOutbox)
                .filter(EmailOutbox.template_key == "account.email_change_notice")
                .first()
            )
            assert row is not None
            assert "<table" in row.html_body  # engine output, not inline <br> body
            assert "a@x.com" in row.html_body and "b@x.com" in row.html_body
        finally:
            db.close()
