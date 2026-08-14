# Sprint 3 · Plan 07 - Omnichannel WhatsApp Templates: Manage / Submit / Sync (Slice B1)

> **Feature:** Full WhatsApp message-template management on the omnichannel **channel form → Templates tab** - build, submit, edit, delete templates, with Meta-driven status/quality sync. The headline of the WABA-management work.
>
> **This plan = Slice B1** (text + media-header + standard-button templates, categories Marketing/Utility). Configuration + Profile = plan 06 (Slice A). **Authentication** templates = plan 08 (Slice B2, distinct shape, grilled separately).
>
> Builds on plan 06's tab structure, mirror-with-Sync model, and dev-safe stance. Module: `service_backend/modules/omnichannel/` (schema `app_omnichannel`, idempotent-ALTER, no core pollution).

---

## 0. Locked decisions (grilled - see plan 06 §0/§9)

| # | Decision | Resolution |
|---|----------|------------|
| T1 | **Lifecycle** | **Local-draft model, NOT the status engine.** `LOCAL_DRAFT →(Submit)→ PENDING →(Meta review)→ APPROVED / REJECTED / PAUSED / DISABLED`. |
| T2 | **Why not status engine** | Meta **owns the fixed enum + drives transitions externally** (webhook). The engine's value (configurable graph, edge-role auth, terminal rules, notifications, two-tier) is inapplicable, and exposing an editable graph for Meta's review states is a foolproof-UI violation. Render via a frontend **StatusBadge registry**; reactions = workflow event (deferred). |
| T3 | **Permissions** | Dedicated `templates.read` / `templates.manage` (module CSV, granted to tenant Admin in `install_tenant`). Existing send-picker endpoint keeps `conversations.reply`. |
| T4 | **Builder scope v1** | Category **Marketing + Utility**; one language/template; header **TEXT or media (IMAGE/VIDEO/DOC)**; body + positional `{{n}}` vars + samples; footer; buttons **Quick-reply / URL (static+dynamic) / Phone / Copy-code**. **Omit** Flow + Catalog/Carousel buttons (need resources we don't manage → foolproof) and Authentication (→ B2). |
| T5 | **Storage** | **Single canonical store** = Meta-shape `components_json`; friendly⇄Meta transform `lib/whatsapp-template.ts` (parity-pinned FE/BE). |
| T6 | **Sync** | **Dual push + pull.** Webhook (3 template fields) updates the local row; **Sync** button pulls via `list_templates` (also the dev path). No WS realtime. `template.status_changed` workflow event = emit-ready, trigger deferred (BL-109). |
| T7 | **Edit / Delete** | Edit gated by status (draft=free, approved/rejected/paused=components-only re-submit→PENDING, pending/disabled=hidden). Delete: draft=local only, synced=Meta DELETE then hard-delete local row; **single confirm**, no typed-slug, no soft-trash. |
| T8 | **UI** | Templates tab = embedded `ResourceList`; create/edit = **full-page two-pane builder route** (editor ‖ live WhatsApp-bubble preview) + read-only **View payload**. Drop the "Label" column. |
| T9 | **Dev shortcuts** | Service-layer: Submit→PENDING+fake `meta_template_id`; Sync promotes local PENDING→APPROVED; edit→PENDING; delete→local. Fully demoable with no Meta app. |
| T10 | **Media-header upload** | Draft sample file → `storage_for_tenant` key; on Submit → fetch bytes → Meta resumable upload (`/{app_id}/uploads`) → header handle → component example. Dev stub = fake handle. Heaviest item. (Closes upload-helper dependency for BL-108 profile photo.) |

---

## 1. What ships

The **Templates tab** (plan-06 channel form) goes live:

```
┌─ Templates tab ───────────────────────────────────────────────────────┐
│ [🔍 Search]  [Status ▾] [Category ▾] [Language ▾]   [Sync] [+ Submit] │
│ ─────────────────────────────────────────────────────────────────────│
│ Status    Name              Category   Quality  Language   ⋮          │
│ ●Approved order_update       Utility    High     English    ⋮          │
│ ●Rejected event_invite       Marketing  N/A      English    ⋮          │
│   ⓘ Rejection reason: INVALID_FORMAT                                    │
│ ●Pending  conversation_fu…   Marketing  N/A      English    ⋮          │
└───────────────────────────────────────────────────────────────────────┘
```

- **List:** embedded `ResourceList`, server sort/filter/search/paginate, columns Status (StatusBadge) · Name · Category · Quality · Language · ⋮. Rejected rows show `rejected_reason` inline. Toolbar: Search + Status/Category/Language filters + **Sync** + **Submit Template**.
- **Builder route** (`…/channels/[id]/templates/new` + `/[templateId]`): full-page, two-pane - component editor left, live WhatsApp-bubble preview right (mirror plan 06's preview style / the email-editor two-pane). **View payload** = read-only raw Meta JSON.
- **Row actions (⋮):** Edit (status-gated), Delete, View payload, (Submit if `LOCAL_DRAFT`).

---

## 2. Data model

Extend existing `WhatsappTemplate` (`models.py`) via idempotent-ALTER. Existing cols: `id, tenant_id, channel_id, name, language, category, components_json, status, synced_at, created_at`.

New columns:

| Column | Type | Notes |
|--------|------|-------|
| `meta_template_id` | `String` nullable | Meta's `message_template_id` / `hsm_id`; webhook match key |
| `quality` | `String` nullable | GREEN/YELLOW/RED → High/Medium/Low (display map) |
| `rejected_reason` | `String` nullable | from `message_template_status_update` |
| `last_synced_at` | `UTCDateTime` nullable | stamped on Sync |
| `media_sample_key` | `String` nullable | `storage_for_tenant` key for a draft media-header sample (pre-submit) |

`status` value set widens to: `LOCAL_DRAFT, PENDING, APPROVED, REJECTED, PAUSED, DISABLED`. `components_json` = **Meta component-array shape** (canonical, single store - T5). `name`+`language` stay the natural key for the send-picker; `meta_template_id` is the reliable sync key.

> **No `WhatsappTemplate` deletion is soft** - delete removes the row (T7).

---

## 3. The component shape + transform (parity-pinned)

`types/whatsapp-template.ts` (FE) mirror = `app/.../template_schemas.py` (BE), pinned by a parity test (mirrors the form/template-engine pattern).

**Friendly builder type** (edited in the UI):
```ts
interface WaTemplateDoc {
  name: string;                 // lowercase snake_case, ≤512
  category: 'MARKETING' | 'UTILITY';
  language: string;             // Meta lang code, e.g. en_US
  header?:
    | { format: 'TEXT'; text: string; example?: string }         // ≤1 var
    | { format: 'IMAGE' | 'VIDEO' | 'DOCUMENT'; sampleKey?: string }; // media
  body: { text: string; examples: string[] };  // examples[i] = sample for {{i+1}}
  footer?: { text: string };
  buttons?: WaButton[];         // QUICK_REPLY | URL(static|dynamic) | PHONE_NUMBER | COPY_CODE
}
```

`lib/whatsapp-template.ts` exports `toMetaComponents(doc)` / `fromMetaComponents(components, meta)` - used FE (builder ⇄ preview, submit payload) and mirrored BE (validation + submit + sync parse). One transform, no drift.

**Variable rule:** `body.examples.length` MUST equal the count of distinct `{{n}}` in `body.text`; header TEXT allows ≤1 var with one example. Enforced both layers → `422 {fieldErrors}`.

---

## 4. Backend

**Adapter** (`adapters/whatsapp_cloud.py`) - new methods (dev-stubbed):
- `create_template(credentials, waba_id, components_payload) -> {meta_template_id, status}` → `POST /{waba_id}/message_templates`. Dev: fake id + `PENDING`.
- `edit_template(credentials, meta_template_id, components_payload) -> None` → `POST /{meta_template_id}`. Dev: no-op.
- `delete_template(credentials, waba_id, name, meta_template_id|None) -> None` → `DELETE /{waba_id}/message_templates?name=&hsm_id=`. Dev: no-op.
- `upload_resumable(credentials, app_id, file_bytes, mime) -> handle` → Meta `/{app_id}/uploads` session → upload → file handle. Dev: fake handle. **(T10 - heaviest; shared helper, reused by BL-108 profile photo.)**
- `parse_inbound` extended: recognise `message_template_status_update` / `message_template_quality_update` / `message_template_category_update` change payloads → events `{kind: 'template_status'|'template_quality'|'template_category', message_template_id, name, language, status?, reason?, quality?, category?}`.
- `list_templates` already returns name/language/category/status/components - reuse for pull-sync; add `quality_score` + `id` to the field set.

**Service** - new `TemplateManagementService`:
- `list(channel_id, tenant_id, filters, page)` - all statuses, paginated, tenant-scoped.
- `save_draft(channel_id, tenant_id, doc)` - validate → upsert `LOCAL_DRAFT` row (`components_json` = `toMetaComponents`); media sample → `storage_for_tenant` key into `media_sample_key`.
- `submit(channel_id, tenant_id, template_id)` - validate → (media-header: fetch sample bytes → `upload_resumable` → handle into example) → `adapter.create_template` → set `meta_template_id` + `PENDING`. Dev: PENDING+fake id.
- `edit(channel_id, tenant_id, template_id, doc)` - status gate (T7); draft=local; synced=`adapter.edit_template`→`PENDING`.
- `delete(channel_id, tenant_id, template_id)` - draft=local row delete; synced=`adapter.delete_template`→hard-delete row.
- `sync(channel_id, tenant_id)` - pull `list_templates` → reconcile by `meta_template_id` (fallback name+language): update status/quality/category, stamp `last_synced_at`. Dev: promote local `PENDING`→`APPROVED`.
- `apply_webhook_event(channel_id, event)` - called from the inbound pipeline; match row → update status/quality/category/`rejected_reason`. **Emit-ready** `template.status_changed` (logged seam, trigger deferred BL-109).

**Server validation** (`template_schemas.py validate_doc`): name snake_case ≤512 + unique per channel, category in {MARKETING,UTILITY}, language in Meta set, body required non-empty, sample-count == `{{n}}` count, buttons ≤10 quick-reply / URL+phone shape / copy-code rules, header constraints → `422 {fieldErrors}`.

**Router** - new `routers/templates.py`, mounted under the omnichannel prefix:
- `GET  /channels/{id}/templates/manage` (gated `templates.read`) - list all statuses. *(distinct path from the existing `conversations.reply` send-picker `GET /channels/{id}/templates`.)*
- `POST /channels/{id}/templates` (`templates.manage`) - save draft.
- `PATCH /channels/{id}/templates/{tid}` (`templates.manage`) - edit.
- `POST /channels/{id}/templates/{tid}/submit` (`templates.manage`) - submit.
- `DELETE /channels/{id}/templates/{tid}` (`templates.manage`) - delete.
- `POST /channels/{id}/templates/sync` (`templates.manage`) - Sync.

**Inbound pipeline** (`services/inbound_service.py`): after message/status handling, route `template_*` events → `TemplateManagementService.apply_webhook_event`. **Idempotent** (status update may repeat).

**Permissions** (`permissions/permissions.csv`): add
```
templates,WhatsApp Templates,read,Read,View WhatsApp message templates
templates,WhatsApp Templates,manage,Manage,Create/submit/edit/delete templates
```
Granted to tenant Admin in the module's `install_tenant` grant (mirror the existing channel/conversation grants).

---

## 5. Frontend

- **Templates tab** in the channel form (`app/(protected)/omnichannel/settings/channels/[id]/components/`): embedded `ResourceList` config (`use-template-list-config.ts`) - columns, filters, fetcher → `templateService.listManage`, row actions registry. **Submit Template** → routes to the builder.
- **Builder route** (`.../templates/new` + `[templateId]/page.tsx`): two-pane.
  - Left: `WaTemplateBuilder` - name/category/language (SearchSelect), header type toggle (None/Text/Media → media = file input with sniff-gated upload to draft storage), body rich-ish textarea with `{{n}}` insert + per-variable sample inputs, footer, button repeater (type SearchSelect → conditional fields). Validation mirror via `lib/form-validate`-style per-field errors.
  - Right: `WaBubblePreview` - renders `WaTemplateDoc` as a WhatsApp message bubble live. **View payload** dialog = `toMetaComponents(doc)` pretty-printed read-only.
  - Actions: **Save draft**, **Submit** (validates then submits), dirty-guard via the shell's AlertDialog.
- **StatusBadge registry** for template statuses (Approved=green, Rejected=red, Pending=amber, Paused=grey, Disabled=grey, Local draft=neutral) - frontend-only, per the no-status-engine decision.
- Layering: UI → hooks (`use-template-list`, `use-template-builder`) → `template-service.{ts,mock,real}` → `api-client`. **Frontend-first** with the mock returning canned templates across all statuses so the builder + list states tune offline.
- Dropdowns = `SearchSelect`; truncated cells = `ClampedText`. Mobile + desktop verified (two-pane builder stacks `flex-col lg:flex-row`, preview below editor on mobile - same responsive rule as the email/form builders).

---

## 6. Dev-safe behavior (no Meta app)

Service-layer shortcuts (T9), gated by the `credentials.dev` flag:
- Submit → `PENDING` + fake `meta_template_id` (no Meta call); media `upload_resumable` → fake handle.
- Sync → promote local `PENDING` → `APPROVED` (simulates review completing - the visible pull path without webhooks).
- Edit → `PENDING`; Delete → local row delete.

A tester completes draft → submit → Sync(→approved) → edit → delete entirely offline. Real mode drives live Graph + the webhook updates the row asynchronously.

---

## 7. Tests (TDD)

**Backend** (`tests/test_omni_templates.py`):
- transform round-trip `toMetaComponents`/`fromMetaComponents` (text, media header, all button types) - parity goldens.
- `validate_doc` matrix: bad name, dup name, bad category/lang, empty body, sample-count mismatch, button-limit, bad URL/phone → 422.
- `save_draft` → LOCAL_DRAFT row; `submit` (dev) → PENDING + meta id; media submit → upload called, handle in payload.
- `edit` status gate (draft free / approved components-only→PENDING / pending hidden→409); `delete` (draft local / synced calls Meta + removes row).
- `sync` (dev) promotes PENDING→APPROVED; reconcile by meta_template_id.
- `apply_webhook_event` updates status/quality/category/reason, idempotent.
- Tenant-scoping (cross-tenant template id → 404) + perm gates (`templates.read`/`manage`).

**Frontend** (vitest): transform mirror parity, builder validation, StatusBadge registry, bubble preview render, mock-driven list/builder states.

**E2E** (`e2e/omni-templates.spec.ts`, real clicks, dedicated tenant + dev channel, timestamped names): open channel → Templates tab → Submit Template → build (name/category/body+var/sample/footer/quick-reply button) → Save draft → list shows Local draft → Submit → Pending → Sync → Approved → Edit body → Pending → Delete → gone. Desktop + mobile pass. Markdown test-execution report (`07-…-test-report.md`).

---

## 8. Migrations / bootstrap

`bootstrap.py` idempotent-ALTER for the 5 new `WhatsappTemplate` columns. `permissions.csv` sync runs via `install()` (module catalog). `install_tenant` grant extended with `templates.read/manage`. No alembic (module convention; BL-029).

**Runbook addition:** real-mode template webhooks require the Meta App Dashboard → WhatsApp → Webhooks to subscribe `message_template_status_update`, `message_template_quality_update`, `message_template_category_update` (the `subscribed_apps` call subscribes the app; the *fields* are app-level config). Document in `documentation/plans/sprint-1/04-omnichannel-embedded-signup-runbook.md`.

---

## 9. Out of scope → backlog

| BL | Item |
|----|------|
| BL-108 | Profile photo upload - reuses the `upload_resumable` helper built here |
| BL-109 | `template.status_changed` workflow trigger - webhook handler is emit-ready; wire the trigger + per-channel selectivity |
| BL-110 | Flow / Catalog / Carousel buttons + product templates - need WhatsApp Flows / Meta catalog we don't manage (foolproof-gated) |
| BL-111 | Named variables (`{{order_id}}`) + multi-language template sets |
| (plan 08) | **Authentication** templates (Slice B2) - OTP / copy-code / one-tap, Meta-auto-generated body, `code_expiration_minutes`, security recommendation. Grill separately. |
