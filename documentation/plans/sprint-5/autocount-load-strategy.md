# AutoCount load strategy - behaviour card (Step 1: measure + plan)

Lane AUTOCOUNT-LOAD-STRATEGY. Goal: our sync is never the reason AutoCount is slow, and stock stays fresh enough.
No code in this step. Numbers marked **(code)** are derived from the code on `main` @ f8d694f9; numbers marked
**(prod?)** need the read-only prod query in section 5 to confirm (Cloudflare said ~53k calls / 24 h from SS prod).

## 1. What we call today (per book, from the code)

Every open-REST task walks its endpoint **in full on every run**: the `*bypage` endpoints have no server-side
changed-since filter, so the `LastModified` watermark is applied by us after the walk
(`http_source/source.py:4-9`, `:1170`). Default schedule of a new task: incremental every 15 min, reconcile daily
02:00 MYT, quiet hours off (`services/etl_service.py:224,229,264-266,577-593`). Page size: connection-wide, clamped
**50-1000** (`http_source/client.py:56,117`), so the vendor's 3000 is not settable today. Pause between pages:
connection-wide 0-90 s, default 0 (`http_source/gentle.py`, #363).

| Task (endpoint) | Runs | Calls per run **(code)** | Notes |
|---|---|---|---|
| Stock balance `/itembatchbalqtybypage` | every 15 min | ~70 pages x 1000 rows | + lookups `/itembypage` and `/itemuombypage`, reused for 60 min per worker process (`gentle.py` lookup cache) |
| Product `/itembypage` | every 15 min | ~12 pages (`client.py:48`) | + `/itemuombypage` lookup walked again every run |
| Unit of measure (distinct over `/itembypage`) | every 15 min | ~12 pages | a **second full walk** of the same item endpoint |
| Customer `/debtorbypage` | every 15 min | a few pages **(prod?)** | |
| Branch, Location, ItemGroup, ItemBrand, ItemClass, Terms | every 15 min | 1 call each (branch paged) | small |
| DO / GRN / Project registration feeds | poll 60 min, sweep 24 h (`doc_feed/schedule.py:33`) | small (server-filtered by LastModified / date) | backfills stopped by owner 26 Nov |
| Document finder (CRM screens, on demand) | per user action | one call per day searched (`doc_lookup/reader.py`) | live, not from our copy |
| Retries | per failure | timeout 1 retry; 5xx/400 2 retries at 1 s, 4 s; 2 timeouts halve page size and restart the walk from page 1 (`source.py:81-108`) | a halving restart re-reads every page already read |

**Overlap: nothing stops two of our jobs hitting the same book at once.** The overlap guard is per task
(`scheduler.py:376`), not per book or server. Product/stock/masters run on `worker_jobs` (2 at a time), document
incrementals on `worker_jobs_docs` (2 at a time) (`docker-compose.yml:261,283`), plus previews, the document finder
and write-back on the web process. All 15-min tasks share the same `:00/:15/:30/:45` grid, so at each quarter hour
the stock walk, the product walk and the UOM walk of the **same** book start within seconds of each other, and
both books (one server) do the same. Worst case today: 4+ concurrent requests to one server, or 8 per task with
`maxConcurrentPages` > 1.

### Estimated calls per hour, per book (code)

stock 4 x 70 = 280, its lookups ~2 x 27 = 54, product 4 x 27 = 108, UOM 4 x 12 = 48, customer ~20, small masters
~24, document feeds ~5: **about 540 per book per hour, ~1,080 for two books, 24 h a day**. Cloudflare's ~53k/day
(~2,200/h) is about twice this, so retries, halving restarts, previews, the finder and SQL-side or other books make
up the rest - section 5's query splits it.

## 2. Strategy (keep / drop, with numbers)

| | Candidate | Verdict | Effect |
|---|---|---|---|
| a | **Page size per task** (task value overrides the connection; cap raised to 3000) | KEEP | stock 70 -> 24 pages per run; item/UOM lookups ~27 -> ~9. Fewer, heavier calls: vendor says 3000 is fine for stock balance; for product keep 1000 until a db3 timing shows 3000 is not slower per row. The walk already trusts the echoed `PageSize` (`source.py:13`), so a wrapper that clamps is safe. |
| b | **One request at a time per AutoCount server** (Redis lock per base host, held per page request, not per run) | KEEP | concurrency 4+ -> 1. Held per request so a short DO poll slots between two stock pages instead of waiting 20 min behind the whole walk. `maxConcurrentPages` > 1 is ignored while the lock is on. |
| c | **Adaptive pause + circuit breaker** | KEEP | pause = owner's floor; if a page takes > 2x that endpoint's normal time (median of its last good run) or > 20 s, the next pause doubles (up to the 90 s max); each fast page halves it back to the floor. 3 timeouts/5xx in a row on a server -> every task on that server stops for 10 min ("AutoCount is slow, paused until 10:40"), then one test call; ok -> resume. The halving restart (re-reads from page 1) is replaced by: halve and continue from the page that failed. |
| d | **Schedule by weight** | KEEP | product, UOM, customer, small masters: hourly 08:00-19:00, plus the nightly 02:00 full run, nothing between 19:00 and 08:00 (quiet hours already exist per task, `etl_service.py:261-322`). Stock: every 15 min 08:00-19:00, hourly at night. Stagger start minutes so tasks on one server never start on the same minute. |
| e | **Changed-since filter for items/debtors** | ASK VENDOR | not available on `*bypage` today (only on the DO/GRN `byLastModified` routes). If the vendor adds `LastModifiedFrom` to `/itembypage`, product drops from ~12 pages to ~1 per run - the single biggest win for them. |
| f | Skip unchanged rows (hash) | ALREADY DONE, DROP | `ac_row_hash` already skips unchanged writes; it cuts our DB load, not theirs. |
| g | Read-through for screens | KEEP (small) | the document finder reads live; serve it from our synced DO/GRN copy first and only go live for today's documents. Low volume, lower priority. |
| h | **One item walk shared by product, UOM and stock** (new) | KEEP | product, UOM and stock's lookup each walk `/itembypage` separately; share one walk per server per run window (the lookup cache, keyed by server + path, made shared via Redis instead of per worker process). Removes 2 of 3 item walks. |

### Calls per hour, per book (estimate)

| | Before (any hour) | After, 08:00-19:00 | After, 19:00-08:00 |
|---|---|---|---|
| Stock balance (+ lookups) | ~334 | 4 x 24 + 9 = ~105 | 24 + 9 = ~33 |
| Product + UOM | ~156 | ~9 (one shared walk at 3000) or ~27 at 1000 | 0 (nightly full only) |
| Customer + small masters | ~44 | ~11 | 0 |
| Document feeds | ~5 | ~5 | ~5 |
| **Total per book** | **~540** | **~130-150** | **~38** |
| Max concurrent requests to the server | 4+ | 1 | 1 |
| Per day, two books | ~26k (code) / ~53k (Cloudflare) | | **~4.1k (-84 % vs code estimate)** |

Stock freshness unchanged in office hours (15 min); at night 60 min.

## 3. Settings (owner rule: admin UI per connection, no env flags)

On the AutoCount connection form: "Pages per request" per task (on the task form, default = connection),
"One request at a time" (on, default on), "Pause between pages" (existing, becomes the floor of the adaptive pause),
"Slow page threshold (seconds)" (20), "Stop after N failures in a row" (3) / "Wait before retry (minutes)" (10).
Office hours reuse the task's existing quiet-hours fields. Every pause, slow page and stop shows in the run's
activity and on Scheduled Tasks (last run / last error / Run now).

## 4. Questions (max 5, each with a recommendation)

1. **Lock scope: per server or per book?** Both books sit behind one server. Recommend **per server** (base host): the
   slow thing is the one machine, not the book.
2. **Product page size: 3000 too, or stay at 1000?** Recommend **stay 1000 until one db3 timing run** compares
   seconds per 1000 rows at 1000 vs 3000; stock goes to 3000 now per the vendor.
3. **Office hours for the warehouse:** recommend **08:00-19:00 MYT, Mon-Sat**, stock 15 min inside, 60 min outside;
   product/masters hourly inside, nightly only outside. Change if the warehouse works later.
4. **Ask the vendor for a changed-since filter on `/itembypage` and `/debtorbypage`?** Recommend **yes** - it is the
   only change that removes the full product scan; until then (h) + (d) keep it to ~1 walk an hour.
5. **Circuit breaker defaults: 3 failures in a row -> stop that server's tasks for 10 min, then one test call?**
   Recommend **yes**, plus alert on the second open within an hour.

## 5. Prod read needed (read-only, crew runs it)

Per call: `integration_activity` rows with `source='autocount'`, `operation LIKE 'GET %'` (the open-REST client
records every page with `latency_ms`, `http_source/client.py:301`, `activity.py:155`).

```sql
-- calls, avg and p95 latency per endpoint per book, last 7 days
SELECT split_part(split_part(operation, ' ', 2), '?', 1) AS path,
       request_summary_json->>'url' ~ '/db1/' AS db1, request_summary_json->>'url' ~ '/db2/' AS db2,
       count(*) AS calls, count(*) / 7 AS per_day,
       avg(latency_ms)::int AS avg_ms,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY latency_ms)::int AS p95_ms,
       count(*) FILTER (WHERE status <> 'success') AS failed
FROM integration_activity
WHERE source = 'autocount' AND created_at > now() - interval '7 days'
GROUP BY 1, 2, 3 ORDER BY calls DESC;

-- overlap: runs of one tenant (both books share one server) whose [started_at, finished_at] intersect
SELECT a.entity_type, b.entity_type, count(*)
FROM app_autocount.ac_sync_run a JOIN app_autocount.ac_sync_run b
  ON a.tenant_id = b.tenant_id AND a.id < b.id
 AND a.started_at < b.finished_at AND b.started_at < a.finished_at
WHERE a.started_at > now() - interval '7 days'
GROUP BY 1, 2 ORDER BY 3 DESC;

-- pages, duration, queue wait per task
SELECT company_id, entity_type, mode, count(*), avg(source_pages)::int, avg(duration_ms)::int,
       percentile_cont(0.95) WITHIN GROUP (ORDER BY duration_ms)::int, avg(requests)::int
FROM app_autocount.ac_sync_run WHERE started_at > now() - interval '7 days'
GROUP BY 1, 2, 3 ORDER BY 4 DESC;
```

## 6. Step 2 build order (after answers)

1. (a) per-task page size, cap 3000 - smallest, biggest stock win. 2. (b) per-server lock. 3. (c) adaptive pause +
breaker + continue-from-failed-page. 4. (d) office-hours schedule defaults + staggered start minutes, with a
backfill for existing tasks (owner-approved values only). 5. (h) shared item walk. 6. (g) finder read-through.
Tests red-first per step; live calls only on db3.
