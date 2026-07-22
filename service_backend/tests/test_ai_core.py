"""Core AI subsystem tests (Phase B-i slice 1, AC-BI-01..14).

Covers: provider-protocol conformance for all three adapters, the `llm`
one-per-type carve-out, skill version immutability + label rollback,
substitution-only prompt composition, trace/span write + payload caps, the
retention sweep, stub determinism + fixture control, permission gating and
tenant scoping.

Everything here runs OFFLINE — the stub adapter answers, so the suite needs no
API key, costs nothing and never touches the network (AC-BI-12/13).
"""
from datetime import datetime, timedelta, timezone

import pytest

from app.ai import (
    AiClient,
    StubResponse,
    any_llm_connection,
    compose,
    field_schema,
    prune_traces,
    stub_fixtures,
)
from app.ai.tracing import (
    MAX_PAYLOAD_CHARS,
    TRUNCATED_FLAG,
    TraceWriter,
    cap_payload,
)
from app.integrations import get_provider
from app.integrations.base import LLMError, LLMResult, ModelOption
from app.models.ai import (
    SPAN_KIND_LLM_CALL,
    TRACE_STATUS_ERROR,
    TRACE_STATUS_OK,
    AiAgent,
    AiSkill,
    AiSkillVersion,
    AiSpan,
    AiTrace,
)
from app.models.connection import Connection
from app.models.tenant import PLATFORM_TENANT_ID
from app.models.user import User
from app.secrets import encrypt_secret
from tests.conftest import ACTIVE_EMAIL, ACTIVE_PASSWORD, DEFAULT_TENANT_ID

LLM_PROVIDERS = ("anthropic", "openai", "gemini")


def _login(client, email=ACTIVE_EMAIL, password=ACTIVE_PASSWORD):
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def _make_connection(db, *, tenant_id=DEFAULT_TENANT_ID, provider="gemini", dev=True, **kwargs):
    conn = Connection(
        tenant_id=tenant_id,
        provider=provider,
        type="llm",
        name=kwargs.pop("name", f"{provider} key"),
        config_json={},
        # `dev` credentials route to the stub adapter (the omnichannel `_is_dev`
        # pattern) — no network, no key.
        credentials_json=encrypt_secret({"apiKey": "x", "dev": True} if dev else {"apiKey": "x"}),
        **kwargs,
    )
    db.add(conn)
    db.commit()
    db.refresh(conn)
    return conn


def _make_agent(db, connection, *, tenant_id=DEFAULT_TENANT_ID, **kwargs):
    agent = AiAgent(
        tenant_id=tenant_id,
        name=kwargs.pop("name", "Griller"),
        connection_id=connection.id if connection else None,
        model=kwargs.pop("model", "stub-model-1"),
        **kwargs,
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    return agent


def _demo_user(db):
    return db.query(User).filter(User.email == ACTIVE_EMAIL).first()


# ── AC-BI-01/02: provider protocol conformance ───────────────────────────


@pytest.mark.parametrize("provider_key", LLM_PROVIDERS)
def test_llm_provider_registered_with_required_surface(provider_key):
    """AC-BI-02 — all three registered as type='llm' with the full verb set."""
    provider = get_provider(provider_key)
    assert provider is not None, f"{provider_key} not registered"
    assert provider.type == "llm"
    for verb in ("fields", "test", "models", "complete"):
        assert callable(getattr(provider, verb, None)), f"{provider_key}.{verb} missing"


@pytest.mark.parametrize("provider_key", LLM_PROVIDERS)
def test_llm_provider_marks_api_key_secret(provider_key):
    """AC-BI-03 — the key field is `secret`, so it routes to credentials_json
    (Fernet, write-only) and never into displayable config."""
    fields = get_provider(provider_key).fields()
    api_key_fields = [f for f in fields if f.get("secret")]
    assert api_key_fields, f"{provider_key} declares no secret field"
    assert all(f["type"] == "password" for f in api_key_fields)


@pytest.mark.parametrize("provider_key", LLM_PROVIDERS)
def test_llm_provider_has_static_model_fallback(provider_key):
    """AC-BI-05 — a curated static list exists so the form renders when the live
    catalog call fails."""
    static = get_provider(provider_key).static_models
    assert static, f"{provider_key} has no static fallback models"
    assert all(isinstance(m, ModelOption) and m.id for m in static)


@pytest.mark.parametrize("provider_key", LLM_PROVIDERS)
def test_llm_provider_test_reports_clean_error_without_key(provider_key):
    """AC-BI-04 — a bad/absent key yields a clean message, never a traceback and
    never the key echoed."""
    result = get_provider(provider_key).test({}, {})
    assert result.ok is False
    assert "Traceback" not in result.message
    assert len(result.message) < 400


def test_llm_result_enforces_text_xor_structured():
    """AC-BI-01 — `text` and `structured` are mutually exclusive."""
    assert LLMResult(text="hi").text == "hi"
    assert LLMResult(structured={"a": 1}).structured == {"a": 1}
    with pytest.raises(ValueError):
        LLMResult(text="hi", structured={"a": 1})
    with pytest.raises(ValueError):
        LLMResult()


def test_gemini_schema_downconversion_strips_unsupported_keys():
    """The adapter owns its own structured-output dialect — callers pass plain
    JSON Schema and never learn Gemini rejects `additionalProperties`."""
    from app.integrations.gemini_provider import to_gemini_schema

    converted = to_gemini_schema(
        {
            "type": "object",
            "additionalProperties": False,
            "$schema": "http://json-schema.org/draft-07/schema#",
            "properties": {"a": {"type": "string", "additionalProperties": False}},
            "required": ["a"],
        }
    )
    assert "additionalProperties" not in converted
    assert "$schema" not in converted
    assert "additionalProperties" not in converted["properties"]["a"]
    assert converted["required"] == ["a"]


def test_gemini_disables_thinking_on_structured_calls(monkeypatch):
    """CRITICAL (S3 live bug): gemini-2.5-flash runs away on structured
    extraction with thinking ON. The adapter must send
    `generationConfig.thinkingConfig.thinkingBudget=0` on any structured call."""
    import app.integrations.gemini_provider as gp

    captured = {}

    def fake_http(method, url, *, headers=None, json_body=None, timeout=None):
        captured["body"] = json_body
        return {
            "candidates": [
                {"content": {"parts": [{"text": '{"summary": "x"}'}]}, "finishReason": "STOP"}
            ],
            "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 4},
        }

    monkeypatch.setattr(gp, "_http_json", fake_http)
    gp.GeminiProvider().complete(
        {},
        {"apiKey": "x"},
        model="gemini-2.5-flash",
        system="s",
        messages=[{"role": "user", "content": "hi"}],
        output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
    )
    thinking = captured["body"]["generationConfig"].get("thinkingConfig")
    assert thinking == {"thinkingBudget": 0}


@pytest.mark.parametrize(
    "provider_key, provider_module, payload",
    [
        (
            "gemini",
            "app.integrations.gemini_provider",
            {
                "candidates": [
                    {"content": {"parts": [{"text": '{"summary": "partia'}]}, "finishReason": "MAX_TOKENS"}
                ],
                "usageMetadata": {"promptTokenCount": 5, "candidatesTokenCount": 4096},
            },
        ),
        (
            "openai",
            "app.integrations.openai_provider",
            {
                "choices": [{"message": {"content": '{"summary": "partia'}, "finish_reason": "length"}],
                "usage": {},
                "model": "gpt-4o",
            },
        ),
        (
            "anthropic",
            "app.integrations.anthropic_provider",
            {"content": [], "stop_reason": "max_tokens", "usage": {}},
        ),
    ],
)
def test_truncated_structured_response_raises_clean_llmerror(
    provider_key, provider_module, payload, monkeypatch
):
    """A runaway/truncated structured body → a clean LLMError, NEVER a raw
    json.loads crash on a fragment (defense; the grill turns this into an error
    trace). Covers all three adapters."""
    import importlib

    module = importlib.import_module(provider_module)
    monkeypatch.setattr(module, "_http_json", lambda *a, **k: payload)
    with pytest.raises(LLMError):
        get_provider(provider_key).complete(
            {},
            {"apiKey": "x"},
            model="m",
            system="s",
            messages=[{"role": "user", "content": "hi"}],
            output_schema={"type": "object", "properties": {"summary": {"type": "string"}}},
        )


# ── AC-BI-03b: the `llm` one-per-type carve-out ──────────────────────────


def test_two_active_llm_connections_coexist(session_factory):
    """AC-BI-03b — a tenant may hold several ACTIVE LLM connections, so
    different agents can use different providers."""
    db = session_factory()
    _make_connection(db, provider="anthropic", name="Claude")
    _make_connection(db, provider="gemini", name="Gemini")
    rows = (
        db.query(Connection)
        .filter(Connection.tenant_id == DEFAULT_TENANT_ID, Connection.type == "llm")
        .all()
    )
    assert len(rows) == 2
    db.close()


def test_two_active_same_provider_llm_connections_rejected(client, session_factory):
    """AC-BI-03b — `uq_connection_tenant_provider` still applies: no two ACTIVE
    Anthropic rows."""
    headers = _login(client)
    body = {
        "provider": "anthropic",
        "name": "Claude A",
        "config": {},
        "credentials": {"apiKey": "k"},
    }
    first = client.post("/integrations/connections", json=body, headers=headers)
    assert first.status_code == 201, first.text
    second = client.post(
        "/integrations/connections",
        json={**body, "name": "Claude B"},
        headers=headers,
    )
    assert second.status_code == 409
    assert "already exists" in second.json()["detail"]


def test_llm_connections_do_not_block_each_other_via_api(client):
    """AC-BI-03b end-to-end: Anthropic + Gemini both accepted for one tenant."""
    headers = _login(client)
    for provider in ("anthropic", "gemini", "openai"):
        res = client.post(
            "/integrations/connections",
            json={
                "provider": provider,
                "name": f"{provider} key",
                "config": {},
                "credentials": {"apiKey": "k"},
            },
            headers=headers,
        )
        assert res.status_code == 201, f"{provider}: {res.text}"


def test_storage_one_per_type_invariant_unchanged(client):
    """AC-BI-03b — storage/email must KEEP one-active-per-type. The carve-out
    is surgical; loosening storage would break deterministic resolution."""
    headers = _login(client)
    first = client.post(
        "/integrations/connections",
        json={
            "provider": "s3",
            "name": "Bucket A",
            "config": {"bucket": "a", "region": "us-east-1"},
            "credentials": {"accessKeyId": "k", "secretAccessKey": "s"},
        },
        headers=headers,
    )
    assert first.status_code == 201, first.text
    second = client.post(
        "/integrations/connections",
        json={
            "provider": "r2",  # different provider, SAME type
            "name": "Bucket B",
            "config": {"accountId": "acc", "bucket": "b"},
            "credentials": {"accessKeyId": "k", "secretAccessKey": "s"},
        },
        headers=headers,
    )
    assert second.status_code == 409, second.text
    assert "storage" in second.json()["detail"]


# ── AC-BI-07: skill versions are immutable; rollback is a label move ─────


def test_skill_edit_mints_new_version_and_moves_label(client):
    headers = _login(client)
    created = client.post(
        "/ai/skills",
        json={"key": "grill", "name": "Grill", "description": "d", "body": "v1 body"},
        headers=headers,
    )
    assert created.status_code == 201, created.text
    skill = created.json()
    assert skill["activeVersionNumber"] == 1
    v1_id = skill["activeVersionId"]

    updated = client.patch(
        f"/ai/skills/{skill['id']}", json={"body": "v2 body"}, headers=headers
    ).json()
    assert updated["activeVersionNumber"] == 2
    assert updated["body"] == "v2 body"
    assert updated["activeVersionId"] != v1_id

    # The PRIOR version row is untouched — never mutated in place.
    versions = client.get(f"/ai/skills/{skill['id']}/versions", headers=headers).json()
    assert [v["version"] for v in versions] == [2, 1]
    v1 = next(v for v in versions if v["version"] == 1)
    assert v1["body"] == "v1 body", "the previous version was mutated"
    assert v1["id"] == v1_id


def test_skill_rollback_is_a_label_move_not_a_copy(client):
    headers = _login(client)
    skill = client.post(
        "/ai/skills",
        json={"key": "grill", "name": "Grill", "body": "v1 body"},
        headers=headers,
    ).json()
    v1_id = skill["activeVersionId"]
    client.patch(f"/ai/skills/{skill['id']}", json={"body": "v2 body"}, headers=headers)

    rolled = client.post(
        f"/ai/skills/{skill['id']}/rollback", json={"versionId": v1_id}, headers=headers
    )
    assert rolled.status_code == 200, rolled.text
    body = rolled.json()
    assert body["activeVersionId"] == v1_id
    assert body["activeVersionNumber"] == 1
    assert body["body"] == "v1 body"
    # No new version was created by the rollback — it is purely a label move.
    assert body["versionCount"] == 2


def test_skill_unchanged_body_does_not_mint_a_version(client):
    """Saving the form twice must not inflate history with identical rows."""
    headers = _login(client)
    skill = client.post(
        "/ai/skills", json={"key": "g", "name": "G", "body": "same"}, headers=headers
    ).json()
    again = client.patch(
        f"/ai/skills/{skill['id']}", json={"body": "same"}, headers=headers
    ).json()
    assert again["versionCount"] == 1


def test_skill_rollback_refuses_foreign_version_id(client):
    """A version id belonging to ANOTHER skill can never be activated onto this
    one (the polymorphic-target rule)."""
    headers = _login(client)
    a = client.post(
        "/ai/skills", json={"key": "a", "name": "A", "body": "a1"}, headers=headers
    ).json()
    b = client.post(
        "/ai/skills", json={"key": "b", "name": "B", "body": "b1"}, headers=headers
    ).json()
    res = client.post(
        f"/ai/skills/{a['id']}/rollback",
        json={"versionId": b["activeVersionId"]},
        headers=headers,
    )
    assert res.status_code == 404


# ── AC-BI-08: prompt composition is substitution-only ────────────────────


def test_compose_substitutes_tokens():
    out = compose(
        "Capture: {{ target_fields }}\nFrom: {{ source_artifacts }}",
        {"target_fields": ["problem_statement", "success_metric"], "source_artifacts": "idea-1"},
    )
    assert "- problem_statement" in out
    assert "- success_metric" in out
    assert "idea-1" in out
    assert "{{" not in out


def test_compose_never_evaluates_eval_shaped_bodies():
    """AC-BI-08 — the anti-SSTI house rule. Jinja/f-string/`${}` constructs are
    INERT TEXT; only `{{ token }}` substitution happens."""
    hostile = (
        "{% for x in ().__class__.__base__.__subclasses__() %}LOOP{% endfor %}\n"
        "{{ 7*7 }}\n"
        "${__import__('os').system('echo pwned')}\n"
        "{{ config.items() }}"
    )
    out = compose(hostile, {})
    # Nothing was EVALUATED: `7*7` never became 49, and the loop body appears
    # exactly once (a real Jinja render would repeat it per subclass).
    assert "49" not in out
    assert out.count("LOOP") == 1
    # The eval-shaped constructs survive VERBATIM — proof they were never parsed
    # as anything but literal text.
    assert "{% for x in ().__class__.__base__.__subclasses__() %}" in out
    assert "{% endfor %}" in out
    assert "${__import__('os').system('echo pwned')}" in out
    # `{{ config.items() }}` is not even a valid token shape, so it survives as
    # literal text rather than resolving to a config dump.
    assert "{{ config.items() }}" in out
    assert "dict_items" not in out


def test_compose_missing_token_collapses_to_empty():
    out = compose("A {{ missing }} B", {})
    assert out == "A  B"


def test_field_schema_marks_nothing_required():
    """Bi-D13 — the TURN default marks nothing required: coverage is incremental
    and an unreached field is simply absent."""
    schema = field_schema([{"key": "problem_statement", "label": "Problem"}])
    assert schema["type"] == "object"
    assert "problem_statement" in schema["properties"]
    assert "required" not in schema


def test_field_schema_required_marks_every_key():
    """AC-BI-24c — the EXTRACTION schema marks EVERY key required so the model
    returns a value for each field (including one synthesized across turns), never
    silently omitting synthesized fields. Partial emit still holds — the paired
    directive + enforce_required=False keep a genuinely-blank field blank."""
    fields = [
        {"key": "problem_statement", "label": "Problem"},
        {"key": "business_goal", "label": "Goal"},
        {"key": "constraints", "label": "Constraints"},
    ]
    schema = field_schema(fields, required=True)
    assert schema["required"] == ["problem_statement", "business_goal", "constraints"]
    # An empty field list must not emit an empty required[] (a degenerate schema).
    assert "required" not in field_schema([], required=True)


def test_extraction_directive_demands_a_value_for_every_field():
    """AC-BI-24c — the extraction directive tells the model to return a value for
    EVERY field and to SYNTHESIZE across turns, while still never inventing."""
    from app.ai.grill import GrillContext, _compose_extraction_system

    ctx = GrillContext(
        tenant_id="t",
        target_id="br",
        target_fields=[{"key": "business_goal", "label": "Goal"}],
        target_doc={},
        source_artifacts=["Problem: exports are slow"],
        source_type="idea",
        source_ids=["idea-1"],
        template_version=1,
        agent=None,
        skill_body="Grill about {{ target_fields }} using {{ source_artifacts }}.",
        skill_key="grill-me-business",
        prompt_version=1,
    )
    directive = _compose_extraction_system(ctx)
    assert "value for EVERY field" in directive
    assert "SYNTHESIZE" in directive
    assert "NEVER invent" in directive


# ── AC-BI-09/10: traces, spans, payload caps ─────────────────────────────


def test_trace_and_spans_written_on_completion(session_factory):
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    result, trace = AiClient(db).complete(
        tenant_id=DEFAULT_TENANT_ID,
        agent=agent,
        system="be helpful",
        messages=[{"role": "user", "content": "hello"}],
    )
    db.commit()

    assert result.text is not None
    assert trace.status == TRACE_STATUS_OK
    assert trace.provider == "stub"
    assert trace.agent_name == "Griller"
    assert trace.span_count == 1
    # Trace usage is the roll-up of its spans — cost tracking reads the trace,
    # so it must never drift from the spans.
    spans = db.query(AiSpan).filter(AiSpan.trace_id == trace.id).all()
    assert len(spans) == 1
    assert spans[0].span_kind == SPAN_KIND_LLM_CALL
    assert trace.tokens_in == sum(s.tokens_in for s in spans)
    assert trace.tokens_out == sum(s.tokens_out for s in spans)
    db.close()


def test_failed_completion_still_writes_an_error_trace(session_factory):
    """A failure must remain OBSERVABLE — that is what traces are for."""
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    with stub_fixtures(StubResponse(error="provider exploded")):
        with pytest.raises(LLMError):
            AiClient(db).complete(
                tenant_id=DEFAULT_TENANT_ID,
                agent=agent,
                system="s",
                messages=[{"role": "user", "content": "x"}],
            )
    db.commit()
    trace = db.query(AiTrace).filter(AiTrace.tenant_id == DEFAULT_TENANT_ID).first()
    assert trace is not None
    assert trace.status == TRACE_STATUS_ERROR
    assert "provider exploded" in (trace.error or "")
    db.close()


def test_span_payload_is_capped_and_truncation_marked():
    """AC-BI-10 — a long grill must not bloat Postgres, and a clipped payload
    must be distinguishable from a short one."""
    huge = "x" * (MAX_PAYLOAD_CHARS + 5_000)
    capped = cap_payload({"system": huge, "short": "ok"})
    assert len(capped["system"]) <= MAX_PAYLOAD_CHARS + 20
    assert capped["system"].endswith("[truncated]")
    assert capped[TRUNCATED_FLAG] is True
    assert capped["short"] == "ok"


def test_cap_payload_does_not_mutate_the_caller_object():
    """The SQLAlchemy in-place-JSON-mutation trap: cap must return a NEW dict."""
    original = {"system": "x" * (MAX_PAYLOAD_CHARS + 10)}
    cap_payload(original)
    assert len(original["system"]) == MAX_PAYLOAD_CHARS + 10


def test_cap_payload_handles_nested_structures():
    capped = cap_payload({"messages": [{"content": "y" * (MAX_PAYLOAD_CHARS + 100)}]})
    assert capped["messages"][0]["content"].endswith("[truncated]")


def test_long_completion_is_capped_when_traced(session_factory):
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    with stub_fixtures(StubResponse(text="z" * (MAX_PAYLOAD_CHARS + 2_000))):
        _, trace = AiClient(db).complete(
            tenant_id=DEFAULT_TENANT_ID,
            agent=agent,
            system="s",
            messages=[{"role": "user", "content": "x"}],
        )
    db.commit()
    span = db.query(AiSpan).filter(AiSpan.trace_id == trace.id).first()
    assert span.output_json["text"].endswith("[truncated]")
    db.close()


def test_retention_sweep_prunes_ok_but_keeps_error_and_flagged(session_factory):
    """AC-BI-10 — `ok` prunes on the short window; `error`/`flagged` keep the
    longer one so a bad result stays diagnosable."""
    from app.config import settings

    db = session_factory()
    now = datetime.now(timezone.utc)
    old = now - timedelta(days=settings.ai_trace_retention_days + 5)
    ancient = now - timedelta(days=settings.ai_trace_error_retention_days + 5)

    def add(status, created_at, flagged=False):
        trace = AiTrace(
            tenant_id=DEFAULT_TENANT_ID,
            agent_name="a",
            status=status,
            flagged=flagged,
            created_at=created_at,
        )
        db.add(trace)
        db.flush()
        db.add(
            AiSpan(
                trace_id=trace.id,
                tenant_id=DEFAULT_TENANT_ID,
                span_kind=SPAN_KIND_LLM_CALL,
                dotted_order="1",
            )
        )
        return trace

    # Capture ids BEFORE the prune — a deleted ORM instance can no longer be
    # attribute-accessed (ObjectDeletedError).
    fresh_ok_id = add(TRACE_STATUS_OK, now).id
    old_ok_id = add(TRACE_STATUS_OK, old).id
    old_error_id = add(TRACE_STATUS_ERROR, old).id
    old_flagged_id = add(TRACE_STATUS_OK, old, flagged=True).id
    ancient_error_id = add(TRACE_STATUS_ERROR, ancient).id
    db.commit()

    deleted = prune_traces(db, now=now)
    assert deleted == 2  # old_ok + ancient_error

    surviving = {t.id for t in db.query(AiTrace).all()}
    assert fresh_ok_id in surviving
    assert old_error_id in surviving, "error traces keep the longer window"
    assert old_flagged_id in surviving, "flagging preserves an ok trace"
    assert old_ok_id not in surviving
    assert ancient_error_id not in surviving

    # Child spans cascade — no orphans left behind.
    orphans = (
        db.query(AiSpan).filter(AiSpan.trace_id.notin_(list(surviving))).count()
    )
    assert orphans == 0
    db.close()


def test_retention_sweep_is_wired_into_the_beat_task():
    """AC-BI-10 — the sweep runs on the beat tick, in its OWN isolated
    try/except so a prune failure never breaks the beat."""
    import inspect

    from app.workflow_engine import worker

    source = inspect.getsource(worker.run_due_workflows_task)
    assert "prune_traces" in source
    assert "AI trace prune failed" in source


# ── AC-BI-11: key resolution order ───────────────────────────────────────


def test_resolution_prefers_tenant_connection_over_platform(session_factory):
    db = session_factory()
    _make_connection(db, tenant_id=PLATFORM_TENANT_ID, provider="openai", name="Platform")
    own = _make_connection(db, provider="gemini", name="Own")
    assert any_llm_connection(db, DEFAULT_TENANT_ID).id == own.id
    db.close()


def test_resolution_falls_back_to_platform_connection(session_factory):
    db = session_factory()
    platform = _make_connection(
        db, tenant_id=PLATFORM_TENANT_ID, provider="openai", name="Platform"
    )
    assert any_llm_connection(db, DEFAULT_TENANT_ID).id == platform.id
    db.close()


def test_resolution_is_deterministic_across_several_llm_rows(session_factory):
    """AC-BI-03b — with the carve-out a tenant can hold several rows, so the
    prerequisite probe must pick DETERMINISTICALLY.

    The ordering is (created_at, id): the id tiebreak is what makes the pick
    stable even when several rows share a timestamp, which is exactly what
    happens when they are seeded in one transaction. Asserting stability is the
    real contract — asserting WHICH row would just re-encode the tiebreak.
    """
    db = session_factory()
    _make_connection(db, provider="anthropic", name="First")
    _make_connection(db, provider="gemini", name="Second")
    _make_connection(db, provider="openai", name="Third")
    picks = {any_llm_connection(db, DEFAULT_TENANT_ID).id for _ in range(5)}
    assert len(picks) == 1, "the prerequisite probe is not deterministic"
    db.close()


def test_no_connection_anywhere_reports_missing_prerequisite(session_factory):
    db = session_factory()
    assert any_llm_connection(db, DEFAULT_TENANT_ID) is None
    db.close()


def test_prerequisite_endpoint_reports_absence(client):
    """AC-BI-11 — the UI must be able to warn BEFORE anything runs."""
    headers = _login(client)
    res = client.get("/ai/agents/prerequisite", headers=headers)
    assert res.status_code == 200
    assert res.json()["hasConnection"] is False


def test_prerequisite_endpoint_lists_llm_connections(client):
    headers = _login(client)
    client.post(
        "/integrations/connections",
        json={"provider": "gemini", "name": "G", "config": {}, "credentials": {"apiKey": "k"}},
        headers=headers,
    )
    body = client.get("/ai/agents/prerequisite", headers=headers).json()
    assert body["hasConnection"] is True
    assert [c["provider"] for c in body["connections"]] == ["gemini"]


# ── AC-BI-06: agents + missing-prerequisite warning ──────────────────────


def test_agent_holds_no_credential_of_its_own(session_factory):
    """AC-BI-06 — credentials live ONLY on the connection."""
    columns = {c.name for c in AiAgent.__table__.columns}
    assert not any(
        hint in name
        for name in columns
        for hint in ("api_key", "apikey", "credential", "secret", "token")
    ), f"ai_agents carries a credential-ish column: {columns}"


def test_agent_without_connection_surfaces_warning(client):
    headers = _login(client)
    created = client.post(
        "/ai/agents", json={"name": "Orphan", "model": "x"}, headers=headers
    )
    assert created.status_code == 201, created.text
    assert created.json()["warning"], "an agent with no connection must warn"


def test_agent_warns_when_its_connection_is_deleted(client, session_factory):
    headers = _login(client)
    conn = client.post(
        "/integrations/connections",
        json={"provider": "gemini", "name": "G", "config": {}, "credentials": {"apiKey": "k"}},
        headers=headers,
    ).json()
    agent = client.post(
        "/ai/agents",
        json={"name": "A", "connectionId": conn["id"], "model": "gemini-2.5-flash"},
        headers=headers,
    ).json()
    assert agent["warning"] is None

    client.delete(f"/integrations/connections/{conn['id']}", headers=headers)
    after = client.get(f"/ai/agents/{agent['id']}", headers=headers).json()
    assert after["warning"], "a deleted connection must surface a warning, not fail silently"


def test_agent_rejects_a_non_llm_connection(client):
    """Foolproof-UI's backend half: only valid options are storable."""
    headers = _login(client)
    smtp = client.post(
        "/integrations/connections",
        json={
            "provider": "smtp",
            "name": "Mail",
            "config": {"host": "h", "port": "587"},
            "credentials": {"password": "p"},
        },
        headers=headers,
    ).json()
    res = client.post(
        "/ai/agents", json={"name": "A", "connectionId": smtp["id"]}, headers=headers
    )
    assert res.status_code == 422


def test_agent_duplicate_name_rejected(client):
    headers = _login(client)
    client.post("/ai/agents", json={"name": "Dup"}, headers=headers)
    second = client.post("/ai/agents", json={"name": "Dup"}, headers=headers)
    assert second.status_code == 409


def test_agent_temperature_bounds_enforced(client):
    headers = _login(client)
    res = client.post("/ai/agents", json={"name": "Hot", "temperature": 9}, headers=headers)
    assert res.status_code == 422


# ── AC-BI-06b: an agent equips MANY skills ───────────────────────────────


def _create_skill(client, headers, key, name="Skill"):
    return client.post(
        "/ai/skills", json={"key": key, "name": name, "body": "b"}, headers=headers
    ).json()


def test_agent_equips_zero_one_and_many_skills(client):
    """AC-BI-06b — the equipped set is a many-many; 0, 1 and N all valid."""
    headers = _login(client)
    s1 = _create_skill(client, headers, "s1", "First")
    s2 = _create_skill(client, headers, "s2", "Second")
    s3 = _create_skill(client, headers, "s3", "Third")

    # Zero.
    none = client.post("/ai/agents", json={"name": "None"}, headers=headers).json()
    assert none["skills"] == []

    # One.
    one = client.post(
        "/ai/agents", json={"name": "One", "skillIds": [s1["id"]]}, headers=headers
    ).json()
    assert [s["id"] for s in one["skills"]] == [s1["id"]]
    assert one["skills"][0]["name"] == "First"

    # Many.
    many = client.post(
        "/ai/agents",
        json={"name": "Many", "skillIds": [s1["id"], s2["id"], s3["id"]]},
        headers=headers,
    ).json()
    assert {s["id"] for s in many["skills"]} == {s1["id"], s2["id"], s3["id"]}


def test_agent_update_replaces_the_equipped_set(client):
    """skillIds on update REPLACES the set; [] clears it; omitting leaves it."""
    headers = _login(client)
    s1 = _create_skill(client, headers, "s1")
    s2 = _create_skill(client, headers, "s2")
    agent = client.post(
        "/ai/agents", json={"name": "A", "skillIds": [s1["id"]]}, headers=headers
    ).json()

    swapped = client.patch(
        f"/ai/agents/{agent['id']}", json={"skillIds": [s2["id"]]}, headers=headers
    ).json()
    assert [s["id"] for s in swapped["skills"]] == [s2["id"]]

    # Omitting skillIds leaves the set unchanged.
    renamed = client.patch(
        f"/ai/agents/{agent['id']}", json={"name": "A2"}, headers=headers
    ).json()
    assert [s["id"] for s in renamed["skills"]] == [s2["id"]]

    # [] clears it.
    cleared = client.patch(
        f"/ai/agents/{agent['id']}", json={"skillIds": []}, headers=headers
    ).json()
    assert cleared["skills"] == []


def test_agent_equip_dedupes_repeated_skill_ids(client):
    headers = _login(client)
    s1 = _create_skill(client, headers, "s1")
    agent = client.post(
        "/ai/agents",
        json={"name": "Dup", "skillIds": [s1["id"], s1["id"]]},
        headers=headers,
    ).json()
    assert [s["id"] for s in agent["skills"]] == [s1["id"]]


def test_agent_equip_allows_platform_tier_skill(client, session_factory):
    """AC-BI-06b — a platform-tier skill id is a valid equip target."""
    db = session_factory()
    skill = AiSkill(tenant_id=None, key="platform-grill", name="Platform Grill")
    db.add(skill)
    db.flush()
    version = AiSkillVersion(skill_id=skill.id, tenant_id=None, version=1, body="shared")
    db.add(version)
    db.flush()
    skill.active_version_id = version.id
    db.commit()
    platform_skill_id = skill.id
    db.close()

    headers = _login(client)
    agent = client.post(
        "/ai/agents",
        json={"name": "Uses platform skill", "skillIds": [platform_skill_id]},
        headers=headers,
    )
    assert agent.status_code == 201, agent.text
    assert [s["id"] for s in agent.json()["skills"]] == [platform_skill_id]


def test_agent_equip_refuses_foreign_tenant_skill(client, session_factory):
    """AC-BI-06b — a skill id from ANOTHER tenant is refused (polymorphic-target
    rule: validate on write)."""
    from app.models.tenant import Tenant

    db = session_factory()
    default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
    other = Tenant(name="Other AI", slug="other-ai-skill", status_id=default_tenant.status_id)
    db.add(other)
    db.flush()
    foreign = AiSkill(tenant_id=other.id, key="foreign", name="Foreign")
    db.add(foreign)
    db.flush()
    foreign_id = foreign.id
    db.commit()
    db.close()

    headers = _login(client)
    res = client.post(
        "/ai/agents",
        json={"name": "Sneaky", "skillIds": [foreign_id]},
        headers=headers,
    )
    assert res.status_code == 422, res.text


def test_agent_skill_set_is_tenant_scoped_on_read(client, session_factory):
    """AC-BI-06b — the join is tenant-scoped: another tenant's agent+equip is
    invisible, and its equipped skills never leak into our read."""
    db = session_factory()
    # A platform-tenant agent equipping a platform-tenant skill.
    skill = AiSkill(tenant_id=PLATFORM_TENANT_ID, key="theirs", name="Theirs")
    db.add(skill)
    db.flush()
    agent = AiAgent(tenant_id=PLATFORM_TENANT_ID, name="Platform agent")
    agent.skills = [skill]
    db.add(agent)
    db.commit()
    foreign_agent_id = agent.id
    db.close()

    headers = _login(client)
    # The foreign agent is not in our list, and fetching it 404s.
    listed = client.get("/ai/agents", headers=headers).json()
    assert all(a["id"] != foreign_agent_id for a in listed["data"])
    assert client.get(f"/ai/agents/{foreign_agent_id}", headers=headers).status_code == 404


def test_skill_delete_blocked_while_equipped(client):
    """A skill still equipped by an agent warns before it is un-equipped."""
    headers = _login(client)
    skill = _create_skill(client, headers, "equipped")
    client.post(
        "/ai/agents", json={"name": "Equipper", "skillIds": [skill["id"]]}, headers=headers
    )
    res = client.delete(f"/ai/skills/{skill['id']}", headers=headers)
    assert res.status_code == 409
    assert "equip" in res.json()["detail"]


def test_disabled_agent_refuses_to_run(session_factory):
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn, is_enabled=False)
    with pytest.raises(LLMError):
        AiClient(db).complete(
            tenant_id=DEFAULT_TENANT_ID,
            agent=agent,
            system="s",
            messages=[{"role": "user", "content": "x"}],
        )
    db.close()


# ── AC-BI-05: model picker ───────────────────────────────────────────────


def test_models_endpoint_falls_back_to_static_list_on_provider_failure(
    client, session_factory
):
    """AC-BI-05 — the form must STILL RENDER when the live call fails."""
    headers = _login(client)
    conn = client.post(
        "/integrations/connections",
        json={
            "provider": "anthropic",
            "name": "Claude",
            "config": {},
            # A real (non-dev) credential, so the live path is attempted and
            # fails against the network-less test environment.
            "credentials": {"apiKey": "definitely-not-a-real-key"},
        },
        headers=headers,
    ).json()
    res = client.get(f"/ai/agents/models?connection_id={conn['id']}", headers=headers)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["isLive"] is False
    assert body["data"], "static fallback must be served"
    assert body["message"]


# ── AC-BI-12: stub determinism + fixture control ─────────────────────────


def test_stub_is_deterministic_for_identical_input(session_factory):
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    client_ = AiClient(db)
    args = dict(
        tenant_id=DEFAULT_TENANT_ID,
        agent=agent,
        system="s",
        messages=[{"role": "user", "content": "same question"}],
    )
    first, _ = client_.complete(**args)
    second, _ = client_.complete(**args)
    assert first.text == second.text
    db.close()


def test_stub_fixture_can_declare_an_invalid_extraction(session_factory):
    """AC-BI-12 — a spec can script an extraction MISSING a field, so slice 3's
    retry/partial-emit paths become deterministically testable."""
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    schema = field_schema(
        [{"key": "problem_statement"}, {"key": "success_metric"}]
    )
    with stub_fixtures(StubResponse(structured={"problem_statement": "only this"})):
        result, _ = AiClient(db).complete(
            tenant_id=DEFAULT_TENANT_ID,
            agent=agent,
            system="s",
            messages=[{"role": "user", "content": "x"}],
            output_schema=schema,
        )
    assert result.structured == {"problem_statement": "only this"}
    assert "success_metric" not in result.structured
    db.close()


def test_stub_queue_drains_then_falls_back(session_factory):
    """A drained queue must not hang or raise — it returns the derived reply."""
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    with stub_fixtures(StubResponse(text="scripted")):
        first, _ = AiClient(db).complete(
            tenant_id=DEFAULT_TENANT_ID, agent=agent, system="s",
            messages=[{"role": "user", "content": "x"}],
        )
        second, _ = AiClient(db).complete(
            tenant_id=DEFAULT_TENANT_ID, agent=agent, system="s",
            messages=[{"role": "user", "content": "x"}],
        )
    assert first.text == "scripted"
    assert second.text != "scripted"
    db.close()


def test_stub_structured_call_returns_schema_shaped_object(session_factory):
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    schema = field_schema([{"key": "problem_statement"}, {"key": "scope"}])
    result, _ = AiClient(db).complete(
        tenant_id=DEFAULT_TENANT_ID,
        agent=agent,
        system="s",
        messages=[{"role": "user", "content": "x"}],
        output_schema=schema,
    )
    assert result.text is None
    assert set(result.structured) == {"problem_statement", "scope"}
    db.close()


def test_stub_answers_when_no_connection_is_configured(session_factory):
    """AC-BI-12 — zero API key, zero cost, zero network."""
    db = session_factory()
    agent = _make_agent(db, None)
    result, trace = AiClient(db).complete(
        tenant_id=DEFAULT_TENANT_ID,
        agent=agent,
        system="s",
        messages=[{"role": "user", "content": "x"}],
    )
    assert result.text is not None
    assert trace.provider == "stub"
    db.close()


# ── AC-BI-14: permission gating ──────────────────────────────────────────


def test_ai_permissions_declared_in_core_csv():
    """AC-BI-14 — agents+skills share `ai_agents.*`; traces are SEPARATE."""
    from pathlib import Path

    csv_text = Path("app/permissions/permissions.csv").read_text()
    assert "ai_agents,AI Agents,read" in csv_text
    assert "ai_agents,AI Agents,manage" in csv_text
    assert "ai_traces,AI Traces,read" in csv_text


def test_ai_endpoints_reject_unauthenticated(client):
    for path in ("/ai/agents", "/ai/skills", "/ai/traces"):
        assert client.get(path).status_code == 401, path


def test_manage_required_to_write_agents(client, session_factory):
    """The backend is the real boundary — read alone cannot write."""
    db = session_factory()
    user = _demo_user(db)
    role = user.roles[0]
    role.permissions = [p for p in role.permissions if p.key != "ai_agents.manage"]
    db.commit()
    db.close()

    headers = _login(client)
    assert client.get("/ai/agents", headers=headers).status_code == 200
    assert (
        client.post("/ai/agents", json={"name": "Nope"}, headers=headers).status_code
        == 403
    )


def test_trace_read_is_separable_from_agent_manage(client, session_factory):
    """AC-BI-14 — the whole point of the split: trace access (raw prompts) can be
    revoked WITHOUT losing the ability to configure agents."""
    db = session_factory()
    user = _demo_user(db)
    role = user.roles[0]
    role.permissions = [p for p in role.permissions if p.key != "ai_traces.read"]
    db.commit()
    db.close()

    headers = _login(client)
    assert client.get("/ai/traces", headers=headers).status_code == 403
    assert client.get("/ai/agents", headers=headers).status_code == 200
    assert (
        client.post("/ai/agents", json={"name": "Still allowed"}, headers=headers).status_code
        == 201
    )


def test_implied_read_normalization_for_ai_manage():
    """AC-BI-14 — granting `ai_agents.manage` forces `ai_agents.read`
    server-side (the blanket implied-read rule applies to the new keys too)."""
    from app.services.role_service import apply_implied_read

    assert "ai_agents.read" in apply_implied_read(["ai_agents.manage"])
    # `ai_traces.read` is already a read — it implies nothing further, and it is
    # NOT implied by `ai_agents.manage` (the separation AC-BI-14 requires).
    assert "ai_traces.read" not in apply_implied_read(["ai_agents.manage"])


# ── tenant scoping ───────────────────────────────────────────────────────


def test_agents_are_tenant_scoped(client, session_factory):
    """Cross-tenant access is refused — the load-bearing isolation rule."""
    db = session_factory()
    other_agent = AiAgent(tenant_id=PLATFORM_TENANT_ID, name="Platform agent")
    db.add(other_agent)
    db.commit()
    other_id = other_agent.id
    db.close()

    headers = _login(client)
    listed = client.get("/ai/agents", headers=headers).json()
    assert all(a["id"] != other_id for a in listed["data"])
    assert client.get(f"/ai/agents/{other_id}", headers=headers).status_code == 404


def test_traces_are_tenant_scoped(client, session_factory):
    db = session_factory()
    foreign = AiTrace(tenant_id=PLATFORM_TENANT_ID, agent_name="theirs")
    db.add(foreign)
    db.commit()
    foreign_id = foreign.id
    db.close()

    headers = _login(client)
    assert client.get(f"/ai/traces/{foreign_id}", headers=headers).status_code == 404
    listed = client.get("/ai/traces", headers=headers).json()
    assert all(t["id"] != foreign_id for t in listed["data"])


def test_agent_cannot_point_at_another_tenants_connection(client, session_factory):
    """A stored connection id is validated on WRITE and re-scoped at USE time."""
    from app.models.tenant import Tenant

    db = session_factory()
    # A connection owned by a THIRD tenant — neither the caller nor the platform
    # fallback, so it must be entirely invisible.
    default_tenant = db.query(Tenant).filter(Tenant.id == DEFAULT_TENANT_ID).first()
    other = Tenant(name="Other", slug="other-ai", status_id=default_tenant.status_id)
    db.add(other)
    db.flush()
    foreign_id = _make_connection(db, tenant_id=other.id, provider="gemini").id
    db.commit()
    db.close()

    headers = _login(client)
    res = client.post(
        "/ai/agents", json={"name": "Sneaky", "connectionId": foreign_id}, headers=headers
    )
    assert res.status_code == 404


def test_skill_list_includes_platform_tier_rows(client, session_factory):
    """Two-tier skills: a platform-tier row is visible to every tenant."""
    db = session_factory()
    skill = AiSkill(tenant_id=None, key="platform-grill", name="Platform Grill", is_system=True)
    db.add(skill)
    db.flush()
    version = AiSkillVersion(skill_id=skill.id, tenant_id=None, version=1, body="shared")
    db.add(version)
    # FLUSH before reading `version.id` — the uuid default is applied at INSERT,
    # not at construction, so an unflushed instance still has id=None.
    db.flush()
    skill.active_version_id = version.id
    db.commit()
    db.close()

    headers = _login(client)
    listed = client.get("/ai/skills", headers=headers).json()
    row = next(s for s in listed["data"] if s["key"] == "platform-grill")
    assert row["isPlatform"] is True
    assert row["body"] == "shared"


def test_tenant_edit_of_platform_skill_forks_rather_than_mutating(client, session_factory):
    """A tenant's edit must never mutate the SHARED platform default."""
    db = session_factory()
    skill = AiSkill(tenant_id=None, key="shared", name="Shared")
    db.add(skill)
    db.flush()
    version = AiSkillVersion(skill_id=skill.id, tenant_id=None, version=1, body="platform body")
    db.add(version)
    db.flush()  # mint version.id before labelling
    skill.active_version_id = version.id
    db.commit()
    platform_skill_id = skill.id
    db.close()

    headers = _login(client)
    updated = client.patch(
        f"/ai/skills/{platform_skill_id}", json={"body": "tenant body"}, headers=headers
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["id"] != platform_skill_id, "the platform row was edited in place"
    assert updated.json()["isPlatform"] is False

    db = session_factory()
    untouched = db.query(AiSkill).filter(AiSkill.id == platform_skill_id).first()
    active = (
        db.query(AiSkillVersion)
        .filter(AiSkillVersion.id == untouched.active_version_id)
        .first()
    )
    assert active.body == "platform body"
    db.close()


def test_platform_tier_skill_cannot_be_deleted_by_a_tenant(client, session_factory):
    db = session_factory()
    skill = AiSkill(tenant_id=None, key="undeletable", name="Undeletable")
    db.add(skill)
    db.commit()
    skill_id = skill.id
    db.close()

    headers = _login(client)
    assert client.delete(f"/ai/skills/{skill_id}", headers=headers).status_code == 409


# ── AC-BI-03: credentials are write-only ─────────────────────────────────


def test_llm_credentials_are_never_echoed(client):
    """AC-BI-03 — the API key is never returned by any endpoint."""
    headers = _login(client)
    created = client.post(
        "/integrations/connections",
        json={
            "provider": "gemini",
            "name": "G",
            "config": {},
            "credentials": {"apiKey": "super-secret-key-value"},
        },
        headers=headers,
    )
    assert "super-secret-key-value" not in created.text
    fetched = client.get(f"/integrations/connections/{created.json()['id']}", headers=headers)
    assert "super-secret-key-value" not in fetched.text
    listed = client.get("/integrations/connections", headers=headers)
    assert "super-secret-key-value" not in listed.text


def test_blank_credential_on_update_keeps_the_stored_key(client, session_factory):
    """AC-BI-03 — the documented blank-to-keep contract."""
    from app.secrets import decrypt_secret

    headers = _login(client)
    created = client.post(
        "/integrations/connections",
        json={
            "provider": "gemini",
            "name": "G",
            "config": {},
            "credentials": {"apiKey": "keep-me"},
        },
        headers=headers,
    ).json()
    client.patch(
        f"/integrations/connections/{created['id']}",
        json={"name": "Renamed", "credentials": {"apiKey": ""}},
        headers=headers,
    )
    db = session_factory()
    row = db.query(Connection).filter(Connection.id == created["id"]).first()
    assert decrypt_secret(row.credentials_json)["apiKey"] == "keep-me"
    assert row.name == "Renamed"
    db.close()


def test_config_patch_merges_rather_than_wipes(client, session_factory):
    """AC-BI-03 — a partial config PATCH merges."""
    headers = _login(client)
    created = client.post(
        "/integrations/connections",
        json={
            "provider": "gemini",
            "name": "G",
            "config": {"defaultModel": "gemini-2.5-flash", "other": "keep"},
            "credentials": {"apiKey": "k"},
        },
        headers=headers,
    ).json()
    client.patch(
        f"/integrations/connections/{created['id']}",
        json={"config": {"defaultModel": "gemini-2.5-pro"}},
        headers=headers,
    )
    db = session_factory()
    row = db.query(Connection).filter(Connection.id == created["id"]).first()
    assert row.config_json["defaultModel"] == "gemini-2.5-pro"
    assert row.config_json["other"] == "keep", "an omitted config key was wiped"
    db.close()


# ── platform LLM env seed ────────────────────────────────────────────────


def test_platform_llm_seed_is_idempotent_and_refuses_without_fernet_key(
    session_factory, monkeypatch, capsys
):
    from app.config import settings
    from app.seed import seed_platform_llm_connection

    db = session_factory()
    monkeypatch.setattr(settings, "platform_llm_api_key", "env-key")
    monkeypatch.setattr(settings, "platform_llm_provider", "gemini")
    monkeypatch.setattr(settings, "platform_llm_model", "gemini-2.5-flash")

    # No FERNET_KEY → refuse LOUDLY (an ephemeral key would be unreadable by
    # the API process), and write nothing.
    monkeypatch.setattr(settings, "fernet_key", "")
    seed_platform_llm_connection(db)
    assert "FERNET_KEY" in capsys.readouterr().out
    assert (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.type == "llm")
        .count()
        == 0
    )

    monkeypatch.setattr(settings, "fernet_key", "hkPQ0Yq5r3vXk7l9m2n4o6p8q0s2t4u6w8y0z2A4B6C=")
    seed_platform_llm_connection(db)
    db.commit()
    seed_platform_llm_connection(db)  # idempotent
    db.commit()
    rows = (
        db.query(Connection)
        .filter(Connection.tenant_id == PLATFORM_TENANT_ID, Connection.type == "llm")
        .all()
    )
    assert len(rows) == 1
    assert rows[0].provider == "gemini"
    assert rows[0].config_json["defaultModel"] == "gemini-2.5-flash"
    db.close()


def test_grill_api_key_alias_is_honoured(monkeypatch):
    """The legacy `GRILL_API_KEY` name keeps working; the canonical
    PLATFORM_LLM_API_KEY wins when both are set."""
    from app.config import settings

    monkeypatch.setattr(settings, "platform_llm_api_key", "")
    monkeypatch.setattr(settings, "grill_api_key", "legacy")
    assert settings.resolved_platform_llm_api_key == "legacy"

    monkeypatch.setattr(settings, "platform_llm_api_key", "canonical")
    assert settings.resolved_platform_llm_api_key == "canonical"


# ── trace surface ────────────────────────────────────────────────────────


def test_trace_detail_returns_ordered_flat_step_list(client, session_factory):
    """AC-BI-09/Bi-D17 — a FLAT ordered list; no tree renderer in v1."""
    db = session_factory()
    conn = _make_connection(db)
    agent = _make_agent(db, conn)
    writer = TraceWriter(db, tenant_id=DEFAULT_TENANT_ID, agent_id=agent.id, agent_name="A")
    writer.add_span(span_kind="llm_call", name="completion")
    writer.add_span(span_kind="validate", name="validate")
    writer.add_span(span_kind="retry", name="retry")
    trace = writer.finish()
    db.commit()
    trace_id = trace.id
    db.close()

    headers = _login(client)
    body = client.get(f"/ai/traces/{trace_id}", headers=headers).json()
    assert body["spanCount"] == 3
    assert [s["spanKind"] for s in body["spans"]] == ["llm_call", "validate", "retry"]
    assert [s["dottedOrder"] for s in body["spans"]] == ["1", "2", "3"]


def test_trace_flag_toggle(client, session_factory):
    db = session_factory()
    trace = AiTrace(tenant_id=DEFAULT_TENANT_ID, agent_name="a")
    db.add(trace)
    db.commit()
    trace_id = trace.id
    db.close()

    headers = _login(client)
    res = client.post(f"/ai/traces/{trace_id}/flag", json={"flagged": True}, headers=headers)
    assert res.status_code == 200
    assert res.json()["flagged"] is True
