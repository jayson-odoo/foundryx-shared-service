import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/**
 * AutoCount ESB — slices 15 + 16 review UI + mapping/formula editor
 * (`sprint-4/14-autocount-sorento-masters`) — E2E against the LIVE stack
 * (Next :3001 → FastAPI :8001 → Postgres). Real user clicks only: after the one
 * `goto` of the sign-in page, EVERY navigation is a click on something a real
 * operator can see. No deep-link `page.goto`.
 *
 * ── Why a scripted vendor, and what stays real ──────────────────────────────
 * AutoCount is customer-hosted and on-prem; no live instance is reachable from
 * CI. So this spec stands a tiny HTTP server in front of the two endpoints the
 * read pipeline calls — `POST /api/Server/Login` and
 * `POST /api/GoodsReceivedNote/GetGoodsReceivedNote` — and points a REAL `erp`
 * connection at it. The slice 15/16 surfaces under test (the mapping editor, the
 * formula builder, both simulators, the Review list) never touch the vendor:
 *   • the mapping editor's source/target catalogs come from the module's own
 *     declared field sets, not a vendor read;
 *   • the whole-mapping simulator runs the REAL MappingEngine over a MOCK record
 *     the operator types (it writes NOTHING and calls no vendor);
 *   • only "Sync now" reads the vendor, and it is used purely to MANUFACTURE a
 *     reviewable batch so the Review list has a row to open.
 *
 * ── Sorento is NOT a dependency ─────────────────────────────────────────────
 * Slice 14's Sorento push was verified separately end-to-end against real
 * Sorento (see the slice-14 test report). Sorento is a cross-repo service and is
 * deliberately NOT exercised here — the mapping/formula surfaces are FoundryX-only.
 *
 * ── Spec isolation ──────────────────────────────────────────────────────────
 * The suite is fullyParallel and a sync mutates tenant-wide AutoCount state, so
 * every test provisions its OWN timestamped tenant via the operator API (setup
 * only — the flow under test stays real clicks) and installs the module there.
 */

const API = 'http://localhost:8001';

const DB_NAME = 'AED_VSOFT';
const COMPANY_NAME = 'V Soft Trading Sdn Bhd';
/** A JWT-shaped string. The client REJECTS a login carrying only the GUID. */
const JWT_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.e2UyZX0.sIgNaTuRe';

// ── scripted vendor (GRN only — used solely to stage a review batch) ─────────

/** Today's date in the vendor's `YYYY/MM/DD` filter format (UTC). */
function vendorDay(): string {
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getUTCFullYear()}/${p(now.getUTCMonth() + 1)}/${p(now.getUTCDate())}`;
}

/** One vendor GRN, header + a nested `GRDTL` line. */
function grn(docKey: string, docNo: string, lastModified: string): Record<string, unknown> {
  return {
    DocKey: docKey,
    DocNo: docNo,
    CreditorCode: '300-A001',
    CompanyName: 'Acme Supplies',
    DocDate: vendorDay(),
    CurrencyCode: 'MYR',
    CurrencyRate: '1.00000000',
    Description: 'July delivery',
    NetTotal: '1200.00000000',
    TaxTotal: '72.00000000',
    FinalTotal: '1272.00000000',
    Cancelled: 'F',
    LastModified: lastModified,
    LastModifiedUserID: 'ADMIN',
    CreatedTimeStamp: `${vendorDay()} 08:00:00`,
    CreatedUserID: 'ADMIN',
    GRDTL: [
      {
        DtlKey: `9${docKey}`,
        ItemCode: 'ITEM-1',
        Description: 'Widget',
        Qty: '120.00000000',
        UOM: 'PCS',
        UnitPrice: '10.00000000',
        SubTotal: '1200.00000000',
        Tax: '72.00000000',
        TaxRate: '6%',
        Location: 'HQ',
        DeliveryDate: vendorDay(),
      },
    ],
  };
}

interface Vendor {
  url: string;
  queueRead(records: Record<string, unknown>[]): void;
  close(): Promise<void>;
}

/** Stand up the scripted AutoCount on an ephemeral loopback port. */
async function startVendor(): Promise<Vendor> {
  const pending: Record<string, unknown>[][] = [];

  const server: Server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const send = (payload: unknown) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(payload));
      };
      if (req.url === '/api/Server/Login') {
        // A BARE ARRAY is the vendor's success shape; the session lives at [0].
        send([
          {
            Token: '3f2504e0-4f89-11d3-9a0c-0305e82c3301',
            JWTToken: JWT_TOKEN,
            DatabaseName: DB_NAME,
            CompanyName: COMPANY_NAME,
          },
        ]);
        return;
      }
      if (req.url === '/api/GoodsReceivedNote/GetGoodsReceivedNote') {
        send({ Status: 'Success', ResultTable: pending.shift() ?? [] });
        return;
      }
      send({ Status: 'Fail', Message: `Unexpected path ${req.url}`, ResultTable: [] });
    });
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;

  return {
    url: `http://127.0.0.1:${port}`,
    queueRead: (records) => pending.push(records),
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
      }),
  };
}

// ── tenant setup (operator API — setup only) ─────────────────────────────────

interface TenantAdmin {
  slug: string;
  tenantId: string;
  email: string;
  password: string;
}

async function operatorToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  if (!res.ok()) throw new Error(`operator login failed: ${await res.text()}`);
  return (await res.json()).access_token as string;
}

/** Dedicated, timestamped tenant with the `autocount` module ACTIVE. */
async function provisionTenant(request: APIRequestContext, tag: string): Promise<TenantAdmin> {
  // Timestamp AND a random suffix so two workers in the same millisecond never
  // collide on `ix_tenants_slug`. Never a fixed literal — residue must not break
  // the next run.
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const slug = `e2e-acm-${tag}-${stamp}`;
  const token = await operatorToken(request);
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E AutoCount Mapping ${tag} ${stamp}`,
      slug,
      adminName: 'AutoCount Admin',
      adminEmail: `admin-${slug}@example.com`,
      adminPassword: 'ChangeMe1!',
    },
  });
  if (!res.ok()) throw new Error(`tenant provisioning failed: ${await res.text()}`);
  const tenantId = (await res.json()).id as string;

  const install = await request.post(
    `${API}/platform/tenants/${tenantId}/modules/autocount/install`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!install.ok()) throw new Error(`module install failed: ${await install.text()}`);

  return { slug, tenantId, email: `admin-${slug}@example.com`, password: 'ChangeMe1!' };
}

// ── UI helpers (real clicks) ─────────────────────────────────────────────────

async function loginTenantAdmin(page: Page, t: TenantAdmin) {
  await page.goto(`http://${t.slug}.localhost:3001/signin`);
  await page.getByPlaceholder('Your email').fill(t.email);
  await page.getByPlaceholder('Your password').fill(t.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Sidebar section → child link. Expands the section when collapsed. */
async function openViaSidebar(page: Page, section: string, child: string, urlRe: RegExp) {
  const link = page.getByRole('link', { name: child, exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText(section, { exact: true }).first().click();
    await expect(link).toBeVisible({ timeout: 15_000 });
  }
  await link.click();
  await page.waitForURL(urlRe);
}

/** Create the AutoCount `erp` connection through the integrations form, then run
 *  Test — the discovered company echoes back on success. */
async function createAndTestConnection(page: Page, vendorUrl: string, name: string) {
  await openViaSidebar(page, 'Settings', 'Integrations', /\/settings\/integrations$/);
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);

  await page.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'AutoCount', exact: true }).click();

  await page.getByPlaceholder('e.g. Company mail server').fill(name);
  await page.getByPlaceholder('https://autocount.customer.com').fill(vendorUrl);
  await page.getByPlaceholder('ADMIN').fill('ADMIN');
  const secrets = page.locator('input[type="password"]');
  await secrets.nth(0).fill('app-vsoft');
  await secrets.nth(1).fill('sup3rSecret!');

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/);

  await page.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Test connection' }).click();
  await expect(page.getByText(new RegExp(`Connected to ${COMPANY_NAME}`)).first()).toBeVisible({
    timeout: 20_000,
  });
}

/** Companies list → Connect company → pick the connection → Create. */
async function connectCompany(page: Page, connectionName: string, label: string): Promise<string> {
  await openViaSidebar(page, 'AutoCount', 'Companies', /\/autocount\/companies$/);
  await page.getByRole('button', { name: 'Connect company' }).click();
  await page.waitForURL(/\/autocount\/companies\/new$/);

  await page.getByRole('combobox', { name: 'AutoCount connection' }).click();
  await page.getByRole('option', { name: new RegExp(connectionName) }).click();
  await page.getByLabel('Label').fill(label);

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/autocount\/companies\/(?!new)[\w-]+$/, { timeout: 20_000 });
  await expect(page.getByText(DB_NAME).first()).toBeVisible();
  const m = /\/autocount\/companies\/([\w-]+)/.exec(new URL(page.url()).pathname);
  if (!m) throw new Error(`not on a company page: ${page.url()}`);
  return m[1];
}

/** No horizontal PAGE scroll — wide content must scroll inside its own box. */
async function expectNoPageScroll(page: Page, where: string) {
  const overflow = await page.evaluate(() => {
    const el = document.documentElement;
    return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
  });
  expect(
    overflow.scrollWidth,
    `${where}: page scrolls horizontally (${overflow.scrollWidth} > ${overflow.clientWidth})`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

/** The surface is usable at BOTH widths, asserted not eyeballed (the mandate). */
async function assertResponsive(page: Page, where: string, anchor: Locator) {
  for (const size of [
    { width: 375, height: 812 },
    { width: 1280, height: 900 },
  ]) {
    await page.setViewportSize(size);
    // Let the reflow land before measuring.
    await page.waitForTimeout(400);
    await expect(anchor, `${where} @${size.width}px: anchor not visible`).toBeVisible();
    const box = await anchor.boundingBox();
    expect(box, `${where} @${size.width}px: anchor has no box`).not.toBeNull();
    expect(box!.x, `${where} @${size.width}px: anchor starts off-screen`).toBeLessThan(size.width);
    await expectNoPageScroll(page, `${where} @${size.width}px`);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

/** Open the supplier entity's field-mapping editor via its row action menu. */
async function openSupplierMapping(page: Page, companyId: string) {
  await page.getByRole('tab', { name: 'Entities' }).click();
  await expect(page.getByText('Supplier').first()).toBeVisible({ timeout: 15_000 });
  const row = page.locator('tr', { hasText: 'Supplier' }).first();
  await row.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Configure mapping' }).click();
  await page.waitForURL(new RegExp(`/autocount/companies/${companyId}/entities/supplier/mapping$`));
  await expect(page.getByText('AutoCount field').first()).toBeVisible({ timeout: 15_000 });
}

// ── the journeys ──────────────────────────────────────────────────────────────

test.describe('AutoCount ESB — slices 15/16 review UI + mapping', () => {
  test('AC-15-40..44 / AC-16-10..31 · mapping editor, formula builder + simulators by clicking', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000);
    const vendor = await startVendor();
    const stamp = Date.now();
    try {
      const tenant = await provisionTenant(request, 'map');
      await loginTenantAdmin(page, tenant);

      const connectionName = `AutoCount Map ${stamp}`;
      await createAndTestConnection(page, vendor.url, connectionName);
      const companyId = await connectCompany(page, connectionName, `Map Co ${stamp}`);

      // ── 1. Mapping editor is read-only until Edit (AC-15-40 / AC-15-44) ────
      await openSupplierMapping(page, companyId);
      // The table renders AutoCount source → Sorento field with the columns the
      // AC calls for, and the default supplier rows are shown by their labels.
      await expect(page.getByText('Sorento field').first()).toBeVisible();
      await expect(page.getByText('Transform').first()).toBeVisible();
      // Read mode = plain values, no comboboxes, and the global Edit toggle.
      await expect(page.getByRole('combobox', { name: 'Transform for row 1' })).toHaveCount(0);
      const editBtn = page.getByRole('button', { name: 'Edit', exact: true });
      await expect(editBtn).toBeVisible();
      // A default deliverable row's source path is rendered read-only.
      await expect(page.getByText('AccNo').first()).toBeVisible();

      // ── 2. Whole-mapping simulator (AC-16-30/31) — clean saved mapping ────
      // Run it BEFORE editing so the mock maps through the untouched default
      // rows: a mock AutoCount record in → the whole Sorento record out, through
      // the REAL MappingEngine, writing nothing.
      await page.getByRole('button', { name: 'Simulate mapping' }).click();
      const simDialog = page.getByRole('dialog');
      await expect(simDialog.getByText('AutoCount record (in)')).toBeVisible();
      const mockRecord = JSON.stringify(
        {
          AccNo: '300-A001',
          CompanyName: 'Acme Supplies',
          EmailAddress: 'ap@acme.example',
          IsActive: 'T',
          Data: [{ AutoKey: 1, LastModified: '2026/03/18 16:03:21' }],
        },
        null,
        2,
      );
      const mockBox = simDialog.getByLabel('Mock AutoCount record');
      await mockBox.fill(mockRecord);
      await simDialog.getByRole('button', { name: 'Run simulation' }).click();
      // record-in → record-out: the projected Sorento record shows every mapped
      // field, and the "T" active flag became a real boolean.
      const output = simDialog.getByTestId('sorento-output');
      await expect(output).toContainText('"code": "300-A001"', { timeout: 20_000 });
      await expect(output).toContainText('"name": "Acme Supplies"');
      await expect(output).toContainText('"is_active": true');
      // Per-field results are legible.
      await expect(simDialog.getByTestId('field-results')).toBeVisible();
      // It writes nothing — a pure preview.
      await expect(simDialog.getByText('This record maps cleanly.')).toBeVisible();
      await page.keyboard.press('Escape');
      await expect(simDialog).toBeHidden();

      // ── 3. Enter Edit — pickers appear (AC-15-44 read-only-until-Edit) ────
      await editBtn.click();
      const transform1 = page.getByRole('combobox', { name: 'Transform for row 1' });
      await expect(transform1).toBeVisible();

      // ── 4. A Boolean preset fills the canonical formula (AC-16-10) ────────
      await transform1.click();
      await page.getByRole('option', { name: 'Boolean', exact: true }).click();

      // ── 5. The formula builder + per-formula simulation (AC-16-11/20) ─────
      await page.getByRole('button', { name: 'Build formula for row 1' }).click();
      const builder = page.getByRole('dialog');
      await expect(builder.getByText('Transform formula')).toBeVisible();
      // The Boolean preset pre-filled `if(value == "T", true, false)`.
      await expect(builder.getByLabel('Formula expression')).toHaveValue(
        'if(value == "T", true, false)',
      );
      await expect(builder.getByTestId('formula-status')).toContainText('Valid formula');
      // Testing tab: a mock value in → live transformed output (client evaluator).
      await builder.getByRole('tab', { name: 'Testing' }).click();
      await builder.getByPlaceholder('e.g. T').fill('T');
      await expect(builder.getByTestId('client-output')).toContainText('true');
      // A different value flips it — proving the formula truly evaluates.
      await builder.getByPlaceholder('e.g. T').fill('F');
      await expect(builder.getByTestId('client-output')).toContainText('false');
      await builder.getByRole('button', { name: 'Apply' }).click();
      await expect(builder).toBeHidden();

      // ── 6. Save through the form's single dirty-guarded save (AC-15-41) ───
      await page.getByRole('button', { name: 'Save', exact: true }).click();
      await expect(page.getByText('Field mapping saved.')).toBeVisible({ timeout: 20_000 });

      // ── 7. Responsive at both widths (the standing mandate) ──────────────
      await assertResponsive(
        page,
        'mapping editor',
        page.getByRole('button', { name: 'Simulate mapping' }),
      );
    } finally {
      await vendor.close();
    }
  });

  test('AC-15-01..03 / AC-15-20 · Review list via the sidebar + push-target read-only-until-Edit', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000);
    const vendor = await startVendor();
    const stamp = Date.now();
    try {
      const tenant = await provisionTenant(request, 'rev');
      await loginTenantAdmin(page, tenant);

      const connectionName = `AutoCount Rev ${stamp}`;
      await createAndTestConnection(page, vendor.url, connectionName);
      const companyId = await connectCompany(page, connectionName, `Rev Co ${stamp}`);

      // ── 1. Push target is read-only until the form's Edit toggle (AC-15-20) ─
      // On the read-by-default Overview the delivery target is a plain
      // label/value, no bare dropdown.
      await expect(page.getByText('Delivery').first()).toBeVisible();
      await expect(page.getByRole('combobox', { name: 'Push delivery target' })).toHaveCount(0);
      // Editing reveals searchable pickers, and Sorento with no connection warns
      // (foolproof-UI, AC-15-21) rather than silently saving a broken target.
      await page.getByRole('button', { name: 'Edit', exact: true }).click();
      const deliveryPicker = page.getByRole('combobox', { name: 'Push delivery target' });
      await expect(deliveryPicker).toBeVisible();
      await deliveryPicker.click();
      await page.getByRole('option', { name: 'Sorento', exact: true }).click();
      await expect(page.getByTestId('sink-connection-warning')).toBeVisible();
      // Leave the target unchanged — cancel out of the edit.
      await page.getByRole('button', { name: 'Cancel', exact: true }).click();
      // The Discard-changes guard may intercept (the form is dirty); confirm it.
      const discard = page.getByRole('button', { name: 'Discard changes', exact: true });
      if (await discard.isVisible().catch(() => false)) await discard.click();

      // ── 2. Manufacture a reviewable batch via a real Sync now ────────────
      vendor.queueRead([grn('7001', 'GRN-7001', `${vendorDay()} 09:15:00`)]);
      await page.getByRole('tab', { name: 'Entities' }).click();
      await expect(page.getByText('Goods received note').first()).toBeVisible({ timeout: 15_000 });
      const grnRow = page.locator('tr', { hasText: 'Goods received note' }).first();
      await grnRow.getByRole('button', { name: 'Actions' }).click();
      await page.getByRole('menuitem', { name: 'Sync now' }).click();
      // Eager dev runs the job inline; a batch with records navigates to review.
      await page.waitForURL(/\/autocount\/review\/[\w-]+/, { timeout: 30_000 });
      await expect(page.getByText('Needs review')).toBeVisible();

      // ── 3. Reach the Review LIST from the sidebar (AC-15-01/02) ───────────
      // Back to the company first (a real click), then the sidebar entry.
      await page.getByRole('link', { name: 'Back' }).click();
      await page.waitForURL(new RegExp(`/autocount/companies/${companyId}$`));
      await openViaSidebar(page, 'AutoCount', 'Review', /\/autocount\/review$/);
      // A config-driven Resource list of batches with the review-state segments.
      await expect(page.getByRole('heading', { name: 'Review' }).first()).toBeVisible();
      await expect(page.getByText('Goods received note').first()).toBeVisible({ timeout: 15_000 });
      // The status segment control is the list's real filter.
      await expect(page.getByText('Needs review').first()).toBeVisible();
      await assertResponsive(page, 'review list', page.getByText('Goods received note').first());

      // ── 4. A batch row opens the review FORM (AC-15-03) ──────────────────
      await page.locator('tr', { hasText: 'Goods received note' }).first().click();
      await page.waitForURL(/\/autocount\/review\/[\w-]+/, { timeout: 20_000 });
      await expect(page.getByText('Needs review')).toBeVisible();
      await expect(page.getByTestId('approve-batch')).toBeVisible();
    } finally {
      await vendor.close();
    }
  });
});
