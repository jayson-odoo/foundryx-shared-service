"""Worker processes have no FastAPI lifespan, so module-registered workflow
nodes (omnichannel trigger/actions, plan sprint-4/17) must be booted
explicitly inside the task. Regression for the prod failure
``Node failed: Unknown action "omnichannel.send_message".`` - invisible in
eager dev because runs execute inline in the API process.

Scoped to the omnichannel manifest: the base conftest fixture mounts no
``app_ideation`` schema, so booting ideation's hooks here would leak its
status entity into later tests."""
from app import module_loader
from app.workflow_engine import registry



def test_boot_module_hooks_registers_module_workflow_nodes(monkeypatch):
    real_discover = module_loader.discover_manifests
    monkeypatch.setattr(
        module_loader,
        "discover_manifests",
        lambda *a, **k: [m for m in real_discover(*a, **k) if m["module_name"] == "omnichannel"],
    )
    # Snapshot AFTER core init - ai_agent.run registers at its module import
    # (cached), so an empty pre-core snapshot restored later would lose it.
    registry._ensure_core()
    saved_actions = dict(registry._ACTIONS)
    saved_triggers = dict(registry._TRIGGERS)
    try:
        # Simulate a fresh worker process: core-only registry, no load_modules().
        for key in list(registry._ACTIONS):
            if key.startswith("omnichannel."):
                del registry._ACTIONS[key]
        for key in list(registry._TRIGGERS):
            if key.startswith("omnichannel."):
                del registry._TRIGGERS[key]
        assert registry.get_action("omnichannel.send_message") is None

        module_loader.boot_module_hooks()

        assert registry.get_action("omnichannel.send_message") is not None
        assert registry.get_action("omnichannel.get_contact") is not None
        assert registry.get_trigger("omnichannel.message_received") is not None
        assert registry.get_action("ai_agent.run") is not None  # core stays
    finally:
        registry._ACTIONS.clear()
        registry._ACTIONS.update(saved_actions)
        registry._TRIGGERS.clear()
        registry._TRIGGERS.update(saved_triggers)


def test_run_workflow_task_boots_module_nodes_before_executing(monkeypatch):
    """The task body (worker-only path - every caller uses .delay) must boot
    module nodes BEFORE the executor resolves actions."""
    from app.workflow_engine import worker

    calls = []
    monkeypatch.setattr(worker, "_ensure_module_nodes", lambda: calls.append("boot"))
    import inspect

    body = inspect.getsource(worker.run_workflow_task.run if hasattr(worker.run_workflow_task, "run") else worker.run_workflow_task)
    assert "_ensure_module_nodes()" in body
    assert body.index("_ensure_module_nodes()") < body.index("run_workflow(db, run_id)")
