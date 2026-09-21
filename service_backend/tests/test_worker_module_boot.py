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


# ── background-job handler registry on the `worker_jobs` process (part 2) ───
#
# Same bug class as the ``autocount_http`` source-impl gap above, on a
# DIFFERENT dispatch path: ``app/jobs/worker.py``'s ``jobs.run`` task never
# called ``_ensure_module_nodes()``/``boot_module_hooks()`` at all - it
# relied entirely on ``app/workflow_engine/worker.py``'s bottom-of-file
# explicit imports (``app.storage_migration.service``, ``modules.autocount.
# sync``, ``modules.meetings.jobs``), each of which registers its job
# handler(s) at its OWN module level (mirrors ``sql_db``'s pattern). But
# omnichannel's four job handlers (contacts export, broadcast send, report
# export, respond.io migration) register ONLY inside its
# ``register_engine_entities()``, reachable exclusively through
# ``boot_module_hooks()`` - no bare import of any omnichannel module
# registers them.
#
# Before sprint-5/11 S1 (PR #76) this was still a RACE: ``jobs.run`` shared
# the same ``workflow`` worker process as ``workflows.run_workflow``/
# ``wake_serialized_task``, and EITHER of those tasks running first would
# warm ``_ensure_module_nodes()`` as an accidental side effect. Since PR #76
# routes ``jobs.run`` onto the DEDICATED ``worker_jobs`` process (consumes
# ONLY the ``jobs`` queue), no workflow-run task EVER executes there - the
# four omnichannel job types are now PERMANENTLY unknown on that process,
# not a race: every dispatch of one raises ``UnknownJobType``.


def test_run_job_task_boots_module_hooks_before_dispatching():
    """Source-order regression (mirrors the workflow-task tests above):
    `run_job_task` must call `_ensure_module_nodes()` before it does any real
    work, so every module's job handler is registered before dispatch."""
    import inspect

    from app.jobs import worker as jobs_worker

    task = jobs_worker.run_job_task
    body = inspect.getsource(task.run if hasattr(task, "run") else task)
    assert "_ensure_module_nodes()" in body
    assert body.index("_ensure_module_nodes()") < body.index("run_job(db, job_id)")


def test_worker_jobs_process_resolves_every_registered_job_type_before_running_one():
    """Subprocess proof of the `worker_jobs` gap. Two independent measures,
    derived at test time (never a hand-maintained list, so a fifth module's
    job handler cannot drift silently past this test):

    1. A STATIC grep of the source tree (excluding `.venv`/`tests`) for
       `register_job_handler(` CALL sites (excluding the `def` line itself) -
       the ground-truth count of distinct job types the codebase declares,
       independent of any boot path.
    2. A SUBPROCESS that simulates the real `worker_jobs` process: a bare
       `import app.jobs.worker` (what `celery -A app.workflow_engine.worker
       worker -Q jobs` boots - no `workflows.run_workflow` ever runs there
       to warm anything as a side effect), captures the registry BEFORE
       dispatch, then calls `run_job_task` ITSELF directly (the plain
       function, not `.delay()`/Celery - calling a `@celery_app.task`
       synchronously runs its real body) for a job id that does not exist,
       and captures the registry AFTER. Calling the task function directly
       - not manually calling `_ensure_module_nodes()` - is deliberate: a
       test that calls the boot helper itself would pass whether or not
       `run_job_task` actually calls it, which is exactly the assertion
       under test (confirmed: with the fix reverted this variant passed for
       the wrong reason while the source-order test above correctly failed).
       `run_job_task` is expected to raise once it reaches the DB lookup (no
       schema on this bare `sqlite://`) - that happens AFTER the boot call,
       so the exception is swallowed and the registry state is read anyway.

    Asserts the AFTER count matches the static grep count (every declared
    job type resolves via `handler_for` on this process), and that the
    BEFORE set was a strict subset (proving there was a real gap this fix
    closes, not a vacuously-true check)."""
    import json
    import re
    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    call_site_re = re.compile(r"(?<!def )register_job_handler\(")
    static_count = 0
    for py_file in root.rglob("*.py"):
        parts = py_file.relative_to(root).parts
        if parts[0] in (".venv", "tests", "alembic"):
            continue
        text = py_file.read_text(encoding="utf-8", errors="ignore")
        static_count += len(call_site_re.findall(text))
    assert static_count > 0, "the grep pattern itself found nothing - it is broken, not the codebase"

    script = (
        "import json\n"
        "import app.jobs.worker as jobs_worker\n"
        "from app.jobs.registry import list_job_handlers, handler_for\n"
        "before = sorted(d.type for d in list_job_handlers())\n"
        "try:\n"
        "    jobs_worker.run_job_task('drift-test-nonexistent-job-id')\n"
        "except Exception:\n"
        "    pass\n"  # expected: no schema on this bare sqlite:// - the boot call already ran by then
        "after = sorted(d.type for d in list_job_handlers())\n"
        "for job_type in after:\n"
        "    handler_for(job_type)\n"  # raises UnknownJobType if it does not actually resolve
        "print(json.dumps({'before': before, 'after': after}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(root),
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
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    before, after = payload["before"], payload["after"]

    assert len(after) == static_count, (
        f"expected {static_count} job types (from {call_site_re.pattern!r} call "
        f"sites in the source tree) but the worker_jobs process resolved "
        f"{len(after)}: {after}. A module's job handler is registered "
        f"somewhere `_ensure_module_nodes()` never reaches."
    )
    assert set(before) < set(after), (
        "the BEFORE set (a bare `import app.jobs.worker`, no boot helper "
        "called yet) was not a strict subset of AFTER - either the fix is "
        "gone (before == after == the small set) or boot_module_hooks() "
        f"regressed. before={before!r} after={after!r}"
    )
    for expected_type in (
        "omnichannel.contacts_export",
        "omnichannel.broadcast_send",
        "omnichannel.report_export",
        "omnichannel.respondio_migration",
    ):
        assert expected_type in after, (
            f"'{expected_type}' still unresolved on the worker_jobs process - "
            "this is the exact prod gap (UnknownJobType on every dispatch)."
        )
