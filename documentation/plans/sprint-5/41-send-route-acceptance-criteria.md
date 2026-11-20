# Plan 41 acceptance criteria: send route responsiveness and media fetch limits

`POST /api/v1/omnichannel/messages` will carry a partner inbox's main traffic. Its work should stay off the event loop, a media fetch should have a total time limit, and send errors should keep credentials out of stored text.

## Rules

| AC | Rule |
|---|---|
| AC-41-01 | `POST /messages`, JSON and multipart, runs its blocking work off the event loop. While one send waits on a slow media URL, another request to the same worker is answered without waiting for it |
| AC-41-02 | Moving off the loop changes nothing else on the wire: same status codes, bodies, error codes and `Idempotency-Key` behaviour for every path of the route, JSON and multipart, and the database session still closes after the request |
| AC-41-03 | A media fetch has a hard total limit of 60 s across connect, headers and body. Nothing a remote server sends can extend it, including headers arriving a byte at a time and a compressed body that decodes to nothing. Over the limit answers `422 media_fetch_failed`, sends nothing and creates no message row. This covers both fetch paths: media by URL and an interactive message's header URL |
| AC-41-04 | A response declaring a `Content-Length` over the 100 MB fetch cap answers `422 oversize` before any of its body is read. A response without that header stays capped while reading. The fetch asks for no compression, and a response with any other `Content-Encoding` answers `422 media_fetch_failed`, so the cap counts real bytes |
| AC-41-05 | The fetch's existing rules are unchanged: https only, the same URL validation, redirects refused |
| AC-41-06 | On the WhatsApp send path, the channel's token appears in no activity record and no stored message error, whatever the provider's error text or a transport error says. The provider's reason otherwise stays in the text, because the inbox composer shows it. A transport error stores its class name, not its message, and keeps its retry behaviour, and the exception chain holds no token either. This covers the send call and the media upload call |
| AC-41-07 | `documentation/omnichannel/consumer-integration-guide.md` states the 60 s limit, the 100 MB early refusal, the compression rule and `429 media_fetch_busy` in section 4.2, adds all of them to the error table, names both the process and the per-tenant limit wherever the 429 appears, and has a changelog row. No other contract change |
| AC-41-08 | No database transaction or pooled connection is held while a media fetch runs, or while the fetched media is being stored |
| AC-41-09 | A media URL or redirect target the HTTP client cannot process, such as a malformed address, a bad port, control characters or an over-long URL, answers `422 media_fetch_failed`, not `500`, and so does any other unexpected error during the fetch, such as a bad TLS record. A media URL that is not a string answers `422 invalid_media_url`. A redirect whose target cannot be processed answers a typed 422 too, `invalid_media_url` or `media_fetch_failed`. The message of a fetch failure is fixed wording, with no remote bytes or network detail |
| AC-41-10 | At most 4 media fetches run at once per server process, and at most 2 per tenant in that process, however many API keys it has. A slot is held from before the URL's lookup until the fetched media has been stored. A send over either limit answers `429 media_fetch_busy` straight away, sends nothing, creates no message row and frees its `Idempotency-Key` so a retry can go through. A slot is freed on every outcome. Sends with no media URL are not affected |

## Build notes

Paths are under `service_backend/modules/omnichannel/`.

- `routers/api_v1.py` `send_message`: keep `await request.form()`, `await upload.read()` and `await request.json()` on the loop, and run `svc.send` and `svc.send_multipart` through `run_in_threadpool`. The session is handed to one thread at a time, never used by two at once.
- `services/public_gateway_service.py` `_fetch_url`: keep its sync signature and its validation. Run the fetch as `asyncio.run(asyncio.wait_for(<async fetch with httpx.AsyncClient>, MEDIA_FETCH_TOTAL_SECONDS))`, with `MEDIA_FETCH_TOTAL_SECONDS = 60.0`. A check between chunks cannot be a deadline: it never runs while headers are dripping or while a compressed body yields nothing. Each fetch gets its own short loop in the worker thread. Both fetch paths share it. Release read transactions before it, per `documentation/engineering/storage-and-background-jobs.md`, and in `TenantStorage.save` (`app/services/storage.py`) once its connection and adapter are resolved, right before the write, so every storage write follows the same rule.
- Send `Accept-Encoding: identity` and read with `aiter_raw`. Limits are constants: `MEDIA_FETCH_MAX_CONCURRENT = 4`, `MEDIA_FETCH_MAX_PER_TENANT = 2`, in one small gate. Both callers of `_fetch_url` take the slot, non-blocking, before calling it, and hold it through storing the media, so the lookup, the fetch and the store are all counted.
- `Content-Length` is compared only when it is plain ASCII digits. Keep the check after the redirect and status checks, so a 404 with a large length still answers as a 404.
- `services/idempotency.py`: the in-memory store's check-then-set is now reachable from two threads, so make it atomic.
- `adapters/whatsapp_cloud.py` `_send_impl` and `upload_media`: `provider_error_text` (`adapters/meta_graph.py`) already removes long opaque strings. Add removal of the channel's literal token, and its whitespace-split pieces, before that. Unlike a read receipt the text cannot be dropped, since the composer shows it (`adapters/base.py` `SendError`).

## Decisions

- 60 s allows a large legitimate file on a slow host. It is a hard deadline because, with the work off the loop, the worker's 120 s timeout no longer stops a slow fetch: the heartbeat keeps running.
- The event loop used to limit fetches to one per worker by accident. Moving off the loop removes that, so AC-41-10 sets the limit on purpose, with a per-tenant share so one tenant cannot take every slot: a tenant can mint more keys, so a per-key share would not hold. 4 per process keeps worst-case buffered media near 1 GB per worker, measured at 959 MiB, since joining the chunks briefly doubles each buffer. The numbers are constants, so they can be tuned once real traffic is known.
- A DNS lookup that stalls can outlast the deadline, because the worker waits for the lookup's thread on exit. The operating system's resolver timeout bounds that.
- Stored errors written before this change are not rewritten here.
