"""Module schema drift guard (issue #89, prod 26 Sep 2026).

The last line of defence against "module code ahead of its schema": the
26 Sep deploy served ideation code at migration 0010 against a database at
0007 (``column ideas.title does not exist`` on every save). Bootstrap now
aborts on a module migration failure, but a path that skips bootstrap (a
hand-started container, ``SKIP_MIGRATIONS=1``, an operator killing a stuck
retry loop) must still never serve traffic on a stale schema. So every API
process (``app.main`` lifespan) and every Celery worker/beat process checks,
at start, each module under per-module Alembic:

- DB version == code head        -> start.
- DB version is a KNOWN revision
  of this code, but not the head -> the DB is BEHIND: refuse to start with
                                    the named ``ModuleSchemaDrift``.
- DB version is UNKNOWN to this
  code's script directory        -> the DB is AHEAD (normal during blue/green:
                                    the new colour migrates first while the old
                                    colour, or its workers, may still restart)
                                    or carries a foreign revision: log a
                                    WARNING and start. Refusing here would take
                                    the still-serving old colour down mid-deploy.
- no version table               -> the module was never installed in this
                                    database: bootstrap's job, not a drift.
- no ``alembic/`` dir            -> legacy create_all module: ignored.

No-op on a non-Postgres engine (the SQLite test suite; module Alembic is
Postgres-only). ``SKIP_MIGRATIONS=1`` skips bootstrap, NOT this guard: the
bypass exists for a hand-run expand-contract rollout, where the operator
migrates first - a behind schema is exactly the state it must never serve.
A check that cannot read the database raises too (fail closed): an API or
worker that cannot reach its database cannot do useful work anyway, and the
restart policy retries it.
"""
import logging
from typing import Optional, Set, Tuple

from sqlalchemy import inspect, text

from app.module_loader import MODULES_DIR, discover_manifests

logger = logging.getLogger(__name__)


# The API lifespan and Celery worker/beat start run the guard only while this
# is True. Deliberately a module attribute, NOT an env-driven setting: the test
# suite (conftest) switches it off because its DATABASE_URL is unreachable,
# and production gets no environment switch that could disable the guard.
STARTUP_GUARD_ENABLED = True


def run_startup_guard(engine) -> None:
    """The process-start entry point (API lifespan, Celery worker/beat)."""
    if STARTUP_GUARD_ENABLED:
        check_module_schema_drift(engine)


class ModuleSchemaDrift(RuntimeError):
    """An installed module's database schema is behind its code's alembic
    head. Carries ``module_name``, ``code_head`` and ``db_version``."""

    def __init__(self, module_name: str, code_head: str, db_version: str):
        self.module_name = module_name
        self.code_head = code_head
        self.db_version = db_version
        super().__init__(
            f"ModuleSchemaDrift: module '{module_name}' database schema is at "
            f"{db_version} but this code needs {code_head}. Refusing to start: "
            f"serving module code ahead of its schema 500s every request that "
            f"touches the new columns. Run `python -m scripts.bootstrap_db` "
            f"(see DEPLOY.md, 'Module migration lock timeout')."
        )


def _alembic_dir(manifest: dict):
    d = MODULES_DIR / manifest["_dir"] / "alembic"
    return d if d.is_dir() else None


def _script_directory(manifest: dict):
    d = _alembic_dir(manifest)
    if d is None:
        return None
    from alembic.script import ScriptDirectory

    return ScriptDirectory(str(d))


def _split(version: Optional[str]) -> Set[str]:
    return {v for v in (version or "").split(",") if v}


def module_code_head(manifest: dict) -> Optional[str]:
    """The module's alembic head revision from its on-disk ``alembic/versions``
    (several heads are comma-joined, sorted), or ``None`` when the module has
    no ``alembic/`` dir (legacy create_all module)."""
    script = _script_directory(manifest)
    if script is None:
        return None
    heads = sorted(script.get_heads())
    return ",".join(heads) if heads else None


def module_code_revisions(manifest: dict) -> Set[str]:
    """Every revision id this code's ``alembic/versions`` knows (empty set when
    the module has no ``alembic/`` dir). A DB version outside this set is
    ahead of (or foreign to) this code."""
    script = _script_directory(manifest)
    if script is None:
        return set()
    return {rev.revision for rev in script.walk_revisions()}


def module_db_version(engine, manifest: dict) -> Optional[str]:
    """The module's stamped version from ``<schema>.alembic_version_<name>``
    (several rows are comma-joined, sorted), or ``None`` when the table does
    not exist (module never installed in this database)."""
    name = manifest["module_name"]
    schema = manifest.get("schema")
    table = manifest.get("alembic_version_table") or f"alembic_version_{name}"
    if not inspect(engine).has_table(table, schema=schema):
        return None
    qualified = f'"{schema}"."{table}"' if schema else f'"{table}"'
    with engine.connect() as conn:
        rows = conn.execute(text(f"SELECT version_num FROM {qualified}")).scalars().all()
    versions = sorted(v for v in rows if v)
    return ",".join(versions) if versions else None


def _classify(code_head: str, db_version: str, known: Set[str]) -> Tuple[str, Set[str]]:
    """``(verdict, unknown)`` where verdict is ``current`` | ``ahead`` | ``behind``."""
    heads, db = _split(code_head), _split(db_version)
    if db == heads:
        return "current", set()
    unknown = db - known
    if unknown:
        return "ahead", unknown
    return "behind", set()


def check_module_schema_drift(engine) -> None:
    """Raise ``ModuleSchemaDrift`` for the first installed module whose
    database is BEHIND its code; warn (and allow) when it is ahead/unknown.
    No-op on a non-Postgres engine."""
    if getattr(getattr(engine, "dialect", None), "name", None) != "postgresql":
        return
    for manifest in discover_manifests():
        name = manifest["module_name"]
        code_head = module_code_head(manifest)
        if code_head is None:
            continue  # legacy create_all module - no alembic history to compare
        db_version = module_db_version(engine, manifest)
        if db_version is None:
            continue  # never installed in this database - bootstrap's job
        verdict, unknown = _classify(code_head, db_version, module_code_revisions(manifest))
        if verdict == "behind":
            logger.critical(
                "Module '%s' schema drift: database at %s, code head %s - refusing to start",
                name, db_version, code_head,
            )
            raise ModuleSchemaDrift(name, code_head, db_version)
        if verdict == "ahead":
            logger.warning(
                "Module '%s' database is at %s, which this code does not know "
                "(code head %s; unknown %s). Assuming a newer colour already "
                "migrated it (blue/green) and starting anyway.",
                name, db_version, code_head, ",".join(sorted(unknown)),
            )


_CELERY_GUARD_INSTALLED = False


def install_celery_drift_guard() -> None:
    """Run the guard when a Celery worker or beat process starts (not when
    the API merely imports a worker module to enqueue tasks). Idempotent.

    - Fail CLOSED: Celery's signal dispatch swallows ``Exception`` from a
      handler, so ANY failure (a drift, or a guard that could not read the
      database) becomes a logged ``SystemExit(1)``, which it does not
      swallow: the container exits and the deploy's worker gate sees it.
    - No inherited sockets: ``worker_init`` / ``beat_init`` fire in the
      PARENT, before the prefork pool forks. A pooled connection left behind
      would be inherited by every child (one psycopg2 socket shared across
      processes: interleaved protocol, one child reading another's rows), so
      the app engine's pool is disposed after the check, whatever happened.
    """
    global _CELERY_GUARD_INSTALLED
    if _CELERY_GUARD_INSTALLED:
        return
    from celery.signals import beat_init, worker_init

    def _guard(**_kwargs) -> None:
        from app.database import engine

        try:
            run_startup_guard(engine)
        except ModuleSchemaDrift as exc:
            logger.critical("%s", exc)
            raise SystemExit(1) from exc
        except Exception as exc:  # noqa: BLE001 - fail closed, see docstring
            logger.critical(
                "module schema drift guard could not run (%s: %s); refusing to "
                "start this Celery process (fail closed)", type(exc).__name__, exc,
            )
            raise SystemExit(1) from exc
        finally:
            engine.dispose()

    worker_init.connect(_guard, weak=False)
    beat_init.connect(_guard, weak=False)
    _CELERY_GUARD_INSTALLED = True
