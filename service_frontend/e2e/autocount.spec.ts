import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/**
 * AutoCount ESB - slice 1 read pipeline (sprint-4/13, AC-13-14) - E2E against
 * the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Real user clicks
 * only: after the one `goto` of the sign-in page, EVERY navigation is a click
 * on something a real operator can see. No deep-link `page.goto`.
 *
 * ── Why a scripted vendor, and what stays real ──────────────────────────────
 * AutoCount is customer-hosted and on-prem; no live instance is reachable from
 * CI (the demo box is IP-whitelisted to one workstation). So this spec stands a
 * tiny HTTP server in front of the two endpoints the slice-1 pipeline calls -
 * `POST /api/Server/Login` and `POST /api/GoodsReceivedNote/GetGoodsReceivedNote`
 * - and points a REAL `erp` connection at it.
 *
 * Only the vendor's socket is scripted. Everything downstream is the production
 * code path: the real provider `test()`, real company discovery from the login
 * response, the real `autocount_sync` job handler, real watermark, real mapping
 * + coercion, real `compute_diff`, real staged rows, real approval claim.
 *
 * TWO syncs run so the review surface shows a genuine before → after: sync 1
 * stages two new GRNs and is approved (establishing the "before"), sync 2
 * changes one of them and adds a third.
 *
 * ── Honest scope of "pushed" ────────────────────────────────────────────────
 * The slice-1 consumer sink is a DELIBERATE logging no-op (`sinks.LoggingSink`,
 * `delivered=False` always) - backlog BL-133. A record reaching `PUSHED` means
 * "handed to the sink", NOT "delivered to the consumer". This spec therefore
 * asserts the click path and the staged-record lifecycle, and does NOT claim
 * the GRN appeared in a consumer. See the test report's AC-13-14 verdict.
 *
 * ── Spec isolation ──────────────────────────────────────────────────────────
 * The suite is fullyParallel and a sync mutates tenant-wide AutoCount state, so
 * every test provisions its OWN timestamped tenant via the operator API (setup
 * only - the flow under test stays real clicks) and installs the module there.
 * No fixed literal names: residue from an earlier run must never collide.
 */

const API = 'http://localhost:8001';

// ── scripted vendor ──────────────────────────────────────────────────────────

const DB_NAME = 'AED_VSOFT';
const COMPANY_NAME = 'V Soft Trading Sdn Bhd';
/** A JWT-shaped string. The client REJECTS a login carrying only the GUID. */
const JWT_TOKEN = 'eyJhbGciOiJIUzI1NiJ9.e2UyZX0.sIgNaTuRe';

interface GrnOptions {
  lastModified: string;
  supplier?: string;
  description?: string;
  net?: string;
  tax?: string;
  total?: string;
  qty?: string;
}

/** Today's date in the vendor's `YYYY/MM/DD` filter format (UTC). */
function vendorDay(): string {
  const now = new Date();
  const p = (n: number) => String(n).padStart(2, '0');
  return `${now.getUTCFullYear()}/${p(now.getUTCMonth() + 1)}/${p(now.getUTCDate())}`;
}

/**
 * One vendor GRN, header + nested `GRDTL` lines (AC-13-06 - one call, no
 * fan-out). Values carry the vendor's real quirks: `"F"` for false, 8-dp
 * decimal strings, `YYYY/MM/DD` dates.
 */
function grn(docKey: string, docNo: string, o: GrnOptions): Record<string, unknown> {
  const net = o.net ?? '1200.00000000';
  return {
    DocKey: docKey,
    DocNo: docNo,
    CreditorCode: '300-A001',
    CompanyName: o.supplier ?? 'Acme Supplies',
    DocDate: vendorDay(),
    CurrencyCode: 'MYR',
    CurrencyRate: '1.00000000',
    Description: o.description ?? 'July delivery',
    NetTotal: net,
    TaxTotal: o.tax ?? '72.00000000',
    FinalTotal: o.total ?? '1272.00000000',
    Cancelled: 'F',
    LastModified: o.lastModified,
    LastModifiedUserID: 'ADMIN',
    CreatedTimeStamp: `${vendorDay()} 08:00:00`,
    CreatedUserID: 'ADMIN',
    GRDTL: [
      {
        DtlKey: `9${docKey}`,
        ItemCode: 'ITEM-1',
        Description: 'Widget',
        Qty: o.qty ?? '120.00000000',
        UOM: 'PCS',
        UnitPrice: '10.00000000',
        SubTotal: net,
        Tax: o.tax ?? '72.00000000',
        TaxRate: '6%',
        Location: 'HQ',
        DeliveryDate: vendorDay(),
      },
    ],
  };
}

interface Vendor {
  url: string;
  /** Queue the ResultTable the NEXT read should return. */
  queueRead(records: Record<string, unknown>[]): void;
  logins(): number;
  reads(): number;
  /** Every read filter the backend actually sent - asserted for AC-13-05. */
  filters(): Record<string, unknown>[];
  close(): Promise<void>;
}

/** Stand up the scripted AutoCount on an ephemeral loopback port. */
async function startVendor(): Promise<Vendor> {
  const pending: Record<string, unknown>[][] = [];
  const sentFilters: Record<string, unknown>[] = [];
  let logins = 0;
  let reads = 0;

  const server: Server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      let body: Record<string, unknown> = {};
      try {
        body = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
      } catch {
        body = {};
      }
      const send = (payload: unknown) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(payload));
      };

      if (req.url === '/api/Server/Login') {
        logins += 1;
        // A BARE ARRAY is the vendor's success shape, and the session lives at
        // [0]. Both `Token` (a GUID) and `JWTToken` are returned - the client
        // must pick the JWT.
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
        reads += 1;
        sentFilters.push(body);
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
    logins: () => logins,
    reads: () => reads,
    filters: () => sentFilters,
    close: () =>
      new Promise<void>((resolve) => {
        server.close(() => resolve());
      }),
  };
}

// ── tenant setup (operator API - setup only) ─────────────────────────────────

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
  // Timestamp AND a random suffix: two workers starting in the same
  // millisecond would otherwise mint the same slug and collide on
  // `ix_tenants_slug`. Never a fixed literal - residue must not break the
  // next run.
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const slug = `e2e-ac-${tag}-${stamp}`;
  const token = await operatorToken(request);
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E AutoCount ${tag} ${stamp}`,
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

/** Tenant-admin bearer token, for READ-BACK assertions the UI cannot express. */
async function tenantToken(request: APIRequestContext, t: TenantAdmin): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: t.email, password: t.password, tenantSlug: t.slug },
  });
  if (!res.ok()) throw new Error(`tenant login failed: ${await res.text()}`);
  return (await res.json()).access_token as string;
}

interface StagedRow {
  id: string;
  docNo: string | null;
  status: string;
}

/**
 * How many times the approval of THIS job actually ran the push loop. Every
 * real approval writes exactly one masked activity row (`approve <jobId>`); an
 * idempotent replay returns the stored result and writes nothing. So this count
 * is the honest "pushed exactly once" evidence (AC-13-13).
 */
async function countApprovals(
  request: APIRequestContext,
  token: string,
  jobId: string,
): Promise<number> {
  const res = await request.get(`${API}/integration-logs?page_size=200`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) throw new Error(`activity read failed: ${await res.text()}`);
  const body = await res.json();
  return (body.data as { operation: string }[]).filter(
    (row) => row.operation === `approve ${jobId}`,
  ).length;
}

async function readStaged(
  request: APIRequestContext,
  token: string,
  jobId: string,
): Promise<{ jobStatus: string; rows: StagedRow[] }> {
  const res = await request.get(`${API}/autocount/jobs/${jobId}/staged`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok()) throw new Error(`staged read failed: ${await res.text()}`);
  const body = await res.json();
  return { jobStatus: body.job.status as string, rows: body.data as StagedRow[] };
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
    // `force: true` - Next dev mode's `<nextjs-portal>` build-activity overlay
    // can transiently sit over this click target during a hot-reload/compile
    // tick and fail the actionability check even though the element is fully
    // visible; the click itself is still real (CDP-dispatched at the element's
    // coordinates), not a shortcut around a genuine UI block.
    await page.getByText(section, { exact: true }).first().click({ force: true });
    // Generous: the first render against a cold server (or a just-restarted
    // backend) can exceed the 5s default while the layout hydrates.
    await expect(link).toBeVisible({ timeout: 15_000 });
  }
  await link.click();
  await page.waitForURL(urlRe);
}

/**
 * Create the AutoCount `erp` connection through the standard integrations form
 * (AC-13-01: four fields, no AppSecret, no company field), then run the Test
 * action - the "clicks Test" half of AC-13-14.
 */
async function createAndTestConnection(page: Page, vendorUrl: string, name: string) {
  await openViaSidebar(page, 'Settings', 'Integrations', /\/settings\/integrations$/);
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);

  await page.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'AutoCount', exact: true }).click();

  await page.getByPlaceholder('e.g. Company mail server').fill(name);
  await page.getByPlaceholder('https://autocount.customer.com').fill(vendorUrl);
  await page.getByPlaceholder('ADMIN').fill('ADMIN');
  // FormRow labels aren't wired to inputs (no htmlFor, BL-080) - target the
  // secrets by type. Provider field order: AppId, then Password.
  const secrets = page.locator('input[type="password"]');
  await secrets.nth(0).fill('app-vsoft');
  await secrets.nth(1).fill('sup3rSecret!');

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/);

  await page.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Test connection' }).click();
  // Success echoes the DISCOVERED company (AC-13-01/04) - proof the AppId
  // selected the intended company database, not just that auth worked.
  await expect(page.getByText(new RegExp(`Connected to ${COMPANY_NAME}`)).first()).toBeVisible({
    timeout: 20_000,
  });
}

/** Companies list → Connect company → pick the connection → Create. */
async function connectCompany(page: Page, connectionName: string, label: string) {
  await openViaSidebar(page, 'AutoCount', 'Companies', /\/autocount\/companies$/);
  await page.getByRole('button', { name: 'Connect company' }).click();
  await page.waitForURL(/\/autocount\/companies\/new$/);

  await page.getByRole('combobox', { name: 'AutoCount connection' }).click();
  await page.getByRole('option', { name: new RegExp(connectionName) }).click();
  await page.getByLabel('Label').fill(label);

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/autocount\/companies\/(?!new)[\w-]+$/, { timeout: 20_000 });
  // The company database is DISCOVERED from the login response, never typed.
  await expect(page.getByText(DB_NAME).first()).toBeVisible();
}

function companyIdFromUrl(page: Page): string {
  const m = /\/autocount\/companies\/([\w-]+)/.exec(new URL(page.url()).pathname);
  if (!m) throw new Error(`not on a company page: ${page.url()}`);
  return m[1];
}

function jobIdFromUrl(page: Page): string {
  const m = /\/autocount\/review\/([\w-]+)/.exec(new URL(page.url()).pathname);
  if (!m) throw new Error(`not on a review page: ${page.url()}`);
  return m[1];
}

/**
 * Open the company's Entities tab. Entities moved off the Overview tab onto
 * their own Resource-shell list - the catalogue is heading for nine-plus
 * entities, each with its own sync mode, cap and watermark.
 */
async function openEntitiesTab(page: Page) {
  await page.getByRole('tab', { name: 'Entities' }).click();
  await expect(page.getByText('Goods received note').first()).toBeVisible({
    timeout: 15_000,
  });
}

/**
 * Run the GRN entity's "Sync now" from its row action menu (the Resource-shell
 * action registry - the same registry that surfaces in the bulk menu). Eager
 * dev runs the job inline, so when the batch has records the app itself
 * navigates to the review surface - a click-driven navigation, not a URL
 * shortcut.
 *
 * Scoped to the GRN row by its visible entity label rather than `.first()` -
 * entity rows are `ORDER BY entity_type ASC`, so which row lands first shifts
 * as more entities are added ("Customer" now sorts before "Goods received
 * note"). Locating by row keeps the spec correct regardless of catalogue
 * order.
 */
async function clickSyncNow(page: Page) {
  await openEntitiesTab(page);
  const row = page.getByRole('row', { name: /Goods received note/i });
  await row.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Sync now' }).click();
}

async function syncNow(page: Page) {
  await clickSyncNow(page);
  await page.waitForURL(/\/autocount\/review\/[\w-]+/, { timeout: 30_000 });
  await expect(page.getByText('Needs review')).toBeVisible();
}

/** No horizontal PAGE scroll - wide content must scroll inside its own box. */
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

/** AC-13-44 - the surface is usable at BOTH widths, asserted not eyeballed. */
async function assertResponsive(page: Page, where: string, anchor: Locator) {
  for (const size of [
    { width: 375, height: 812 },
    { width: 1280, height: 900 },
  ]) {
    await page.setViewportSize(size);
    // Let the reflow land before measuring - a box read on the same tick as the
    // resize still reports the OLD layout and produces a phantom failure.
    await page.waitForTimeout(400);
    await expect(anchor, `${where} @${size.width}px: anchor not visible`).toBeVisible();
    // Visible AND laid out inside the viewport - a clipped control has a box
    // starting past the right edge.
    const box = await anchor.boundingBox();
    expect(box, `${where} @${size.width}px: anchor has no box`).not.toBeNull();
    expect(box!.x, `${where} @${size.width}px: anchor starts off-screen`).toBeLessThan(size.width);
    await expectNoPageScroll(page, `${where} @${size.width}px`);
  }
  await page.setViewportSize({ width: 1280, height: 900 });
}

// ── the journey ──────────────────────────────────────────────────────────────

test.describe('AutoCount ESB - slice 1 read pipeline', () => {
  test('AC-13-14 · Test → Sync now → review → Approve, entirely by clicking', async ({
    page,
    request,
  }) => {
    test.setTimeout(180_000);
    const vendor = await startVendor();
    const stamp = Date.now();
    try {
      const tenant = await provisionTenant(request, 'flow');
      const token = await tenantToken(request, tenant);
      await loginTenantAdmin(page, tenant);

      // ── 1. Connect + Test the AutoCount connection ───────────────────────
      const connectionName = `AutoCount V Soft ${stamp}`;
      await createAndTestConnection(page, vendor.url, connectionName);
      expect(vendor.logins(), 'Test must sign in exactly once (AC-13-03)').toBe(1);

      // ── 2. Register the company (discovered, never typed) ────────────────
      await connectCompany(page, connectionName, `V Soft ${stamp}`);
      const companyId = companyIdFromUrl(page);
      await assertResponsive(page, 'company detail', page.getByText(DB_NAME).first());

      // ── 3. Sync 1 - two brand-new GRNs, staged for review ────────────────
      vendor.queueRead([
        grn('1001', 'GRN-0001', { lastModified: `${vendorDay()} 09:15:00` }),
        grn('1002', 'GRN-0002', {
          lastModified: `${vendorDay()} 10:00:00`,
          supplier: 'Beta Hardware',
        }),
      ]);
      await syncNow(page);
      const job1 = jobIdFromUrl(page);

      // The delta fetch carried the watermark window (AC-13-05) and the
      // list-valued identifier key that stops a silent full-table scan
      // (AC-13-04a).
      const filter = vendor.filters()[0];
      expect(filter.LastModifiedFrom, 'no LastModifiedFrom sent').toBeTruthy();
      expect(filter.LastModifiedTo, 'no LastModifiedTo sent').toBeTruthy();
      expect(Array.isArray(filter.DocNo), 'DocNo must be a LIST').toBe(true);

      await expect(page.getByText('2 records · 2 changed')).toBeVisible();

      // AC-13-11 - the job stops at needs_review and NOTHING is pushed.
      const before = await readStaged(request, token, job1);
      expect(before.jobStatus).toBe('needs_review');
      expect(before.rows).toHaveLength(2);
      expect(
        before.rows.every((r) => r.status === 'STAGED'),
        'a record was pushed before approval (AC-13-11)',
      ).toBe(true);

      await assertResponsive(page, 'review (new records)', page.getByTestId('approve-batch'));

      // AC-14-20 - approval is gated behind a dry-run preview (never approve
      // blind). This connection's sink is the slice-1 logging no-op, so the
      // preview reports `previewable: false` - which still satisfies the gate
      // (hasRun flips true, no error) and unblocks Approve.
      await page.getByTestId('preview-push').click();
      await expect(page.getByTestId('approve-batch')).toBeEnabled({ timeout: 15_000 });

      // Approve → both records PUSHED, job done.
      await page.getByTestId('approve-batch').click();
      // Wait for the DECIDED state, not merely the in-flight disable - the
      // submitting flag flips before the POST resolves and would race the
      // read-back below.
      await expect(page.getByText('This batch has already been reviewed.')).toBeVisible({
        timeout: 30_000,
      });
      const after1 = await readStaged(request, token, job1);
      expect(after1.jobStatus).toBe('done');
      expect(after1.rows.map((r) => r.status).sort()).toEqual(['PUSHED', 'PUSHED']);

      // ── 4. Sync 2 - one CHANGED GRN + one new one ────────────────────────
      // Back to the company by clicking Back, then sync again.
      await page.getByRole('link', { name: 'Back' }).click();
      await page.waitForURL(new RegExp(`/autocount/companies/${companyId}$`));

      vendor.queueRead([
        grn('1001', 'GRN-0001', {
          lastModified: `${vendorDay()} 11:30:00`,
          description: 'July delivery (revised)',
          net: '1400.00000000',
          total: '1484.00000000',
          qty: '140.00000000',
        }),
        grn('1003', 'GRN-0003', {
          lastModified: `${vendorDay()} 12:00:00`,
          supplier: 'Gamma Metals',
          description: 'Bar stock',
          net: '830.00000000',
          total: '880.00000000',
          qty: '55.00000000',
        }),
      ]);
      await syncNow(page);
      const job2 = jobIdFromUrl(page);
      expect(job2).not.toBe(job1);

      const staged2 = await readStaged(request, token, job2);
      expect(staged2.jobStatus).toBe('needs_review');
      const changedRow = staged2.rows.find((r) => r.docNo === 'GRN-0001');
      const newRow = staged2.rows.find((r) => r.docNo === 'GRN-0003');
      expect(changedRow, 'GRN-0001 not staged').toBeTruthy();
      expect(newRow, 'GRN-0003 not staged').toBeTruthy();

      // ── 5. AC-13-12 - the diff shows ONLY the changed fields ─────────────
      // The staged list is a Resource-shell table (AC-15-10/11) - a row opens
      // its full diff in a detail drawer rather than rendering it inline, so
      // the diff is reached by opening the row, not a per-record card testid.
      await page.getByRole('row', { name: new RegExp(changedRow!.docNo!) }).click();
      const changeRows = page.getByTestId('record-diff').locator('[data-testid^="diff-row-"]');

      // Exactly FOUR canonical fields moved: description, net_total, total and
      // the nested lines (qty + sub_total). A scoped COUNT, so an
      // over-rendering regression that dumps every field fails here.
      await expect(changeRows).toHaveCount(4);
      await expect(page.getByTestId('diff-row-description')).toBeVisible();
      await expect(page.getByTestId('diff-row-net_total')).toBeVisible();
      await expect(page.getByTestId('diff-row-total')).toBeVisible();
      await expect(page.getByTestId('diff-row-lines')).toBeVisible();

      // Untouched fields are absent - including `last_modified`, which changes
      // on EVERY re-fetch and is deliberately excluded as tautological noise.
      for (const absent of [
        'supplier_name',
        'supplier_code',
        'currency_code',
        'tax_total',
        'doc_no',
        'doc_date',
        'cancelled',
        'last_modified',
      ]) {
        await expect(
          page.getByTestId(`diff-row-${absent}`),
          `unchanged field ${absent} rendered as a change (AC-13-12)`,
        ).toHaveCount(0);
      }

      // Before → after values are the real ones, not placeholders.
      await expect(page.getByText('July delivery (revised)')).toBeVisible();
      await expect(page.getByText('July delivery', { exact: true })).toBeVisible();

      await assertResponsive(page, 'review (diff)', page.getByTestId('record-diff'));
      await page.keyboard.press('Escape');

      // A first-seen record expands its FULL payload as the diff (nothing →
      // value for every canonical field) rather than being diffed against
      // nothing - proof it renders real content, not an empty/error state.
      await page.getByRole('row', { name: new RegExp(newRow!.docNo!) }).click();
      await expect(page.getByTestId('record-diff')).toBeVisible();
      await expect(page.getByTestId('diff-no-changes')).toHaveCount(0);
      await page.keyboard.press('Escape');

      // ── 6. Approve → PUSHED + done ───────────────────────────────────────
      // AC-14-20 - same dry-run-before-approve gate as sync 1.
      await page.getByTestId('preview-push').click();
      await expect(page.getByTestId('approve-batch')).toBeEnabled({ timeout: 15_000 });
      await page.getByTestId('approve-batch').click();
      // Wait for the DECIDED state, not merely the in-flight disable - the
      // submitting flag flips before the POST resolves and would race the
      // read-back below.
      await expect(page.getByText('This batch has already been reviewed.')).toBeVisible({
        timeout: 30_000,
      });
      const after2 = await readStaged(request, token, job2);
      expect(after2.jobStatus).toBe('done');
      expect(after2.rows.map((r) => r.status).sort()).toEqual(['PUSHED', 'PUSHED']);

      // ── 7. AC-13-13 - approval is idempotent ─────────────────────────────
      // A replay (double-click, retry, redelivered request) must be a NO-OP
      // that returns the original result - never a second push and never a
      // scary error on the second click of a successful action. The UI
      // disables the button, so the replay is issued at the boundary that a
      // real double-submit would reach.
      expect(await countApprovals(request, token, job2), 'first approval not logged').toBe(1);

      const replay = await request.post(`${API}/autocount/jobs/${job2}/approve`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      expect(replay.status(), 'replayed approve must not error (AC-13-13)').toBe(200);
      const replayBody = await replay.json();
      expect(replayBody.result.pushed, 'replay re-reported a different push count').toBe(2);

      const afterReplay = await readStaged(request, token, job2);
      expect(afterReplay.jobStatus).toBe('done');
      expect(afterReplay.rows).toHaveLength(2);
      expect(afterReplay.rows.map((r) => r.status).sort()).toEqual(['PUSHED', 'PUSHED']);
      // Pushed exactly ONCE: the replay ran no second push loop.
      expect(
        await countApprovals(request, token, job2),
        'the replay pushed a second time (AC-13-13)',
      ).toBe(1);

      // ── 8. The run is visible in history, reachable by clicking ──────────
      await page.getByRole('link', { name: 'Back' }).click();
      await page.waitForURL(new RegExp(`/autocount/companies/${companyId}$`));
      await page.getByRole('tab', { name: 'Runs' }).click();
      await expect(page.getByText('Goods received note').first()).toBeVisible();
      await assertResponsive(page, 'company runs', page.getByRole('tab', { name: 'Runs' }));

      // ── 9. A sync that legitimately finds nothing SAYS so ────────────────
      // The reported defect: clicking Sync now a second time produced silence.
      // The behaviour was correct (the vendor had no changes since the
      // watermark, and an empty batch must not advance it) - only the UI was
      // mute. An empty run must read as a successful no-op: no navigation to a
      // review surface that has nothing in it, and no failure badge.
      vendor.queueRead([]);
      await clickSyncNow(page);
      const outcome = page.getByTestId('sync-outcome');
      await expect(outcome).toBeVisible({ timeout: 30_000 });
      await expect(outcome).toContainText(/no changes since last sync/i);
      // Still on the company - an empty batch never pretends to be reviewable.
      expect(new URL(page.url()).pathname).toBe(`/autocount/companies/${companyId}`);

      // …and the state that makes the zero explicable is on the row itself.
      await expect(page.getByText('Synced up to').first()).toBeVisible();
      await assertResponsive(page, 'company entities', outcome);

      expect(vendor.reads(), 'exactly three delta fetches ran').toBe(3);
    } finally {
      await vendor.close();
    }
  });

  test('AC-13-12 · Discard closes the batch without pushing', async ({ page, request }) => {
    test.setTimeout(180_000);
    const vendor = await startVendor();
    const stamp = Date.now();

    try {
      const tenant = await provisionTenant(request, 'discard');
      const token = await tenantToken(request, tenant);
      await loginTenantAdmin(page, tenant);

      const connectionName = `AutoCount Discard ${stamp}`;
      await createAndTestConnection(page, vendor.url, connectionName);
      await connectCompany(page, connectionName, `Discard Co ${stamp}`);

      vendor.queueRead([grn('2001', 'GRN-9001', { lastModified: `${vendorDay()} 09:00:00` })]);
      await syncNow(page);
      const jobId = jobIdFromUrl(page);

      await page.getByTestId('discard-batch').click();
      await page.getByRole('button', { name: 'Discard', exact: true }).last().click();
      await expect(page.getByText('This batch has already been reviewed.')).toBeVisible({
        timeout: 30_000,
      });

      const after = await readStaged(request, token, jobId);
      expect(after.jobStatus).toBe('done');
      // Discarded, never deleted - the raw payload stays for audit (AC-13-07)
      // and nothing reached the sink.
      expect(after.rows.map((r) => r.status)).toEqual(['DISCARDED']);
    } finally {
      await vendor.close();
    }
  });
});
