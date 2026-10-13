# Head browser pass (9ea985db)

Data: the local Postgres reset to just `scripts/seed_idea_portal.py`. Backend :8001, production frontend build :3001. Playwright and Chromium, real clicks. The embed is reached with a Sorento-shaped assertion through `POST /embed/session` → `/embed/ideas/portal#token=` (CRM user, `ideas_manage` not sent). Screenshots are `head-*.png` in this folder.

| Result | Surface | Width | Check | Detail |
|---|---|---|---|---|
| PASS | SS app | 1280 | signed out -> sign-in screen, staff only |  |
| PASS | SS app | 1280 | sign-in returns to /portal/ideas |  |
| PASS | SS app | 1280 | roadmap columns in order | Under review / Planned / In progress / Complete |
| PASS | SS app | 1280 | IDEA-0010 + IDEA-0014 under review |  |
| PASS | SS app | 1280 | rejected idea not on roadmap |  |
| PASS | SS app | 1280 | no horizontal scroll (roadmap) |  |
| PASS | SS app | 1280 | idea page: Business problem shown, dropped fields absent |  |
| PASS | SS app | 1280 | upvote 0 -> 1, voters list You/Staff |  |
| PASS | SS app | 1280 | activity newest first: like, comment(+reply), upvotes, submitted | comment_like,comment,upvotes,submitted |
| PASS | SS app | 1280 | manager: hide switch toggles |  |
| PASS | SS app | 1280 | no horizontal scroll (idea) |  |
| PASS | SS app | 1280 | feedback list (hidden idea visible to a manager) | 8 rows |
| PASS | SS app | 1280 | submit -> own idea page, Your idea, use cases as list |  |
| PASS | SS app | 1280 | changelog: delivered idea with seeded note |  |
| PASS | SS app | 1280 | manager edits changelog note |  |
| PASS | SS app | 375 | no horizontal scroll (Roadmap) | scrollWidth 375 |
| PASS | SS app | 375 | no horizontal scroll (Feedback) | scrollWidth 375 |
| PASS | SS app | 375 | no horizontal scroll (Changelog) | scrollWidth 375 |
| PASS | SS app | 375 | no horizontal scroll (idea), stacks | scrollWidth 375 |
| PASS | SS app | 375 | sign-out -> portal sign-in screen (staff login ended) |  |
| PASS | SS app | 375 | reopen after sign-out stays signed out |  |
| PASS | Embed | 1280 | roadmap renders via embed SSO |  |
| PASS | Embed | 1280 | no tenant header / avatar / sign-out button |  |
| PASS | Embed | 1280 | hidden idea not shown (CRM user, not manager) |  |
| PASS | Embed | 1280 | no horizontal scroll (roadmap) | scrollWidth 1280 |
| PASS | Embed | 1280 | idea page opens inside the iframe route |  |
| PASS | Embed | 1280 | CRM user upvotes |  |
| PASS | Embed | 1280 | CRM user comments, shown as Staff |  |
| PASS | Embed | 1280 | no manager controls (hide switch / note) |  |
| PASS | Embed | 1280 | no horizontal scroll (idea) | scrollWidth 1280 |
| PASS | Embed | 375 | roadmap renders via embed SSO |  |
| PASS | Embed | 375 | no tenant header / avatar / sign-out button |  |
| PASS | Embed | 375 | hidden idea not shown (CRM user, not manager) |  |
| PASS | Embed | 375 | no horizontal scroll (roadmap) | scrollWidth 375 |
| PASS | Embed | 375 | idea page opens inside the iframe route |  |
| PASS | Embed | 375 | no horizontal scroll (idea) | scrollWidth 375 |
| PASS | Embed | 1280 | bad token -> clean expired state, iframe stays on /embed |  |
| PASS | All | - | no uncaught page errors |  |
