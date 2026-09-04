import { execFile } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from '@playwright/test';

/**
 * Plan sprint-5/01 (AutoCount DB-only company onboarding) - slice S3 E2E,
 * AC-01-24. Real clicks against the LIVE stack (Next -> FastAPI -> Postgres).
 * After sign-in every navigation is a click on something a real operator can
 * see - no deep-link `page.goto`.
 *
 * ── The journey ─────────────────────────────────────────────────────────────
 * AutoCount -> Companies -> Connect company -> Source "SQL database" -> pick
 * the connection -> Create -> Overview (Integration "SQL database") ->
 * Entities -> Add entity (Customer offered, Goods received note not) ->
 * Customer -> Query tab (connection LOCKED, no picker) -> schema tree ->
 * `etl_demo_customers` -> Test query (rows render) -> key column -> Save (the
 * Customer row is born on the DB source) -> Entities -> Connect company again
 * (every SQL connection already registered). The Connect-company form, the
 * Query tab and the Entities tab are each also asserted at 375x812 (no
 * horizontal page scroll, controls still visible - AC-01-15 / AC-01-21).
 *
 * ── Why this Postgres is the "AutoCount" database ───────────────────────────
 * The `sql_database` connection points back at the Foundryx database itself
 * (plan 22's `etl_demo_customers` rig - `python -m scripts.seed_etl_demo_source`
 * creates the dev-fixture tables inside `foundryx_service`), so the create-time
 * identity probe (`SELECT current_database()`, AC-01-02) genuinely matches
 * `config.database`, the schema tree lists a real table, and Test query returns
 * real rows - no second server, no customer data.
 *
 * ── Spec isolation ──────────────────────────────────────────────────────────
 * The suite is fullyParallel, so this spec provisions its OWN timestamped
 * tenant via the operator API (setup only - the flow under test stays real
 * clicks), installs the `autocount` module there, creates the `sql_database`
 * connection through the integrations API inside that tenant, and archives +
 * purges the tenant afterwards (best effort). Every name carries a per-run
 * stamp - never a fixed literal.
 *
 * ── Ports ───────────────────────────────────────────────────────────────────
 * Defaults to the standard :3001/:8001 stack; a worktree run overrides both
 * via `PLAYWRIGHT_BASE_URL` (through the config's `baseURL`) + `E2E_API_URL`.
 */

const API = process.env.E2E_API_URL ?? 'http://localhost:8001';
const DATABASE = 'foundryx_service';
const DEMO_TABLE = 'etl_demo_customers';

test.setTimeout(240_000);

// ── backend dev-fixture helper (the seed rig's own documented CLI) ──────────

const BACKEND_DIR = path.resolve(__dirname, '..', '..', 'service_backend');
const VENV_PYTHON = path.join(BACKEND_DIR, '.venv', 'bin', 'python');
const PYTHON_BIN = existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3';

/** `python -m scripts.seed_etl_demo_source` with no args = create/top-up the
 * `public.etl_demo_*` source tables, idempotent. Nothing tenant-scoped. */
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
  // Timestamp AND a random suffix so two workers in the same millisecond never
  // collide on `ix_tenants_slug`. Never a fixed literal.
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 8)}`;
  const slug = `e2e-dbco-${stamp}`;
  const token = await operatorToken(request);
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E AutoCount DB Company ${stamp}`,
      slug,
      adminName: 'AutoCount Admin',
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
      {
        headers,
        data: { transitionId: archive.id },
      },
    );
    if (!moved.ok()) return false;
    const purged = await request.post(
      `${API}/platform/tenants/${t.tenantId}/purge`,
      {
        headers,
        data: { confirmSlug: t.slug },
      },
    );
    return purged.ok();
  } catch {
    return false;
  }
}

/** The tenant admin's own token (the connection is created INSIDE the
 * dedicated tenant - setup only, the company flow stays real clicks). */
async function tenantToken(
  request: APIRequestContext,
  t: TenantAdmin,
): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: t.email, password: t.password, tenantSlug: t.slug },
  });
  if (!res.ok())
    throw new Error(`tenant admin login failed: ${await res.text()}`);
  return (await res.json()).access_token as string;
}

/** A `sql_database` connection pointed at this very Foundryx Postgres. */
async function createSqlDatabaseConnection(
  request: APIRequestContext,
  t: TenantAdmin,
  name: string,
): Promise<string> {
  const token = await tenantToken(request, t);
  const res = await request.post(`${API}/integrations/connections`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      provider: 'sql_database',
      name,
      config: {
        dbType: 'postgresql',
        host: '127.0.0.1',
        port: '5432',
        database: DATABASE,
        username: 'foundryx',
      },
      credentials: { password: 'foundryx' },
    },
  });
  if (!res.ok())
    throw new Error(
      `sql_database connection create failed: ${await res.text()}`,
    );
  return (await res.json()).id as string;
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
  // `.first()` - a detail page's OWN breadcrumb can carry a same-named link
  // ("Companies" on a company's breadcrumb), which would otherwise
  // strict-mode-violate alongside the sidebar's.
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

/** No horizontal PAGE scroll - wide content must scroll inside its own box. */
async function expectNoPageScroll(page: Page, where: string) {
  const overflow = await page.evaluate(() => {
    const el = document.documentElement;
    return {
      scrollWidth: el.scrollWidth,
      clientWidth: el.clientWidth,
      innerWidth: window.innerWidth,
    };
  });
  expect(
    overflow.scrollWidth,
    `${where}: page scrolls horizontally (${overflow.scrollWidth} > ${overflow.clientWidth})`,
  ).toBeLessThanOrEqual(
    Math.max(overflow.clientWidth, overflow.innerWidth) + 1,
  );
}

/** Companies list -> Connect company (the shell's create button). */
async function openConnectCompany(page: Page) {
  await openViaSidebar(
    page,
    'AutoCount',
    'Companies',
    /\/autocount\/companies$/,
  );
  await page.getByRole('button', { name: 'Connect company' }).click();
  await page.waitForURL(/\/autocount\/companies\/new$/);
}

/** The Source segmented control (Radix ToggleGroup, type=single -> radios). */
function sourceOption(page: Page, label: string) {
  return page.getByRole('radio', { name: label, exact: true });
}

// ── AC-01-24: the real-click journey ────────────────────────────────────────

test('AC-01-24 DB company: connect from a SQL database -> add Customer -> locked connection -> preview rows', async ({
  page,
  request,
  baseURL,
}) => {
  if (!baseURL)
    throw new Error('baseURL is required (playwright config `use.baseURL`)');

  // The plan-22 dev rig: `public.etl_demo_customers` inside this very Postgres
  // (idempotent - a no-op when the tables already exist).
  await runSeed([]);

  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const connectionName = `E2E DB Co Postgres ${stamp}`;
  const companyLabel = `E2E DB Company ${stamp}`;

  const tenant = await provisionTenant(request);
  try {
    await createSqlDatabaseConnection(request, tenant, connectionName);

    await loginTenantAdmin(page, tenant, baseURL);

    // ── Connect company: Source toggle -> SQL database -> picker -> Create ──
    // (AC-01-12/14/16)
    await openConnectCompany(page);
    await expect(sourceOption(page, 'AutoCount API')).toBeVisible();
    // The only unbound connection is a SQL one, so "SQL database" is already
    // the default (AC-01-12) - the operator still clicks it, as the journey says.
    await sourceOption(page, 'SQL database').click();
    await expect(sourceOption(page, 'SQL database')).toHaveAttribute(
      'data-state',
      'on',
    );
    await expect(page.getByTestId('connect-company-banner')).toBeHidden();

    const create = page.getByRole('button', { name: 'Create', exact: true });
    // Create is withheld until a connection is picked (AC-01-13).
    await expect(create).toBeDisabled();

    await page
      .getByRole('combobox', { name: 'SQL database connection' })
      .click();
    await page
      .getByRole('option', { name: new RegExp(connectionName) })
      .click();
    await page.getByLabel('Label').fill(companyLabel);
    await expectNoPageScroll(page, 'connect company @1280');

    // ── Responsive: the Connect-company form at 375px (AC-01-15) ──────────
    // Toggle, picker, label and Create stack - no horizontal scroll, nothing
    // clipped - then back to desktop so the rest of the journey is unaffected.
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(500);
    await expectNoPageScroll(page, 'connect company @375');
    await expect(sourceOption(page, 'SQL database')).toBeVisible();
    await expect(
      page.getByRole('combobox', { name: 'SQL database connection' }),
    ).toBeVisible();
    await expect(page.getByLabel('Label')).toBeVisible();
    await expect(create).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForTimeout(300);

    await expect(create).toBeEnabled();
    await create.click();
    // The Resource shell may carry record-nav state on the URL - never anchor
    // the id at the end.
    await page.waitForURL(/\/autocount\/companies\/(?!new)[\w-]+(\?|$)/, {
      timeout: 30_000,
    });

    // ── Overview: identity DISCOVERED from the connection, kind stated ──────
    // (AC-01-02 live: the probe matched `config.database`; AC-01-16)
    await expect(
      page.getByText(companyLabel, { exact: true }).first(),
    ).toBeVisible({
      timeout: 20_000,
    });
    await expect(
      page.getByText(DATABASE, { exact: true }).first(),
    ).toBeVisible();
    await expect(page.getByTestId('company-source-kind')).toHaveText(
      'SQL database',
    );
    await expect(
      page.getByRole('link', { name: 'Open connection' }),
    ).toBeVisible();

    // ── Entities: Add entity offers every sql_db entity, never GRN ──────────
    // (AC-01-05: a DB company seeds NOTHING, so the Entities list is empty
    // and every one of the nine is addable; AC-01-17)
    await page.getByRole('tab', { name: 'Entities' }).click();
    const addEntity = page.getByRole('combobox', { name: 'Add entity' });
    await expect(addEntity).toBeVisible({ timeout: 20_000 });
    await addEntity.click();
    const options = page.getByRole('option');
    await expect(options.filter({ hasText: /^Customer$/ })).toHaveCount(1);
    await expect(options.filter({ hasText: /^Supplier$/ })).toHaveCount(1);
    await expect(options.filter({ hasText: /^Product$/ })).toHaveCount(1);
    await expect(
      options.filter({ hasText: /Goods received note/ }),
    ).toHaveCount(0);
    await expect(options).toHaveCount(9);
    await options.filter({ hasText: /^Customer$/ }).click();
    await page.getByTestId('add-entity-configure').click();
    await page.waitForURL(/\/entities\/customer(\?|$)/, { timeout: 20_000 });

    // ── Query tab: the connection is LOCKED (no picker), preview returns rows
    // (AC-01-19, AC-01-24)
    const editToggle = page.getByRole('button', { name: /^Edit$/ }).first();
    await expect(editToggle).toBeVisible({ timeout: 60_000 });
    await editToggle.click();

    const locked = page.getByTestId('locked-connection');
    await expect(locked).toBeVisible({ timeout: 30_000 });
    await expect(locked).toContainText(connectionName);
    await expect(locked).toContainText(DATABASE);
    await expect(
      page.getByRole('combobox', { name: 'Connection' }),
    ).toHaveCount(0);
    await expect(page.getByTestId('no-sql-connection')).toHaveCount(0);

    // Schema tree -> the demo table -> Insert SELECT * -> Test query.
    await page.getByLabel('Search tables').fill(DEMO_TABLE);
    await page
      .getByRole('treeitem', { name: new RegExp(DEMO_TABLE) })
      .first()
      .click();
    await page.getByTestId('sql-insert-starter').click();
    await expect(page.getByTestId('sql-editor')).toContainText(DEMO_TABLE);
    await page.getByTestId('sql-test-query').click();
    await expect(page.getByTestId('sql-preview-badge')).toBeVisible({
      timeout: 30_000,
    });
    const previewRows = page
      .getByTestId('sql-preview-success')
      .locator('tbody tr');
    expect(await previewRows.count()).toBeGreaterThan(0);
    await expect(
      page.getByTestId('sql-preview-success').getByText('acc_no').first(),
    ).toBeVisible();
    await expectNoPageScroll(page, 'task editor / query tab @1280');

    // ── Responsive: the task editor Query tab at 375px (AC-01-21) ──────────
    // The schema tree stacks above the editor and the preview grid scrolls
    // inside its own box; the locked row and the preview badge stay visible.
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(500);
    await expectNoPageScroll(page, 'task editor / query tab @375');
    await expect(locked).toBeVisible();
    await expect(page.getByTestId('sql-preview-badge')).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForTimeout(300);

    // Save the query - the Customer row is born on the DB source with the
    // company connection filled server-side (AC-01-09/10 live).
    await page
      .getByRole('combobox')
      .filter({ hasText: 'Pick columns' })
      .first()
      .click();
    await page.getByRole('option', { name: 'acc_no', exact: true }).click();
    await page.keyboard.press('Escape');
    await page.getByRole('button', { name: /^Save/ }).first().click();
    await expect(editToggle).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId('task-save-error')).toHaveCount(0);
    // Read mode keeps the locked row - still no picker.
    await expect(locked).toBeVisible();
    await expect(
      page.getByRole('combobox', { name: 'Connection' }),
    ).toHaveCount(0);

    // ── Back to the company: the born row lists, Customer is no longer addable
    await page
      .getByRole('link', { name: 'Companies', exact: true })
      .first()
      .click();
    await page.waitForURL(/\/autocount\/companies(\?|$)/);
    await page
      .getByRole('row', { name: new RegExp(companyLabel) })
      .first()
      .click();
    await page.waitForURL(/\/autocount\/companies\/(?!new)[\w-]+(\?|$)/, {
      timeout: 20_000,
    });
    await page.getByRole('tab', { name: 'Entities' }).click();
    const customerRow = page.getByRole('row', { name: /Customer/ }).first();
    await expect(customerRow).toBeVisible({ timeout: 20_000 });
    // API-only row actions are hidden on a DB company (AC-01-18).
    await customerRow.getByRole('button', { name: 'Actions' }).first().click();
    await expect(
      page.getByRole('menuitem', { name: /configure database query/i }),
    ).toBeVisible();
    await expect(
      page.getByRole('menuitem', { name: /change source/i }),
    ).toHaveCount(0);
    await expect(
      page.getByRole('menuitem', { name: /lookback|first-run/i }),
    ).toHaveCount(0);
    await page.keyboard.press('Escape');
    await addEntity.click();
    await expect(
      page.getByRole('option').filter({ hasText: /^Customer$/ }),
    ).toHaveCount(0);
    await expect(page.getByRole('option')).toHaveCount(8);
    await page.keyboard.press('Escape');
    await expectNoPageScroll(page, 'company / entities tab @1280');

    // ── Responsive: the Entities tab at 375px (user mandate, AC-01-21) ──────
    await page.setViewportSize({ width: 375, height: 812 });
    await page.waitForTimeout(500);
    await expectNoPageScroll(page, 'company / entities tab @375');
    await expect(customerRow).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.waitForTimeout(300);

    // ── A second Connect company with the same connection ───────────────────
    // The connection is BOUND now, so the picker withholds it (foolproof-UI)
    // and the per-source banner explains why (AC-01-13; the backend's 409 for
    // an already-bound connection is pinned by `test_autocount_db_company.py`).
    await openConnectCompany(page);
    await sourceOption(page, 'SQL database').click();
    await expect(page.getByTestId('connect-company-banner')).toHaveText(
      /Every SQL database connection is already registered as a company\./,
    );
    await expect(
      page.getByRole('combobox', { name: 'SQL database connection' }),
    ).toBeDisabled();
    await expect(
      page.getByRole('button', { name: 'Create', exact: true }),
    ).toBeDisabled();
  } finally {
    const purged = await purgeTenant(request, tenant);
    if (!purged)
      console.warn(
        `[autocount-db-company] tenant ${tenant.slug} was not purged`,
      );
  }
});
