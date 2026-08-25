# Sprint 3 · Plan 07 - Test Execution Report (Slice B1: WhatsApp Templates)

> **Plan:** [`07-omnichannel-templates.md`](./07-omnichannel-templates.md) ·
> **UAC:** [`07-omnichannel-templates-uac.md`](./07-omnichannel-templates-uac.md)
> **Mode:** dev-stub (no `META_APP_ID` → adapter stubs) against the LIVE stack
> (Next :3001 → FastAPI :8001 → Postgres `app_omnichannel`). Real user clicks.
> **Branch:** `sprint-3/07-omnichannel-templates`

---

## 1. Automated suites

| Suite | Scope | Result |
|-------|-------|--------|
| Backend `tests/test_omni_templates.py` | transform round-trip (text/media/all buttons), `validate_doc` matrix, draft→submit→sync→edit→delete (dev), webhook apply (idempotent + malformed-safe), tenant-scope 404, perm gates | **17 / 17 pass** |
| Backend `tests/test_omnichannel*` (regression) | onboarding, channels, conversations, webhooks, profile | **53 / 53 pass** |
| Frontend `lib/whatsapp-template.test.ts` | transform parity golden (FE⇄BE), round-trip, `validateDoc` matrix, quality map | **13 / 13 pass** |
| Frontend full vitest | regression across all suites | **584 / 584 pass** |
| E2E `omni-templates.spec.ts` | real-click lifecycle, validation, responsive | **3 / 3 pass** |

E2E journeys: ① build (name/body+var/sample) → **Save draft** → list shows *Local draft* → row **Submit** → *Pending* → **Sync** → *Approved* → **Delete** → gone · ② sample-count mismatch blocked inline before submit (BR-11/GP-1) · ③ builder two-pane stacks at 375px, no horizontal overflow.

---

## 2. UAC sign-off (dev-stub, both viewports)

| # | Criterion | Priority | Result | Evidence |
|---|-----------|----------|:------:|----------|
| BR-1 | List all statuses + filters/search | MUST | ✅ | embedded ResourceList; Status/Category/Language filterFields + search |
| BR-2 | Rejected reason shown inline | MUST | ✅ | Status cell renders `rejected_reason` |
| BR-3 | Two-pane builder | MUST | ✅ | E2E ①; editor ‖ live bubble preview |
| BR-4 | Save draft (no Meta call) | MUST | ✅ | E2E ①; LOCAL_DRAFT row, dev path |
| BR-5 | Submit → PENDING + meta id | MUST | ✅ | E2E ①; backend lifecycle test |
| BR-6 | Media-header upload on submit | MUST | ✅(dev) | `upload_resumable` stub → handle in example; `[real]` deferred |
| BR-7 | Sync reconciles status/quality | MUST | ✅ | E2E ① (PENDING→Approved); quality High/Med/Low map |
| BR-8 | Webhook async update | MUST | ✅(unit) | `apply_webhook_event` test; `[real]` deferred |
| BR-9 | Edit status-gated | MUST | ✅ | draft free / approved→PENDING / pending 409 (backend `test_edit_pending_blocked_409`) |
| BR-10 | Delete (draft local / synced Meta) | MUST | ✅ | E2E ①; backend delete test |
| BR-11 | Variable/sample integrity 422 | MUST | ✅ | E2E ②; backend + FE `validateDoc` |
| BR-12 | View payload raw JSON | SHOULD | ✅ | View payload dialog (`toMetaComponents`) on list + builder |
| GP-1 | Field-level validation before submit | MUST | ✅ | E2E ②; per-field inline errors |
| GP-2 | Status-driven action set | MUST | ✅ | Submit only on LOCAL_DRAFT; Edit hidden for PENDING/DISABLED (`isVisible`) |
| GP-3 | Dirty-guard AlertDialog | MUST | ✅ | builder Back → Discard-changes AlertDialog (not `window.confirm`) |
| GP-4 | In-flight feedback + double-submit | SHOULD | ✅ | Save/Submit/Sync/Delete spinners + disabled |
| GP-5 | Errors recoverable, input preserved | MUST | ✅ | 422 maps to fields, builder input kept; submit failure keeps draft |
| GP-6 | Media sniff-gated upload | MUST | ✅ | `detect_upload_mime` (magic bytes, images+PDF) |
| GP-7 | Sync freshness visible | SHOULD | ✅ | last-synced via `useDatetime` (stamped `last_synced_at`) |
| GP-8 | ClampedText on overflow | SHOULD | ✅ | name cell uses ClampedText |
| GP-9 | Only supported buttons offered | MUST | ✅ | builder offers Quick-reply/URL/Phone/Copy-code only |
| UX-1 | Resource-shell list | MUST | ✅ | config-driven ResourceList |
| UX-2 | Two-pane builder pattern | MUST | ✅ | full-page route, editor ‖ preview |
| UX-3 | StatusBadge registry | MUST | ✅ | `TEMPLATE_STATUS_REGISTRY` |
| UX-4 | SearchSelect dropdowns | MUST | ✅ | category/language/header/button-type all SearchSelect |
| UX-5 | Responsive both breakpoints | MUST | ✅ | E2E ③; `flex-col lg:flex-row` |
| UX-6 | Faithful live preview | MUST | ✅ | E2E ① asserts substituted value in bubble |
| UX-7 | Brand + white-label, no raw CSS | MUST | ✅ | utility classes only |
| UX-8 | House datetime formatter | SHOULD | ✅ | `useDatetime` |
| UX-9 | No instructional copy | MUST | ✅ | labels + neutral empty states only |
| SEC-1 | Tenant scoping → 404 | MUST | ✅ | `test_template_cross_tenant_404` |
| SEC-2 | Permission gates server-side | MUST | ✅ | `wa_templates.read/manage`; `test_template_permission_gates` |
| SEC-3 | Module isolation | MUST | ✅ | 5 cols via ADD COLUMN IF NOT EXISTS; module CSV |
| SEC-4 | Dev-safe, no Meta app | MUST | ✅ | full lifecycle offline (E2E ①) |
| SEC-5 | Single store + parity-pinned transform | MUST | ✅ | `components_json`; FE golden pins `toMetaComponents` |
| SEC-6 | Webhook safe + idempotent | MUST | ✅(unit) | `test_apply_webhook_*` (idempotent + malformed-safe) |

**All MUST criteria pass in dev-stub mode at both viewports.**

---

## 3. `[real]` against a connected number

Not exercised locally (no Meta app). The acceptance rule's `[real]` rows - BR-5/6/7/8/10, GP-5/6, SEC-6 - remain a UAT step once a real WABA token + the 3 template webhook fields (`message_template_status_update`/`_quality_update`/`_category_update`) are subscribed (runbook). The dev path is the same code with the adapter's real Graph branch.

---

## 4. Notes / deviations

- **Permission keys renamed `templates.*` → `wa_templates.read`/`wa_templates.manage`** - the core Template Engine (sprint-2/07) already owns the global `templates.read`/`templates.manage` keys, so the plan's `templates.*` would collide on `permissions.key`. Granted to tenant Admin via the install-aware grant.
- **Service named `whatsapp-template-service.*`** (not `template-service.*`) - the core email Template Engine already owns `template-service.*`.
- Backend `save_profile`-style write paths surface a Meta `SendError` as a recoverable **502** (submit/delete), leaving the local row unchanged.
- E2E ran on the dev server; a `waitForTimeout(300)` after `setViewportSize` lets the layout reflow before the overflow check (a reflow-timing race, not a content overflow - measured `scrollWidth ≤ innerWidth`).
