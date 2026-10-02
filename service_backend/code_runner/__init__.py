"""Foundryx Code runner (sprint-4/19 S4).

A SEPARATELY DEPLOYED, stdlib-only service that executes builder-authored
Python for the ``code.run`` workflow action. It is deliberately independent of
the application: no ``app.*`` imports, no database, no Redis, no secrets. The
backend talks to it over HTTP through ``app.workflow_engine.code_runner``.

Layers of defense (none is the sole boundary):

1. ``policy`` - static AST validation (imports, dangerous builtins, dunder
   access, reflection) rejected before anything runs. Applied by the backend
   at publish time AND by the runner before execution.
2. ``sandbox`` - every execution is a FRESH child process (``python -I -S``)
   with an empty environment, ``/`` as cwd, hard ``resource`` limits (address
   space, CPU seconds, file size 0, process count, open files) and a wall-clock
   kill. The child runs ``harness`` with a restricted builtins table.
3. Deployment - the runner container is non-root, read-only, no network egress
   (internal-only compose network), no application env vars.
"""

RUNNER_VERSION = "1.0.0"
