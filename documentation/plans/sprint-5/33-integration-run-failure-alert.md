# Plan 33 - Alert when a scheduled integration run keeps failing

Lane: SS-INTEGRATION-ALERT (crew), branch `crew/ss-integration-alert`, size M.
Status: PLAN (behaviour card pending owner answers; no code yet).

## Why

Owner, 22 Oct 2026 14:06 (prod, integration "Stock balance", AutoCount Open API -> Sorento, Active):
many Incremental runs in a row ended Failed with `AutoCount answered HTTP 502 on page N.` and
nobody noticed until he opened the screen. He wants a watcher that alerts: "cannot wait until the
user raise this".

## Step 0 - what "AutoCount answered HTTP 502" means

Read-only, from the code; posted as a `crew-note` on the PR. Summary kept here once filed.

## Step 1 - behaviour card (BEFORE code)

Filed as one `crew report --ask`. Crew defaults proposed in the brief:

- Trigger per integration: 2 consecutive failed scheduled runs, OR no successful run for 3x the
  schedule interval.
- One alert per incident; while still failing, a reminder at most every 4 h; a "recovered" notice
  when a run succeeds again.
- Channels: in-app notification + email to integration admins (owner included). WhatsApp off by
  default.
- Text names the integration, company, first-failure time, failed-run count, last error line and a
  link to the Runs tab.
- Thresholds configurable per integration, defaults above.

Owner answers: (pending)

## Step 2 - build (after the card)

UAC, slices and tickets are written here once the card is answered. Pipeline: UAC -> mockup
(incident banner on the integration page and its list row) -> tester red tests -> coder -> kill
test -> reviewer -> agent-browser 1280 + 375 -> laneboard hand-test script.
