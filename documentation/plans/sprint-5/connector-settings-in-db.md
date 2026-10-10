# Claude connector settings in the database (lane SETTINGS-IN-DB-SS)

PR #119. Owner decisions are recorded on the PR (behaviour card Q1-Q5 all (a), then the
environment-ceiling question (a)).

## What changed

The Claude connector module's `CONNECTOR_*` settings can now live in the database and be
edited on **Settings > Claude connector**. The environment still works and stays the
fallback, so existing deployments behave exactly as before until someone saves a value.

| Where | What |
|---|---|
| Products tab | **Add product**, and **Edit** on each card. Both open a full-page form at `/settings/claude-connector/products/[key]` with the tabs Details · Secrets · Advanced. Each value shows its source: *Saved here*, *Environment*, *Default* or *Not set*. |
| Access tab (new) | Public base URL, allowed client IP ranges, allowed redirect URLs, manifest cache, call timeout and call-log retention, plus a *Recent changes* list. |

Saving takes effect on the next request. Nothing is cached, so no restart is needed.

## Rules

- **Per-field precedence.** A non-blank database value wins. Otherwise the environment value applies, but only when the environment assigns that product key to the same tenant. Otherwise the built-in default applies. An environment product edited here keeps falling back field by field.
- **Secrets.**
  - The two shared secrets are encrypted with the core Fernet key (`FERNET_KEY`, `app/secrets.py`).
  - They are write-only: the API and UI only ever show *Set*, *Missing* or *Unreadable*.
  - A blank secret keeps the stored value. *Remove the saved secret* falls back to the environment.
  - Outside development, a secret is refused when no `FERNET_KEY` is set.
- **Operator secrets stay bound.** Once a URL, the connection ID, the issuer or an audience is saved here, the environment's secrets no longer apply. The save asks for both secrets, so a tenant can never send operator-signed traffic elsewhere.
- **Outbound safety.** A database-set API base URL must be a public https URL. The SSRF guard (`app/services/url_guard.py`) re-checks it before every call. Environment URLs stay exempt, so internal targets remain possible through `.env`.
- **The environment is a ceiling, but only for what it sets.**
  - Saved IP ranges must sit inside `CONNECTOR_ALLOWED_CLIENT_CIDRS`.
  - Redirect URLs must be listed in `CONNECTOR_REDIRECT_ALLOWLIST`.
  - Retention must be at or below `CONNECTOR_CALL_LOG_RETENTION_DAYS`.
  - The page shows each limit. If the environment is tightened later, a looser stored value is ignored.
  - When the environment sets nothing, the saved value stands alone.
- **Key ownership.** Product keys are unique across the deployment because the key is the URL. The operator's environment assignment of a key beats another tenant's row with the same key. `new` is reserved.
- **Permissions.**
  - `connector.read` views the settings; the new `connector.settings` edits them.
  - Existing tenants get `connector.settings` through a one-shot sweep onto their system Admin role, when that role holds `connector.manage`.
  - Delete is a typed product-key confirm and is refused (409) while the product has active grants.
- **Audit.** `app_connector.settings_audit` records who changed which fields and when. It stores field names only, never values.
- **Issue #118.** The IP allow-list shows a warning while `client_ip` trusts the first X-Forwarded-For hop. Flip `FORWARDED_FOR_TRUSTED` in `modules/connector/services/client_access.py` when lane SS-118-XFF merges.

## Data

Migration `modules/connector/alembic/versions/0002_connector_settings.py` adds three tables to `app_connector`:

- `product_settings`
- `tenant_settings`
- `settings_audit`

Nothing changes in `public`.

## Acceptance (verified)

| Id | Check | Evidence |
|---|---|---|
| S-01 [BE] | DB-only product resolves without env; live on next request | `test_db_only_product_resolves_without_any_env` |
| S-02 [BE] | Per-field precedence + sources; clearing falls back | `test_db_field_wins_blank_falls_back_to_env` |
| S-03 [BE] | Secrets encrypted at rest, never returned; blank keeps; clear falls back; unreadable fails closed | `test_secrets_*`, `test_unreadable_secret_is_misconfigured_not_500` |
| S-04 [BE] | Tenant isolation; env of another tenant never applies; key squatting loses to env | `test_foreign_tenant_*`, `test_env_*`, `test_operator_env_assignment_beats_a_squatted_db_key` |
| S-05 [BE] | SSRF guard at save and per call | `test_api_base_url_rejects_internal_and_odd_targets`, `test_outbound_call_rechecks_tenant_set_base_url` |
| S-06 [BE] | Env ceiling for CIDRs/redirects/retention; none when env unset | `test_tenant_may_only_narrow_operator_security_settings`, `test_without_environment_limits_the_tenant_value_stands_alone` |
| S-07 [BE] | Perms, audit, sweep, delete guard, per-tenant retention | `test_read_perm_cannot_edit`, `test_changes_are_audited_by_field_name_only`, `test_sweep_*`, `test_delete_*`, `test_retention_is_per_tenant` |
| S-08 [FE] | Products Add/Edit, product form, Access tab, warnings, limits, never-stuck states | vitest in `app/(protected)/settings/claude-connector/components/*.test.tsx` |
| S-09 [E2E] | Real-click pass at 1280 and 375 against Postgres | 21/21 checks, screenshots on the PR |
| S-10 [T] | Migration on Postgres: upgrade from main, fresh DB, rerun | sandbox Postgres 16 |
