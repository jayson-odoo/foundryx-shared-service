# AutoCount load strategy - acceptance criteria

Lane AUTOCOUNT-LOAD-STRATEGY. Plan + owner answers: `autocount-load-strategy.md`. Tests:
`service_backend/tests/test_autocount_load_strategy.py`, `test_autocount_office_hours.py`,
`service_frontend/.../field-hint.test.ts`.

## LS-1 Page size [BE][T]
- LS-1-1 Given an open-REST connection, when the stock balance task walks, then each balance page asks for 3000 rows (connection "Stock balance page size", default 3000, 50-3000) and its item / UOM lookups ask for the connection "Page size".
- LS-1-2 Given a product (or any other) task, when it walks, then it asks for the connection "Page size" (still max 1000).

## LS-2 One request at a time per server [BE][T]
- LS-2-1 Given two tasks on two books of one AutoCount server, when both walk, then at most one request to that server is in flight at any moment.
- LS-2-2 The turn is held for one request only (page by page) and handed back on success and on failure; a crashed holder frees the server by itself.
- LS-2-3 A different server is never held up.
- LS-2-4 "One request at a time per server" = No: requests do not wait.
- LS-2-5 Given a sync page in flight and another sync page waiting, when a person's call arrives (write, document finder, preview, write-back read), then the person's call goes next and waits at most for the page in flight.
- LS-2-6 Redis unreachable: the request goes ahead (today's behaviour), a warning is logged.

## LS-3 Adaptive pause [BE][T]
- LS-3-1 A page slower than "Slow page" doubles the pause before the next page (at least 5 s, at most 90 s); a page faster than half of it halves the pause, never below "Pause between pages". 0 = off.
- LS-3-2 The run records the owner's pause, and a note in the run activity names each lengthening.

## LS-4 Safety stop [BE][T]
- LS-4-1 N failed requests in a row (timeout, connection error, 5xx/524) on a server stop every scheduled request to it for M minutes (defaults 3 / 10; 0 = off). A good answer resets the count; a 4xx is not a failure.
- LS-4-2 After the stop one test call is let through; good = everything resumes, bad = stopped again.
- LS-4-3 A stopped server fails the run once with "AutoCount is not answering well, so the sync to this server is paused until dd/mm/yyyy, h:mm am/pm. It resumes by itself." and no retry ladder.
- LS-4-4 A person's call is never refused by the stop; its good answer lifts it.

## LS-5 Settings [BE][FE][T]
- LS-5-1 The five fields show on the AutoCount open-REST connection form with their defaults; out-of-range values are refused at save with a plain message; a connection saved before this lane reads the defaults.

## LS-6 Document feeds [BE][T]
- LS-6-1 Feed reads take the same turn and use the connection's own policy; the document finder reads at a person's priority.
- LS-6-2 A stopped server fails a feed poll once (`VENDOR_STOPPED`) without retries.
- LS-6-3 Feed days are paced with the same adaptive pause.

## LS-7 Office hours from Sorento CRM [BE][FE][T]
- LS-7-1 SS reads `GET /api/v1/external/work-calendar` and `.../is-working-day` with the Sorento connection's API key, cached 1 h (a key or base URL change reads again).
- LS-7-2 Outside office hours (weekday ranges, hours, today's holiday): the stock balance runs at most hourly; other open-REST lists wait for the next office-hours start; the nightly full run still runs; direct-database tasks are unaffected.
- LS-7-3 No access / unreadable shape: every hour is office hours, and the Sorento connection page shows "Office hours could not be read from Sorento CRM (<reason>); every hour counts as office hours." under the base URL; readable shows "Office hours from Sorento CRM: Monday - Friday, 9:00 am - 5:30 pm".
