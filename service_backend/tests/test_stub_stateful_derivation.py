"""The dev stub LLM produces evidence-backed stateful patches deterministically
(plan sprint-4/19 S5) so the seeded progress-update proof runs with no key."""
import json

from app.ai.stub import stub_provider

PARAMS = [
    {"key": "task", "type": "string", "required": True, "stateful": True},
    {"key": "status", "type": "enum", "enumValues": ["in_progress", "blocked", "completed"], "required": True, "stateful": True},
    {"key": "blocker", "type": "string", "required": False, "stateful": True},
    {"key": "decision", "type": "enum", "enumValues": ["ready", "needs_clarification"], "required": True},
    {"key": "reply", "type": "string", "required": True},
]
SCHEMA = {"type": "object", "properties": {"outputs": {}, "statePatches": {}, "pendingField": {}}}


def _call(message, accepted=None, pending=None):
    payload = {
        "currentMessage": message,
        "acceptedState": accepted or {},
        "outputParameters": PARAMS,
        "pendingClarification": pending,
    }
    return stub_provider.complete({}, {}, model="stub", system="", messages=[{"role": "user", "content": json.dumps(payload)}], output_schema=SCHEMA).structured


def test_opening_message_names_the_task_and_asks_for_status():
    out = _call("Launch landing page")
    assert out["statePatches"]["task"] == {"operation": "set", "value": "Launch landing page", "evidence": "Launch landing page"}
    assert out["statePatches"]["status"] == {"operation": "no_change"}
    assert out["outputs"]["decision"] == "needs_clarification"
    assert out["outputs"]["reply"] == "What is the status?"
    assert out["pendingField"] == "status"


def test_short_answer_resolves_pending_enum_and_blocked_asks_for_blocker():
    out = _call("blocked", accepted={"task": "Launch landing page"}, pending={"question": "What is the status?", "field": "status"})
    assert out["statePatches"]["status"] == {"operation": "set", "value": "blocked", "evidence": "blocked"}
    assert out["statePatches"]["task"] == {"operation": "no_change"}
    assert out["pendingField"] == "blocker" and out["outputs"]["decision"] == "needs_clarification"


def test_pending_text_field_takes_the_whole_short_message_and_becomes_ready():
    out = _call(
        "Waiting for finance approval",
        accepted={"task": "Launch landing page", "status": "blocked"},
        pending={"question": "What is the blocker?", "field": "blocker"},
    )
    assert out["statePatches"]["blocker"]["operation"] == "set"
    assert out["statePatches"]["blocker"]["value"] == "Waiting for finance approval"
    assert out["outputs"]["decision"] == "ready" and out["pendingField"] is None
    assert out["outputs"]["reply"].startswith("Recorded:")


def test_correction_changes_only_the_named_field():
    out = _call("It is completed now", accepted={"task": "Launch landing page", "status": "blocked", "blocker": "finance"})
    assert out["statePatches"]["status"] == {"operation": "set", "value": "completed", "evidence": "completed"}
    assert out["statePatches"]["task"] == {"operation": "no_change"}
    assert out["statePatches"]["blocker"] == {"operation": "no_change"}
    assert out["outputs"]["decision"] == "ready"


def test_evidence_is_the_exact_message_slice_for_spaced_enum_values():
    out = _call("we are In Progress on it", accepted={"task": "x"})
    assert out["statePatches"]["status"] == {"operation": "set", "value": "in_progress", "evidence": "In Progress"}
