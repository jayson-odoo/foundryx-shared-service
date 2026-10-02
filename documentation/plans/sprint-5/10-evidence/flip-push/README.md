# Evidence: AC-10-52 flip-to-automatic journey (new evidence dir, this run)

Run date: 2026-09-20 (UTC), approx 13:04-13:16Z. HEAD `17dc2c619b42224d1211f9006d1c805aec498cd0`.
Lane: backend `:8009`, frontend `:3009`, DB `foundryx_service_s40`. Tenant `default`, user
`demo@example.com` (Admin). Company `Sorento SRT S40`, entity `product`
(`0e6f5c95-b099-4a1f-8de9-425b63f561b4` / `product`).

This directory did not exist before this run (per the brief). Both a 375px and a 1280px pass were
run end to end, each starting from Product's `pull` state (left there by `pull-setup/`'s own
journey) and ending back on `pull` (net no state change across the whole evidence session).

## Journey (real clicks, both viewports)

1. **Companies -> Sorento SRT S40 -> Entities -> Product -> Actions -> Configure source ->
   Schedule -> Edit -> switch Delivery to Push.** The Incremental (`Every 15 minutes`) and
   Reconcile (`Daily at 02:00`) cadence controls return with their SAVED values (unchanged from
   before this entity was ever switched to Pull). `01-schedule-push-cadence-returned-375.png`,
   `05-schedule-push-cadence-returned-1280.png`. **PASS.**
2. **Save.** Toast "Task saved." at both viewports. `04-entities-delivery-push-375.png` (Entities
   list re-check: Product's Delivery column now reads `Push`). **PASS.**
3. **The consumer's pull now answers 409 PUSH_ACTIVE.** Curl transcript (full text below) against
   the public gateway `POST /api/v1/autocount/snapshots {"companyCode":"SRT","entity":"products"}`
   using a live, unrevoked pull API key: `HTTP 409 {"code":"PUSH_ACTIVE","message":"This book is
   now automatic.",...}` - reproduced independently at BOTH the 375px pass (using the
   `S6 flip-push probe ...` key, since-revoked) and the 1280px pass (using the
   `AC-10-50 pull-setup 1280 ...` key, since-revoked - see `pull-keys-snapshots/README.md` Run 4).
   **PASS**, exact match to AC-10-52's own wording ("the consumer's pull now answers 409
   PUSH_ACTIVE").
4. **Runs tab shows the schedule armed.** Switched to the Runs tab (Radix tab click required
   keyboard `ArrowRight` navigation from a focused tab - a plain `click` on the tab element was
   observed to be a no-op on this build, a CDP/React-synthetic-event mismatch already flagged in
   earlier evidence sessions for this same tablist component; keyboard navigation is the reliable,
   real-user-equivalent path and was used throughout this evidence run). The Runs tab lists the
   task's 11 prior sync-run rows (all historical, unaffected by this session); the Schedule tab
   itself (re-checked via the same keyboard nav) now shows `Next 20 Sept 2026, 21:04` for
   Incremental and `Next 21 Sept 2026, 10:00` for Reconcile - the schedule is armed.
   `02-runs-tab-schedule-armed-375.png`, `03-schedule-tab-next-run-armed-375.png`,
   `06-runs-tab-schedule-armed-1280.png`. **PASS.**
5. **Revert.** Edit -> switch Delivery back to `Pull on request` -> Save -> toast "Task saved." -
   confirmed via a direct DB read afterward: `('0e6f5c95-...', 'product', 'pull', 'active')`,
   matching the state `pull-setup/`'s journey had left it in. Done at both viewports (once per
   pass), net zero drift on the shared lane entity.

## PUSH_ACTIVE 409 transcripts

```
=== 375px pass (key: S6 flip-push probe 20260920T130458Z, since revoked) ===
POST /api/v1/autocount/snapshots {"companyCode":"SRT","entity":"products"}
Response: {"code":"PUSH_ACTIVE","message":"This book is now automatic.","companyCode":"SRT","entity":"products"}
HTTP: 409

=== 1280px pass (key: AC-10-50 pull-setup 1280 20260920T131041Z, since revoked) ===
POST /api/v1/autocount/snapshots {"companyCode":"SRT","entity":"products"}
Response: {"code":"PUSH_ACTIVE","message":"This book is now automatic.","companyCode":"SRT","entity":"products"}
HTTP: 409
```

## Responsive

Both widths confirmed clean, no unexpected scroll, cadence controls and Runs table render
correctly at 375px (internal scroll on the Runs table) and 1280px (full width).

## House rules

- No hint/instructional copy. **PASS.**
- Console: only the pre-existing benign `DialogContent` a11y warning; no page errors. **PASS.**
- No em/en dashes, no "Foundryx" branding visible. **PASS.**

## AC verdict (this run)

- **AC-10-52 [E2E]** PASS at both 375px and 1280px. Flip Product back to Push -> cadence controls
  return with saved values -> Save -> Runs tab shows the schedule armed -> the consumer's pull now
  answers `409 PUSH_ACTIVE`, proven by two independent curl transcripts (one per viewport pass,
  different keys). Product reverted to `pull`/`active` at the end, matching its state before this
  evidence run touched it.
