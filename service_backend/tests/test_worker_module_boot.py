"""Worker processes have no FastAPI lifespan, so module-registered workflow
nodes (omnichannel trigger/actions, plan sprint-4/17) must be booted
explicitly inside the task. Regression for the prod failure
``Node failed: Unknown action "omnichannel.send_message".`` - invisible in
eager dev because runs execute inline in the API process.

Scoped to the omnichannel manifest: the base conftest fixture mounts no
``app_ideation`` schema, so booting ideation's hooks here would leak its
status entity into later tests."""
import os
from pathlib import Path

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


def test_wake_serialized_task_boots_module_nodes_before_draining():
    """The serialized drain executes runs in the worker process too (sprint-4/19
    S2) - it must boot module nodes exactly like run_workflow_task."""
    import inspect

    from app.workflow_engine import worker

    task = worker.wake_serialized_task
    body = inspect.getsource(task.run if hasattr(task, "run") else task)
    assert "_ensure_module_nodes()" in body
    assert body.index("_ensure_module_nodes()") < body.index("drain_serialized_runs(db")


# ── AutoCount source-impl registry on the worker import path (prod hotfix) ──
#
# ``ac_entity_config.source_impl`` factories (`modules/autocount/sources.py`
# `_SOURCES`) are a SEPARATE registry from the workflow node registry above,
# with a separate failure mode: ``sql_db`` registers itself at
# ``sync.py`` module level (``register_sql_db_source()``), so the worker's
# single ``import modules.autocount.sync`` (``app/workflow_engine/worker.py``)
# always picks it up. ``autocount_http`` did NOT - it was registered only
# inside ``register_http_source()``, itself called only from the module
# install hook (``modules/autocount/bootstrap.py``), which runs in the API
# process (``load_modules``) and NEVER in the worker. Every Open API task and
# every pull-gateway snapshot build failed for real on the Celery worker with
# ``UnknownSourceImpl: No AutoCount source implementation registered for
# 'autocount_http'`` - invisible to eager dev/test, which runs everything
# inline in the API process and never exercises the worker's own import
# chain. A subprocess is required: the registry is a plain module-level dict,
# so anything already imported by an earlier test in this same process (e.g.
# a fixture that imports ``modules.autocount.http_source.source`` directly)
# would mask the exact gap that broke prod.


def test_worker_import_alone_registers_every_autocount_source_impl():
    """Simulates the REAL worker boot: a bare `import
    app.workflow_engine.worker` (a fresh Celery process's first line), no
    FastAPI lifespan, no `load_modules()`/install-hook call. Every
    `source_impl` an `ac_entity_config` row can select must resolve after
    that ONE import alone. Fails on the unfixed code with
    `['autocount_read', 'sql_db']` (no `autocount_http`)."""
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.workflow_engine.worker\n"
            "from modules.autocount.sources import _SOURCES\n"
            "print(','.join(sorted(_SOURCES)))\n",
        ],
        cwd=str(Path(__file__).resolve().parent.parent),
        env={
            **os.environ,
            "DATABASE_URL": "sqlite://",
            "CELERY_TASK_ALWAYS_EAGER": "true",
        },
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    registered = result.stdout.strip().split(",")
    assert "autocount_read" in registered, result.stdout
    assert "sql_db" in registered, result.stdout
    assert "autocount_http" in registered, (
        "autocount_http missing from the worker's own import chain - this is "
        f"the prod incident reproduced. stdout={result.stdout!r} "
        f"stderr={result.stderr}"
    )


def test_http_source_module_registers_at_import_time_not_only_via_the_install_hook():
    """Lighter, in-process companion to the subprocess test above, isolating
    the exact fix: `http_source/source.py` must call `register_source` at
    MODULE level (like `sql_source/source.py`'s own pattern), not only
    inside `register_http_source()` (which only the API install hook calls).

    This test's own process already has `autocount_http` registered - the
    conftest template-DB fixture installs the `autocount` module (the REAL
    install-hook path) once per worker process before any test runs - so a
    bare `source_factory('autocount_http')` call would pass for the wrong
    reason regardless of this fix. The registry entry is removed and the
    module is force-reloaded to prove the MODULE'S OWN import re-registers
    it, independent of the install hook ever having run."""
    import importlib

    import modules.autocount.http_source.source as http_source_module
    from modules.autocount.models import SOURCE_IMPL_AUTOCOUNT_HTTP
    from modules.autocount.sources import _SOURCES, source_factory

    _SOURCES.pop(SOURCE_IMPL_AUTOCOUNT_HTTP, None)
    try:
        importlib.reload(http_source_module)
        factory = source_factory(SOURCE_IMPL_AUTOCOUNT_HTTP)
        assert factory is not None
    finally:
        # Restore the module object other already-imported code (e.g.
        # `modules.autocount.bootstrap`) holds a reference to, so later
        # tests in this process see the same registered state they expect.
        importlib.reload(http_source_module)
