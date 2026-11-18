# Lane META-LEADS-GUIDE-PAGE - public lead-capture guide page

Owner ask (18 Nov): "i think the guide better to have a frontend page like maybe a video or step by step guide".

Status: **mock v1, waiting for owner OK** (`mock-v1.html` in this folder). Nothing is built until then.

## Route and identity

- `/public/lead-capture/guide` in the existing `(public)` group: no login, served by the Shared Service frontend.
  `middleware.ts:30` already covers `/public/lead-capture/:path*` (no framing, no Referer) - the guide inherits that.
- Partner name + logo = the host tenant's public branding (`app/(public)/layout.tsx` already resolves it per host).
  One Shared Service tenant = one partner app, so the partner name is configuration, not text in the page.
  Bare host = a generic "your app".
- Hosts in code samples are built from the page's own origin (wizard URL) and the backend URL, never hard-coded.
- Fake data only: `app.partner.example`, "Test Person", "Sunrise Homes (test)", `fxl_live_...`.

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
| `/be/api/v1/...` | gateway mounts at `/api/v1/lead-capture`; `/be` is the production proxy prefix | `manifest.json` routers, `DEPLOY.md:78` |

## Screenshots + video

A committed capture script drives the real wizard page on the simulated Facebook path with fake data and writes
PNGs + `manifest.json` (button box per step) + a webm + a WebVTT caption file into `public/media/lead-capture-guide/`.
Run on demand (npm script, documented here) when the wizard changes.

Open question for crew: the brief names Playwright, but Playwright is retired from this repo
(`AGENTS.md:37`, guard test `service_frontend/no-playwright.guard.test.ts` fails on the word). Proposal: the
`agent-browser` CLI (the repo's sanctioned browser tool) - see the PR's crew-ask.
