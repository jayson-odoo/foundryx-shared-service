import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import {
  createServer,
  type IncomingMessage,
  type Server,
  type ServerResponse,
} from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from '@playwright/test';

/**
 * Sprint-5/02 (AutoCount document mapping - sql_db sales_order) - AC-02-26 E2E.
 * Real clicks against the LIVE stack (Next -> FastAPI -> Postgres). After
 * sign-in every navigation is a click on something a real operator can see -
 * no deep-link `page.goto`.
 *
 * ── The journey ─────────────────────────────────────────────────────────────
 * DB company (the plan-01/22 "ETL Demo Co" spec rig, `--company` idempotent
 * find-or-create) -> Settings/Integrations (a scripted Sorento consumer, same
 * pattern `autocount-db-etl.spec.ts` uses) -> Overview: Delivery = Sorento ->
 * Entities -> Add entity -> Sales order -> Configure -> Query tab -> Use
 * preset "AutoCount SO" -> the header+line query text is then adapted to this
 * rig's flat `public.etl_demo_so_headers`/`etl_demo_so_lines` tables (see
 * below) -> Test query + Test line query (real rows) -> Save -> Mapping tab
 * shows the preset-seeded header + line rows, enabled -> Simulate mapping on
 * a real previewed header -> status + line fields render -> Review & Activate
 * -> Run preview passes (the scripted Sorento never fails a record) ->
 * Activate.
 *
 * ── Why the query text is EDITED after "Use preset" ─────────────────────────
 * `presets.py`'s "AutoCount SO" preset is written for the REAL AutoCount
 * schema (`{database}.dbo.SO`/`Debtor`, real MSSQL table/column casing) -
 * exactly as documented ("a preset is a STARTING POINT, never re-applied").
 * This spec's own Postgres-native demo tables (`etl_demo_so_headers`/
 * `etl_demo_so_lines`, no `Debtor`/`Item` master join tables) are a DIFFERENT
 * shape, so the query text is replaced with an equivalent SELECT against
 * those tables - but every column is DOUBLE-QUOTED under the SAME alias the
 * preset's own field-mapping rows expect (`AS "DocKey"`, `AS "DocNo"`, ...),
 * so Postgres preserves the exact case and the preset-seeded mapping rows
 * (persisted at Save, independent of the query text) resolve against the
 * real result columns with ZERO further editing - the same discipline a real
 * operator follows when pointing a preset at their own database's shape.
 *
 * ── Why a scripted Sorento consumer ─────────────────────────────────────────
 * Same reasoning as `autocount-db-etl.spec.ts`: AC-02-26's "Review & Activate
 * preview passes" needs a sink whose `dry_run` actually implements the
 * contract - "ETL Demo Co" is born `sink_impl=logging` (no `dry_run`), so
 * this spec stands a tiny HTTP server speaking the minimal Appendix A6/A8
 * contract and points a REAL `sorento` consumer connection at it via real
 * clicks, then re-anchors the company's own Delivery to it (Overview tab).
 * Only the consumer's socket is scripted; the extraction, mapping engine,
 * dry-run call and activation gate are all the real production code path.
 *
 * ── Spec isolation ──────────────────────────────────────────────────────────
 * A DEDICATED, timestamped tenant (never the `default` tenant `autocount-db-
 * etl.spec.ts` shares) - `ensure_demo_company` is a find-or-create PER TENANT
 * (`(tenant_id, database_name)` uniqueness), so a fresh tenant always gets its
 * OWN "ETL Demo Co" with no collision against any other spec. Every created
 * name carries the tenant's own timestamp. Archived + purged in `finally`.
 * The `public.etl_demo_so_*` SOURCE tables are shared/idempotent dev fixture
 * data (never tenant-scoped) - this spec only READS them (Test query) and
 * never mutates/deletes a row, so a concurrent run touching the same tables
 * cannot break this journey's assertions (row COUNTS are never asserted,
 * only "rows returned").
 *
 * ── Ports ───────────────────────────────────────────────────────────────────
 * Defaults to the standard :3001/:8001 stack; a worktree run overrides both
 * via `PLAYWRIGHT_BASE_URL` (through the config's `baseURL`) + `E2E_API_URL`.
 */

const API = process.env.E2E_API_URL ?? 'http://localhost:8001';

test.setTimeout(240_000);

// ── the scripted Sorento consumer (Appendix A6/A8 minimal contract) ─────────

interface FakeSorento {
  url: string;
  close(): Promise<void>;
}

/** Stand up the scripted Sorento consumer on an ephemeral loopback port -
 * always succeeds (created, never failed) so "Review & Activate preview
 * passes" is deterministic. */
async function startFakeSorento(): Promise<FakeSorento> {
  const server: Server = createServer(
    (req: IncomingMessage, res: ServerResponse) => {
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
        const url = new URL(req.url ?? '/', 'http://127.0.0.1');
        const send = (payload: unknown) => {
          res.writeHead(200, { 'Content-Type': 'application/json' });
          res.end(JSON.stringify(payload));
        };

        // The Sorento provider's Test-connection probe.
        if (url.pathname.startsWith('/api/v1/external/read/')) {
          send({ records: [], not_found: body.source_refs ?? [] });
          return;
        }

        if (url.pathname.startsWith('/api/v1/external/ingest/')) {
          const dryRun = url.searchParams.get('dry_run') === 'true';
          const records =
            (body.records as Record<string, unknown>[] | undefined) ?? [];
          const outRecords = records.map((r) => ({
            source_ref: String(r.source_ref ?? ''),
            outcome: 'created',
            entity_id: dryRun
              ? null
              : `stub-${Math.random().toString(36).slice(2, 10)}`,
            diff: {},
            errors: {},
          }));
          send({
            summary: {
              total: outRecords.length,
              created: outRecords.length,
              updated: 0,
              failed: 0,
              retryable: 0,
            },
            records: outRecords,
          });
          return;
        }

        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ message: `unexpected path ${url.pathname}` }));
      });
    },
  );

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;

  return {
    url: `http://127.0.0.1:${port}`,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

// ── backend dev-fixture helper (the seed rig's own documented CLI) ──────────

const BACKEND_DIR = path.resolve(__dirname, '..', '..', 'service_backend');
const VENV_PYTHON = path.join(BACKEND_DIR, '.venv', 'bin', 'python');
const PYTHON_BIN = existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3';

/** `python -m scripts.seed_etl_demo_source <args>` - the documented dev rig
 * (plan 22). Idempotent: safe to call every run. */
function runSeed(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      PYTHON_BIN,
      ['-m', 'scripts.seed_etl_demo_source', ...args],
      {
        cwd: BACKEND_DIR,
        encoding: 'utf8',
        env: { ...process.env, PYTHONPATH: BACKEND_DIR },
      },
      (error, stdout, stderr) => {
        if (error)
          reject(
            new Error(
              `seed_etl_demo_source ${args.join(' ')} failed: ${stderr || error.message}`,
            ),
          );
        else resolve(stdout);
      },
    );
  });
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
    data: {
      email: 'platform@example.com',
      password: 'platform1234',
      tenantSlug: 'platform',
    },
  });
  if (!res.ok()) throw new Error(`operator login failed: ${await res.text()}`);
  return (await res.json()).access_token as string;
}

/** Dedicated, timestamped tenant with the `autocount` module ACTIVE. */
async function provisionTenant(
  request: APIRequestContext,
): Promise<TenantAdmin> {
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const slug = `e2e-acdoc-${stamp}`;
  const token = await operatorToken(request);
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E AutoCount Doc Mapping ${stamp}`,
      slug,
      adminName: 'AutoCount Doc Admin',
      adminEmail: `admin-${slug}@example.com`,
      adminPassword: 'ChangeMe1!',
    },
  });
  if (!res.ok())
    throw new Error(`tenant provisioning failed: ${await res.text()}`);
  const tenantId = (await res.json()).id as string;

  const install = await request.post(
    `${API}/platform/tenants/${tenantId}/modules/autocount/install`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!install.ok())
    throw new Error(`module install failed: ${await install.text()}`);

  return {
    slug,
    tenantId,
    email: `admin-${slug}@example.com`,
    password: 'ChangeMe1!',
  };
}

/** Archive -> purge the E2E tenant (BL-035 two-step). Best effort: a failure
 * here must never fail the journey that already passed. */
async function purgeTenant(
  request: APIRequestContext,
  t: TenantAdmin,
): Promise<boolean> {
  try {
    const token = await operatorToken(request);
    const headers = { Authorization: `Bearer ${token}` };
    const edges = await request.get(
      `${API}/platform/tenants/${t.tenantId}/transitions`,
      { headers },
    );
    if (!edges.ok()) return false;
    const archive = (
      (await edges.json()) as { data: { id: string; label: string }[] }
    ).data.find((e) => /archive/i.test(e.label));
    if (!archive) return false;
    const moved = await request.post(
      `${API}/platform/tenants/${t.tenantId}/transition`,
      { headers, data: { transitionId: archive.id } },
    );
    if (!moved.ok()) return false;
    const purged = await request.post(
      `${API}/platform/tenants/${t.tenantId}/purge`,
      { headers, data: { confirmSlug: t.slug } },
    );
    return purged.ok();
  } catch {
    return false;
  }
}

// ── UI helpers (real clicks) ─────────────────────────────────────────────────

/** Tenants resolve by SUBDOMAIN - the sign-in page is the ONE `goto`. */
async function loginTenantAdmin(page: Page, t: TenantAdmin, baseURL: string) {
  const base = new URL(baseURL);
  await page.goto(`${base.protocol}//${t.slug}.localhost:${base.port}/signin`);
  await page.getByPlaceholder('Your email').fill(t.email);
  await page.getByPlaceholder('Your password').fill(t.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), {
    timeout: 60_000,
  });
}

/** Sidebar section -> child link. Expands the section when collapsed. */
async function openViaSidebar(
  page: Page,
  section: string,
  child: string,
  urlRe: RegExp,
) {
  const link = page.getByRole('link', { name: child, exact: true }).first();
  if (!(await link.isVisible().catch(() => false))) {
    await page
      .getByText(section, { exact: true })
      .first()
      .click({ force: true });
    await expect(link).toBeVisible({ timeout: 15_000 });
  }
  await link.click();
  await page.waitForURL(urlRe);
}

/** Settings -> Integrations -> New -> the Sorento provider, pointed at the
 * scripted consumer this spec stood up. */
async function createSorentoConnection(
  page: Page,
  name: string,
  baseUrl: string,
) {
  await openViaSidebar(
    page,
    'Settings',
    'Integrations',
    /\/settings\/integrations$/,
  );
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);

  await page.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'Sorento', exact: true }).click();

  await page.getByPlaceholder('e.g. Company mail server').fill(name);
  await page.getByPlaceholder('https://sorento.customer.com').fill(baseUrl);
  await page.locator('input[type="password"]').fill('e2e-fake-sorento-key');

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/, {
    timeout: 20_000,
  });
}

/** AutoCount -> Companies -> ETL Demo Co (this tenant's own, freshly created
 * by `--company`, so there is exactly one). */
async function openDemoCompany(page: Page) {
  await openViaSidebar(
    page,
    'AutoCount',
    'Companies',
    /\/autocount\/companies$/,
  );
  await page.getByRole('row', { name: /ETL Demo Co/ }).first().click();
  await page.waitForURL(/\/autocount\/companies\/[\w-]+(\?|$)/, {
    timeout: 20_000,
  });
}

/** Overview tab: Edit -> Delivery = Sorento -> pick `connectionName` -> fill
 * the Sorento company code -> Save (the activation-gate anchor). */
async function setSorentoPushTarget(
  page: Page,
  connectionName: string,
  companyCode: string,
) {
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByRole('button', { name: /^Edit$/ }).first().click();

  await page.getByRole('combobox', { name: 'Push delivery target' }).click();
  await page.getByRole('option', { name: 'Sorento', exact: true }).click();

  await page
    .getByRole('combobox', { name: 'Sorento consumer connection' })
    .click();
  await page.getByRole('option', { name: new RegExp(connectionName) }).click();

  await page.getByTestId('sink-company-code').fill(companyCode);
  await page.getByRole('button', { name: /^Save/ }).first().click();
  await expect(page.getByTestId('sink-company-code-value')).toHaveText(
    companyCode,
    { timeout: 15_000 },
  );
}

/** CodeMirror is not a plain input - click in, select-all, type. Real
 * keystrokes (Playwright dispatches trusted keyboard events), not a value
 * assignment. */
async function setSqlEditor(page: Page, testId: string, sql: string) {
  const host = page.getByTestId(testId);
  await host.click();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.press('Backspace');
  await page.keyboard.insertText(sql);
}

test.describe('AutoCount document mapping - sales order (AC-02-26)', () => {
  let tenant: TenantAdmin;
  let sorento: FakeSorento;

  test.beforeAll(async ({ request }) => {
    // Idempotent dev fixtures - safe alongside any concurrently-running spec.
    await runSeed([]);
    tenant = await provisionTenant(request);
    await runSeed(['--company', '--tenant-slug', tenant.slug]);
    sorento = await startFakeSorento();
  });

  test.afterAll(async ({ request }) => {
    await sorento?.close();
    if (tenant) await purgeTenant(request, tenant);
  });

  test('DB company -> Sales order -> Use preset -> Test -> Save -> Mapping -> Simulate -> Review & Activate preview passes', async ({
    page,
    baseURL,
  }) => {
    await loginTenantAdmin(page, tenant, baseURL!);

    // ── Sorento consumer + push target ────────────────────────────────────
    const connectionName = `E2E Doc Mapping Sorento ${tenant.slug}`;
    await createSorentoConnection(page, connectionName, sorento.url);

    await openDemoCompany(page);
    await setSorentoPushTarget(page, connectionName, 'E2EDOC');

    // ── Entities -> Add entity -> Sales order -> Configure ────────────────
    await page.getByRole('tab', { name: 'Entities' }).click();
    await page.getByRole('combobox', { name: 'Add entity' }).click();
    await page.getByRole('option', { name: 'Sales order', exact: true }).click();
    await page.getByTestId('add-entity-configure').click();
    await page.waitForURL(/\/entities\/sales_order(\?|$)/, { timeout: 20_000 });

    // ── Query tab: Edit -> Use preset -> adapt the query -> Test ──────────
    await page.getByRole('button', { name: /^Edit$/ }).first().click();

    await page.getByRole('combobox', { name: 'Use preset' }).click();
    await page.getByRole('option', { name: 'AutoCount SO', exact: true }).click();

    // Same alias contract "AutoCount SO"'s own preset field rows expect
    // (`DocKey`/`DocNo`/`DebtorAutoKey`/`SalesAgent`/`DocDate`/
    // `RequestedDeliveryDate`/`Note`/`Cancelled`/`DebtorCode`/`DebtorName`/
    // `LastModified`), adapted to this rig's flat demo tables and DOUBLE-
    // QUOTED so Postgres preserves the exact case.
    const headerSql =
      'SELECT doc_key AS "DocKey", doc_no AS "DocNo", ' +
      'debtor_code AS "DebtorAutoKey", agent_code AS "SalesAgent", ' +
      'doc_date AS "DocDate", doc_date AS "RequestedDeliveryDate", ' +
      'doc_no AS "Note", ' +
      '(CASE WHEN cancelled THEN \'T\' ELSE \'F\' END) AS "Cancelled", ' +
      'debtor_code AS "DebtorCode", debtor_code AS "DebtorName", ' +
      'last_modified AS "LastModified" ' +
      'FROM public.etl_demo_so_headers';
    await setSqlEditor(page, 'sql-editor', headerSql);

    const lineSql =
      'SELECT dtl_key AS "DtlKey", item_code AS "ItemAutoKey", ' +
      'location AS "LocationAutoKey", qty AS "Qty", qty AS "TransferedQty", ' +
      'unit_price AS "UnitPrice", 0 AS "DiscountAmt", ' +
      '(qty * unit_price) AS "SubTotal", \'PCS\' AS "UOM", ' +
      'CURRENT_DATE AS "DeliveryDate", item_code AS "ItemCode", ' +
      'item_code AS "Description", location AS "Location", 1 AS "Seq" ' +
      'FROM public.etl_demo_so_lines WHERE doc_key = :doc_key';
    await setSqlEditor(page, 'sql-line-editor', lineSql);

    await page.getByTestId('sql-test-query').click();
    await expect(page.getByTestId('sql-preview-badge')).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId('sql-preview-badge')).toContainText(/[1-9]\d* rows/);

    await page.getByTestId('sql-test-line-query').click();
    await expect(page.getByTestId('sql-line-preview-badge')).toBeVisible({
      timeout: 15_000,
    });

    await page.getByRole('button', { name: /^Save/ }).first().click();
    await expect(page.getByRole('button', { name: /^Edit$/ }).first()).toBeVisible({
      timeout: 15_000,
    });

    // ── Mapping tab shows the seeded header + line rows ───────────────────
    await page.getByRole('tab', { name: 'Mapping' }).click();
    await expect(page.getByRole('heading', { name: 'Header fields' })).toBeVisible();
    await expect(page.getByText('DocNo', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('DtlKey', { exact: true }).first()).toBeVisible();

    // ── Simulate on a real previewed header ───────────────────────────────
    await page.getByRole('button', { name: 'Simulate mapping' }).click();
    await page.getByRole('combobox', { name: 'Header row' }).click();
    await page.getByRole('option').first().click();
    await page.getByRole('button', { name: 'Run simulation' }).click();
    await expect(page.getByTestId('simulate-status')).toBeVisible({
      timeout: 15_000,
    });
    await expect(page.getByTestId('field-results')).toBeVisible();
    // The dialog corner close button can sit outside the viewport once the
    // simulation result grows the dialog taller than the window - Escape is
    // the same real-user affordance Radix dialogs offer, and it always works
    // regardless of scroll position.
    await page.keyboard.press('Escape');
    await expect(page.getByTestId('field-results')).toBeHidden();

    // ── Review & Activate: preview passes ─────────────────────────────────
    await page.getByRole('tab', { name: 'Review & Activate' }).click();
    await page.getByTestId('etl-run-preview').click();
    await expect(page.getByTestId('etl-preview-passed')).toBeVisible({
      timeout: 20_000,
    });
    await expect(page.getByTestId('etl-preview-failed')).toHaveCount(0);

    const activate = page.getByTestId('etl-activate');
    await expect(activate).toBeEnabled();
    await activate.click();
    await expect(page.getByTestId('etl-run-now')).toBeVisible({
      timeout: 15_000,
    });
  });
});
