"""S3 generic Redis workflow action tests (AC-SAR-43..48)."""

import fakeredis
import pytest

from app.models import DEFAULT_TENANT_ID
from app.models.workflow import RUN_PENDING, Workflow, WorkflowRun, WorkflowRunNode
from app.workflow_engine.actions.redis_actions import (
    ActionError,
    WorkflowRedisService,
    literal_config_issues,
    physical_key,
    redis_command,
    use_workflow_redis_client,
    validate_logical_key,
)


@pytest.fixture
def fake_redis():
    client = fakeredis.FakeRedis(decode_responses=True)
    with use_workflow_redis_client(client):
        yield client


def _cmd(config, ctx=None, tenant_id=DEFAULT_TENANT_ID):
    return redis_command(None, tenant_id, config, ctx or {})


def test_set_get_delete_round_trip_with_optional_ttl(fake_redis):
    assert _cmd({"operation": "get", "key": "counter"}) == {"value": None}
    assert _cmd({"operation": "set", "key": "greeting", "value": "hello"}) == {"stored": True}
    assert _cmd({"operation": "get", "key": "greeting"}) == {"value": "hello"}
    assert _cmd({"operation": "set", "key": "temp", "value": "x", "ttlSeconds": "30"}) == {"stored": True}
    assert 0 < fake_redis.ttl(physical_key(DEFAULT_TENANT_ID, "temp")) <= 30
    assert _cmd({"operation": "delete", "key": "greeting"}) == {"deleted": True}
    assert _cmd({"operation": "delete", "key": "greeting"}) == {"deleted": False}  # idempotent


def test_increment_is_atomic_integer_math(fake_redis):
    assert _cmd({"operation": "increment", "key": "n", "amount": "5"}) == {"value": 5}
    assert _cmd({"operation": "increment", "key": "n", "amount": "-2"}) == {"value": 3}
    assert _cmd({"operation": "increment", "key": "n"}) == {"value": 4}
    with pytest.raises(ActionError, match="whole number"):
        _cmd({"operation": "increment", "key": "n", "amount": "1.5"})
    _cmd({"operation": "set", "key": "text", "value": "abc"})
    with pytest.raises(ActionError, match="not valid for the stored value"):
        _cmd({"operation": "increment", "key": "text", "amount": "1"})


def test_list_push_pop_length_honour_ends(fake_redis):
    assert _cmd({"operation": "list_push", "key": "q", "value": "a", "end": "right"}) == {"length": 1}
    assert _cmd({"operation": "list_push", "key": "q", "value": "b", "end": "right"}) == {"length": 2}
    assert _cmd({"operation": "list_push", "key": "q", "value": "z", "end": "left"}) == {"length": 3}
    assert _cmd({"operation": "list_length", "key": "q"}) == {"length": 3}
    assert _cmd({"operation": "list_pop", "key": "q", "end": "left"}) == {"value": "z"}
    assert _cmd({"operation": "list_pop", "key": "q", "end": "right"}) == {"value": "b"}
    assert _cmd({"operation": "list_pop", "key": "q", "end": "right"}) == {"value": "a"}
    assert _cmd({"operation": "list_pop", "key": "q", "end": "right"}) == {"value": None}
    with pytest.raises(ActionError, match="Left or Right"):
        _cmd({"operation": "list_pop", "key": "q", "end": "middle"})


def test_ttl_validation_rejects_non_positive_and_non_numeric(fake_redis):
    with pytest.raises(ActionError, match="TTL seconds"):
        _cmd({"operation": "set", "key": "k", "value": "v", "ttlSeconds": "0"})
    with pytest.raises(ActionError, match="TTL seconds"):
        _cmd({"operation": "set", "key": "k", "value": "v", "ttlSeconds": "soon"})
    assert fake_redis.exists(physical_key(DEFAULT_TENANT_ID, "k")) == 0  # no partial mutation


def test_keys_are_tenant_namespaced_and_reserved_prefixes_rejected(fake_redis):
    _cmd({"operation": "set", "key": "shared", "value": "tenant-a"}, tenant_id="tenant-a")
    _cmd({"operation": "set", "key": "shared", "value": "tenant-b"}, tenant_id="tenant-b")
    assert _cmd({"operation": "get", "key": "shared"}, tenant_id="tenant-a") == {"value": "tenant-a"}
    assert _cmd({"operation": "get", "key": "shared"}, tenant_id="tenant-b") == {"value": "tenant-b"}
    assert sorted(fake_redis.keys("*")) == [
        physical_key("tenant-a", "shared"),
        physical_key("tenant-b", "shared"),
    ]
    # An internal prefix spelled as a logical key still lands inside the
    # tenant namespace - it can never address a lease/broker key - and the
    # obvious attempt is rejected outright.
    for bad in ("foundryx:workflow:serialized:x", "FOUNDRYX:anything", "", "   ", "a\nb"):
        with pytest.raises(ActionError):
            validate_logical_key(bad)
    with pytest.raises(ActionError, match="reserved"):
        _cmd({"operation": "get", "key": "foundryx:workflow:data:tenant-b:shared"}, tenant_id="tenant-a")
    assert WorkflowRedisService("tenant-a", fake_redis).get("shared") == "tenant-a"


def test_merge_rendering_resolves_key_and_value_from_run_context(fake_redis):
    ctx = {"trigger.contact.id": "cnt-1", "nodes.agent.status": "blocked"}
    assert _cmd(
        {"operation": "set", "key": "status:{{ trigger.contact.id }}", "value": "{{ nodes.agent.status }}"},
        ctx,
    ) == {"stored": True}
    assert fake_redis.get(physical_key(DEFAULT_TENANT_ID, "status:cnt-1")) == "blocked"


def test_outage_raises_action_error_without_leaking_physical_details():
    class Down:
        def __getattr__(self, name):
            def _fail(*_args, **_kwargs):
                raise ConnectionError("Error 61 connecting to redis-internal:6379")

            return _fail

    with use_workflow_redis_client(Down()):
        with pytest.raises(ActionError) as excinfo:
            _cmd({"operation": "get", "key": "k"})
    assert "redis-internal" not in str(excinfo.value)
    assert "foundryx:workflow" not in str(excinfo.value)


def test_literal_config_issues_mirror_publish_gate():
    assert literal_config_issues({"operation": "bogus", "key": "k"})
    assert literal_config_issues({"operation": "list_push", "key": "k", "value": "v", "end": "middle"})
    assert literal_config_issues({"operation": "set", "key": "k", "value": "v", "ttlSeconds": "-1"})
    assert literal_config_issues({"operation": "increment", "key": "k", "amount": "1.5"})
    assert literal_config_issues({"operation": "get", "key": "foundryx:internal"})
    # Merge expressions are resolved at run time - never rejected at publish.
    assert literal_config_issues({"operation": "set", "key": "k", "value": "v", "ttlSeconds": "{{ nodes.a.ttl }}"}) == []
    assert literal_config_issues({"operation": "list_pop", "key": "{{ trigger.contact.id }}", "end": "left"}) == []


def test_publish_validation_reports_redis_config_issues(session_factory):
    from app.workflow_engine.schemas import definition_issues, parse_definition

    doc = parse_definition(
        {
            "schemaVersion": 2,
            "nodes": [
                {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
                {"id": "r", "kind": "action", "type": "redis.command", "config": {"operation": "list_push", "key": "k", "value": "v", "end": "middle"}, "position": {}},
            ],
            "edges": [{"id": "e1", "source": "trigger", "target": "r"}],
        }
    )
    issues = definition_issues(doc)
    assert any("List end" in issue for issue in issues)


def test_run_failure_skips_downstream_and_log_hides_physical_prefix(session_factory, fake_redis):
    db = session_factory()
    doc = {
        "schemaVersion": 2,
        "nodes": [
            {"id": "trigger", "kind": "trigger", "type": "manual", "config": {}, "position": {}},
            {"id": "r1", "kind": "action", "type": "redis.command", "config": {"operation": "set", "key": "greeting", "value": "hi"}, "position": {}},
            {"id": "r2", "kind": "action", "type": "redis.command", "config": {"operation": "increment", "key": "greeting", "amount": "1"}, "position": {}},
            {"id": "r3", "kind": "action", "type": "redis.command", "config": {"operation": "get", "key": "greeting"}, "position": {}},
        ],
        "edges": [
            {"id": "e1", "source": "trigger", "target": "r1"},
            {"id": "e2", "source": "r1", "target": "r2"},
            {"id": "e3", "source": "r2", "target": "r3"},
        ],
    }
    workflow = Workflow(tenant_id=DEFAULT_TENANT_ID, name="Redis", description="", draft_definition_json=doc)
    db.add(workflow)
    db.flush()
    run = WorkflowRun(
        tenant_id=DEFAULT_TENANT_ID,
        workflow_id=workflow.id,
        status=RUN_PENDING,
        definition_snapshot_json=doc,
        trigger_payload_json={"triggeredBy": "manual"},
    )
    db.add(run)
    db.commit()
    from app.workflow_engine.executor import run_workflow

    result = run_workflow(db, run.id)
    assert result.status == "failed"
    nodes = {n.node_id: n for n in db.query(WorkflowRunNode).filter(WorkflowRunNode.run_id == run.id).all()}
    assert nodes["r1"].status == "success" and nodes["r1"].output_json == {"stored": True}
    assert nodes["r2"].status == "failed" and "not valid for the stored value" in nodes["r2"].error
    assert nodes["r3"].status == "skipped"
    # The stored value survived the failed node (no partial mutation) and
    # the run log never shows the physical namespace.
    assert fake_redis.get(physical_key(DEFAULT_TENANT_ID, "greeting")) == "hi"
    import json

    dumped = json.dumps([[n.input_json, n.output_json, n.error] for n in nodes.values()])
    assert "foundryx:workflow:data" not in dumped



def test_every_workflow_data_key_carries_a_bounded_ttl(fake_redis, monkeypatch):
    """Review should-fix: platform Redis must not grow without bound. A blank
    TTL gets the default budget, keys born from increment / push get it too,
    and an explicit TTL above the maximum is rejected at publish AND run."""
    from app.config import settings
    from app.workflow_engine.actions.redis_actions import ActionError, literal_config_issues, physical_key

    monkeypatch.setattr(settings, "workflow_redis_default_ttl_seconds", 600)
    monkeypatch.setattr(settings, "workflow_redis_max_ttl_seconds", 3600)

    _cmd({"operation": "set", "key": "plain", "value": "v"})
    assert 0 < fake_redis.ttl(physical_key(DEFAULT_TENANT_ID, "plain")) <= 600
    _cmd({"operation": "set", "key": "explicit", "value": "v", "ttlSeconds": "120"})
    assert 0 < fake_redis.ttl(physical_key(DEFAULT_TENANT_ID, "explicit")) <= 120
    _cmd({"operation": "increment", "key": "counter", "amount": "2"})
    assert 0 < fake_redis.ttl(physical_key(DEFAULT_TENANT_ID, "counter")) <= 600
    _cmd({"operation": "list_push", "key": "queue", "value": "a"})
    assert 0 < fake_redis.ttl(physical_key(DEFAULT_TENANT_ID, "queue")) <= 600
    # A second push never SHORTENS a budget already running.
    fake_redis.expire(physical_key(DEFAULT_TENANT_ID, "queue"), 50)
    _cmd({"operation": "list_push", "key": "queue", "value": "b"})
    assert fake_redis.ttl(physical_key(DEFAULT_TENANT_ID, "queue")) <= 50

    with pytest.raises(ActionError, match="at most 3600"):
        _cmd({"operation": "set", "key": "toolong", "value": "v", "ttlSeconds": "999999"})
    assert not fake_redis.exists(physical_key(DEFAULT_TENANT_ID, "toolong"))
    issues = literal_config_issues({"operation": "set", "key": "k", "value": "v", "ttlSeconds": "999999"})
    assert issues and "at most 3600" in issues[0]
    assert literal_config_issues({"operation": "set", "key": "k", "value": "v", "ttlSeconds": "3600"}) == []
    # Amount parsing is a strict integer pattern (``--5`` used to slip through).
    assert literal_config_issues({"operation": "increment", "key": "k", "amount": "--5"})
    assert literal_config_issues({"operation": "increment", "key": "k", "amount": "-5"}) == []
    with pytest.raises(ActionError, match="whole number"):
        _cmd({"operation": "increment", "key": "k", "amount": "--5"})
