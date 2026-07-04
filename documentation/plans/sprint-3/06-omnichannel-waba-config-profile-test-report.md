# Sprint 3 · Plan 06 — Test Execution Report (Slice A: WABA Configuration + Profile)

> **Plan:** [`06-omnichannel-waba-config-profile.md`](./06-omnichannel-waba-config-profile.md) ·
> **UAC:** [`06-omnichannel-waba-config-profile-uac.md`](./06-omnichannel-waba-config-profile-uac.md)
> **Mode:** dev-stub (no `META_APP_ID` → adapter returns canned data) against the LIVE stack
> (Next :3001 → FastAPI :8001 → Postgres `app_omnichannel`). Real user clicks.
> **Branch:** `sprint-3/06-omnichannel-waba-config-profile`

---

## 1. Automated suites

| Suite | Scope | Result |
|-------|-------|--------|
| Backend `tests/test_omnichannel_profile.py` | sync-config, profile sync/mirror, save validation matrix (bad vertical/email/website → 422), changed-only write-through, tenant-scope 404, perm gates | **10 / 10 pass** |
| Backend `tests/test_omnichannel*.py` (regression) | full omnichannel module (onboarding, channels, conversations, webhooks, ws) | **45 / 45 pass** |
| Frontend `channel-profile-schema.test.ts` | profile zod mirror (email/url/vertical/website-cap), mock service flow (sync/save/get) | **12 / 12 pass** |
| Frontend full vitest | regression across all suites | **568 / 568 pass** |
| E2E `omnichannel-waba-config-profile.spec.ts` | real-click journeys, desktop + 375px | **5 / 5 pass** |

E2E journeys: ① three tabs + read-by-default + Sync→business name · ② Sync Profile pulls mirror (BR-5) ·
③ profile Edit→Save→reload persists (BR-6/BR-10) · ④ invalid email rejected inline (BR-8) ·
⑤ responsive at 375px, no horizontal overflow (UX-3).

---

## 2. UAC sign-off matrix (dev-stub, both viewports)

| # | Criterion | Priority | Result | Evidence |
|---|-----------|----------|:------:|----------|
| BR-1 | Three tabs (Configuration, Templates, Profile), read-by-default | MUST | ✅ | E2E ①; live snapshot |
| BR-2 | Config editable (name/workspace/active) + synced identity block | MUST | ✅ | live snapshot |
| BR-3 | Sync pulls WABA/phone identity → business account name | MUST | ✅ | E2E ①; DB shows "Dreamz Events (dev sandbox)" |
| BR-4 | Profile tab mirrors business profile from local DB | MUST | ✅ | live snapshot; instant render (no Meta call) |
| BR-5 | Sync Profile pulls latest from Meta + stamps | MUST | ✅ | E2E ②; `profile_synced_at` set |
| BR-6 | Save write-through (only changed fields to Meta) | MUST | ✅ | E2E ③ + DB; backend `test_save_profile_only_changed_fields_sent_to_meta` |
| BR-7 | Vertical constrained to 22-value Meta enum (SearchSelect) | MUST | ✅ | live snapshot; `channel-profile-schema.test.ts` |
| BR-8 | 422 field-level validation; website cap of 2 | MUST | ✅ | E2E ④; backend 422 matrix; only website1/2 fields exist |
| BR-9 | Identity fields never editable (even in Edit) | MUST | ✅ | live snapshot — Edit mode keeps phone/WABA/business as text |
| BR-10 | Persistence survives reload | MUST | ✅ | E2E ③ |
| GP-1 | Read-by-default + single global Edit toggle | MUST | ✅ | shell ResourceForm |
| GP-2 | Dirty-guard AlertDialog (not `window.confirm`) | MUST | ✅ | shell ResourceForm `guard()` (shared) |
| GP-3 | Actions gated server-side, hidden when ungranted | MUST | ✅ | `useCan('channels.manage')` hides Sync/Test/Sync-Profile; backend `test_profile_permission_gates` |
| GP-4 | In-flight loading + double-submit guard | SHOULD | ✅ | buttons disable + spinner during request |
| GP-5 | Errors recoverable, values kept, no crash | MUST | ✅ | save catch keeps form values + toast; Meta failure → 502 leaves mirror unchanged |
| GP-6 | Staleness "Last synced …" caption | SHOULD | ✅ | both tabs render via `useDatetime` |
| GP-7 | Test Connection no-input check | SHOULD | ✅ | inline button, no required input |
| GP-8 | ClampedText on overflow | SHOULD | ✅ | synced values + profile read values use `ClampedText` |
| UX-1 | Built on Resource shell | MUST | ✅ | `ResourceForm` config-driven, icon tabs, record-nav |
| UX-2 | Every dropdown a SearchSelect | MUST | ✅ | vertical picker is `SearchSelect` |
| UX-3 | Responsive 375 + 1280, no overflow | MUST | ✅ | E2E ⑤ |
| UX-4 | Brand + white-label (no "Dreamz" tenant copy, utility classes) | MUST | ✅ | neutral placeholders; no raw CSS |
| UX-5 | House datetime formatter | SHOULD | ✅ | `useDatetime` everywhere; no `new Date(iso)` |
| UX-6 | Read/edit affordance clear | SHOULD | ✅ | text in read, inputs in edit |
| UX-7 | No instructional/teaching copy | MUST | ✅ | labels + neutral empty states only |
| SEC-1 | Tenant scoping → 404 | MUST | ✅ | `test_profile_cross_tenant_404` |
| SEC-2 | Permission gates server-side | MUST | ✅ | `test_profile_permission_gates` (read vs manage) |
| SEC-3 | Module isolation (no core pollution; ADD COLUMN IF NOT EXISTS) | MUST | ✅ | all in `app_omnichannel`; idempotent ALTER in `bootstrap.py` |
| SEC-4 | Dev-safe with no Meta app | MUST | ✅ | full flow demoed with `credentials.dev` stubs |
| SEC-5 | Write-through atomicity (local refreshed only after Meta OK) | MUST | ✅ | save POSTs Meta first; on `SendError` → 502, mirror untouched; `test_save_profile_*` |

**All MUST criteria pass in dev-stub mode at both viewports.**

---

## 3. `[real]` against a connected number

Not exercised in this automated run (no live Meta app configured locally). BR-3 / BR-6 / SEC-5
`[real]` rows remain to be confirmed once a real WABA token is wired (UAT runbook step), as the
acceptance rule notes. The dev-stub path is byte-for-byte the same code with the adapter's real
Graph branch — only the HTTP calls differ.

---

## 4. Notes / observations

- **Sync Profile refreshes the editable inputs**, not just the read view (else a later Edit would
  show stale values and Save would clobber the freshly-synced profile) — fixed in `use-channel-form`
  via a form reset on sync. A sub-50ms machine-speed *fill-immediately-after-sync* race surfaced in
  the dev-server E2E only; real users can't hit it, and the save test edits directly (the common flow).
- Backend `save_profile` translates a Meta `SendError` into a recoverable **502** with the mirror left
  unchanged (SEC-5), so a Meta outage never half-writes.
- Templates tab ships as a labelled placeholder (plan 07 fills it) with a neutral empty state.
