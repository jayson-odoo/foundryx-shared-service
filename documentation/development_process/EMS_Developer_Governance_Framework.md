# EMS Development Governance & App Certification Framework

Because the Foundryx EMS is designed as a Platform-as-a-Service (PaaS) with an internal App Store, strict development governance is mandatory. Any future developer (internal hires or third-party agencies) building a custom module MUST adhere to this framework. 

Modules that fail to comply with these rules will be rejected by the system's App Store installer to prevent core system corruption.

---

## 1. Module Architecture & Packaging

To be recognized by the EMS App Store, every module must be completely self-contained. 

* **The Manifest File:** Every module must contain a `manifest.json` file at its root. This defines the `module_name`, `version`, `author`, `required_core_version`, and the entry-point routers (objects of `{ "name", "prefix" }` - the loader dynamic-imports `backend/routers/<name>.py` and mounts it at `prefix` with the per-tenant `require_module` gate injected). It must also declare the **App Store display fields** `title`, `description`, and `icon` - the global `modules` catalog is synced from manifests at bootstrap, and these fields are what tenants see on the storefront card (plan 08).
* **The Bootstrap Contract (certification requirement, plan 08 §4):** every module's `bootstrap.py` MUST export these hooks - the App Store drives the per-tenant lifecycle exclusively through them:
  ```python
  install(engine, db)                         # GLOBAL, idempotent: create schema + tables, sync permissions CSV
  install_tenant(db, tenant_id)               # per-tenant seed (statuses, defaults, ...)
  update_tenant(db, tenant_id, from_version)  # per-tenant data migration/backfill between provisioned versions
  uninstall_tenant(db, tenant_id)             # DELETE the tenant's rows from every module table - NEVER drop schema/tables
  ```
  `uninstall_tenant` is strictly per-tenant: other tenants live in the same module schema, so dropping tables or the schema is an automatic certification failure. Permission GRANTS are the store's concern (granted to the tenant's Admin on install, revoked from all roles on uninstall) - modules must not touch roles.
* **Strict Folder Structure:** Developers cannot scatter files. A module must follow the standard structure:
  ```text
  /my_custom_module
    /frontend (React components)
    /backend
      /routers
      /services
      /repositories
    /alembic (Migrations)
    manifest.json
  ```
* **Zero Global Pollution:** Modules cannot inject code into the core EMS `main.py` or global state managers (like Redux stores outside of their context). They must hook into the system via predefined Event Listeners.

---

## 2. Database Governance (Schema-Isolated Relational Architecture)

Because advanced reporting tools (like Metabase, PowerBI, or Tableau) require rigid, relational database structures, the EMS App Store rejects the pure JSONB metadata approach in favor of a **Schema-Isolated Relational Architecture**.

Third-party developers **are** allowed to use Alembic to create real physical Postgres tables with strong relationships (Foreign Keys), but they must follow strict sandboxing rules:

* **PostgreSQL Schema Isolation:** Apps are forbidden from creating tables in the default `public` schema. If a developer builds a Commercial App, their Alembic script MUST dynamically create a new PostgreSQL schema (e.g., `CREATE SCHEMA app_commercial;`) and build all their tables inside it (e.g., `app_commercial.invoices`).
* **Module-Isolated Migrations:** As defined in the architecture, developers MUST use module-specific Alembic version tables. The commercial app will track its migrations in a table called `alembic_version_commercial` within its isolated schema.
* **No Modifying Core Tables:** A module is strictly prohibited from running `DROP`, `ALTER`, or `TRUNCATE` commands on Core `public` tables (e.g., `public.Users`, `public.Projects`). 
* **Extension via Foreign Keys:** If the Commercial App needs to link an invoice to a project, it simply creates a Foreign Key in `app_commercial.invoices` pointing to `public.Projects(id)`. 
* **Migration Discipline - add-first-delete-later (plan 08 D5, BINDING):** module schemas are SHARED by every tenant on the deployment while tenants may sit at different *provisioned* versions (`tenant_modules.installed_version` gates features - code is never pinned per tenant). Therefore, within a major version, migrations MUST be additive (new tables / new nullable columns are free). Renames, deletions, and type changes are forbidden in one step: add the replacement column first, dual-write, and drop the old one only when no tenant's active version still reads it (expand-contract). A truly breaking rewrite ships as a NEW module listing - the rare escape hatch. The certifier rejects violating migrations.

*Why this is perfect for reporting:* By keeping app tables in isolated schemas, the core database remains uncluttered. However, your reporting analysts can easily write standard SQL `JOIN` statements across schemas (e.g., `SELECT * FROM app_commercial.invoices JOIN public.projects ON ...`) without having to parse complex JSONB structures.

---

## 3. Frontend & UI Guidelines (Metronic Compliance)

To ensure the EMS dashboard remains visually cohesive and premium, developers must follow UI governance.

* **No Global CSS:** Modules are strictly forbidden from injecting `<style>` tags or global `.css` files that could override the core system layout.
* **Metronic Utilities:** All styling must utilize the core Metronic utility classes already loaded by the platform.
* **Component Sandboxing:** Custom React components must be isolated. If an app crashes on the frontend, it should be caught by an Error Boundary specific to that app, ensuring the rest of the EMS dashboard remains usable.

---

## 4. Backend Engine Usage

Developers must leverage the EMS Core Engines rather than building redundant logic.

* **Workflow & Rule Engines:** If an app needs to trigger an action (like sending an email after a specific event), it must register a Trigger in the `Workflow_Nodes` table. It cannot write custom background cron jobs using external libraries.
* **Unified Auth:** Modules cannot implement their own JWT or session logic. They must use the core FastAPI `Depends(get_current_user)` dependency injection.

---

## 5. The Certification Process (Automated CI/CD)

Before an app can be packaged as a `.zip` and uploaded to the EMS App Store, it must pass the **Certification Pipeline**.

1. **Static Analysis (Linter):** A custom linter scans the module's code. If it finds raw SQL queries in the `/routers` folder, or global CSS files, it immediately fails the build.
2. **AI Code Review:** The **Reviewer Agent** reads the module's code specifically looking for architectural violations (like trying to alter a core database table).
3. **Automated E2E Testing:** Playwright runs inside a sandbox environment to ensure installing the module doesn't break the core EMS login or project creation flow.
4. **App Store Approval:** Only after passing these automated checks is the module given a cryptographic "Certified" signature, allowing the EMS App Store to accept and activate it safely.
