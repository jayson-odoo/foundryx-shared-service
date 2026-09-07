"""FastAPI application factory and router wiring."""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import (
    ai,
    app_store,
    auth,
    avatars,
    branding,
    catalog,
    documents,
    emails,
    forms,
    health,
    impersonation,
    imports,
    integration_logs,
    integrations,
    jobs,
    me,
    permissions,
    platform_tenant_branding,
    platform_tenant_modules,
    platform_tenants,
    numbering,
    pending_actions,
    reviews,
    roles,
    rules,
    statuses,
    teams,
    templates,
    terminology,
    users,
    workflows,
)
from app.config import settings
from app.module_loader import load_modules
from app.services.email_dispatcher import start_dispatcher, stop_dispatcher


class _SweepDisabled(Exception):
    """``background_job_orphan_sweep_on_startup`` is off - skip, silently."""


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Derived / computed status (sprint-4/03) - register the re-eval subscriber
    # on the domain-event bus (idempotent). Child/owner changes auto-advance
    # records along their AUTO edges.
    from app.status_engine.derived import install_derived_status

    install_derived_status()
    # Storage-key location registry (sprint-4/10) - register core scalar/JSON
    # locations so a storage migration finds every asset (idempotent; modules
    # register their own via register_module_boot).
    from app.storage_migration.core_locations import ensure_core_locations
    from app.storage_migration.service import register_storage_migration_handler

    ensure_core_locations()
    # Storage migration is the first background-job type (sprint-4/10 Slice 2).
    register_storage_migration_handler()
    # Deferred actions - the grace-window engine (sprint-4/23, T5). Idempotent;
    # module-provided deferred actions register at their own boot hook.
    from app.deferred_actions.handlers import register_deferred_actions

    register_deferred_actions()
    # Teams capability seam (plan 28 S1, D-A8-3) - idempotent; must also run on
    # the module_loader entry points (API router-load + Celery worker boot) so
    # every process that can resolve `team.resolve@1`/etc. has them registered.
    from app.services.team_capabilities import ensure_team_capabilities

    ensure_team_capabilities()
    # Orphaned-job sweep (fix/job-lease-orphan-sweep, prod 2026-09-07): a job
    # left RUNNING by the previous process (deploy drain, crash) is failed
    # here so the scheduler stops skipping its task forever. Guarded like the
    # other startup hooks - a sweep failure must never keep the app down.
    try:
        from app.database import SessionLocal
        from app.jobs.service import sweep_orphaned_jobs

        if not settings.background_job_orphan_sweep_on_startup:
            raise _SweepDisabled()

        _db = SessionLocal()
        try:
            _swept = sweep_orphaned_jobs(_db)
        finally:
            _db.close()
        if _swept:
            logging.getLogger("foundryx.jobs").warning(
                "startup orphan sweep failed %d job(s) left running by a previous process", _swept
            )
    except _SweepDisabled:
        pass
    except Exception:  # noqa: BLE001 - startup must not die on the sweep
        logging.getLogger("foundryx.jobs").exception("startup orphan sweep failed")
    # Email outbox dispatcher (plan 09 §5) - daemon thread, gated by an
    # explicit settings flag (conftest turns it off; tests drive
    # dispatch_pending() directly against their own session).
    if settings.email_dispatcher_enabled:
        start_dispatcher()
    yield
    if settings.email_dispatcher_enabled:
        stop_dispatcher()


app = FastAPI(title="Foundryx Shared Service API", debug=settings.debug, lifespan=lifespan)

# Structured error envelope for the public gateway API (`/api/v1/*`, AC-01-36).
from app.api_errors import install_api_error_handler  # noqa: E402

install_api_error_handler(app)

# Developer Logs / Integration Activity (sprint-4/12) - logs one inbound_api row
# per public-gateway request (path-prefix scoped, failure-isolated, records
# AFTER the response so it never slows/breaks the observed call).
from app.activity_log.middleware import GatewayActivityMiddleware  # noqa: E402

app.add_middleware(GatewayActivityMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    # Tenant subdomains (plan 07 §6) - <slug>.localhost in dev, prod via env.
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Web chat's public visitor API (plan sprint-4/34 / A7b S2, D-A7B-4/AC-WEB-23)
# carries NO cookie and must NEVER advertise `Access-Control-Allow-
# Credentials` - but `CORSMiddleware` (above) stamps that header onto EVERY
# response whose request carries an `Origin` header, UNCONDITIONALLY, before
# it even checks whether the origin matches `cors_origins_list`/
# `cors_origin_regex` (its `simple_response` applies `self.simple_headers` -
# which bakes in `Access-Control-Allow-Credentials: true` whenever
# `allow_credentials=True` - ahead of any origin-match check). Starlette's
# `add_middleware` inserts at index 0 (LIFO), so registering THIS middleware
# AFTER `CORSMiddleware` makes it the OUTER of the two - it runs (and can
# still edit headers) AFTER `CORSMiddleware` has already added its stray
# header, for this one public prefix only. Every other route's CORS
# behaviour is completely unchanged.
#
# Amended 2026-09-09 (BL-SS-183): the same middleware now ANSWERS the CORS
# preflight for this one prefix. A customer website's origin lives on the
# CHANNEL's allowlist, not in this service's own `CORS_ORIGINS` env, so
# `CORSMiddleware` (which knows only the env list) answers the loader's
# preflight with `400 Disallowed CORS origin` and the real POST never
# leaves the browser. Being the OUTER middleware, this handler short-
# circuits before `CORSMiddleware` ever sees the OPTIONS. The echo is not
# allowlist-checked (middleware has no channel context and a preflight
# carries no data): the ACTUAL response still only gets
# `Access-Control-Allow-Origin` when the origin is on the channel's list
# (`cors_headers_for`), and session start still answers an off-list origin
# with the uniform 404 - so an off-list site learns and reads nothing.
_WEBCHAT_PUBLIC_PREFIX = "/public/omnichannel/webchat/"
_WEBCHAT_PREFLIGHT_HEADERS = {
    "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
    "Access-Control-Allow-Headers": "authorization, content-type",
    "Access-Control-Max-Age": "600",
    "Vary": "Origin",
}


@app.middleware("http")
async def _webchat_public_cors(request, call_next):
    on_webchat_public = request.url.path.startswith(_WEBCHAT_PUBLIC_PREFIX)
    if (
        on_webchat_public
        and request.method == "OPTIONS"
        and "access-control-request-method" in request.headers
    ):
        headers = dict(_WEBCHAT_PREFLIGHT_HEADERS)
        origin = request.headers.get("origin")
        if origin:
            headers["Access-Control-Allow-Origin"] = origin
        return Response(status_code=204, headers=headers)
    response = await call_next(request)
    if on_webchat_public:
        if "access-control-allow-credentials" in response.headers:
            del response.headers["access-control-allow-credentials"]
    return response

# Frontend NextAuth calls ${BACKEND_API_URL}/auth/login
app.include_router(auth.router, prefix="/auth", tags=["auth"])
app.include_router(users.router, prefix="/users", tags=["users"])
app.include_router(roles.router, prefix="/roles", tags=["roles"])
# Teams (plan 28, roadmap A8) - core grouping of tenant users, next to roles.
app.include_router(teams.router, prefix="/teams", tags=["teams"])
app.include_router(permissions.router, prefix="/permissions", tags=["permissions"])
app.include_router(impersonation.router, prefix="/impersonation", tags=["impersonation"])
app.include_router(me.router, prefix="/me", tags=["me"])
# App Store (plan 08): tenant-side storefront + operator override.
app.include_router(app_store.router, prefix="/app-store", tags=["app-store"])
# Integration core (plan 09): connections registry + guided setup.
app.include_router(integrations.router, prefix="/integrations", tags=["integrations"])
# Centralized background jobs + storage migration (sprint-4/10). No prefix - the
# router owns its own paths (/jobs, /storage/migrations).
app.include_router(jobs.router, tags=["jobs"])
# Public payment-webhook receiver (sprint-4/07 Cluster F slice 3) - no auth.
app.include_router(
    integrations.webhooks_router, prefix="/integrations/webhooks", tags=["integrations"]
)
# Status engine (sprint-2/01): graph CRUD + the entity registry.
app.include_router(statuses.router, prefix="/statuses", tags=["statuses"])
app.include_router(statuses.entities_router, prefix="/status-entities", tags=["statuses"])
# Tenant branding (sprint-2/03): own-tenant editor + pre-auth consumption.
app.include_router(branding.router, prefix="/branding", tags=["branding"])
app.include_router(branding.public_router, prefix="/public/branding", tags=["branding"])
# Avatars render in <img> (no Bearer header) - public like branding assets.
app.include_router(avatars.public_router, prefix="/public/avatars", tags=["avatars"])
# Rule engine (sprint-2/02): fact whitelist + rules observability.
app.include_router(rules.facts_router, prefix="/rule-facts", tags=["rules"])
app.include_router(rules.rules_router, prefix="/rules", tags=["rules"])
# Template engine + email log (plan sprint-2/07).
app.include_router(templates.router, prefix="/templates", tags=["templates"])
app.include_router(emails.router, prefix="/emails", tags=["emails"])
# Workflow engine (plan sprint-2/08): the last core engine.
app.include_router(workflows.router, prefix="/workflows", tags=["workflows"])
# Terminology (plan sprint-3/08, F10): per-tenant entity relabeling. Read is
# authenticated-only (the client-cache source); edits gated terminology.manage.
app.include_router(terminology.router, prefix="/terminology", tags=["terminology"])

# Core AI subsystem (Phase B-i slice 1). Agents + skills ride ai_agents.read/
# .manage; traces ride a SEPARATE ai_traces.read (raw prompts/completions).
# LLM connections need no new permission - they ride integrations.read/.manage.
app.include_router(ai.agents_router, prefix="/ai/agents", tags=["ai"])
app.include_router(ai.skills_router, prefix="/ai/skills", tags=["ai"])
app.include_router(ai.traces_router, prefix="/ai/traces", tags=["ai"])

# Numbering engine (sprint-4/07, Cluster F) - read numbering.read, edit .manage.
app.include_router(numbering.router, prefix="/numbering", tags=["numbering"])
# Import engine (plan sprint-3/09, F8): generic bulk import for opt-in lists.
app.include_router(imports.router, prefix="/imports", tags=["imports"])
# Developer Logs / Integration Activity console (sprint-4/12) - read API.
app.include_router(
    integration_logs.router, prefix="/integration-logs", tags=["integration-logs"]
)
# Form engine (plan sprint-3/01): the 5th core engine - capture + the scoped
# submission status machine (one /submissions router for cross-form reads).
# Generic Review/Approval engine (plan sprint-4/06 Part 2): core, horizontal.
app.include_router(reviews.router, prefix="/reviews", tags=["reviews"])

app.include_router(forms.router, prefix="/forms", tags=["forms"])
app.include_router(forms.submissions_router, prefix="/submissions", tags=["forms"])
# Pre-auth public form fill/submit (subdomain tenant in path, uniform 404).
app.include_router(forms.public_router, prefix="/public/forms", tags=["forms"])
# Document management / the Drive (plan sprint-3/04) - folders/files/versions,
# upload, sandboxed serve, trash, types, settings, async ZIP jobs.
app.include_router(documents.router, prefix="/documents", tags=["documents"])

app.include_router(catalog.products_router, prefix="/products", tags=["catalog"])
app.include_router(catalog.categories_router, prefix="/product-categories", tags=["catalog"])
app.include_router(catalog.settings_router, prefix="/settings", tags=["settings"])
# Pre-auth public share surface (plan sprint-3/05) - token self-identifies the
# tenant; uniform 404; own throttle bucket; honeypot; CSP-sandbox serving.
app.include_router(
    documents.public_router, prefix="/public/documents", tags=["documents"]
)
# Platform Console (operator-only - require_platform_permission, plan 07).
app.include_router(platform_tenants.router, prefix="/platform/tenants", tags=["platform"])
app.include_router(
    platform_tenant_modules.router, prefix="/platform/tenants", tags=["platform"]
)
app.include_router(
    platform_tenant_branding.router, prefix="/platform/tenants", tags=["platform"]
)
app.include_router(health.router, tags=["health"])
# Deferred actions - the grace-window engine (sprint-4/23, T5).
app.include_router(
    pending_actions.router, prefix="/api/v1/pending-actions", tags=["pending-actions"]
)

# Installed App-Store modules (omnichannel, …) hook in via the loader.
load_modules(app)


@app.get("/")
def root() -> dict:
    return {"name": "Foundryx EMS API", "status": "ok"}
