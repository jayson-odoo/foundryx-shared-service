"""Configuration settings for the FastAPI application."""
from typing import List, Union

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables (.env)."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Database
    database_url: str

    # JWT Authentication (shared secret: FastAPI issues, FastAPI verifies)
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24  # 24h, matches NextAuth maxAge

    # Long-session expiry when the user checks "Remember me" (plan 10 D4).
    # The backend JWT exp is the real session boundary either way.
    remember_me_expire_minutes: int = 43200  # 30d

    # ── Auth hardening (plan 10) ─────────────────────────────────────────────
    # Single-use token TTLs (per-tenant control = BL-039).
    reset_token_ttl_minutes: int = 60
    invite_token_ttl_minutes: int = 10080  # 7d
    # Change-email ceremony (plan sprint-2/04) - ONE window for the whole
    # request (old-side approve AND new-side verify share it).
    email_change_token_ttl_minutes: int = 60
    # Public self-signup kill-switch (D3) - BL-032 re-enables with real tenant
    # provisioning. While false the endpoint 404s.
    signup_enabled: bool = False
    # Honor X-Forwarded-For (first hop) only when deployed behind the known
    # proxy - false for direct uvicorn in dev, or attackers mint fresh
    # counters per spoofed header.
    trust_proxy_headers: bool = False
    # Dual throttle policy (D6): email = temp lock (never permanent - a hard
    # lockout is an attacker DoS on victims); IP = window throttle.
    throttle_email_max_fails: int = 5
    throttle_email_window_minutes: int = 15
    throttle_email_lock_minutes: int = 15
    throttle_ip_max_fails: int = 20
    throttle_ip_window_minutes: int = 15
    # Public-form submissions per IP (plan sprint-3/02 D12). Higher ceiling than
    # login (legit event registration is bursty) but still spam-bounded.
    throttle_form_public_max_fails: int = 30
    throttle_form_public_window_minutes: int = 15
    # Public document-share access per IP (plan sprint-3/05 D6) - own bucket for
    # failed unlock attempts + anonymous uploads.
    throttle_doc_share_max_fails: int = 30
    throttle_doc_share_window_minutes: int = 15
    # Profile Portal auth per IP (plan sprint-4/06 slice 0a, AC-06-16) - own
    # bucket so portal login/OTP/forgot/set-password spam never locks the staff
    # login bucket. Window-throttle like IP (no permanent lock).
    throttle_portal_max_fails: int = 20
    throttle_portal_window_minutes: int = 15
    # Omnichannel embed session exchange per IP (plan sprint-4/11H, AC-11H-08) -
    # own bucket so assertion-exchange spam never locks the staff login bucket.
    # Window-throttle like IP (no permanent lock).
    throttle_embed_max_fails: int = 30
    throttle_embed_window_minutes: int = 15
    # Profile Portal email one-time-code TTL (short - emailed login fallback).
    profile_otp_ttl_minutes: int = 10
    # Form upload caps (D12). Per-file hard ceiling (DoS guard - capped reads
    # never buffer beyond this) + per-submission total. Field-level maxSizeMb
    # (author setting) is enforced under this ceiling.
    form_upload_max_file_mb: float = 10
    form_upload_max_total_mb: float = 25

    # API Server
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # Frontend origin - used to build invite / set-password / reset links.
    frontend_url: str = "http://localhost:3001"

    # CORS - Next.js auto-bumps ports (3000 -> 3001 ...), cover a few.
    cors_origins: str = (
        "http://localhost:3000,http://localhost:3001,http://localhost:3002"
    )
    # Tenants live on subdomains (plan 07 §6) - allow <slug>.localhost in dev
    # and <slug>.<prod-domain> in prod (override in env).
    cors_origin_regex: str = r"http://[a-z0-9-]+\.localhost:300[0-2]"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: Union[str, List[str]]) -> str:
        if isinstance(v, list):
            return ",".join(v)
        return v

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Environment
    environment: str = "development"
    debug: bool = False

    # ── Integration core (plan 09) ──────────────────────────────────────────
    # Core Fernet key for encrypting connection credentials at rest
    # (app/secrets.py). Ephemeral per-process key when unset (dev only - set a
    # stable FERNET_KEY in prod or stored credentials die on restart).
    fernet_key: str = ""

    # Platform-default SMTP - seeded into the PLATFORM tenant's `connections`
    # row at bootstrap (zero-touch on-prem). Unset = no row = dev-log fallback.
    platform_smtp_host: str = ""
    platform_smtp_port: int = 587
    platform_smtp_security: str = "starttls"  # starttls | ssl | none
    platform_smtp_username: str = ""
    platform_smtp_password: str = ""
    platform_smtp_from_email: str = ""
    platform_smtp_from_name: str = "Foundryx EMS"

    # Email outbox (plan 09 §5) - dispatcher cadence + retention housekeeping.
    # `email_dispatcher_enabled` is the explicit kill-switch (tests/one-off
    # scripts set it False) - never sniff the runtime for test frameworks.
    email_dispatcher_enabled: bool = True
    email_outbox_retention_days: int = 90
    email_dispatch_interval_seconds: float = 2.0
    email_send_timeout_seconds: int = 10

    # Workflow run retention (plan sprint-2/10 D4) - the scheduler minute-tick
    # prunes workflow_runs (+ cascade workflow_run_nodes) older than this window
    # so run history can't grow unbounded. Mirrors the email-outbox prune.
    workflow_run_retention_days: int = 30
    # Keyed workflow serialization. Redis leases are renewed while a run is
    # active; the beat backstop wakes durable Pending scopes older than the
    # recovery age without changing their state.
    workflow_serialized_lease_seconds: int = 120
    workflow_serialized_recovery_age_seconds: int = 60
    # Workflow Redis action (S3): every workflow-data key carries a TTL so a
    # tenant's workflows can never grow platform Redis without bound. A blank
    # TTL on `set` (and keys created by increment / list push) gets the
    # default; an explicit TTL above the maximum is rejected at publish/run.
    workflow_redis_default_ttl_seconds: int = 7 * 24 * 3600
    workflow_redis_max_ttl_seconds: int = 30 * 24 * 3600
    # External Code runner (sprint-4/19 S4, D20). Unset = the Code action is
    # unavailable (editor warning, publish blocked). Builder Python NEVER runs
    # in this process - see code_runner/ and app/workflow_engine/code_runner.py.
    code_runner_url: str = ""
    code_runner_token: str = ""
    code_runner_timeout_seconds: float = 15.0

    # ── Import engine (plan sprint-3/09, F8) ────────────────────────────────
    # Global per-tenant cap defaults (import_settings row overrides). Enforced
    # fail-fast at upload. Heavy import files (source + error report) are pruned
    # after this global window; the job row + counts are kept forever.
    import_max_rows: int = 10_000
    import_max_file_mb: int = 10
    import_file_retention_days: int = 30

    # ── Background jobs (plan sprint-4/10) ──────────────────────────────────
    # Centralized background_jobs retention - the beat housekeeping pass prunes
    # TERMINAL jobs (done/failed/aborted) older than this window; running,
    # pending and needs_review jobs are never pruned.
    background_job_retention_days: int = 30

    # ── Platform LLM default (Phase B-i slice 1) ───────────────────────────
    # Env-seeds the PLATFORM tenant's LLM connection, exactly like
    # PLATFORM_SMTP_* / PLATFORM_STORAGE_*: the platform row is the deployment
    # default a tenant without its own key falls back to (Bi-D18).
    #
    # This is a BOOTSTRAP CONVENIENCE ONLY. It is not an alternative runtime
    # credential path - resolution always reads `connections.credentials_json`
    # (Fernet, write-only). Keys entered through the UI behave identically.
    #
    # `GRILL_API_KEY` is accepted as a fallback alias so an existing .env keeps
    # working unchanged; the canonical name is PLATFORM_LLM_API_KEY, because
    # `app/ai/` is core and will serve workflows/forms/omnichannel too, not
    # just grilling.
    platform_llm_provider: str = "gemini"
    platform_llm_model: str = "gemini-2.5-flash"
    platform_llm_api_key: str = ""
    grill_api_key: str = ""  # deprecated alias for platform_llm_api_key

    @property
    def resolved_platform_llm_api_key(self) -> str:
        """Canonical name wins; the legacy alias is the fallback."""
        return (self.platform_llm_api_key or self.grill_api_key or "").strip()

    # ── Core AI subsystem (Phase B-i slice 1, AC-BI-10) ────────────────────
    # Trace retention, swept by the beat task. `ok` traces are noise once the
    # feature works, so they go early; `error`/`flagged` traces are the reason
    # traces exist (attributing a bad result to a prompt version) and keep a
    # deliberately longer window.
    ai_trace_retention_days: int = 14
    ai_trace_error_retention_days: int = 90

    # ── Developer Logs / Integration Activity (plan sprint-4/12) ────────────
    # Global default retention for integration_activity rows (a per-tenant
    # integration_log_settings.retention_days NULL falls back to this). The beat
    # pruner deletes rows older than the effective window per tenant.
    integration_activity_retention_days: int = 30
    # Volume guard (AC-DLC-26) - a lightweight per-process cap on activity writes
    # so a burst degrades to dropping rows (with a logged counter) rather than
    # hammering the DB or blocking. Async/buffered writer = the scale path
    # (backlog). Set generously; 0 disables the guard.
    integration_activity_max_writes_per_second: int = 500

    # ── Omnichannel module (WhatsApp BSP) ───────────────────────────────────
    # Meta app (Foundryx = Tech Provider). Embedded Signup exchanges the code
    # against this one app. Empty in dev until the Meta app is configured.
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_graph_version: str = "v19.0"
    meta_es_config_id: str = ""
    # Fernet key for encrypting channel credentials at rest. A throwaway dev
    # key is generated per-process if unset (NEVER rely on that in prod - set
    # OMNICHANNEL_FERNET_KEY so encrypted credentials survive a restart).
    omnichannel_fernet_key: str = ""

    # ── Omnichannel message processing (plan 05 Phase B) ───────────────────
    # Redis = Celery broker + WS pub/sub fan-out. Local dev = native
    # redis-server (brew install redis), same no-Docker stance as Postgres.
    redis_url: str = "redis://localhost:6379/0"
    # Celery eager mode runs tasks inline (tests; also a no-worker dev escape
    # hatch - real deploys run a worker process and leave this false).
    celery_task_always_eager: bool = False
    # Webhook callback base (the public URL Meta calls; ngrok etc. in dev).
    public_base_url: str = "http://localhost:8001"
    # Signed media URLs on the public gateway (respond.io parity): the returned
    # mediaUrl is an ABSOLUTE, HMAC-signed, time-limited link that opens in a raw
    # browser click (no Authorization header). TTL below (seconds).
    media_signed_url_ttl_seconds: int = 3600
    # Meta webhook verify-token for the GET handshake (set the same value in
    # the Meta app's webhook config).
    meta_webhook_verify_token: str = "foundryx-omnichannel-verify"
    # Media storage (plan sprint-2/06 D1/D10): backend selection is DATA -
    # tenant storage connection → platform connection → local disk. The old
    # STORAGE_BACKEND env is retired; media_root remains for the local adapter.
    media_root: str = "./media"
    # Deployment-default storage connection, env-seeded onto the PLATFORM
    # tenant at bootstrap (mirrors PLATFORM_SMTP_*). provider: "s3" | "r2";
    # unset = no row = local-disk dev fallback.
    platform_storage_provider: str = ""
    platform_storage_bucket: str = ""
    platform_storage_region: str = ""            # s3 only
    platform_storage_account_id: str = ""        # r2 only (endpoint derived)
    platform_storage_endpoint_url: str = ""      # s3 only, MinIO/Wasabi
    platform_storage_access_key_id: str = ""
    platform_storage_secret_access_key: str = ""
    platform_storage_cdn_base_url: str = ""

    # ── Meetings bot fleet (sprint-5 S2) ───────────────────────────────────
    # The image one bot container runs. Empty = the pilot image built locally
    # from modules/meetings/bot; a deploy pins a published tag here.
    meetings_bot_image: str = ""

    # ── Meetings STT (sprint-5 S3) ───────────────────────────────────────────
    # Platform setting, not per-tenant (R5) - one pilot host runs one model.
    # "deepgram" is a recognised NAME with no driver until the first real mlx
    # outage or the prod move names the trigger (M12) - get_provider() fails
    # loudly rather than silently falling back to mlx_local.
    meetings_stt_provider: str = "mlx_local"
    # The dedicated STT venv's python (built by scripts/setup_stt_venv.sh) -
    # NOT the backend's own venv; mlx-whisper needs its own deps on Metal.
    meetings_stt_python: str = "~/foundryx-stt/venv/bin/python"
    # Non-turbo (S3 code-switch fix, R3 amended, 2026-09-01): under the
    # chunked per-chunk detection eval, the turbo model missed the Chinese
    # chunk entirely (detected en) and produced worse code-switch output;
    # the non-turbo model correctly detected zh 0.565 / ms 0.523 on the same
    # chunks. Detection cadence (once vs per-chunk) is the RUNNER's property,
    # not the model's - this setting is only about which model transcribes.
    meetings_stt_model: str = "mlx-community/whisper-large-v3-mlx"
    meetings_stt_timeout_s: int = 3600
    # Chunk length (seconds) the runner segments audio into before detecting
    # language PER CHUNK - what actually fixes code-switched meetings.
    meetings_stt_chunk_s: int = 30
    # Allowlist the per-chunk language detector is constrained to. A quiet or
    # silent chunk misdetects as es/pt/etc without this; the pilot's meetings
    # are only ever en/ms/zh.
    meetings_stt_languages: str = "en,ms,zh"
    # A fixed absolute path, not `tempfile.gettempdir()` - the flock (R1) that
    # serializes transcription only works if every process opens the SAME
    # file; TMPDIR differs per-user/per-shell and is not guaranteed stable.
    meetings_stt_lock_path: str = "/tmp/foundryx-meetings-stt.lock"

    # ── Payment gateways (sprint-4/07 Cluster F slice 3) ───────────────────
    # Webhook anti-replay: reject events whose timestamp is older than this
    # tolerance window (seconds). Stripe's own SDK uses 300s; mirror it.
    payment_webhook_tolerance_seconds: int = 300
    # Abandoned-checkout reaper: a Pending gateway payment with no webhook older
    # than this is swept to Expired (frees the buyer to re-pay, AC-07-33).
    payment_checkout_ttl_minutes: int = 60


settings = Settings()
