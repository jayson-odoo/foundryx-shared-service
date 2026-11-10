# E2E evidence - Omnichannel contact data model (plan 25, AC-CDM-42/43)

Recorded via `agent-browser --session s25`, lane frontend `:3003` / backend `:8004` (DB
`foundryx_service_s25`, commit `51888b6`). Real clicks from `/` throughout (sidebar / breadcrumb
navigation), except two documented setup calls (below). Screenshots numbered = the walkthrough
script; `_debug-*` working screenshots were deleted after the run.

## Tenants created this run (timestamped, dedicated - never the shared `default` tenant)

- **Tenant A** (mutates state): `p25-20260905125540` / "P25 CDM Test 20260905125540" -
  `admin@p25-20260905125540.example.com` / `P25Test1234!`. Omnichannel installed via the
  Services (App Store) UI. Workspace "General" id `671d1f4b-b3bd-4712-84a1-637132bf637c`.
- **Tenant B** (isolation probe, no mutation): `p25-noomni-20260905132854` / "P25 NoOmni
  20260905132854" - `admin@p25-noomni-20260905132854.example.com` / `P25Test1234!`. Omnichannel
  NEVER installed (AC-CDM-43's second half).
- Isolation cross-check also used the **`default`** tenant (`demo@example.com`) as tenant B per
  the brief (read-only probes, no mutation to `default`).

## Environment note (infra, not feature code)

The lane's backend (PID 33727) was started with `CORS_ORIGINS` covering only bare
`http://localhost:3001/3002/3003` and a regex capped at ports `300[0-2]` - real clicks from a
tenant subdomain (`platform.localhost:3003`, `p25-*.localhost:3003`) need the ORIGIN header
`http://<slug>.localhost:3003` to pass CORS preflight, which the existing override didn't cover.
Restarted uvicorn (same worktree, same `DATABASE_URL=...s25`, `ENVIRONMENT=development`) with
`CORS_ORIGINS="http://localhost:3001,http://localhost:3002,http://localhost:3003"` and
`CORS_ORIGIN_REGEX='http://[a-z0-9-]+\.localhost:300[0-3]'` (env override only, `.env` file
untouched). New PID 83176, same DB, nothing else changed. Recorded here per the brief's
"restart only if dead" rule read together with "this lane's CORS default doesn't yet cover
subdomain logins on :3003" - a pre-existing environment gap, not plan-25 product code.

## Setup calls (recorded verbatim, NOT part of the scripted evidence)

The new tenant has no demo threads, and the consumer gateway has no `POST .../contacts` create
endpoint (contacts are created only by an inbound message or an outbound send) - per the brief's
allowance, one inbound-webhook simulation was used to materialize a contact via the REAL pipeline
(`InboundService`), then the resulting contact was inspected via the documented gateway read/PATCH
routes (those calls ARE evidence, cited in the walkthrough below):

```bash
# after real-click channel connect (sandbox) produced channel id 8ad68665-6188-41be-86db-62e5a960ed0c
curl -X POST http://localhost:8004/omnichannel/webhooks/8ad68665-6188-41be-86db-62e5a960ed0c \
  -H "Content-Type: application/json" \
  -d '{"object":"whatsapp_business_account","entry":[{"id":"waba-1","changes":[{"field":"messages","value":{
        "messaging_product":"whatsapp",
        "contacts":[{"wa_id":"60123456789","profile":{"name":"P25 Test Contact"}}],
        "messages":[{"id":"wamid.p25-test-1","from":"60123456789","timestamp":"<unix>","type":"text","text":{"body":"Hello from P25 E2E setup"}}]
      }}]}]}'
# -> 200 {"status":"queued"}, processed inline (CELERY_TASK_ALWAYS_EAGER=true)
```

Everything downstream (opening the thread, the Contact panel, editing Details, moving the
lifecycle stage, tagging) is real UI clicks against this real contact.

## Screenshots (1280px unless noted `-375`)

| # | File | Shows |
|---|---|---|
| 01 | `01-new-tenant-details-1280.png` | Platform operator, New tenant form filled (Details tab) for tenant A. |
| 02 | `02-tenant-created-1280.png` | Tenant A created, detail page. |
| 03 | `03-omnichannel-installed-1280.png` | Modules tab, Omnichannel card now "Active" after real-click Install - **AC-CDM-14** setup (`install_tenant` runs). |
| 04 | `04-tenant-admin-home-1280.png` | Logged in as tenant A's admin at `p25-...localhost:3003`; sidebar shows the **Omnichannel** section (module-gated menu). |
| 05 | `05-workspaces-list-1280.png` | Settings > Workspaces list - the seeded "General" (Default) workspace exists from `install_tenant`. |
| 06 | `06-workspace-tabs-1280.png` | Workspace detail tab strip: Settings · Channels · Members · **Lifecycle · Contact fields · Tags** · API Keys - **AC-CDM-29**. |
| 07 | `07-lifecycle-tab-seed-1280.png` | Lifecycle tab renders the REAL seed graph (New Lead/Hot Lead/Payment/Customer partially visible, "Customized" badge = tenant-owned tier) - **AC-CDM-13/14/30**. |
| 08 | `08-lifecycle-edit-mode-1280.png` | Edit toggle on - Tidy/Add status/Save controls appear - **AC-CDM-30** (read-only until Edit). |
| 09 | `09-add-stage-dialog-1280.png` | "New status" dialog, Label = "Nurture 20260905125540". |
| 10 | `10-stage-added-1280.png` | Stage created (POST succeeds immediately; layout not yet saved). |
| 10b/10c | `10b-tidy-1280.png`, `10c-tidy-scrolled-1280.png` | Tidy auto-layout + scroll reveals all 6 stages incl. the new "Nurture" node, unconnected. |
| 11 | `11-edge-drawn-1280.png` | (interim) before the connect-handle drag succeeded. |
| 12 | `12-edge-created-1280.png` | Dragged New Lead's output handle onto Nurture's input handle -> Transition drawer opened "New Lead -> Nurture 20260905125540"; filled action label "Move to Nurture", "Transition created." toast - **AC-CDM-20**. |
| 13 | `13-lifecycle-saved-1280.png` | Clicked Save - "Workspace updated." toast, edge label "Move to Nurture" visible, back to read-only. |
| 14 | `14-contact-fields-tab-1280.png` | Contact fields tab, empty (fresh workspace). |
| 15 | `15-add-field-dialog-1280.png` | "Add custom field" dialog: Name "Source 20260905125540" (Field ID auto-slugged `source20260905125540`), Type = Dropdown list (options editor appears - **AC-CDM-31**), options "WhatsApp Ads" / "Referral". |
| 16 | `16-field-added-1280.png` | Field created - "Field created." toast, row appended (real POST). |
| 17 | `17-tags-tab-1280.png` | Tags tab, empty. |
| 18 | `18-create-tag-dialog-1280.png` | "Create tag" dialog: emoji, name "VIP 20260905125540", colour swatch picker (Brand `#FF5A00` selected) - **AC-CDM-32**. |
| 19 | `19-tag-created-1280.png` | Tag created - "Tag created." toast, row appended, contacts count 0. |
| 20 | `20-api-keys-tab-1280.png` | API Keys tab, empty. |
| 21 | `21-api-key-minted-1280.png` | Minted a workspace API key (setup, to read/verify the contact created via the webhook simulation below). |
| 22 | `22-channels-tab-1280.png` | Workspace's Channels tab: "No channels connected" (points to the Channels page). |
| 23 | `23-channels-page-1280.png` | (same view, prose click no-op - see step 24). |
| 24 | `24-channels-list-1280.png` | Channels list page (via sidebar), empty. |
| 25 | `25-connect-channel-dialog-1280.png` | "Connect a WhatsApp channel" dialog - simulated Meta Embedded Signup (no `META_APP_ID` configured -> dev-safe/simulated), workspace pre-set to General. |
| 26 | `26-channel-connected-1280.png` | Simulated "Connect with Facebook" popup - phone number picker (Foundryx Events Co. +65 8900 1234). |
| 27 | `27-channel-authorized-1280.png` | "Sandbox channel created" confirmation. |
| 28 | `28-channels-list-connected-1280.png` | Channel now listed as connected. |
| 29 | `29-inbox-list-1280.png` | Inbox thread list: the webhook-simulated contact "P25 Test Contact" shows the **🆕 New Lead** lifecycle badge - **AC-CDM-16/39** (new contact -> initial stage; badge on the row). |
| 30 | `30-thread-open-1280.png` | Thread opened - real click on the row. |
| 31 | `31-contact-panel-open-1280.png` | Contact panel toggled open (header button) - Details/Lifecycle/Tags visible - **AC-CDM-34/35**. |
| 32 | `32-details-edit-mode-1280.png` | Details Edit mode - Phone renders read-only text (not an input); First/Last/Email/Language/Country are typed inputs. |
| 33 | `33-details-scrolled-1280.png` | Scrolled the panel to reveal the "Source 20260905125540" custom field as a searchable `SearchSelect`. |
| 34 | `34-source-selected-1280.png` | Source set to "WhatsApp Ads". |
| 35 | `35-details-saved-1280.png` | Clicked Save - back to read view, "Edit" button restored (ONE PATCH, partial merge) - **AC-CDM-06/36**. |
| 36 | `36-details-source-saved-1280.png` | Scrolled down - Source reads "WhatsApp Ads" persisted. |
| 37 | `37-panel-scrolled-1280.png` | Lifecycle "Move to..." + Tags "Add tag..." pickers visible. |
| 38 | `38-tag-added-1280.png` | Added tag "VIP 20260905125540" via the Add-tag picker - chip appears in the panel AND the thread-list row simultaneously (live WS push, no manual refresh) - **AC-CDM-38**. |
| 39 | `39-lifecycle-moved-1280.png` | "Move to..." picker listed ONLY the fireable edges (Hot Lead/Payment/Customer/Cold Lead/**Nurture** - proving the edge added in step 12 is live); moved New Lead -> Hot Lead. Panel badge AND thread-list row both update to "🔥 Hot Lead" in the SAME screenshot, no reload - **AC-CDM-18/37**. |
| 40 | `40-reload-persists-1280.png` | Hard reload (`?thread=<id>` deep link) - Hot Lead badge + VIP tag chip persist on the thread row. |
| 41 | `41-reload-panel-scrolled-1280.png` | Panel after reload: Source "WhatsApp Ads", Lifecycle "Hot Lead", Tags "VIP..." all persisted server-side - **AC-CDM-42 close**. |
| 42 | `42-inbox-thread-375.png` | 375px: Contact panel renders as a full-screen **Sheet** (D14) with Details/Lifecycle/Tags all readable, no clipping. |
| 43 | `43-thread-view-375.png` | 375px: thread list row shows the lifecycle badge + tag chip cleanly. |
| 44 | `44-workspaces-list-375.png` | 375px: Workspaces list. |
| 45 | `45-workspace-tabs-375.png` | 375px: tab strip shows Settings/Channels/Members, horizontally scrollable (scrollbar visible). |
| 46 | `46-workspace-tabs-scrolled-375.png` | 375px: scrolled tab strip reveals Contact fields/Tags/API Keys - **AC-CDM-29 responsive**. |
| 47 | `47-contact-fields-375.png` | 375px: Contact fields list reflows cleanly. |
| 48 | `48-add-field-dialog-375.png` | 375px: Add custom field dialog - buttons stack full-width, no clipping. |
| 49 | `49-tags-tab-375.png` | 375px: Tags list reflows cleanly. |
| 50 | `50-lifecycle-tab-375.png` | 375px: Lifecycle canvas renders inside its own bounded/zoomable box (pan/zoom controls), "Customized" badge, Nurture node visible. |
| 51 | `51-delete-field-confirm-1280.png` | Delete confirmation dialog for "Source 20260905125540": **"1 contact in this workspace holds a value for this field - it will be removed along with the field."** - **AC-CDM-31/04** (confirmation names the count). |
| 52 | `52-field-deleted-1280.png` | Field deleted, list empty - registry row gone. Verified via `GET /api/v1/omnichannel/contacts?search=P25` (gateway) AND a direct `psql` read of `app_omnichannel.contacts.custom_fields_json` on the LIVE Postgres `foundryx_service_s25` DB that the key was stripped (`{}`) - closes the S0 "Carry to S4" item (live-Postgres strip, not just SQLite). |
| 53 | `53-tenant2-noomni-created-1280.png` | Tenant B (`p25-noomni-...`) created via the platform operator UI, Omnichannel NOT installed. |
| 54 | `54-tenant2-home-1280.png` | Logged in as tenant B's admin - sidebar has **no Omnichannel section at all** (module-gated menu; not just hidden tabs) - **AC-CDM-43** second half, PASS-by-absence (there is no workspace form to check tabs on, because the whole Service is invisible). |

## API probes recorded as evidence (not setup)

```bash
# 409 - move to the contact's OWN current stage (no self-loop edge)
curl -X PATCH http://localhost:8004/api/v1/omnichannel/contacts/3d3a2062-... \
  -H "Authorization: Bearer fxw_live_..." -d '{"lifecycle":"hot_lead"}'
# -> 409 {"error":{"code":"lifecycle_move_not_allowed","message":"No transition from '🔥 Hot Lead' to '🔥 Hot Lead'."}}
```

### AC-CDM-43 isolation (tenant B = `default`, `demo@example.com`; tenant A = `p25-20260905125540`)

```
GET /omnichannel/workspaces/{A-ws}/contact-fields   -> 404 {"detail":"Workspace not found."}
GET /omnichannel/workspaces/{A-ws}/contact-tags      -> 404 {"detail":"Workspace not found."}
GET /omnichannel/workspaces/{A-ws}/lifecycle         -> 404 {"detail":"Workspace not found."}
GET /statuses?entityType=omnichannel_contact_lifecycle&scopeId={A-ws}
    - with tenant A's own token -> 200, 6 statuses (control, proves the route exists)
    - with tenant B's token     -> 404 {"detail":"Workspace not found."}
GET /omnichannel/contacts/{A-contact-id} with tenant B's token -> 404 {"detail":"Conversation not found"}
```

(Note: the UAC text says `/api/v1/statuses` - the actual core canvas mount is plain `/statuses`;
`/api/v1/*` is reserved for the public consumer gateway. Confirmed against the real route table
in `app/main.py`.)

## Console / network

`agent-browser errors`/`console` checked after each major navigation - empty throughout except
the expected toasts. No unexpected client errors.

## Responsive design mandates checked

No horizontal page scroll at 375px on any surface except the Lifecycle canvas itself (a pan/zoom
surface, expected) and the tab strip (deliberately horizontally scrollable, pre-existing shell
pattern). Every dropdown used (Field type, Visibility, Source value, Move to, Add tag) is a
searchable `SearchSelect`/native option list, never a bare unfiltered picker. No instructional
copy observed on any new surface. No "Foundryx" wordmark in tenant-facing copy (tenant names are
user-authored "P25 CDM Test ..." / "P25 NoOmni ...").
