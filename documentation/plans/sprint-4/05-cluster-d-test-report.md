# Sprint 4 · Plan 05 - Cluster D (slice 1) Test Execution Report

**Scope:** Venue master + Offerings + capacity minting + read-only public registration portal (slice 1). Cart / seat-map / checkout = slice 2.
**Stack:** Next :3001 → FastAPI :8001 → native Postgres, default tenant.
**Date:** 2026-06-20.

## Automated suites

| Suite | Result |
|-------|--------|
| Backend `tests/test_cluster_d.py` | **10 passed** |
| Backend full suite (`pytest -q`) | **882 passed**, 0 failures |
| Frontend `tsc --noEmit` | 0 errors |
| Frontend `eslint` (new/changed) | 0 errors |
| Frontend prod build | clean |
| E2E `e2e/cluster-d.spec.ts` | **4 passed** (real clicks, live stack) |

## E2E journeys (Given / When / Then)

### AC-05-OFF-03 · ① Venue + zones + seat generator
- **Given** an admin on `/ems/venues`
- **When** they create a venue, Edit → Zones add "Main", Seats → generate 2×5
- **Then** the venue detail opens, the zone appears, and the zone shows the **"10 seats"** badge. ✅

### AC-05-OFF-01/04 + R3-4 · ② Offerings (GA + RESERVED) + mint + seat map
- **Given** a seeded event + product + a venue with seats, on the event **Offerings** tab
- **When** they create a GA offering, then a RESERVED offering (pick venue + zone), then row "…" → **Mint seats**, then "…" → **View seats**
- **Then** both offerings list, mint toasts **"Minted N seats"**, and the seat-allocation dialog renders the cinema map with a **Free (N)** legend. ✅

### AC-05-PUB-01 + R3-6 · ③ Registration portal
- **Given** an admin on the event detail
- **When** they use the form "…" → **Copy registration link**, then open `/public/register/default/{id}`
- **Then** the link-copied toast shows; the public page (anonymous) renders the event title + offering; the **Register** CTA is disabled (checkout = slice 2). ✅

### Responsive · ④ Mobile
- **Given** a 375px viewport
- **When** loading `/ems/venues`
- **Then** no horizontal overflow. ✅

## Live manual smoke (curl)
- Offering currency omitted → resolves to tenant `default_currency` (**MYR** on the demo tenant). ✅
- Public portal returns event + offerings with **no auth**; unknown tenant/event → uniform 404. ✅
- Re-mint keeps sold/held units (no sale destroyed). ✅ (unit test)

## Notes / deferred to slice 2
- Seat occupancy is all-`free` until tickets exist (tickets = slice 2/3); the seat-allocation map's sold/held demo data was mock-only.
- Public portal is read-only - cart, live seat-map (WS), checkout, per-IP throttle + honeypot all land in slice 2.
- Bulk-import ticket modes (R3-5), nomination/QR, derived participant Checked-in (R3-2) = slices 2/3.

## Fixed alongside
- Core alembic **2 unmerged heads** (plans 03/04) → merge revision `e40b2c4c0135`; live DB realigned via `stamp head`. `bootstrap_db` works again.
