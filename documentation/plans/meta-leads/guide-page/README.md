# Lane META-LEADS-GUIDE-PAGE - public lead-capture guide page

Owner ask (18 Nov): "i think the guide better to have a frontend page like maybe a video or step by step guide".

Status: **built** after owner OK on mock v2 (18 Nov 17:04). Page: `service_frontend/app/(public)/public/lead-capture/guide/`, content: `service_frontend/lib/lead-capture-guide.ts`.

## Route and identity

- `/public/lead-capture/guide` in the existing `(public)` group: no login, served by the Shared Service frontend.
  `middleware.ts:30` already covers `/public/lead-capture/:path*` (no framing, no Referer) - the guide inherits that.
- Partner name + logo = the host tenant's public branding (`app/(public)/layout.tsx` already resolves it per host).
  One Shared Service tenant = one partner app, so the partner name is configuration, not text in the page.
  Bare host = a generic "your app".
- Hosts in code samples are built from the page's own origin (wizard URL) and the backend URL, never hard-coded.
- Fake data only: `app.partner.example`, "Test Person", "Sample Home Page", `fxl_live_...`.

## Element -> reused component map

| Element | Reused component / function |
|---|---|
| Partner logo + name | `BrandMark` - `service_frontend/components/platform/branding` (as the wizard does, `connect/page.tsx:83`) |
| Pilot note | `Alert` - `service_frontend/components/ui/alert.tsx` |
| Developers / customer switch | `Tabs` - `service_frontend/components/ui/tabs.tsx` |
| Section cards, step cards | `Card` - `service_frontend/components/ui/card.tsx` |
| Code blocks with Copy | `useCopyToClipboard` - `service_frontend/hooks/use-copy-to-clipboard.ts` (same hook `components/ui/code.tsx` uses) + `Button` |
| Connection states | `StatusBadge` + `SOURCE_STATUS_REGISTRY` - `app/(protected)/lead-capture/sources/components/source-status.ts:7-11` (labels come from the same registry the app uses) |
| Wizard step names / questions | `WIZARD_STEPS` - `service_frontend/lib/lead-capture-wizard.ts:21-28` (the guide imports them, so a renamed step renames the guide) |
| Long text | `ClampedText` - `service_frontend/components/platform/clamped-text.tsx` |
| Screenshots | `next/image` + a ring/number overlay positioned from the capture manifest |
| Video | native `<video controls>` + `<track kind="captions">` (WebVTT written by the capture script) |

## What the code says vs the draft guide text (fixed in the mock)

| Draft said | Code says | Where |
|---|---|---|
| Wizard starts at Facebook sign-in | First step is **Channel** ("Where do the leads come from?"), then Sign in | `lib/lead-capture-wizard.ts:21-28` |
| Test -> Done | After Test the person clicks **Finish setup**, then **Done** on the summary | `connect/page.tsx:176`, `connect/components/done-screen.tsx:47` |
| States "Waiting for test lead", "Needs reconnect" | Labels are **Waiting for test**, **Reconnect** (also Draft) | `sources/components/source-status.ts:7-11` |
| Lead has `createdAt`; pull is by it | Pull orders and filters by **`receivedAt`**; `createdAt` = Meta's time; item also has `sourceId`, `answers`, `attribution`, ... | `read_service.py:153-180`, `mapping.py:171-187` |
| `nextCursor: "c_000123"` | Opaque base64 cursor; empty first `since` page = `nextCursor: null` | `read_service.py:112-114,196` |
| Fields default "Remarks" | Default targets `name/phone/email/notes`, notes labelled "Lead notes" | `mapping.py:16`, `read_service.py:65` |
| Error "already connected" -> choose another | Button text **Choose another Page**; leads-access -> **Check again** + "Open Meta Business settings" | `connect/components/wizard-problem.tsx:22-41` |
| (missing) | "This Page has no lead forms yet" + **Check again**; "This link has expired" | `wizard-steps.tsx:128-149`, `connect/page.tsx:68-75` |
| connect-sessions body | also optional `sourceId` (reopen for Reconnect / new fields) | `schemas.py:221-223`, `gateway.py:275-293` |
| Push: "same lead shape, same id" | The push body is an event envelope `{id: <event id>, type, occurredAt, data: <Lead>}`: dedupe on `data.id`; `POST /webhooks` returns `secret` once | `consumer-integration-guide.md:395-397,444`, `schemas.py:147-148` |
| Channel button "Facebook Page" | The channel card reads **Facebook** | `connect_session_service.py:350` |
| `/be/api/v1/...` | gateway mounts at `/api/v1/lead-capture`; `/be` is the production proxy prefix | `manifest.json` routers, `DEPLOY.md:78` |

## Screenshots + video (re-generate when the wizard changes)

```bash
# 1. local stack, simulated Facebook (META_APP_ID unset), dev seed:
cd service_backend && python -m scripts.bootstrap_db && uvicorn app.main:app --port 8001
cd service_frontend && rm -rf .next && npm run build && npm start      # :3001
# 2. capture (agent-browser CLI; AGENT_BROWSER=<path> to use a local install,
#    AGENT_BROWSER_EXECUTABLE_PATH=<chrome> if it has no browser of its own):
cd service_frontend && npm run capture:lead-capture-guide
# 3. check the PNGs, then: npx vitest run lib/lead-capture-guide.test.ts
```

`scripts/capture-lead-capture-guide.sh` provisions a fresh local tenant named "Partner CRM" via the dev operator
login, installs Lead Capture, mints a gateway key listing the frontend origin, asks for a connect session exactly as a
partner backend does, then drives the real wizard with real mouse clicks. It writes
`public/media/lead-capture-guide/<step>.png`, `walkthrough.webm` (fails the run if 5 MB or more) and
`walkthrough.vtt` (captions), plus `lib/lead-capture-guide-shots.json` (each step's button box, drawn as the
numbered ring). At the end it disconnects the capture tenant's source, so the simulated Page is free for the next
run. Local stack only: it never needs or touches a real key. Playwright is not used (retired, `AGENTS.md:37`).

## Evidence

`evidence/guide-{developers,customer}-{1280,375}.png`: agent-browser full-page captures of the rebuilt frontend.
At both widths: no horizontal scroll, no "Foundryx" text, 8 code blocks, 9 step cards, 8/8 screenshots loaded,
Copy shows "Copied". The video plays with its captions track showing. No `fxl_live_<secret>` pattern in `.next`.
