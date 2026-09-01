# Sprint 3 · Plan 06 - Omnichannel WABA Management: Configuration + Profile (Slice A)

> **Feature:** Surface Meta `whatsapp_business_management` capabilities as tabs on the omnichannel **channel form**, so a tenant can manage their WABA/phone-number from inside Foundryx instead of the Meta dashboard. Inspiration: respond.io's channel settings (Configuration / Templates / WABA Balance / Profile / Calls). Design follows the Foundryx Resource-shell language, **not** respond.io's.
>
> **This plan = Slice A only** (Configuration + Profile). Templates = Slice B1 (plan 07), Authentication templates = Slice B2 (plan 08). Balance + Calls = backlog (feasibility-blocked / product-gap, see §9).
>
> Module: `service_backend/modules/omnichannel/` + `service_frontend/app/(protected)/omnichannel/`. **First App Store module** - all changes stay inside the module (schema `app_omnichannel`, module permissions CSV, `create_all`/idempotent-ALTER, no core pollution).

---

## 0. Grilling outcome - the locked decision tree

The full feature was grilled (`/grill-me`). Decisions that govern **all three slices**:

| # | Decision | Resolution |
|---|----------|------------|
| D1 | **Scope** | 5 respond.io surfaces ranked by feasibility. Ship **Configuration + Profile + Templates**. Drop **Balance** (no API) + **Calls** (no call-handling) to backlog. |
| D2 | **Slicing** | 3 slices: **A** = Config + Profile (this plan); **B1** = Template CRUD core; **B2** = Authentication templates. One numbered plan + one branch per slice. |
| D3 | **Source of truth** | **Meta is system-of-record** for all Meta-owned data (verified name, business name, profile, templates). Foundryx **mirrors locally + explicit Sync button** (matches existing `WhatsappTemplate` mirror; dev-safe; instant render). **Write-through**: editable fields POST to Meta → on success refresh local. |
| D4 | **Balance** | **Backlog (BL-106).** Meta exposes **no spendable wallet / top-up** for a Tech Provider. respond.io's balance is *their* reseller wallet ledger, not a Meta API. Real Meta data available later: `GET /{business_id}/extendedcredits` (credit-line status) + `pricing_analytics`/`conversation_analytics` (spend). A future read-only "Billing & Usage" tab, never a wallet. |
| D5 | **Calls** | **Backlog (BL-107).** Meta calling-settings API is real (`POST /{phone_number_id}/settings`), but the product has **no call-handling** (no dialer/answer surface). Enabling "allow contacts to call you" = rings into the void = foolproof-UI violation. Ships with the actual call feature. |

Slice-A-specific decisions are in §1-§8. Slice B decisions (local-draft lifecycle, StatusBadge-not-status-engine, builder scope, dedicated `templates.*` perms, webhook dual push/pull sync, edit/delete gates, single Meta-shape store, dev shortcuts, media-header upload) are recorded in the §10 handoff so plan 07 starts grilled.

---

## 1. Slice A - what ships

The channel form goes from **2 read-only tabs** (General, Connection) to a **3-tab** form:

```
┌─ Channel form (ResourceForm, read-by-default + Edit toggle) ──────────┐
│  [ Configuration ]   [ Templates ]   [ Profile ]                       │
│   ↑ this plan          ↑ plan 07       ↑ this plan                      │
└───────────────────────────────────────────────────────────────────────┘
```

**Configuration tab** (merges today's General + Connection):
- *Editable (our data):* internal name, workspace, active toggle.
- *Synced read-only (Meta-owned):* phone number (`display_phone_number`), phone_number_id, WABA id, **business account name** (new), **verified name** (new), `last_verified_at`.
- Actions: **Sync** (pull phone + WABA details, stamp `last_verified_at`), **Test Connection** (existing).

**Profile tab** (WhatsApp Business Profile, `GET/POST /{phone_number_id}/whatsapp_business_profile`):
- *Editable + write-through:* `about`, `address`, `description`, `email`, `vertical` (Meta industry enum - SearchSelect), `websites` (max 2).
- *Read-only:* current profile photo (display `profile_picture_url` only - **upload deferred**, BL-108).
- Actions: **Sync Profile** (pull from Meta), **Save** (POST changed fields to Meta → refresh local).

Both tabs honor the Resource shell's read-by-default + global **Edit toggle**; Meta-owned identity fields stay read-only even in edit mode.

---

## 2. Data model (module schema `app_omnichannel`)

No new table - extend `Channel` (`modules/omnichannel/models.py`). Added via the module's **idempotent-ALTER** bootstrap pattern (`bootstrap.py`), **not** alembic (module convention; BL-029 unchanged).

New columns on `Channel`:

| Column | Type | Source | Notes |
|--------|------|--------|-------|
| `business_account_name` | `String` nullable | `GET /{waba_id}?fields=name` | synced read-only |
| `verified_name` | `String` nullable | `fetch_phone_details` (already returns it) | synced read-only |
| `profile_about` | `String` nullable | profile GET | write-through |
| `profile_address` | `String` nullable | profile GET | write-through |
| `profile_description` | `Text` nullable | profile GET | write-through |
| `profile_email` | `String` nullable | profile GET | write-through |
| `profile_vertical` | `String` nullable | profile GET | Meta enum value |
| `profile_website_1` | `String` nullable | profile GET | write-through |
| `profile_website_2` | `String` nullable | profile GET | write-through |
| `profile_picture_url` | `String` nullable | profile GET | display-only |
| `profile_synced_at` | `UTCDateTime` nullable | - | stamped on profile Sync |

> `last_verified_at` already exists and is reused for config-sync staleness. All datetime = `UTCDateTime` (house rule).

**Vertical enum** (Meta `whatsapp_business_profile.vertical`): `UNDEFINED, OTHER, AUTO, BEAUTY, APPAREL, EDU, ENTERTAIN, EVENT_PLAN, FINANCE, GROCERY, GOVT, HOTEL, HEALTH, NONPROFIT, PROF_SERVICES, RETAIL, TRAVEL, RESTAURANT, ALCOHOL, ONLINE_GAMBLING, PHYSICAL_GAMBLING, OTC_DRUGS`. Mirror as a const list FE + BE (parity), drive the SearchSelect + the save-time 422 whitelist.

---

## 3. Backend

**Adapter** (`adapters/whatsapp_cloud.py`) - new methods (all **dev-stubbed** when `credentials.dev` or no `META_APP_ID`):
- `fetch_waba_details(credentials, waba_id) -> {name}` → `GET /{waba_id}?fields=name`. Dev stub: canned name.
- `get_business_profile(credentials, phone_number_id) -> dict` → `GET /{phone_number_id}/whatsapp_business_profile?fields=about,address,description,email,vertical,websites,profile_picture_url`. Dev stub: canned profile.
- `update_business_profile(credentials, phone_number_id, fields: dict) -> None` → `POST /{phone_number_id}/whatsapp_business_profile`. Dev stub: no-op OK.

> `fetch_phone_details` (display_phone_number + verified_name) already exists - reuse for config-sync.

**Service** - new `ChannelProfileService` (`services/`):
- `sync_config(channel_id, tenant_id)` → fetch phone + waba details → write `display_phone_number`, `verified_name`, `business_account_name`, stamp `last_verified_at`. Tenant-scoped repo lookup.
- `get_profile(channel_id, tenant_id)` → return mirrored profile fields (no Meta call; render from DB).
- `sync_profile(channel_id, tenant_id)` → Meta GET → write profile_* cols + `profile_synced_at`.
- `save_profile(channel_id, tenant_id, payload)` → validate (vertical in whitelist, ≤2 websites, email/url shape) → Meta POST changed fields → on success refresh local → 422 on bad input.

> Business/repository split per layering rule. `MessageService` untouched.

**Router** - extend `routers/channels.py`:
- `POST /channels/{id}/sync-config` (gated `channels.manage`) → `sync_config`.
- `GET /channels/{id}/profile` (gated `channels.read`) → mirrored profile.
- `PATCH /channels/{id}/profile` (gated `channels.manage`) → `save_profile`.
- `POST /channels/{id}/profile/sync` (gated `channels.manage`) → `sync_profile`.

> No new permission keys this slice - Config/Profile are channel concerns under existing `channels.read`/`channels.manage`. (`templates.*` keys land in plan 07.)

Schemas (`schemas/`, camelCase via `ApiModel` for the Z-suffix datetime rule): `ChannelProfileOut`, `ChannelProfileUpdate`, extend `ChannelOut` with `businessAccountName`, `verifiedName`, `lastVerifiedAt`, `profileSyncedAt`.

---

## 4. Frontend

Channel form is already a `ResourceForm` (`app/(protected)/omnichannel/settings/channels/[id]/`). Changes:

- **Merge** `channel-form-fields.tsx` General + Connection sections into one **Configuration** tab render. Editable: name, workspace, active. Read-only synced block: phone number, phone_number_id, WABA id, business account name, verified name, last verified - each with a `last_verified_at` "Last synced …" caption (use `useDatetime`). Toolbar: **Sync** + **Test Connection** actions (action registry).
- **New Profile tab** - `components/.../channel-profile-tab.tsx`: FormRow fields (about/address/description/email + vertical SearchSelect + website1/website2), photo shown read-only, **Sync Profile** + **Save** actions. Read-by-default; Edit toggle enables the inputs.
- Layering: UI → `use-channel-profile.ts` hook → `channel-service` (extend existing service trio `.ts/.mock/.real`) → `api-client`. **No fetch/axios in components** (hard-fail rule).
- Mock service returns canned profile + synced config so the **frontend-first** phase + all states (loading/error/success) tune with no backend (methodology step 4).
- Mobile + desktop verified (375px / 1280px) per the responsive mandate - the tab strip already scrolls (`min-w-0` fix from plan 01); profile form stacks single-column on mobile.

Dropdowns = `SearchSelect` (vertical), never bare `<Select>` (BL-062 mandate). Truncated synced values use `ClampedText`.

---

## 5. Dev-safe behavior

Module must fully demo with **no Meta app** (`META_APP_ID`/`SECRET` unset → `credentials.dev` flag):
- `sync-config` → adapter dev stub returns canned business name + verified name; writes them locally so the Configuration tab populates.
- `profile/sync` → canned profile. `PATCH profile` → echoes back (local write succeeds). `profile save` round-trips offline.

Real mode: live Graph calls; verified against a connected number in UAT.

---

## 6. Tests (TDD, both layers)

**Backend** (`tests/`, pytest + httpx, SQLite with `schema_translate_map`):
- `ChannelProfileService.sync_config` writes business name + verified name (dev stub).
- `sync_profile` mirrors all profile fields + stamps `profile_synced_at`.
- `save_profile` validation matrix: bad vertical → 422, >2 websites → 422, bad email → 422; happy path writes local + (mock) Meta POST called with only changed fields.
- Tenant-scoping: another tenant's channel id → 404 (never cross-tenant).
- Permission gates: `channels.read` for GET profile, `channels.manage` for sync/save.

**Frontend** (vitest + RTL): profile form validation mirror (vertical whitelist, website cap, email), SearchSelect render, read/edit toggle, mock-driven loading/error/success.

**E2E** (`e2e/`, real clicks, dedicated tenant + connected dev channel): open channel → Configuration tab → Sync → assert business name appears; Profile tab → Edit → change About + vertical → Save → reload → persisted. Desktop + mobile viewport pass. Produces the Markdown test-execution report (`06-…-test-report.md`).

---

## 7. Migrations / bootstrap

`bootstrap.py create_schema_and_tables` gains idempotent `ALTER TABLE … ADD COLUMN IF NOT EXISTS` for the 11 new `Channel` columns (Postgres) - same pattern as the existing `agent_last_read_at` late-add. No alembic (module convention).

---

## 8. Out of scope (this slice) → backlog

| BL | Item | Reason |
|----|------|--------|
| BL-106 | WABA **Billing & Usage** read-only tab (`extendedcredits` credit-line status + `pricing_analytics` spend chart + WhatsApp-Manager deep-link) | No wallet/top-up API for a Tech Provider; different (analytics) shape of work |
| BL-107 | **WhatsApp Calls** settings + in-app call handling | Product has no call-answer surface; enabling = foolproof dead-end |
| BL-108 | Profile **photo upload** (Meta resumable-upload `/{app_id}/uploads` → `profile_picture_handle`) | Needs `META_APP_ID` + multi-step upload; the upload helper gets built in plan 07 (media headers), so fold this in after |

---

## 9. Slice B handoff (plans 07 + 08) - grilled, ready to write

**Plan 07 - Templates core (Slice B1).** Locked decisions:
- **Local-draft lifecycle** (NOT the status engine - Meta owns the fixed enum + drives transitions externally; engine's configurable-graph/edge-auth are inapplicable & would expose a graph the tenant must never edit): `LOCAL_DRAFT → (Submit) → PENDING → APPROVED/REJECTED/PAUSED/DISABLED`. Render via a frontend **StatusBadge registry**, not the status engine.
- **Dedicated perms** `templates.read` / `templates.manage` (granted to tenant Admin in `install_tenant`); existing send-picker endpoint keeps `conversations.reply`.
- **Builder v1 scope:** categories Marketing + Utility; one language/template; header TEXT **and media (IMAGE/VIDEO/DOC** via Meta resumable upload); body + positional `{{n}}` vars + sample values; footer; buttons Quick-reply / URL (static+dynamic) / Phone / Copy-code. **Omit** Flow + Catalog/Carousel buttons (need resources we don't manage → foolproof) and Authentication (→ B2).
- **Single canonical store** = Meta-shape `components_json`; friendly⇄Meta transform in `lib/whatsapp-template.ts` (parity-pinned FE/BE). New cols: `meta_template_id`, `quality`, `rejected_reason`, `last_synced_at`.
- **Sync = dual push + pull:** webhook (`message_template_status_update` / `_quality_update` / `_category_update` - added to `parse_inbound`; requires those 3 fields enabled in the Meta App Dashboard, runbook) updates the local row; **Sync button** pulls via `list_templates` (also the dev path). **No WS realtime** (not a live inbox). `template.status_changed` workflow event = webhook handler emit-ready but trigger **deferred** (backlog).
- **Edit gate:** LOCAL_DRAFT fully editable; APPROVED/REJECTED/PAUSED → components-only, Save re-submits → PENDING; PENDING/DISABLED → edit hidden. **Delete:** LOCAL_DRAFT = local only; synced = Meta `DELETE` then hard-delete local row; single confirm (no typed-slug, no soft-trash).
- **UI:** Templates tab = embedded `ResourceList` (Status/Name/Category/Quality/Language + ⋮; Search + Status/Category/Language filters + Sync + Submit Template); create/edit = **full-page two-pane builder route** (component editor ‖ live WhatsApp-bubble preview) + read-only **View payload**. Drop the "Label" column (respond.io-proprietary).
- **Dev shortcuts (service layer):** Submit→PENDING+fake `meta_template_id`; Sync promotes local PENDING→APPROVED; edit→PENDING; delete→local. Profile/WABA-detail dev stubs as in this slice.
- **Backend:** new `TemplateManagementService` + `templates.py` router (`/channels/{id}/templates` CRUD + sync); server-side validation (name snake_case ≤512, category/language valid, body required, sample-count == `{{n}}` count, button limits) → `422 {fieldErrors}` mirrored FE.
- **Media-header upload (heaviest):** draft sample file → `storage_for_tenant` key; on Submit → fetch bytes → Meta resumable upload → header handle → component example. Dev stub returns fake handle. (BL-108 profile photo folds in here.)

**Plan 08 - Authentication templates (Slice B2).** Distinct builder shape (Meta auto-generates body/footer; choose code-delivery copy-code/one-tap/zero-tap, button text, `code_expiration_minutes`, `add_security_recommendation`). **Grill separately at plan-08 time.**
