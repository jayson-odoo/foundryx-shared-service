# SS-FEEDBACK-RENAME: no user-visible "idea" (lane FEEDBACK-RENAME)

Owner ruling 15 Nov: "Let's not call it idea anymore. It's feedback. The type can be
idea, but I don't want to see any front end page or URL that is idea."

## Scope

- Every user-visible word ("Idea", "Ideas", "Ideation") on screens, menus, titles,
  breadcrumbs, buttons, toasts, emails and WhatsApp replies becomes "Feedback".
- Every frontend page URL that says idea/ideas/ideation moves to a feedback path; every
  old URL keeps working through a permanent (308) redirect, query string kept.
- Item numbers show as `FB-0016` (stored `IDEA-0016` unchanged) - pending crew-ask.
- Stays as is: DB tables (`app_ideation.*`), Python modules, API field names, the type
  value `idea` (shown to users with its label), backend API paths consumed by the CRM.

## URL map (old -> new, permanent redirect)

| Old | New |
|---|---|
| `/ideation/ideas` | `/feedback` |
| `/ideation/ideas/new` | `/feedback/new` |
| `/ideation/ideas/:id` | `/feedback/:id` |
| `/ideation/board` | `/feedback/board` |
| `/ideation/business-requirements[/:id]` | `/feedback/business-requirements[/:id]` |
| `/ideation/embed-connections` | `/feedback/embed-connections` |
| `/embed/ideas/portal/feedback` | `/embed/feedback/portal/list` |
| `/embed/ideas[/...]` | `/embed/feedback[/...]` |
| `/public/ideas/:token` | `/public/feedback/:token` |
| `/portal/ideas/feedback` | `/portal/feedback/list` |
| `/portal/ideas[/...]` | `/portal/feedback[/...]` |

The portal's "Feedback" tab subpage was `.../feedback`; under the new `/portal/feedback`
root that would read `/portal/feedback/feedback`, so it is `/portal/feedback/list`
(and `/embed/feedback/portal/list`). Roadmap stays at the root, changelog at `/changelog`,
an item at `/:id`.

Item number (crew answer 1a): shown as `FB-0016` through ONE formatter per layer
(`lib/feedback-number.ts formatFeedbackNumber`, `numbering.display_idea_number`); the
stored value and the wire field stay `IDEA-0016`.

Backend status link (`sinks.py mint_idea_link`): on the shared-service default origin it
now points at `/public/feedback/{token}` (old `/public/ideas` 308s). A tenant
`public_link_base_url` is the tenant's own host and config: a `{token}` template is used
as written, and a plain origin keeps `/public/ideas/{token}` so no link breaks on a host
we do not serve (the CRM redirects its own old paths; editing the setting is config).

Known follow-up (CRM side): the intake response and status-event payloads keep the
stored `idea_number` (`IDEA-0016`) by design; a consumer that prints it formats it as
`FB-0016` itself (crew lane FEEDBACK-RENAME-CRM).

## Tests (red first)

- `lib/feedback-routes.test.ts` (+ `lib/feedback-redirects.wiring.test.ts`): every old URL maps to its new URL, permanent.
- Rendered-text tests on the list, detail, board, portal, public status page: no "Idea".
- Backend: status link path, reply/email text and the displayed number.
