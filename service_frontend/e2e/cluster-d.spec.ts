import { expect, request as pwRequest, test, type Page } from '@playwright/test';

const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

/**
 * Cluster D (sprint-4/05) slice-1 E2E - real user clicks against the live stack
 * (Next :3001 → FastAPI :8001 → Postgres), default tenant.
 *
 * ① Venues: create venue → Edit → add zone → generate seats → counts roll up.
 * ② Offerings: on a seeded event, create a GA offering, create a RESERVED
 *    offering (venue+zone), Mint seats, View the seat-allocation map.
 * ③ Registration portal: copy-link action + the public read-only portal page.
 * ④ Mobile viewport - /ems/venues has no horizontal overflow.
 *
 * Preconditions (event hierarchy + a venue with seats + a product) are seeded
 * via API; the flows under test are exercised through clicks.
 */
const STAMP = Date.now();
const VENUE_UI = `Stadium ${STAMP}`; // created via UI in ①
const SEED_VENUE = `Seeded Arena ${STAMP}`;
const EVENT = `Cluster D Event ${STAMP}`;
const PRODUCT = `D Pass ${STAMP}`;
// slice-3 nomination/transfer fixtures (a confirmed registrant + a nominee)
const NOMINEE = `Nominee ${STAMP}`;
const REGISTRANT_EMAIL = `registrant-${STAMP}@example.com`;
const NOMINEE_EMAIL = `nominee-${STAMP}@example.com`;

let projectId = '';
let nomEventId = ''; // a SECOND event dedicated to the nomination test (isolation)

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/signin'));
}

test.describe.configure({ mode: 'serial' });

test.beforeAll(async () => {
  const ctx = await pwRequest.newContext();
  const token = (
    await (await ctx.post(`${API}/auth/login`, { data: { email: 'demo@example.com', password: 'demo1234' } })).json()
  ).access_token;
  const h = { Authorization: `Bearer ${token}` };
  // event hierarchy
  const type = await (await ctx.post(`${API}/ems/project-types`, { headers: h, data: { name: `D Type ${STAMP}` } })).json();
  const tmpl = await (await ctx.post(`${API}/ems/project-templates`, { headers: h, data: { typeId: type.id, name: 'D Tmpl' } })).json();
  const proj = await (await ctx.post(`${API}/ems/projects`, { headers: h, data: { templateId: tmpl.id, title: EVENT } })).json();
  projectId = proj.id;
  // product
  await ctx.post(`${API}/products`, { headers: h, data: { name: PRODUCT, kind: 'admission' } });
  // a venue with one zone + seats (for the RESERVED offering)
  const v = await (await ctx.post(`${API}/ems/venues`, { headers: h, data: { name: SEED_VENUE } })).json();
  const z = await (await ctx.post(`${API}/ems/venues/${v.id}/zones`, { headers: h, data: { name: 'Block A', kind: 'section' } })).json();
  await ctx.post(`${API}/ems/venues/seats/generate`, { headers: h, data: { zoneId: z.id, rows: 3, perRow: 4 } });

  // ── slice-3 nomination fixture: a SECOND event with a CONFIRMED registrant
  // (mints a participant + a transferable ticket) + a separate nominee profile.
  // Setup uses the operator/public APIs; the TRANSFER itself is real clicks. ──
  const nomEvent = await (
    await ctx.post(`${API}/ems/projects`, { headers: h, data: { templateId: tmpl.id, title: `${EVENT} (Nominate)` } })
  ).json();
  nomEventId = nomEvent.id;
  const nomOffering = await (
    await ctx.post(`${API}/ems/projects/${nomEventId}/offerings`, {
      headers: h,
      data: { productId: (await (await ctx.get(`${API}/products?search=${encodeURIComponent(PRODUCT)}`, { headers: h })).json()).items?.[0]?.id, allocationMode: 'GA', capacity: 50, price: 40, currency: 'MYR' },
    })
  ).json();
  // a published registration isn't required for the public cart confirm path -
  // create cart → GA qty 1 → confirm with the registrant's email (find-or-create
  // profile → participant → ticket). Public endpoints: tenant slug in the path.
  const cart = await (await ctx.post(`${API}/public/register/default/${nomEventId}/cart`)).json();
  await ctx.post(`${API}/public/register/default/${nomEventId}/cart/${cart.cartId}/ga`, {
    data: { offeringId: nomOffering.id, qty: 1 },
  });
  await ctx.post(`${API}/public/register/default/${nomEventId}/cart/${cart.cartId}/confirm`, {
    data: { attendees: [{ name: `Registrant ${STAMP}`, email: REGISTRANT_EMAIL }] },
  });
  // a distinct, eligible nominee profile to transfer the ticket to
  await ctx.post(`${API}/ems/profiles`, { headers: h, data: { email: NOMINEE_EMAIL, fullName: NOMINEE } });
  await ctx.dispose();
});

test('① Venues - create venue, add zone, generate seats', async ({ page }) => {
  await login(page);
  await page.goto('/ems/venues');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();

  // create
  await page.getByRole('button', { name: /new venue/i }).click();
  const dlg = page.getByRole('dialog');
  await dlg.getByLabel('Name *').fill(VENUE_UI);
  await dlg.getByRole('button', { name: /^create$/i }).click();
  // lands on the venue detail
  await page.waitForURL(/\/ems\/venues\/[0-9a-f-]+/);
  await expect(page.getByRole('heading', { name: VENUE_UI, level: 1 })).toBeVisible();

  // Edit on → Zones tab → add a zone
  await page.getByRole('button', { name: /^edit$/i }).click();
  await page.getByRole('tab', { name: /zones/i }).click();
  await page.getByLabel('Zone name').fill('Main');
  await page.getByRole('button', { name: /add zone/i }).click();
  await expect(page.getByText('Main', { exact: false }).first()).toBeVisible();

  // Seats tab → generate 2 x 5 = 10 seats
  await page.getByRole('tab', { name: /seats/i }).click();
  await page.getByLabel('Rows').fill('2');
  await page.getByLabel('Seats / row').fill('5');
  await page.getByRole('button', { name: /generate/i }).click();
  // the zone seat-count badge (exact - avoids matching the "Generated 10 seats." toast)
  await expect(page.getByText('10 seats', { exact: true })).toBeVisible();
});

test('② Offerings - GA + RESERVED with mint + seat map', async ({ page }) => {
  await login(page);
  await page.goto(`/ems/events/${projectId}`);
  await page.getByRole('tab', { name: /offerings/i }).click();

  // ── GA offering ──
  await page.getByRole('button', { name: /new offering/i }).click();
  let dlg = page.getByRole('dialog');
  await dlg.getByRole('combobox').first().click(); // Product
  await page.getByRole('option', { name: PRODUCT }).click();
  // allocation defaults to GA; create
  await dlg.getByRole('button', { name: /^create$/i }).click();
  await expect(page.getByRole('dialog')).toBeHidden();
  await expect(page.getByRole('row').filter({ hasText: PRODUCT }).first()).toBeVisible();

  // ── RESERVED offering drawing from the seeded venue ──
  await page.getByRole('button', { name: /new offering/i }).click();
  dlg = page.getByRole('dialog');
  await dlg.getByRole('combobox').first().click(); // Product
  await page.getByRole('option', { name: PRODUCT }).click();
  // Allocation → Reserved
  await dlg.getByRole('combobox').nth(1).click();
  await page.getByRole('option', { name: /reserved/i }).click();
  // Venue
  await dlg.getByText('Pick a venue').click();
  await page.getByRole('option', { name: SEED_VENUE }).click();
  // Zones (MultiSelect) - pick the seeded zone
  await dlg.getByText(/pick zones/i).click();
  await page.getByRole('option', { name: /Block A/ }).click();
  await page.keyboard.press('Escape');
  await dlg.getByRole('button', { name: /^create$/i }).click();
  await expect(page.getByRole('dialog')).toBeHidden();

  // Mint seats via the RESERVED row "…"
  const reservedRow = page.getByRole('row').filter({ hasText: /Reserved/ });
  await reservedRow.getByRole('button').last().click();
  await page.getByRole('menuitem', { name: /mint seats/i }).click();
  await expect(page.getByText(/Minted \d+ seats/i)).toBeVisible();

  // View seats → seat-allocation dialog shows the cinema map
  await reservedRow.getByRole('button').last().click();
  await page.getByRole('menuitem', { name: /view seats/i }).click();
  const seatDlg = page.getByRole('dialog').filter({ hasText: /seat allocation/i });
  await expect(seatDlg).toBeVisible();
  await expect(seatDlg.getByText(/Free \(/)).toBeVisible();
});

test('③ Registration portal - copy link action + public page', async ({ page }) => {
  await page.context().grantPermissions(['clipboard-read', 'clipboard-write']);
  await login(page);
  await page.goto(`/ems/events/${projectId}`);

  // form "…" → Copy registration link → toast
  await page.getByRole('button', { name: /more|actions|…|⋯/i }).first().click().catch(() => {});
  const copyItem = page.getByRole('menuitem', { name: /copy registration link/i });
  await expect(copyItem).toBeVisible();
  await copyItem.click();
  await expect(page.getByText(/registration link copied/i)).toBeVisible();

  // public portal page (anonymous) - REAL interactive checkout (live backend)
  await page.goto(`/public/register/default/${projectId}`);
  // the event's real offerings render (GA stepper + Reserved "Select seats")
  await expect(page.getByText(PRODUCT).first()).toBeVisible();
  // Continue is disabled until a ticket is chosen…
  await expect(page.getByRole('button', { name: /continue/i })).toBeDisabled();
  // add a GA ticket → cart updates → Continue enables
  await page.getByRole('button', { name: 'Increase' }).first().click();
  await expect(page.getByRole('button', { name: /continue \(1\)/i })).toBeEnabled();
});

test('⑤ Public checkout flow - seats → details → confirm (real backend)', async ({ page }) => {
  await page.goto(`/public/register/default/${projectId}`);
  // reserved offering → open the seat map, pick a free seat
  await page.getByRole('button', { name: /select seats/i }).click();
  await page.getByText('Stage').waitFor();
  // first selectable (free) seat button in the grid
  const freeSeat = page.locator('button.bg-success\\/15').first();
  await freeSeat.click();
  await expect(page.getByRole('button', { name: /1 seat/i })).toBeVisible();
  // continue → details
  await page.getByRole('button', { name: /continue/i }).click();
  await page.getByLabel('Full name *').first().fill('Alex Tan');
  await page.getByLabel('Email *').first().fill('alex@example.com');
  await page.getByRole('button', { name: /continue/i }).click();
  // review → continue to payment
  await page.getByRole('button', { name: /continue to payment/i }).click();
  // payment (mock card) → pay
  await page.getByLabel('Card number').fill('4242 4242 4242 4242');
  await page.getByLabel('Expiry (MM/YY)').fill('12/27');
  await page.getByLabel('CVC').fill('123');
  await page.getByRole('button', { name: /^pay /i }).click();
  // done - paid
  await expect(page.getByText(/you’re registered|you're registered/i)).toBeVisible();
  await expect(page.getByText(/Order/).first()).toBeVisible();
});

test('⑥ Nomination/transfer - participant "…" → Nominate → Transfer (slice 3)', async ({ page }) => {
  await login(page);
  await page.goto(`/ems/events/${nomEventId}`);
  // Participants tab - the confirmed registrant is listed
  await page.getByRole('tab', { name: /participants/i }).click();
  const regRow = page.getByRole('row').filter({ hasText: REGISTRANT_EMAIL });
  await expect(regRow).toBeVisible();

  // row "…" → Nominate / transfer ticket
  await regRow.getByRole('button').last().click();
  await page.getByRole('menuitem', { name: /nominate \/ transfer ticket/i }).click();

  // the dialog loads the registrant's transferable ticket; pick the nominee
  const dlg = page.getByRole('dialog').filter({ hasText: /nominate \/ transfer ticket/i });
  await expect(dlg).toBeVisible();
  // New attendee SearchSelect → choose the nominee
  await dlg.getByText(/select|choose|search/i).first().click().catch(() => {});
  // open the nominee picker (the only SearchSelect when one transferable ticket)
  await dlg.getByRole('combobox').last().click();
  await page.getByRole('option', { name: NOMINEE }).click();
  await dlg.getByRole('button', { name: /^transfer$/i }).click();

  // toast confirms transfer + QR rotation
  await expect(page.getByText(/ticket transferred/i)).toBeVisible();

  // the backend reflects the transfer: the registrant's ticket is now Transferred
  const ctx = await pwRequest.newContext();
  const token = (
    await (await ctx.post(`${API}/auth/login`, { data: { email: 'demo@example.com', password: 'demo1234' } })).json()
  ).access_token;
  const h = { Authorization: `Bearer ${token}` };
  // resolve the nominee participant → its tickets now carry the transferred one
  const parts = await (await ctx.get(`${API}/ems/projects/${nomEventId}/participants?pageSize=200`, { headers: h })).json();
  const profiles = await (await ctx.get(`${API}/ems/profiles?pageSize=200`, { headers: h })).json();
  const nominee = profiles.items.find((p: { email: string; id: string }) => p.email === NOMINEE_EMAIL);
  const nomineePart = parts.items.find((pp: { profileId: string; id: string }) => pp.profileId === nominee.id);
  expect(nomineePart).toBeTruthy();
  const tks = await (
    await ctx.get(`${API}/ems/projects/${nomEventId}/participants/${nomineePart.id}/tickets`, { headers: h })
  ).json();
  expect(tks.some((t: { status: string }) => t.status === 'transferred')).toBeTruthy();
  await ctx.dispose();
});

test('④ Mobile - /ems/venues no horizontal overflow', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 800 });
  await login(page);
  await page.goto('/ems/venues');
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(2);
});
