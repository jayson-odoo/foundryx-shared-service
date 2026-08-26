# Sprint 2 · Plan 07 - Template Engine (email surface)

**Branch:** `sprint-2/07-template-engine`
**Closes/advances:** BL-024 (core template engine - email surface), BL-038 (user-editable email templates), BL-066 (per-tenant email branding adoption). Also ships the **email outbox UI** (Email log - list/detail/retry/cancel, D14). Third of the four-engine foundation; the Workflow engine (BL-025) depends on this plan's `render_email(template, facts)` contract for its SendEmail action.
**Research base:** `documentation/research/template-engine-builder-landscape.md` (OSS lib landscape + EMS competitor analysis - read it; the decisions below cite it).
**Defers (new backlog items):** badge/ticket fixed-canvas designer + PDF, repeater/loop block, draft/versioning, marketing unsubscribe machinery, saved-blocks library. Website builder (CMS, project plan §2.4) = its own future plan; the research doc and this plan's schema philosophy feed it.

---

## Context

The project plan (§1.2.4) calls for a multi-format template engine (email/web/PDF) with a drag-and-drop design tool. Research verdict: **one visual builder cannot serve email + webpage + badge** - output models are irreconcilable (MJML tables vs flow DOM vs mm-precise print canvas), and every successful EMS product (Eventbrite, Cvent, Webex Events…) runs separate purpose-built editors. What they DO share is the merge-field vocabulary and the brand asset library - both of which Foundryx already has as first-class engines (rule-engine fact registry, `tenant_branding`).

So the Template Engine = **one engine, several editors**: shared template store, shared merge fields, shared brand assets, shared render dispatch - per-surface editor UIs and compilers added surface-by-surface. This plan ships the engine core + the **email surface** (the workflow-engine dependency); badge canvas and website builder follow as separate efforts on the same foundation.

Existing seams this plan builds on: `email_outbox` + dispatcher (plan 09), Jinja2 transactional templates (migrated away here), `merge-field-editor` component (plan sprint-2/01 - "the standard template-builder input, BL-024 adopts"), rule-engine fact registry + `RuleBuilder` + `validate_tree` (plan sprint-2/02), `tenant_branding` + version-busted assets (plan sprint-2/03), status-engine notification specs (plan sprint-2/01).

### Locked design decisions (from grilling)

1. **D1 - Scope = engine core + email only.** Invitations = email-type templates (no special casing). Badge/ticket fixed-canvas editor + PDF (WeasyPrint path) = backlogged. Website builder = future plan (needs Projects/Events entities to exist; Puck = research front-runner, NOT Craft.js - downgraded from project plan §2.4 for bus-factor/maintenance).
2. **D2 - Hand-rolled block editor, OUR JSON schema.** GrapesJS rejected (imperative API, own CSS layer vs no-global-CSS rule, HTML-string blocks, editor-owned JSON). Unlayer/easy-email rejected (open-core traps - resold-PaaS poison). Maily.to rejected (doc-composer shape, weak section/column layout). The block schema is a **forever-contract** (research: Mailchimp's classic↔new migration wall) - it must be ours, editor-agnostic, `schemaVersion: 1` at doc root from day one. House precedent: FlowCanvas over react-flow, RuleBuilder from scratch.
3. **D3 - Block grammar = Brevo-style two-level model.** **Section** (layout row: columns `100 | 50/50 | 33/33/33 | 67/33`, background color, padding) → **Blocks**: Heading (H1-H3, align), Text (rich-lite: bold/italic/underline/link/lists + merge-field chips), Image (StorageService upload, alt, width, align, optional link), Button (label + href both merge-enabled, brand-primary default), Divider, Spacer, SocialLinks, BrandHeader, BrandFooter, CustomHTML (sanitized escape hatch - the industry-standard pressure valve). Nesting depth = 1 (no columns-in-columns; email clients hate it). Stable block `id`s. Every block/section carries a `conditionsJson` slot (D8).
4. **D4 - Brand blocks resolve from `tenant_branding` at render time.** `tenant_branding` gains social URLs (facebook/instagram/x/linkedin/youtube/tiktok/website) + footer text fields (company name, address line, tagline); Branding settings UI gains a "Social & Footer" section. BrandHeader = logo + bg; BrandFooter = footer text + socials. Per-template prop overrides allowed; defaults live-follow a rebrand (no stale compiled copies). New blank template opens with BrandHeader + BrandFooter pre-inserted (deletable). Future legal footer (CAN-SPAM/PDPA sender address, unsubscribe) homes here - machinery backlogged.
5. **D5 - Merge renderer = own micro-renderer, substitution only.** `{{ dotted.path }}` (matches project plan's Handlebars syntax + existing merge-field-editor). **Never raw Jinja2 on tenant-authored content (SSTI→RCE); sandboxed Jinja2 also rejected** (syntax surface + sandbox-escape history). Vocabulary = rule-engine fact registry per template context. Logic lives structurally: block-level visibility via the rule engine, NOT string-spliced conditionals. Substituted values HTML-escaped by default; Button/link hrefs URL-validated. Missing fact ⇒ empty string + logged warning in sends; preview shows unresolved tokens loudly. No loops (backlog: repeater block) and no partials (brand blocks cover that use case). Status-engine notification rendering migrates onto this ONE renderer.
6. **D6 - Two-tier templates table (status-engine D7 pattern).** `templates`: `id, tenant_id (NULL = platform default), type ('email')`, `key` (addressable, e.g. `auth.reset_password`), `name`, `context` (fact-source binding), `subject` (merge-enabled), `doc_json (JSON(none_as_null=True))`, `is_system`, timestamps. Reads resolve tenant fork else platform; a tenant's first edit of a system template forks it; "Reset to platform default" deletes the fork. System templates: key/context/delete locked; name/subject/doc editable. Custom templates: tenant-owned, full CRUD. No draft/publish v1 (edit live + preview + test-send; versioning = backlog).
7. **D7 - System transactional mails migrate onto the engine.** Every Jinja2 product mail (reset password, invite, email-change approve/verify + notices, tenant provision…) becomes a platform-default block template; `email_service.send_*` resolves by key → engine render → outbox. Safety rail: each **template context** declares **required facts** (e.g. `auth.password_reset` requires `resetLink` consumed in ≥1 block) - save validates, named 422 if missing. This closes BL-038 and BL-066 (brand blocks put the tenant's logo/colors in every mail - the white-label mandate finally holds for email). Dev console-log fallback + outbox semantics unchanged.
8. **D8 - Conditional block visibility ships, UI included.** Block settings drawer gains "Visibility conditions" mounting `<RuleBuilder>` (facts = the template context's sources); renderer prunes failing blocks per recipient before compile. Research: conditional content = the #1 demanded premium feature, competitors gate it behind enterprise tiers - ours is nearly free (rule engine evaluate + validate_tree already exist). Thin fact sets on auth contexts now; shines as event/attendee entities register.
9. **D9 - Full pipeline at render time, per send.** Prune conditions → JSON→MJML→compile→HTML→merge-substitute → outbox. No compiled-HTML caching (per-recipient structure makes a single cache wrong by construction; brand values stay live). Compiler = **mrml** (Rust MJML port, PyPI - verified `mrml 0.2.4`; no Node sidecar). **Phase 0 spike** validates all block mappings (`mj-section/column/text/image/button/divider/spacer/social/mj-raw`) against Gmail/Outlook-web; fallback = hand-rolled table compiler for our bounded grammar (researched as viable). Preview endpoint runs the SAME renderer - preview IS production, no drift. Plain-text sibling auto-derived from the block tree at render (never authored).
10. **D10 - Notification specs gain `template_id`.** Status-engine notification specs may reference an engine template instead of inline subject/body; inline stays supported (no migration of existing specs); both paths render through the one renderer. `TemplateService.render_email(db, template, facts)` (+ resolve-by-key helper) = the contract the Workflow engine's SendEmail action consumes next.
11. **D11 - Template contexts = code-side registry** (mirrors `STATUS_ENTITIES` / fact-source registration): `TemplateContext(key, label, fact_sources, required_facts, sample_facts)`. Core registers the auth/account/tenant contexts; modules register theirs at install. Sample facts feed preview + test-send + editor chips (fact registry `FactDef` gains a `sample` value).
    **The engine is PLATFORM CORE, not an App Store module** (CLAUDE.md auth/SMTP rule: core auth mails render through it, the core Workflow engine consumes it - an uninstallable engine could brick password recovery). Modules ADOPT it via this registry: register `TemplateContext`s + seed their platform-tier default templates in `install()`, deregister at uninstall - same lifecycle as permissions.csv / fact sources / status entities.
12. **D12 - Frontend surface = house Resource shell.** Menu `Templates` (Settings cluster, gated `templates.read`, tagged in ALL THREE menu arrays - sidebar/mega/mobile). List: Name, Key, Context, Type, Tier badge (Default | Customized), Updated; actions: Edit, Duplicate, Test send, Reset to default (forks), Delete (custom only). Form: **Settings** tab (name, subject with merge chips, context, key) + **Design** tab (canvas, gated by the global Edit toggle - FlowCanvas precedent). Canvas: left palette (dnd-kit drag-in), center email canvas with inline on-canvas text editing (industry trend; merge-field-editor inside Text/Heading), right settings drawer for the selected block/section (style props + Visibility conditions). Preview toggle inside Design: desktop 600px / mobile 375px (no client-emulation - Litmus territory, never v1). Explicit Save = single PATCH with dirty-guard (house Form invariant); canvas edits buffer client-side.
13. **D13 - Permissions** = `templates.read` / `templates.manage` (core CSV; implied-read normalization applies). Platform-tier editing: platform tenant signs into its own console, same pages (NULL-tenant rows visible/editable only there - status-engine precedent). Custom-HTML sanitized server-side at save (nh3/ammonia class sanitizer; same posture as the future §2.4 embed block, kin to BL-067).
14. **D14 - Email outbox UI ships in this plan** (the outbox currently lives DB-only; test-send debugging wants it anyway). Resource shell end-to-end:
    - **List** (`Email log`, menu beside Integrations): To, Subject, Template key, Status badge, Attempts, Created, Sent. Segments All | Pending | Sent | Failed | Cancelled. Tenant-scoped - own tenant's mail only (platform tenant sees platform mail); cross-tenant operator view = NOT v1.
    - **Detail** = read-only ResourceForm (**no Edit toggle**): Overview tab (recipient, status, timestamps, attempts, `last_error`, `used_fallback`, connection) + Body tab - HTML rendered in a **sandboxed iframe** (no scripts; links clickable, open new tab via `allow-popups`), raw-HTML/text-sibling toggle.
    - **Actions** (row + bulk): **Retry** on FAILED|CANCELLED → status PENDING + `next_attempt_at = now` (attempts counter keeps counting - history honest); dispatcher claims on next pass. **Cancel** on PENDING → new status CANCELLED via atomic `UPDATE … WHERE id = ? AND status = 'PENDING'` - rowcount 0 ⇒ 409 "already sending/sent" (the dispatcher's lease claim wins the race). Cancelled rows are retryable.
    - **Retention**: dispatcher housekeeping currently prunes sent rows immediately - switch to `outbox_retention_days` setting (default 30); SENT/FAILED/CANCELLED rows prune only when older.
    - **Permissions**: new core `emails.read` / `emails.manage` (retry/cancel ride manage). Sensitivity accepted knowingly: bodies contain live reset/invite links (account-takeover capabilities) - body view is perm-gated detail, and tenant Admin already holds comparable power (PATCH user email); noted, not blocked.
    - **Endpoints**: `GET /emails` (paginated, filter-translator over whitelisted columns), `GET /emails/{id}`, `POST /emails/{id}/retry`, `POST /emails/{id}/cancel`. No migration - table already carries every surfaced field; only the CANCELLED status constant + retention setting are new.

---

## Wire schema - block document (camelCase, `doc_json`)

```jsonc
{
  "schemaVersion": 1,
  "sections": [
    {
      "id": "sec_8f2k",
      "layout": "50/50",                  // "100" | "50/50" | "33/33/33" | "67/33"
      "background": "#FFFFFF",
      "padding": { "top": 16, "bottom": 16, "left": 24, "right": 24 },
      "conditionsJson": null,             // rule-engine tree (plan 02 schema) | null = always
      "columns": [
        { "id": "col_1", "blocks": [
          { "id": "blk_a1", "type": "heading", "level": 2, "align": "left",
            "text": "Hi {{recipient.firstName}}," },
          { "id": "blk_a2", "type": "button", "label": "Reset password",
            "href": "{{resetLink}}", "conditionsJson": null }
        ]},
        { "id": "col_2", "blocks": [
          { "id": "blk_b1", "type": "image", "storageKey": "…", "alt": "…", "width": 240 }
        ]}
      ]
    },
    { "id": "sec_brand_footer", "layout": "100", "columns": [ { "id": "c", "blocks": [
      { "id": "blk_f", "type": "brandFooter", "overrides": null }   // renders from tenant_branding
    ]}]}
  ]
}
```

Block types v1: `heading, text, image, button, divider, spacer, socialLinks, brandHeader, brandFooter, customHtml`. `conditionsJson` valid on any section/block. Schema versioning policy: migrate-on-read, bump `schemaVersion` only on breaking shape changes.

---

## Data model

One Alembic migration:
- `templates` table (D6) - `UTCDateTime` columns, `JSON(none_as_null=True)` for `doc_json`, UNIQUE(tenant_id, key) with NULL-tenant platform rows; every repository query tenant-scoped (tenant fork ∪ platform defaults on read).
- `tenant_branding` - add social URL columns + footer text fields (D4); `version` bump semantics unchanged.
- `notification_specs.template_id` - nullable FK (D10).

Seed: platform-default system templates for every existing transactional mail (block-doc ports of the Jinja2 templates, Foundryx-branded via brand blocks).

## Backend (`service_backend/`)

- **`app/template_engine/`** (mirrors `app/status_engine/`, `app/rule_engine/`):
  - `schemas.py` - Pydantic block-document models (camelCase), `validate_doc(doc, context)` → named 422s (unknown block type, bad layout, depth, missing required facts, invalid conditions via `rule_engine.validate_tree`, un-sanitizable custom HTML).
  - `contexts.py` - `TemplateContext` registry (D11); core registers auth/account/tenant contexts with required + sample facts.
  - `compiler.py` - block doc → MJML string (the 10 mappings) → `mrml` compile → HTML; plain-text derivation.
  - `renderer.py` - `render_email(db, template, facts, *, preview=False)`: resolve brand values → prune `conditionsJson` per facts (rule engine, fail-closed) → compile → merge-substitute (escape/URL-validate, D5) → `{subject, html, text}`.
  - `merge.py` - the micro-renderer: `{{ dotted.path }}` substitution against the fact dict, nothing else.
- **`TemplateService` / `TemplateRepository`** - two-tier resolve-by-key (tenant fork else platform), fork-on-first-edit, reset-to-default, duplicate, CRUD; save runs `validate_doc`.
- **`email_service`** - `send_*` functions resolve their template by key through the engine (D7); enqueue path/outbox/dispatcher untouched.
- **`status_machine`** - notification dispatch honors `template_id` when set (D10); inline path now renders via `merge.py` (one renderer).
- **Routers** - `api/v1/templates.py`: CRUD + `GET /template-contexts` + `POST /templates/preview` (doc+context → rendered HTML with sample facts; supports unsaved drafts) + `POST /templates/{id}/test-send` (sample facts → real mail to current user via outbox) + `/{id}/duplicate` + `/{id}/reset`. Gated `templates.read`/`templates.manage`.
- **Outbox UI backend (D14)** - `api/v1/emails.py` (`GET /emails`, `GET /emails/{id}`, `POST /emails/{id}/retry`, `POST /emails/{id}/cancel`) → `EmailLogService`/repository (tenant-scoped, filter-translator whitelist); CANCELLED status constant; cancel = atomic conditional UPDATE (409 on race loss); retry guard (FAILED|CANCELLED only); dispatcher housekeeping moves to `outbox_retention_days` (default 30).
- **Permissions CSV** - `templates.read`, `templates.manage`, `emails.read`, `emails.manage`; Admin re-grant at seed.
- **Deps** - `mrml`, `nh3` (requirements.txt).

## Frontend (`service_frontend/`)

- **`components/platform/email-editor/`** - the block editor: `<EmailEditor doc onChange>` (palette, canvas, dnd-kit drag/reorder, inline text editing via merge-field-editor, block/section settings drawer with RuleBuilder visibility section, preview pane 600/375). Editor-agnostic doc in/out - the JSON schema is the only contract.
- **`types/templates.ts`** - block-document TS types, `schemaVersion` const.
- **Templates pages** - `app/(protected)/settings/templates/` ResourceList + ResourceForm per D12; `<RequirePermission permission="templates.read">`.
- **Branding settings** - "Social & Footer" section (D4).
- **Notification spec UI** - template picker (SearchSelect over `/templates?context=`) beside the inline editor.
- **Email log pages (D14)** - `app/(protected)/settings/email-log/` ResourceList (segments All|Pending|Sent|Failed|Cancelled, retry/cancel in the action registry, row+bulk) + read-only detail (no Edit toggle; Body tab = sandboxed iframe, raw/text toggle); menu entry gated `emails.read` (all three menu arrays).
- **Services/hooks** - `services/template-service.ts` + `services/email-log-service.ts` (mock first, real swap at the boundary), `hooks/use-templates`, `use-template-editor`, `use-email-log`.
- **New dep** - `@dnd-kit/core` (+sortable).

---

## Phases

- **Phase 0 - mrml spike (hours):** compile a doc exercising all 10 block mappings via `mrml`; eyeball in Gmail + Outlook web. Gaps → hand-rolled table compiler decision BEFORE Phase A locks the schema↔compiler seam.
- **Phase A - frontend-first:** TS schema, EmailEditor (palette/canvas/drawer/inline edit/RuleBuilder/preview), Templates list+form, Email log list+detail (D14), branding Social & Footer section - all against mock services; Vitest.
- **Phase B - backend:** migration + seed ports of system mails, `app/template_engine/`, services/repos/routers (templates + emails), email_service + status_machine integration, outbox retry/cancel/retention, permissions, pytest.
- **Phase C - E2E + report:** real-click journeys (below), Test Execution Report, CLAUDE.md section, backlog updates, memory.

## TDD

- **Backend (pytest):** compiler mapping per block type (golden MJML/HTML fragments); merge renderer (substitution, HTML-escape, URL-validate, missing→empty, no code execution on `{{__class__}}`-style probes); conditional pruning (block hidden per facts, fail-closed, section-level); `validate_doc` 422 matrix (unknown type, missing required fact, bad conditions, dirty custom HTML sanitized/rejected); two-tier resolve + fork-on-edit + reset + UNIQUE enforcement; system-template guards (key/context/delete locked); email_service sends render through engine (outbox row contains branded HTML + text sibling); notification `template_id` path; endpoint permission gates; preview with sample facts; test-send enqueues to current user only. **Outbox (D14):** list tenant-scoped + filtered; retry only FAILED|CANCELLED (else 409) → row goes PENDING with `next_attempt_at` now, attempts preserved; cancel only PENDING (atomic - simulated claimed row ⇒ 409); cancelled row retryable end-to-end; retention prune spares younger-than-`outbox_retention_days` rows; `emails.*` permission gates.
- **Frontend (Vitest+RTL):** palette drag-in adds block; reorder; settings drawer edits props; RuleBuilder mounts with context facts; merge chips insert tokens; preview toggles widths; dirty-guard; tier badge + reset action visibility; permission gating. Email log: segment filters, retry/cancel action visibility per status, sandboxed-iframe body render (no script execution), raw/text toggle.
- **E2E (Playwright, real clicks, timestamped names, dedicated tenant - branding isolation rule):** ① create custom template → drag blocks → insert merge field → save → preview → test-send (maildir rig asserts delivery + brand logo). ② edit system reset-password template → fork → trigger real forgot-password → mail uses forked branded template → reset to default → mail reverts. ③ add visibility condition on a block → test-send/preview reflects pruning. ④ notification spec picks a template → transition fires → outbox mail rendered from it. ⑤ Email log: test-send row appears → open detail → body renders + link click opens new tab → cancel a pending row (dispatcher disabled window) → status Cancelled → retry → delivered.

## Verification (end-to-end)

1. `python -m scripts.bootstrap_db` (seeds platform templates); `uvicorn … --port 8001`; `python -m pytest -q` green.
2. `npm run build && npm start`; Vitest green.
3. Manual: Templates list shows seeded system rows (Default tier) → edit one → Design canvas → brand header shows tenant logo → test-send lands branded mail → forgot-password mail matches.
4. Regression: every existing transactional flow (reset, invite, email-change, provision) still delivers; outbox/dispatcher/throttle untouched.

---

## Follow-up backlog (log in `backlog.md`)

- **Badge/ticket fixed-canvas designer** - Konva/Fabric editor (x/y, nudge, alignment guides, per-element data binding + visibility rules - Webex Events reference) → SVG → fixed-size HTML → WeasyPrint PDF; batch render (Canva Bulk-Create model). Same template store/merge/conditions foundation.
- **Repeater/loop block** - line-item tables (invoice mails/PDFs).
- **Template draft/versioning + audit** - edit-live is v1; staged publish + history later.
- **Marketing unsubscribe/compliance machinery** - list-unsubscribe headers, suppression list; footer fields from D4 are the home.
- **Saved-blocks library** - tenant-reusable composed blocks (research: the no-code composition tier).
- **Website builder plan** - Puck front-runner; consumes this schema philosophy + brand/fact seams; needs Projects/Events entities first.
- Close BL-024 (email surface; badge/web tracked above), BL-038, BL-066.
