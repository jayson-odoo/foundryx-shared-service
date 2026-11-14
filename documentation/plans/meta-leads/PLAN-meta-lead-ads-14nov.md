# Meta Lead Ads: is plan 64 the right mechanism? (owner review, 14/11/2026)

**What this is.** A check of the existing Lead Capture plan, not a new plan. Plan 64 and its acceptance criteria are
already written: `documentation/plans/sprint-5/64-lead-capture.md` and `64-lead-capture-acceptance-criteria.md` on
branch `claude/wizardly-albattani-ymi7d2` (not yet on main). The clickable mock is the "Lead Capture Wizard" artifact.
I checked that plan against Meta's current docs and against this repo's code. Below: the answer, what is missing,
the risks, and 5 decisions.

**Nothing is built yet.** No Lead Capture code, table or permission exists on main (no `lead_capture` or `leadgen`
anywhere under `service_backend` or `service_frontend`, and no `lead` key in any `permissions.csv`). What does exist is
the Facebook sign-in, Page list, Page subscribe and Meta webhook intake that omnichannel already uses. Plan 64 reuses
them (Section 6).

**How sure I am about the Meta facts.** This sandbox cannot open `developers.facebook.com` (the address is blocked).
Every Meta fact below comes from search summaries of Meta's own pages, not from reading them. Each one is marked
**(unconfirmed)**, and each is on the list for the 1-day Meta test (spike S-META) on the Foundryx Page.

---

## 1. Short answer to your question

**Yes, the mechanism is right.** It has one Foundryx Meta app, and Shared Service receives every lead from Meta. Each
EcoHub customer connects their own Facebook Page from inside EcoHub with "Continue with Facebook". Shared Service
fetches each lead and pushes it to EcoHub, signed. Nobody edits Shared Service settings to add a Page or a form.

That is better than the earlier chat's fixed `meta_pages` table. That table needs a person at Foundryx to add every
Page and token by hand, and it cannot show a customer that their connection broke. Plan 64 replaces it with a
self-serve source per customer (`lc_source`) that reports its own health. **Recommendation: keep plan 64. Drop the
static-table approach.**

**Does "All forms (recommended)" pick up new ads and forms created later, with nothing to do in EcoHub?**

- **New ads that use an existing form: yes.** Meta sends leads per Page, not per ad, so a new ad is covered.
- **New forms on the same Page: yes, the lead arrives (unconfirmed, but this is how Page-level leadgen is described).**
  In "All forms" mode Lead Capture applies no form filter (artifact brief "forms"; plan section 4, `config_json`).
- **Two gaps in the plan, both easy to close:**
  1. **New questions on a new form.** The field mapping is set once, at setup, for the forms that exist then
     (AC-64-24). A new form's lead still arrives: name, phone and email are matched automatically and other answers
     go to Lead notes. But nothing tells you a new form appeared with questions nobody mapped. **Fix:** show a notice
     on the source in EcoHub ("New form 'Raya promo' found, 2 answers go to Lead notes. Map them"), with the mapping
     reopening on that form only. Decision 3.
  2. **Catching up missed leads on new forms.** The 15-minute catch-up reads "each LIVE form" (AC-64-28). In "All
     forms" mode it must re-read the Page's form list each run, or a lead missed on a new form is never recovered.
     **Fix:** one sentence added to AC-64-28.
- **Not automatic, by design:** a **new Facebook Page** needs one "Connect a source" in EcoHub. So does an ad run from
  a Page that was never connected.

## 2. Setup experience in EcoHub (as the artifact shows it)

**Two ways in, one wizard:** Leads > "All leads | Lead Capture" toggle, and Company Settings > Lead Capture tab.
Both show the same source list and a "Connect a source" button that opens the wizard in a popup.

| Channel | Steps the customer sees | Automatic or guided |
|---|---|---|
| Facebook | Pick channel > Continue with Facebook > Page (picked automatically if only one is shared) > Forms ("All forms" default, or tick some) > Fields (name/phone/email matched, rest to Lead notes) > Send a test lead > Done ("Waiting for the first real lead") | Automatic |
| Instagram | Same as Facebook, plus an "Instagram account" step: reads the account linked to the Page; if none, an animated guide plus "Check again" | Automatic |
| WhatsApp | Pick number (or "Connect a new number" through the existing omnichannel sign-up) > Which chats become leads (from an ad, recommended / every new chat / after a few questions) > Test | Automatic, needs omnichannel |
| Google Ads | Copy webhook URL + key > animated guide for pasting them into the lead form > Google's "Send test data" > Done | Guided |
| Website form | Copy one line of embed code > paste on your site > first submission = test > Done | Guided |
| TikTok | Shown in the mock, **not built** until the TikTok spike confirms how TikTok sends leads | Guided, later |

**Screens the artifact does not have** (drawn in `mock/meta-leads-error-states.html`, fake data only; the artifact's
other screens are reused unchanged):

| # | Situation | What EcoHub shows | Button |
|---|---|---|---|
| E1 | The customer unticked a permission on Facebook's consent screen | "Facebook did not give permission to read leads." | Try again |
| E2 | The customer shared no Page, or is not an admin of the Page | "No Page was shared. You need to be an admin of the Page that runs the ads." | Try again |
| E3 | The Page limits who can read leads (Leads Access in Meta Business settings) | "This Page only lets chosen apps read its leads. Add Lead Capture under Leads Access." Animated guide | Check again |
| E4 | The Page is already connected to another company (`PAGE_IN_USE`) | "This Page is already connected to another account." Nothing about the other company is shown | Choose another Page |
| E5 | The connection broke: password changed, admin removed, or permission removed (`NEEDS_RECONNECT`) | Red "Reconnect" status in the list, plus one email. New leads wait and are caught up after reconnecting | Reconnect |
| E6 | A new form with unmapped questions was found (gap 1 above) | "New form found, 2 answers go to Lead notes." | Map fields |
| E7 | The test lead fails because the form already has an old test lead (Meta allows one at a time, unconfirmed) | Handled silently: the old test lead is removed and the test is sent again | none |

## 3. Meta facts checked (all unconfirmed, see the note at the top)

| Topic | What Meta's pages say (search summary) | Effect on plan 64 |
|---|---|---|
| How leads arrive | Webhook on the Page with field `leadgen`. It carries only ids (`leadgen_id, page_id, form_id, ad_id, adgroup_id, created_time`); the lead is fetched with `GET /{leadgen_id}` | Matches plan (AC-64-26) |
| Subscribe a Page | `POST /{page_id}/subscribed_apps?subscribed_fields=leadgen` with the Page token | Matches. **Risk R1 below** |
| Permissions | Meta's "Retrieving leads" page asks for `leads_retrieval` **and `pages_manage_ads`** for full lead data, plus `pages_show_list`, `pages_read_engagement`, and `pages_manage_metadata` for webhooks. Ad and campaign names need `ads_management` | **Plan D4 is missing `pages_manage_ads`.** `business_management` is not named anywhere for leads. Decision 4 |
| App Review | Lead permissions must pass App Review (Advanced Access) before a Page whose admin has no role on the app can connect. Business Verification is needed for Advanced Access | Matches plan rollout step 4 and AC-64-81 |
| Development mode | Only people with a role on the app get real leads | The owner test on the Foundryx Page works before App Review |
| Tokens | A Page token made from a long-lived user token has no expiry date, but it stops working if that person changes their password, loses Page admin, or removes the app. Facebook Login for Business can instead issue a business "system user" token that does not depend on one person | Plan uses the person-based token plus `NEEDS_RECONNECT`. Decision 2 |
| Meta retries | Meta retries a failed webhook for about 36 hours, then drops it, and may send duplicates | Plan's 15-minute catch-up and dedupe cover this |
| Leads Access | All Page admins can read leads by default. If the business restricts it, the app must be added, or Meta returns error 103 "CRM access has been revoked" | Needs screen E3 |
| Test lead | `POST /{form_id}/test_leads` exists; only one test lead per form at a time | Needs E7 handling (delete, then send again) |
| Instagram leads | Third-party sources say Instagram-placement leads arrive through the linked Page's same webhook | Plan assumes this; confirm in S-META |
| Graph API version | Current is v25 or v26 (2026). **This repo's backend default is v19.0** (`service_backend/app/config.py:377`) and the frontend's is v23.0 (`service_frontend/lib/embedded-signup.ts:21`) | **Risk R4** |
| Rate limits | Lead reads have their own per-Page limit (third-party only) | Low risk at our volume; check headers in S-META |

## 4. Risks found in the code (things plan 64 does not yet say)

- **R1 Two features share one Page subscription.** Omnichannel already subscribes a Page for Messenger with a fixed
  field list that has no `leadgen` (`service_backend/modules/omnichannel/adapters/messenger.py:94` and `:311-312`).
  If a Page subscribe call replaces the app's field list (likely, unconfirmed), then connecting Lead Capture could
  switch off Messenger on that Page. Reconnecting Messenger later could switch off leads. **Fix:** one shared
  "subscribe Page" function that reads the current fields and adds to them (lane S0). This also satisfies your
  reuse-functions rule.
- **R2 Leads would be dropped before Lead Capture sees them.** Omnichannel's webhook drops a `page` event when no
  Messenger channel exists for that Page, and when omnichannel is not active for the tenant
  (`service_backend/modules/omnichannel/services/inbound_service.py:81-93`). It also reads only `messaging[]`, never
  `changes[]` (`adapters/messenger.py:643-651`). Plan D5 says the hand-off to Lead Capture happens "after its own
  handling". It must happen **before** those checks, or a lead-only Page or a lead-only customer never gets a lead.
  One-line correction to D5 and AC-64-26.
- **R3 Login settings are not wired into the deploy.** Meta permissions come from a Login for Business "config id"
  set in Meta's dashboard, not from code (`service_frontend/lib/embedded-signup.ts:87`). The existing Messenger and
  Instagram config ids are not in `docker-compose.yml` or `.github/workflows/deploy.yml`, and plan 64's new
  `LEAD_CAPTURE_LOGIN_CONFIG_ID` needs adding to both (AC-64-80 already says so).
- **R4 Old Graph API version.** v19.0 is from early 2024 and is past or near Meta's end of support (unconfirmed).
  Move to the version S-META tests on, in lane S0, for omnichannel too.
- **R5 Third copy of webhook sending code.** Plan D7 builds its own signed delivery and retry. Omnichannel already
  has one (`modules/omnichannel/services/webhook_delivery.py:45` retry steps, `:85-92` signature). The two retry
  ladders already differ (omnichannel stops at 6 h, plan 64 adds 24 h). **Recommendation:** lift omnichannel's
  sender into one shared function in L4 instead of a copy (backlog BL-SS-210 already names this).
- **R6 Personal data is not encrypted in storage.** Plan 64 encrypts tokens and keys, but stores lead answers
  (`fields_json`, `raw_json`) as plain JSON for 180 days. **Recommendation:** encrypt those two columns with the
  existing helper (`service_backend/app/secrets.py:30` `encrypt_secret`); phone and email stay searchable in their
  own columns. Add to AC-64-50.
- **R7 No history on a source.** Your standing rule: every tracked action shows in the record's History tab. Plan 64
  logs gateway calls (AC-64-72) but not "connected / reconnected / disconnected / mapping changed, by whom". Add an
  AC and use the shared history component.
- **Not a risk:** the earlier chat assumed Keycloak. Shared Service has no Keycloak; it issues its own sign-in tokens
  (`service_backend/app/security.py:51`). EcoHub calls Shared Service with a key kept only in ecohub-backend, and
  Shared Service signs what it sends back (AC-64-62). No Caddy change is needed: everything under `/be/*` already
  reaches the backend (`DEPLOY.md:39-46`).
- **EcoHub code is not re-checked here.** This sandbox cannot open the EcoHub repositories. EcoHub facts come from
  plan 64 fact F9 (statuses in `lib/constants/filter-options.ts:1`, Company Settings tabs in
  `components/company-settings-form.tsx:724-739`, menu in `config/menu.ts`), verified when plan 64 was written.

**Standing rules the artifact breaks** (fix when lane L-ECO builds the real screens, no decision needed):

- Dates read "12 Nov 2026" and "9:54 pm"; they should read 12/11/2026 and 14/11/2026, 9:54 pm.
- "Lead Ref · Client Name" and "Live · test passed" join two values in one cell.
- The sources list button reads "Connect a source"; your list rule asks for "Create" in the toolbar row. Either keep
  "Connect a source" as an exception or relabel it.

## 5. Open checks (spikes)

- **S-META (1 day, the owner's Foundryx Page, app in Development mode).** Confirm everything marked unconfirmed:
  - the permission set
  - that new forms arrive with no action
  - Instagram routing
  - the test-lead call and its one-at-a-time limit
  - token type and what breaks it
  - the Graph version
  - whether subscribing replaces the field list (R1)

  Record real (Foundryx-only) payloads as test fixtures.
- **S-TT.** How TikTok sends leads. TikTok stays hidden until then (already in plan 64).

## 6. Data and reliability: plan 64 already covers

- **Dedupe at both ends:** Shared Service on Page lead id (AC-64-27); EcoHub on lead id, answering OK only after
  saving (AC-64-67).
- **Retries to EcoHub:** 1 m, 5 m, 30 m, 2 h, 6 h, 24 h, then Failed with Redeliver (AC-64-63).
- **Catch-up:** every 15 minutes from Meta (AC-64-28), plus EcoHub's nightly pull (AC-64-65).
- **Unknown answers:** the raw answer is always kept (AC-64-50); custom answers go to Lead notes.
- **Purge:** 180 days (AC-64-54).
- **Audit:** every gateway call is logged (AC-64-72).

Add: R6 (encryption), R7 (history), and gaps 1 and 2 from Section 1. The 15-minute catch-up and the 180-day purge
must also appear on Scheduled Tasks with last run, last error and Run now (standing rule).

**Reuse (no second copy):**

| Existing code | Where |
|---|---|
| Facebook code exchange | `adapters/messenger.py:202` |
| Long-lived token | `adapters/messenger.py:238` |
| Page list | `adapters/messenger.py:269` |
| Page subscribe | `adapters/messenger.py:311` |
| Connect session | `models.py:175`, 5-minute life at `services/meta_connect_service.py:36` |
| Embed token | `routers/embed.py:33` |
| Gateway key pattern | `models.py:754`, `services/api_key_service.py:22` |
| Capabilities | `app/module_platform/capabilities.py:37,54` |
| Safe outbound URL check | `app/services/url_guard.py:140` |

All paths are under `service_backend/modules/omnichannel/` except the last two, which are under `service_backend/`.

## 7. Decisions for you (5)

1. **One Facebook Page, two products (for example EcoHub and another Foundryx product).**
   - (a) Refuse the second connection, as plan 64 does (`PAGE_IN_USE`).
   - (b) Allow it and send each lead to both.

   **Recommend (a) for release 1.** It is simpler and safer for personal data. Change to (b) when a real customer
   needs it.
2. **Kind of Facebook connection.**
   - (a) Tied to the person who clicked Connect. Breaks if they leave or change their password; the customer then
     clicks Reconnect.
   - (b) A business "system user" connection through Login for Business. Does not depend on one person.

   **Recommend (b) if S-META confirms it works for Pages and leads, otherwise (a).** Both keep the Reconnect screen.
3. **New form with questions nobody mapped.**
   - (a) Deliver at once (name/phone/email matched, rest in Lead notes) and show "Map fields" on the source.
   - (b) Hold those leads until someone maps them.

   **Recommend (a).** A held lead is a lost sale.
4. **Facebook permissions to submit for App Review.**
   - (a) Plan 64's list.
   - (b) Plan 64's list plus `pages_manage_ads` (Meta's leads page lists it).
   - (c) As (b), plus `ads_management` so EcoHub shows campaign and ad names.

   **Recommend (b) now, (c) later.** Every extra permission makes App Review harder; ad names are nice to have.
5. **What release 1 contains.**
   - (a) Plan 64 Phase A as written: Facebook, Instagram, WhatsApp ads, Google Ads, website form.
   - (b) Facebook and Instagram plus delivery to EcoHub first; WhatsApp ads, Google Ads and website form in release 2.

   **Recommend (b).** You get Facebook and Instagram leads in EcoHub sooner, and Meta App Review (the slowest step,
   days to weeks) can start in parallel.

The look of the wizard and the app name on Facebook's consent screen are already open questions O-1 and O-2 in plan
64. They are not repeated here.

## 8. Work order (hand-testable slices, release 1 = decision 5b)

| # | Slice (plan 64 lane) | Size | What you can test by hand |
|---|---|---|---|
| 1 | Meta test on the Foundryx Page (S-META) | S, 1 day | Send a test lead from Meta's testing tool; see the real webhook and lead recorded. Confirms Section 3 |
| 2 | Shared Meta plumbing + Page-subscribe fix + Graph version (S0, with R1, R2, R4) | M | Messenger on a connected Page still works exactly as before; omnichannel tests unchanged |
| 3 | Lead Capture module, sources and leads lists, gateway key (L1) | M | Install Lead Capture for a test company; see the empty Sources and Leads lists; create a key |
| 4 | Delivery to EcoHub: signed push, retries, pull, purge (L4, with R5 and R6) | M | Point a test receiver at it; a fake lead arrives signed; stop the receiver and watch the retries and the Failed state; press Redeliver |
| 5 | Wizard shell, all channels simulated (L2) | L | Click through the whole wizard at phone and desktop width with no Meta app |
| 6 | Facebook and Instagram for real (L3, with gaps 1 and 2, screens E1-E7) | L | On the Foundryx Page: Connect, pick forms, map, send a test lead, see Live; remove the app in Facebook and see Reconnect |
| 7 | EcoHub: toggle, Settings tab, popup, receiver (L-ECO, EcoHub repos) | M | From EcoHub: Connect a source, finish, and see the test lead in Leads |
| 8 | Release 2: Google Ads + website form (L5), WhatsApp ads (L6), TikTok after its spike | M each | Per channel, as in the artifact |

App Review and Business Verification (lane OPS) start right after slice 1, because Meta's review takes days to
weeks. No customer outside Foundryx can connect until it passes.
