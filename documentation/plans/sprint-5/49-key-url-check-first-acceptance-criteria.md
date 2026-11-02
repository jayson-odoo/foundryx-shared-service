# Plan 49 acceptance criteria: callback URL check before database work on key routes

| AC | Rule |
|---|---|
| AC-49-01 | [BE] On `POST /api/v1/omnichannel/webhooks` and `PATCH /api/v1/omnichannel/webhooks/{id}` the callback URL is checked (parsed and resolved) while the request holds no database transaction or pooled connection |
| AC-49-02 | [BE] Every other key route that resolves a host does the same |
| AC-49-03 | [BE] Answers are unchanged: a URL that fails the check answers as today, and the row locks and key re-read from plan 43 still run after the check |
| AC-49-04 | [E2E-server] On a real server with a slow resolver, concurrent key PATCHes do not hold the pool, and a staff revoke answers within a second and takes effect |

No migration, no new permission, no screen change, no wire change.
