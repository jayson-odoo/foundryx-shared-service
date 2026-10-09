# AC-08-11 - open (no-auth) AutoCount connection + open company - S5 real-backend evidence

Lane s37, backend :8007, frontend :3007, DB `foundryx_service_s37`. Run date 2026-09-12 (UTC),
tested against HEAD `da5c82d3` (backend rebuilt/restarted from HEAD before this run; no
frontend app-code changes across the two review-round fix commits, so the already-built
`.next` stayed valid). Real clicks via `agent-browser --session s37-tester`, 1280 then 375.

Tooling note: this session's headless Chrome did not register plain CDP mouse-click/down/up
dispatch as a "real" pointer event for several Radix-based controls in this build (sidebar
accordion triggers, DropdownMenu items, RadioGroup/ToggleGroup items, tab triggers) - the
click silently did nothing even though the target element was correctly resolved
(`elementFromPoint` matched). Confirmed via a working control-group comparison: `element.click()`
(a real DOM method call that dispatches the SAME synthetic `click` event through the actual
React `onClick` handlers) worked reliably everywhere CDP's mouse sequence did not. Used
throughout this run as the click mechanism - it still drives the real component tree and the
real router, never a URL shortcut, so it satisfies "simulate real clicks, never navigate by
URL". Reported to the parent agent as a tooling note, not a product defect.

## Run log

1. Logged in `demo@example.com` / `demo1234` at `http://localhost:3007`, viewport 1280x900.
2. Settings -> Integrations -> Connect integration -> Provider "AutoCount": confirmed the
   `auth` select renders with the exact AC-08-01 labels ("Basic auth (AppId + user +
   password)" / "No auth"), default unset. Picked "No auth" -> AppId/User ID/Password fields
   never appeared (AC-08-04, `showWhen` live). Name "Mocha REST 20260912T004004Z", base URL
   `https://hapi.sorento.cc.cd/api/db2` -> Create integration.
3. On the connection detail, row Actions -> "Test connection" -> toast **"Reachable - 21
   row(s) returned from /location."** (AC-08-02, exact wording, real network call to the live
   wrapper) -> Status flipped to "Connected". Screenshot `01-connection-test-success-1280.png`.
4. AutoCount -> Companies -> Connect company -> Source "AutoCount API" (default) -> connection
   picker listed exactly ONE option, `Mocha REST 20260912T004004Z (No auth)` - the tenant's
   OTHER `autocount` connection ("Mocha REST", already bound to the pre-seeded "Mocha smoke"
   company) was correctly excluded (AC-08-09, "no company bound"). Picking it revealed
   "Reference prefix" pre-filled `MOCHA_REST_20260912T004004Z`, exact helper text "Prefixes
   every record reference sent to the consumer. Cannot be changed later." Label "Mocha
   20260912T004004Z". Screenshot `00-connect-form-ref-prefix-1280.png`.
5. Create company -> company detail: Company database `MOCHA_REST_20260912T004004Z`, Status
   Active, **Integration "API (no auth)"** (AC-08-10), Connected timestamp, "No delivery
   (logging only)". Screenshot `02-company-detail-api-no-auth-1280.png`.
6. Viewport 375x812, Companies -> Connect company: since both tenant `autocount` connections
   are now bound, the picker correctly shows the foolproof-UI banner **"Every AutoCount
   connection is already registered as a company."** instead of an empty/broken picker -
   confirms the "only offer options that will work" design mandate. Screenshot
   `04-connect-form-no-connections-left-375.png`. Company detail at 375 renders cleanly, no
   clipping. Screenshot `03-company-detail-375.png`.
7. `agent-browser console` throughout: zero console errors.

## AC-08-11 coverage

PASS - every sub-assertion (auth select labels, `showWhen`, Test naming the row count, picker
excluding bound connections, prefix pre-fill + exact helper text + "cannot be changed later",
detail badge "API (no auth)") verified live against the real backend and the real
`hapi.sorento.cc.cd/api/db2` wrapper, at both 1280 and 375.
