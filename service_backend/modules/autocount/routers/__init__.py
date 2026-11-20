"""AutoCount HTTP routers.

Each is router-THIN - HTTP + Pydantic only; all DB work lives in a
service/repository (code-review hard-fail otherwise). Every module route is
gated by ``require_module("autocount")`` (injected by the loader) plus its own
``require_permission``.

  companies  /autocount/companies   register + read AutoCount companies (+ the
                                    per-entity direct-DB ETL task, plan 22)
  sql        /autocount/sql         SQL connections, schema browse, query preview
  sync       /autocount             trigger, review, approve, discard
"""
