# Meta Lead Ads: prod release checklist (EcoHub first)

Owner, 18 Nov: "Meta lead gen works end to end on the test app; next = deploy to prod and tell EcoHub how to use it."
Names only, no values. Code refs are on `main` unless a PR branch is named.

## 1. What must be in prod, in merge order

Already on `main` (prod needs a build that contains them; check the deployed sha):

| PR | What it gives EcoHub |
|---|---|
| #237 S0 | Core Meta plumbing: sign-in code exchange, Page list, Page subscribe/unsubscribe |
| #245 P | Lead Capture spine: webhook -> fetch lead -> store -> push / pull |
| #251 L-A | Form questions, test lead, the "waiting for test" state that turns LIVE |
| #258 L-B | Form filter, 15-minute catch-up, token health + reconnect, disconnect |

Still open, merge in this order:

| Order | PR | Required for EcoHub? | Why |
|---|---|---|---|
| 1 | **#262 L-C** wizard | **Yes** | Without it a Page can only be connected by our staff script with a token from the Foundryx business, so only Pages owned by Foundryx work. L-C adds the "Connect" link EcoHub opens (connect-sessions), Facebook sign-in for the customer's own Page, and the Sources / Leads screens. It carries migration `0005_lc_connect_session` and bumps the module to 0.1.2 |
| 2 | **#259 L-D** keys / delivery / fields screens | **No, not to receive leads** | Everything EcoHub calls (`GET /leads`, `POST /webhooks`, `PUT /fields`) is already on `main`, and our admin can create the key with the staff API. L-D only adds the screens for this, so nobody needs the API (owner rule "no backend configuration"). Merge after #262: the only conflict between them is `service_frontend/config/menu.config.tsx` |
| any | #236 (this plan PR) | No | Docs only |

Gap in both PRs: no screen sets a key's **allowed origins** (the EcoHub web address the wizard reports back to). Until one exists it is one staff call: `PUT /lead-capture/keys/{id}/origins` (#262, `routers/staff.py:105`).

Deploy notes:
- Deploy with `bootstrap_db` (module migration `0005`), not `init_db`.
- Celery worker + beat must run in prod: the webhook only queues the lead and the worker fetches it (`app/workflow_engine/worker.py:345`), and the 15-minute catch-up runs on beat (`docker-compose.yml:303`).
- In Services, press **Update** on Lead Capture for any company that already has it (0.1.1 -> 0.1.2).

## 2. Prod config

### Server environment (names only)

| Name | Used for |
|---|---|
| `META_APP_ID` | The LIVE Meta app. Also tells the wizard to use real Facebook (unset = simulated) |
| `META_APP_SECRET` | Code exchange + webhook signature check (`app/integrations/meta/signature.py:15`). It is ONE secret, so WhatsApp and Lead Ads must be on the SAME Meta app in prod |
| `LEAD_CAPTURE_LOGIN_CONFIG_ID` | Facebook Login for Business configuration for lead capture (#262 `app/config.py:391`). Unset = the wizard does not offer Facebook |
| `META_GRAPH_VERSION` | Graph version. The default is `v19.0`; set it to a current version (see note below) |
| `META_WEBHOOK_VERIFY_TOKEN` | The token typed into the Meta webhook setup (handshake, `modules/omnichannel/routers/webhooks.py:23`) |
| `FERNET_KEY`, `OMNICHANNEL_FERNET_KEY` | Encrypt the stored Page tokens. Must be stable |
| `FRONTEND_URL` | The host of the wizard link (#262 `connect_session_service.py`, `url = FRONTEND_URL + /public/lead-capture/connect`) |
| `PUBLIC_BASE_URL`, `CORS_ORIGINS`, `NEXT_PUBLIC_BACKEND_API_URL` | Existing; the frontend one is baked at build time |

The deploy workflow already passes all of these (#262 adds `LEAD_CAPTURE_LOGIN_CONFIG_ID` to `.github/workflows/deploy.yml`, `docker-compose.yml` and `.env.example`), so add each one as a GitHub secret / var. The lead wizard reads the app id and config id from the server, so it needs no `NEXT_PUBLIC_*` value.

**Not verified:** whether `v19.0` is still served. Meta keeps each version for about two years and v19.0 came out in early 2024, so set `META_GRAPH_VERSION` (and `NEXT_PUBLIC_META_GRAPH_VERSION`) to the version the app dashboard shows as current.

### On the LIVE Meta app

| Where | Value |
|---|---|
| App settings > Basic > App domains | The prod SS host (the host in `FRONTEND_URL`) |
| Facebook Login for Business > Settings > Valid OAuth Redirect URIs | `https://<prod SS host>/wa-callback`. This is the same callback the WhatsApp signup uses (#262 `service_frontend/lib/embedded-signup.ts:40,105`), so it may already be listed |
| Facebook Login for Business > Configurations | A new configuration with token type "User access token" and these permissions: `pages_show_list`, `pages_manage_metadata`, `pages_read_engagement`, `leads_retrieval`, `pages_manage_ads` (#262 `meta_leads.py:43`). Its id becomes `LEAD_CAPTURE_LOGIN_CONFIG_ID` |
| Webhooks > object **Page** | Callback `https://<prod SS host>/be/omnichannel/webhooks/lead`, verify token = `META_WEBHOOK_VERIFY_TOKEN`, subscribe the field **`leadgen`**. Any last path segment works; `lead` is the convention from the test run |
| Per Page | Nothing to do by hand: the connect step subscribes the Page's `leadgen` itself (core `subscribe_page_fields`) |
| App mode | Live |

## 3. Meta review before a business outside the app (EcoHub's customers) can connect

| Item | Needed? | Status |
|---|---|---|
| Advanced Access for `leads_retrieval`, `pages_manage_ads`, `pages_manage_metadata`, `pages_read_engagement`, `pages_show_list` | **Yes**, via App Review, with the screencast in `app-review-pack.md` | Not submitted (plan review doc, section on App Review) |
| `business_management` | **No** for this flow: the configuration uses a user token and lists the Pages the person manages. Needed only if the configuration is switched to a system-user token | - |
| Business Verification | **Yes**, required for any Advanced Access | Done: the Foundryx business portfolio was verified 03/11/2025 (`app-review-pack.md:7`) |
| Leads Access (customer side) | Only when the customer's business restricts which apps read its leads: they add our app under Business settings > Integrations > Leads Access | The wizard shows this case as its own error screen |

Until App Review passes, only people who have a role on the Foundryx Meta app can connect a Page. For a pilot, add the EcoHub customer's Page admin as an app Tester.

Meta's rules, from Meta's docs:
- "Permissions with Standard Access can only be requested from app users who have a role on the requesting app." Advanced Access "can be requested from any app user", is approved per permission through App Review, and "Business Verification is required to get Advanced Access". Source: [Access Levels](https://developers.facebook.com/docs/graph-api/overview/access-levels/).
- Business Verification has been required for Advanced Access since 1 Feb 2023. Source: [Meta developer blog](https://developers.facebook.com/blog/post/2023/02/01/developer-platform-requiring-business-verification-for-advanced-access/).
- Lead reads need `leads_retrieval`, with `pages_manage_ads`, plus the Page permissions for webhooks. Source: [Retrieving Leads](https://developers.facebook.com/docs/marketing-api/guides/lead-ads/retrieving), as read on 15/11 (plan review doc).

**Not verified today:** `developers.facebook.com` was blocked in this session on 18/11, so the quotes above come from search results. Meta has started renaming "Standard / Advanced Access" to "Limited / Full Access" on some pages, so the dashboard labels may differ.

## 4. EcoHub

See `docs/lead-capture/ecohub-quickstart-simple.md` (updated for prod).
