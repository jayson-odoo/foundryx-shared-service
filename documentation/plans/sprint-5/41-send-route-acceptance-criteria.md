# Plan 41 acceptance criteria: send route responsiveness and media fetch limits

`POST /api/v1/omnichannel/messages` will carry a partner inbox's main traffic. Its work should stay off the event loop, a media fetch should have a total time limit, and send errors should keep credentials out of stored text.

## Rules

| AC | Rule |
|---|---|
| AC-41-01 | `POST /messages`, JSON and multipart, runs its blocking work off the event loop. While one send waits on a slow media URL, another request to the same worker is answered without waiting for it |
| AC-41-02 | Moving off the loop changes nothing else on the wire: same status codes, bodies, error codes and `Idempotency-Key` behaviour for every path of the route, and the database session still closes after the request |
| AC-41-03 | A media fetch has a total limit of 60 s across connect, headers and body, on top of the existing 15 s per read. Over the limit answers `422 media_fetch_failed`, sends nothing and creates no message row. This covers both fetch paths: media by URL and an interactive message's header URL |
| AC-41-04 | A response declaring a `Content-Length` over the media cap answers `422 oversize` before any of its body is read. A response without that header stays capped while reading, as it is today |
| AC-41-05 | The fetch's existing rules are unchanged: https only, the same URL validation, redirects refused |
| AC-41-06 | On the WhatsApp send path, the channel's token appears in no activity record and no stored message error, whatever the provider's error text or a transport error says. The provider's reason otherwise stays in the text, because the inbox composer shows it. A transport error stores its class name, not its message |
| AC-41-07 | `documentation/omnichannel/consumer-integration-guide.md` states the 60 s limit in section 4.2 and in the `media_fetch_failed` error row, and has a changelog row. No other contract change |

## Build notes

Paths are under `service_backend/modules/omnichannel/`.

- `routers/api_v1.py` `send_message`: keep `await request.form()`, `await upload.read()` and `await request.json()` on the loop, and run `svc.send` and `svc.send_multipart` through `run_in_threadpool`. The session is handed to one thread at a time, never used by two at once.
- `services/public_gateway_service.py` `_fetch_url`: `MEDIA_FETCH_TOTAL_SECONDS = 60.0`, measured with `time.monotonic()`, checked as each chunk arrives and before the read starts. Keep it one function, so both fetch paths share it.
- `adapters/whatsapp_cloud.py` `_send_impl` and `upload_media`: `provider_error_text` (`adapters/meta_graph.py`) already removes long opaque strings. Add removal of the channel's literal token, and its whitespace-split pieces, before that. Unlike a read receipt the text cannot be dropped, since the composer shows it (`adapters/base.py` `SendError`).

## Decisions

- 60 s allows a large legitimate file on a slow host. The worker's 120 s timeout stays above it.
- A limit on how many fetches one key may run at once is out of scope. Sends have no per-key limit today.
- Stored errors written before this change are not rewritten here.
