# 42 WhatsApp token health: plan

UAC: `42-token-health-acceptance-criteria.md`. Size M, no migration.

## Design

```text
beat, every 6 h (workflow worker, the only beat host)
  run_channel_token_checks          no Meta call, tenant-agnostic scan
    check_channel_token(id)         one task per channel, omni queue
      read credentials
      adapter.check_token           ok | dead | unknown
      dead:    ERROR if credentials unchanged, one email on the change
      ok:      clear ERROR per is_active
      unknown: nothing

POST /omnichannel/channels/{id}/replace-token
  assert_whatsapp, tenant scope, not trashed
  adapter.check_token(new token)    anything but ok: 422, nothing saved
  save in place, clear ERROR
  adapter.subscribe_app             read the answer: subscribed true | false | null
  adapter.token_expiry              tokenExpiresAt or null
```

## Decisions

- **Classifier, not `test_connection`.** `test_connection` returns `ok=False` for 5xx and network errors alike (`whatsapp_cloud.py:878-891`), and rate limit codes count as permanent (`meta_graph.py:52-57`). `check_token` reads `error.code`, and only 190 is dead.
- **`is_active` is never written here.** Setting it would move identity routing (`message_service.py:214-248`), the gateway default (`public_gateway_service.py:185-208`) and broadcasts (`broadcast_send_service.py:230-236`). Inbound does not read status (`inbound_service.py:145-185`).
- **`ensure_statuses` before `status_id_for`,** which returns None when unseeded (`services/statuses.py:68-74`), and `_items` would then read ACTIVE (`channel_service.py:54`).
- **Guard on credentials:** the status write compares the `credentials_json` value the check read, so a replace during a check wins.
- **Tenant filter:** `active_tenants` in `modules/meetings/jobs.py:139-154` ignores suspension, so the scan adds that check. Existing omnichannel sweeps have no module filter. `run_due_broadcasts` (`broadcast_send_service.py:538-591`) is the shape to copy.
- **Probe:** never `sync_profile` (it nulls the profile mirror on a dead token, `channel_profile_service.py:108-120`) or `sync_config` (it stamps `last_verified_at` on failure, `channel_profile_service.py:87-95`).
- **`subscribed_apps`:** today a blind POST with the answer ignored (`whatsapp_cloud.py:147-150`). Replace reads its answer. Existing connect callers keep their behaviour.
- **Refusals are 422,** because Cloudflare replaces an origin 5xx body. Same reasoning as the template submit path.
- **Dialog:** an action with `run` opening a dialog, as `channel-widget-tab.tsx:50,83,319` does. A new `confirm:` would have to pass `confirm-carve-outs.inventory.test.ts` and is not needed.
- **Status filter:** the screen already offers it (`use-channels-list-config.tsx:36-46`) and sends `filter=` (`services/channel-service.real.ts:25`), but the router and repository take none (`routers/channels.py:42-52`, `channel_repository.py:21-31`).
- **Rename:** `channel_service.py:121-124` resets status whenever the form sends `isActive`, which it always does (`use-channel-form.tsx:131-134`).

## Order

Red tests by the tester for backend and frontend, then one coder, backend first and then the dialog against the real route. The dialog reuses an existing pattern on an existing screen, so there is no separate mock phase or static mock. Then reviewer, security-reviewer and browser verification in parallel, then the guide.

## Known limits

Real Meta replies for error 190, `debug_token` and `subscribed_apps` are stubbed at the adapter until the environment test. `debug_token` may be refused for a token minted under another app, which is why an unreadable expiry never blocks a save.
