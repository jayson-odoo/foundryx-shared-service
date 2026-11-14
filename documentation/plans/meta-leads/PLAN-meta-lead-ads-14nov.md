# Meta Lead Ads: is plan 64 the right mechanism? (owner review, 14/11/2026, decisions taken ~22:45)

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
     go to Lead notes. But nothing tells you a new form appeared with questions nobody mapped. **Fix (decided, AC-64-35):** show a notice
     on the source in EcoHub ("New form 'Raya promo' found, 2 answers go to Lead notes. Map them"), with the mapping
     reopening on that form only. Decision 3.
  2. **Catching up missed leads on new forms.** The 15-minute catch-up reads "each LIVE form" (AC-64-28). In "All
     forms" mode it must re-read the Page's form list each run, or a lead missed on a new form is never recovered.
     **Fix (folded into AC-64-28).**
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
other screens are reused unchanged). **Approved by the owner 14/11/2026 22:45 ("ok")**, v2 including the Page
sharing switch:

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

## 7. Decisions taken (owner, 14/11/2026 ~22:45)

His words: "for meta, 1 it should be toggleable per product, 2b, 3a, 4b, 5b".

| # | Decision | Ruling | Now in plan 64 |
|---|---|---|---|
| 1 | One Facebook Page, more than one product | **A toggle per product** (new option, see section 8) | D13, AC-64-25, AC-64-36, AC-64-37 |
| 2 | Kind of Facebook connection | **(b)** business "system user" connection if the Meta test confirms it, otherwise (a); Reconnect stays | D4, AC-64-20 |
| 3 | New form with unmapped questions | **(a)** deliver at once, "Map fields" notice on the source | D14, AC-64-35 |
| 4 | Facebook permissions for App Review | **(b)** plan 64 list plus `pages_manage_ads`; ad and campaign names later | D4, AC-64-20 |
| 5 | Release 1 | **(b)** Facebook + Instagram + delivery to EcoHub; WhatsApp ads, Google Ads and website form in release 2 | section 6 |

Also folded into plan 64: gap 2 (AC-64-28: in "All forms" mode every catch-up run re-reads the Page's form list),
R1 (one shared Page-subscribe function, D15), R2 (hand-off before omnichannel's checks, D5 and AC-64-26), R6 (lead
answers encrypted, AC-64-55) and R7 (History tab, AC-64-38). Plan 64 is copied onto this branch with those edits
(`documentation/plans/sprint-5/64-lead-capture*.md`), so its original branch `claude/wizardly-albattani-ymi7d2` is
now superseded by this PR.

## 8. Decision 1 in detail: sharing a Facebook Page between products

**What the customer sees.** One switch in each product's Lead Capture settings (in EcoHub: Company Settings > Lead
Capture, above the source list):

> **Share Facebook Pages with other products** - Off
> *When on, a Page you connect here can also send its leads to another product that has this switched on.*

**Default: Off.** That matches plan 64's original behaviour, and no company's leads go anywhere new unless it chose so.

**The rule when a Page is connected.**

| This product's switch | Every product already on that Page | Result |
|---|---|---|
| Any | (nobody else on the Page) | Connects |
| On | All On | Connects. Each new lead goes to every product on the Page, each with its own field mapping |
| Off | Any | "This Page is already connected to another account." (E4) |
| On | At least one Off | Same E4 message. It never says which side said no, so nobody learns about the other company |

- **Turning the switch Off later** stops new products joining. Pages already shared stay connected, and the setting
  shows "Shared with 1 other product" so the effect is visible.
- **One product disconnecting** never stops the others. The Page stops sending to Shared Service only when the last
  product leaves it.
- **Each product still needs a Page admin** to sign in and pick the Page. Sharing never hands one company's Page to
  another without that Page's own admin consenting.

**What changes underneath** (for the build lanes):

- **Index.** The old one-Page-one-company index `(platform, Page id)` becomes `(company, platform, Page id)`: one live
  source per Page per company. The cross-company rule moves into the connect step, which holds a database lock on
  that Page id while it checks, so two companies connecting at the same moment cannot both slip past.
- **Setting storage.** A small `lc_settings` table, one row per company. Staff change it in Shared Service; EcoHub
  changes it through `GET|PUT /api/v1/lead-capture/settings`.
- **Lead delivery.** For a shared Page, the lead is fetched from Meta once. It is then stored and delivered once per
  product, each mapped its own way and sent only to that product. Each copy has its own retries and its own History.
- **The 180-day purge and the duplicate check** stay per company, so nothing crosses between products.

**Who sets it.** Assumption: one EcoHub customer company is one Shared Service account. EcoHub decides whether to
show the switch to its customers or set it once for all of them through the API. If that assumption is wrong, crew
should tell me before lane L1.

## 9. Release 1 build lanes (no code until you approve this list)

Order is the dependency order. Lanes 3 and 4 can run in parallel after lane 2; lane 5 can start alongside them with
everything simulated.

| # | Lane (plan 64 id) | Size | What it delivers | What you test by hand |
|---|---|---|---|---|
| 1 | **Meta test, 1 day (S-META)** | S | On the Foundryx Page with the app in Development mode, confirms every fact marked unconfirmed in section 3: <br>- the permission list, and whether the system-user connection works (decision 2) <br>- that new forms arrive with nothing to do <br>- that Instagram leads come through the Page <br>- the test-lead call and its one-at-a-time limit <br>- whether subscribing replaces the field list (R1) <br>- the Graph version <br>Real payloads from Foundryx's own Page are kept as test files | Submit a lead with Meta's Lead Ads Testing Tool; we show you the lead as it arrived. You get a one-page result with "confirmed / changed" per fact, and any change to plan 64 before lane 2 starts |
| 2 | **Shared Meta plumbing (S0 + R1, R2, R4)** | M | Facebook sign-in, Page list and Page subscribe moved to one shared place. Subscribe keeps every feature's fields. Leads are handed over before omnichannel's checks. One current Graph version | Messenger on a connected Page works exactly as before (send and receive a message). Nothing new to see yet |
| 3 | **Lead Capture module (L1 + D1 switch)** | M | Install, permissions, Sources and Leads lists, gateway key, published EcoHub fields, the sharing switch and its API | Install Lead Capture for a test company. See the empty Sources and Leads lists, flip the sharing switch, and see the change in the source's History |
| 4 | **Delivery to EcoHub (L4 + R5, R6)** | M | Signed push with retries and Redeliver, built on ONE shared sender with omnichannel's. Pull API, encrypted lead answers, 180-day purge on Scheduled Tasks, consumer guide | Point a test receiver at it and send a fake lead: it arrives signed. Stop the receiver and watch the retries and the Failed state. Press Redeliver. Run the purge from Scheduled Tasks |
| 5 | **Wizard shell (L2, Facebook + Instagram only)** | L | Hosted wizard, popup hand-back to EcoHub, step engine, animated guides, done screen. Every step simulated; WhatsApp, Google Ads, website form and TikTok hidden | Click through Facebook and Instagram end to end at phone and desktop width, light and dark, with no Meta app |
| 6 | **Facebook + Instagram for real (L3 + decisions 1-3, screens E1-E7)** | L | Real sign-in, Page and forms, field mapping, subscribe, lead fetch, 15-minute catch-up with form-list re-read, "Map fields" notice, Reconnect, shared-Page delivery | On the Foundryx Page: Connect, Send test lead, see Live. Add a new form and submit to it: the lead arrives and "Map fields" shows. Remove the app in Facebook and see Reconnect. Connect the same Page from a second test company with the switch On on both, and see the lead reach both; then repeat with one switch Off and see the "already connected" message |
| 7 | **EcoHub (L-ECO, EcoHub repos)** | M | Leads > Lead Capture toggle, Company Settings > Lead Capture tab with the sharing switch, popup, ecohub-backend receiver that creates the Lead | From EcoHub: Connect a source, finish, and see the test lead in Leads as New. Send it twice and still see one lead |
| 8 | **Meta App Review + Business Verification (OPS)** | S of our time, days to weeks at Meta | Runbook and screencast recorded on the Foundryx Page. Submitted right after lane 1 so Meta's wait runs in parallel | Nothing to click. Until it passes, only Pages whose admins have a role on the Foundryx app can connect |

Release 2 (after release 1 is live): Google Ads + website form (L5, M), WhatsApp ads (L6, M), then TikTok after
its spike.

The plan 64 lane order changes slightly: L4 moves ahead of L2 so delivery is testable before any wizard exists.
security-reviewer stays mandatory on lanes 2, 4, 5 and 6.

## 10. Which Meta app, and do we really need App Review? (owner question 14/11/2026 ~22:50)

### 10.1 We already have a Meta app, and plan 64 reuses it

**What the code shows:**

- **App id and secret** come from deploy secrets `META_APP_ID` / `META_APP_SECRET`
  (`.github/workflows/deploy.yml:366-367`, `docker-compose.yml:55-56`, `service_backend/app/config.py:375-376`).
  The values are not in the repo.
- **Products added:** WhatsApp and Facebook Login for Business, per the go-live runbook
  (`documentation/plans/sprint-1/04-omnichannel-embedded-signup-runbook.md:7-8`).
- **One webhook address for all Meta traffic:** `https://<host>/be/omnichannel/webhooks/<id>`. The route is
  `service_backend/modules/omnichannel/routers/webhooks.py:54` mounted at `modules/omnichannel/manifest.json:131`, and
  Caddy strips `/be` (`DEPLOY.md:45`). Meta's payload, not the address, decides the company
  (`modules/omnichannel/services/inbound_service.py:76-78`).
- **Verify token:** `META_WEBHOOK_VERIFY_TOKEN` (`deploy.yml:370`).

**Permissions the app uses today:**

- WhatsApp: `whatsapp_business_management` and `whatsapp_business_messaging`
  (`modules/omnichannel/adapters/whatsapp_cloud.py:123-124`).
- Messenger and Instagram: the Messenger and Instagram connect use Login for Business config ids
  (`service_frontend/lib/embedded-signup.ts:31-34`). Their permission lists live in Meta's dashboard, not in the repo.

**App Review status:** the repo records it as NOT done. Backlog BL-017 "Meta App Review + Business Verification" is
still Open (`documentation/backlogs/backlog.md:40`). WhatsApp therefore works only for numbers whose owner has a role
on the app (Development mode or Standard Access). **Owner to confirm** what Meta's dashboard shows today.

**Conclusion:** plan 64 adds the lead permissions and the Page `leadgen` webhook field to this same app. One
App Review submission can cover both BL-017 (WhatsApp) and the lead permissions.

### 10.2 When App Review is needed (unconfirmed: Meta's pages cannot be opened from this sandbox)

| Who connects | Needs App Review? |
|---|---|
| Foundryx's own Page, connected by someone with a role on the app (admin, developer, tester) | **No.** Standard Access covers people with a role on the app, so lane 1 and every Foundryx hand test run today |
| An EcoHub customer's Page, connected by that customer's own staff | **Yes.** Advanced Access for `leads_retrieval`, `pages_manage_ads`, `pages_manage_metadata`, `pages_show_list`, `pages_read_engagement`. Business Verification of Foundryx's business portfolio is required for Advanced Access. If decision 2's system-user connection is used, Login for Business may add `business_management` (lane 1 checks) |
| Workaround without App Review | Each customer could make a Foundryx staff member an admin of their Page, or share the Page with Foundryx's business portfolio as a partner. Foundryx would then connect it for them. This breaks "self-serve from EcoHub" and puts staff on every customer's Page. **Not recommended** beyond the first one or two pilot customers |

So: **yes, App Review is needed** for the product you described (customers connect their own Pages from EcoHub). It
is not needed to build and test everything on the Foundryx Page. Lanes 1-7 do not wait for it; only going live for
customers does.

### 10.3 What the owner provides or clicks, and what crew prepares

| # | Item | Who | Notes |
|---|---|---|---|
| 1 | **Business portfolio** (Meta Business Manager) that owns the app, with its id | Owner | The app must belong to the business being verified |
| 2 | **Business Verification:** legal company name exactly as registered, registration document, business address, business phone, website domain, and an email on that domain (or domain verified by DNS / meta tag) | Owner | Documents only the owner holds. Meta may call or email the phone/email for a code |
| 3 | **Domain verification** of the website domain in Business Settings | Owner clicks; crew can add the meta tag if the domain is ours | Needed if Meta asks for it during verification |
| 4 | **App roles:** owner stays Admin; add any staff who will test (Admin or Tester). Crew has no Facebook account, so every Facebook-side click in testing is the owner's or staff's | Owner | Also needed for lane 1 |
| 5 | **App settings > Basic:** app icon (1024x1024), category (Business), contact email, Privacy Policy URL, Terms URL, Data Deletion URL | Owner pastes; crew prepares the pages and the icon file | The three URLs must be public pages |
| 6 | **Privacy Policy page** covering lead data: what is collected, why, the 180-day retention, deletion, contact | Crew drafts, owner approves the wording | Public page on our domain. White-label question: Foundryx-branded, since it is the app's policy |
| 7 | **Terms of Service page** | Crew drafts, owner approves | Same |
| 8 | **Data deletion:** a public instructions page, plus optionally Meta's data deletion callback endpoint | Crew builds | Callback = one small endpoint; can be added to lane 4 |
| 9 | **Use-case text per permission** (why we need each, how it is used, what the user sees) | Crew writes | From the wizard copy |
| 10 | **Screencasts per permission:** sign in, pick Page, pick forms, test lead, lead appears | Crew scripts; **owner records** (Facebook login is his) | Recorded on the Foundryx Page in Development mode after lane 6 |
| 11 | **Reviewer test access:** a Shared Service test company login + written steps; Meta reviewers use their own Facebook test account to connect | Crew prepares the test company and steps; owner pastes them into the submission | No real customer data |
| 12 | **Submit** the review and answer Meta's follow-up questions | Owner submits (dashboard access); crew drafts every answer | Typical wait: days to weeks (unconfirmed) |
| 13 | **Annual Data Use Checkup / Data Protection Assessment** when Meta asks | Owner signs; crew drafts | Recurring, yearly (unconfirmed) |

### 10.4 What lane 1 (Meta test, 1 day) needs from the owner

Secrets go through crew's secret channel only, never in a PR or comment.

1. **App id + app secret** of the existing app, for the test copy.
2. **Foundryx Page id**, with at least one Instant Form. Crew can guide the owner through creating one; no running
   ad is needed.
3. **A system-user token** from the Foundryx business, assigned to the Foundryx Page with the lead permissions, for
   the API checks. Alternative: the owner signs in once through the test copy's "Continue with Facebook".
4. **Owner's yes for crew to add the `leadgen` field** to the app's Page webhook subscription. It is the same app
   and the same address, and Messenger is unaffected. This can be done by API with the app token, or by the owner
   in the dashboard.
5. **A public address for the test copy** so Meta can reach it (crew sets up a tunnel), and **network access to
   graph.facebook.com** from the test machine.
6. **About 20 minutes of the owner's time:**
   - one Facebook sign-in
   - one Lead Ads Testing Tool submission
   - one new test form, to prove new forms arrive with no action
