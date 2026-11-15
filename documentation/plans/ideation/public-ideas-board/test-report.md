# PUBLIC-IDEAS-BOARD test execution report (shared-service slice)

Branch `crew/public-ideas-board`. Backend: pytest (in-memory SQLite) + a sandbox-local Postgres 16 for the migration
and the live pass. Frontend: vitest + a fresh production build (`rm -rf .next && npm run build`, `npm start` on :3001)
against uvicorn :8001. Live data: masked, fake rows seeded in the sandbox only (Dealer A on two contact rows with
the same phone, Dealer B, 7 items incl. one hidden, one test). Browser runs: Playwright real clicks (agent-browser is
not installed in the cloud sandbox), evidence in `evidence/live/live-*-{1280,375}.png`.

| AC | Scenario | Precondition | Steps | Expected | Actual | Result |
|---|---|---|---|---|---|---|
| AC-FB-01 | Link is random + stable | contact | mint twice | same token, 43 URL-safe chars | as expected (`test_ac_fb_01`) | PASS |
| AC-FB-02 | Cancel then re-mint | live link | cancel, mint | old 401, new works | as expected (`test_ac_fb_02`) | PASS |
| AC-FB-03 | Planted foreign contact | link row -> other tenant's contact | exchange | 401 | 401 (`test_ac_fb_03`) | PASS |
| AC-FB-10 | Contact principal | live link | exchange, `/me` | kind contact, role Dealer, first name, canManage false | as expected | PASS |
| AC-FB-11 | Bad links / module off | - | exchange malformed, unknown, blank; module INACTIVE | uniform 401 + no-store/noindex/no-referrer | as expected | PASS |
| AC-FB-12 | Cancel / contact delete kills a live session | session open | cancel; delete contact | next request 401 | as expected | PASS |
| AC-FB-13 | Failed exchanges throttled | - | 25 bad exchanges | 429 + Retry-After after 20 | as expected | PASS |
| AC-FB-14 | Phone-shaped name hidden | contact named with a phone | `/me` | name null | null | PASS |
| AC-FB-20 | All = staff non-manager set | draft, test, hidden, merged child, visible | list + roadmap | only the visible item | as expected; live: hidden + test items absent | PASS |
| AC-FB-21 | My requests | own, same-phone twin, same-NAME stranger, hidden own | `mine=true` | own + twin + hidden own; never the stranger | as expected; live: IDEA-0001 + IDEA-0002 (twin row) | PASS |
| AC-FB-22 | One vote per contact | - | vote, vote; intake vote pre-existing | on/off, voter id = contact id, shared with intake | as expected; live 0 -> 1 -> 0 at both widths | PASS |
| AC-FB-23 | Comment, delete own only | staff comment exists | post, delete others', delete own | role Dealer; others' 403/404; own 204 | as expected; live comment shows "Dealer / Dealer" | PASS |
| AC-FB-24 | No submit / hide / note | - | POST idea, PUT hidden, PUT note | 403 each | as expected; live: no Submit form, no sign-out | PASS |
| AC-FB-25 | Detail 404s | hidden-not-mine, draft | GET | 404 | as expected | PASS |
| AC-FB-26 | Ruling (b): text only on own items | own item, other dealer's item with text, untitled item | contact GET detail/list, search | others: problem/outcome/use cases/workaround null, title = number when untitled, search ignores others' text; staff full | as expected (`test_rb_*`, red when the guard is removed); vitest: no fields section; live: see AC-FB-43 | PASS |
| AC-FB-30 | Link shape | contact idea / CRM template base / plain base / foreign contact | `mint_board_link` | `/public/feedback/board/{t}/{n}`; CRM `/feedback/board/{t}/{n}`; plain base; null | as expected | PASS |
| AC-FB-31 | `board_url` on status events | contact idea | status change | payload board_url = requester's link, track_url unchanged | as expected | PASS |
| AC-FB-32 | WhatsApp reply link | conversational intake | confirm / re-confirm / voted | replier's own board link; never the author's (B1); test turn + one-shot keep the per-idea link | as expected (`test_rr1_*`, create-idea + intake-contract suites) | PASS |
| AC-FB-33 | Staff cancel | contact idea + same-phone sibling | endpoint + grace-window action | both links 401; 404 foreign/no contact; 401 unauthenticated; one live link enforced by DB | as expected | PASS |
| AC-FB-40 | Link mode renders the existing board | live link | open link | Feedback first, no Submit, "My requests", Feedback wording | as expected (vitest + live) | PASS |
| AC-FB-41 | Opens the item by number; bad link | link with `/IDEA-0001`; junk token | open | item page; "This link is not valid." | as expected at both widths | PASS |
| AC-FB-42 | Token in memory only | - | open, check storage | no localStorage entry | only pre-existing `nextauth.message`, `language` | PASS |
| AC-FB-43 | Real-click journey at 375 + 1280 | fresh build, live backend | link -> item -> upvote on/off -> comment -> Feedback -> My requests -> Roadmap -> bad link | all steps work, no horizontal scroll, dates dd/mm/yyyy | as expected (`evidence/live/`) | PASS |
| AC-FB-50 | Contracts | - | read docs | board_url + link contract + CRM page contract | `status-events-contract.md`, `feedback-link-contract.md`, `own-ideas-contract.md` | PASS |
| - | Migration 0020 on live Postgres | ideation stamped 0019 | `bootstrap_db` | table + partial unique index created, stamp 0020 | as expected | PASS |

Deferred: CRM `/feedback/{token}` page (second PR, sorento-crm; repo not attached to this sandbox yet). Free-text
exposure settled by owner ruling (b) (AC-FB-26). Low items logged: BL-SS-361, BL-SS-362.
