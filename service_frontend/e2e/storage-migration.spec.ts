import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/**
 * Storage provider migration + centralized Jobs (sprint-4/10, AC-10-18/19/21/22)
 * - E2E against the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Real
 * user clicks only (no URL shortcuts).
 *
 * Spec-isolation (MANDATORY): a migration mutates shared storage state, so every
 * test provisions a DEDICATED, timestamped tenant via the operator API (setup
 * only - the flow under test stays real clicks). No fixed literal names.
 *
 * Offline-deterministic storage:
 *  - AC-10-18 (test-gated Start): the candidate bucket's Endpoint URL points at a
 *    CLOSED port (localhost:9), so the wizard's Test fails with an honest
 *    transport error and Start never enables - no cloud/creds needed.
 *  - AC-10-21/22 (full green migration): a local **moto** S3 server (started by
 *    the tester harness at MOTO_ENDPOINT with buckets `mig-source`/`mig-target`)
 *    stands in for a real bucket, so a genuine A→B copy+cutover runs and assets
 *    resolve. If moto is not reachable the happy-path test SKIPS (documented) -
 *    it is never a false PASS.
 */

const API = 'http://localhost:8001';
const MOTO = process.env.MOTO_ENDPOINT ?? 'http://localhost:5050';
const SRC_BUCKET = 'mig-source';
const DST_BUCKET = 'mig-target';
const FIXTURE = 'e2e/fixtures/avatar.png';

interface TenantAdmin {
  slug: string;
  email: string;
  password: string;
  name: string;
}

async function provisionTenant(request: APIRequestContext, tag: string): Promise<TenantAdmin> {
  const stamp = Date.now();
  const slug = `e2e-mig-${tag}-${stamp}`;
  const login = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  const token = (await login.json()).access_token as string;
  const name = 'Migr Ester';
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E Migration ${tag} ${stamp}`,
      slug,
      adminName: name,
      adminEmail: `admin-${slug}@example.com`,
      adminPassword: 'ChangeMe1!',
    },
  });
  if (!res.ok()) throw new Error(`tenant provisioning failed: ${await res.text()}`);
  return { slug, email: `admin-${slug}@example.com`, password: 'ChangeMe1!', name };
}

async function loginTenantAdmin(page: Page, t: TenantAdmin) {
  await page.goto(`http://${t.slug}.localhost:3001/signin`);
  await page.getByPlaceholder('Your email').fill(t.email);
  await page.getByPlaceholder('Your password').fill(t.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openIntegrations(page: Page) {
  const link = page.getByRole('link', { name: 'Integrations', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Settings', { exact: true }).first().click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/settings\/integrations$/);
}

/**
 * Fill the S3 config into a connection form (the connect page OR the migration-
 * wizard dialog - same `fields()`-driven ConfigurationTab). `scope` bounds the
 * inputs so the wizard dialog never collides with the connection detail form
 * underneath it; the provider option list is a portal, resolved on `page`.
 */
async function fillS3Config(
  page: Page,
  scope: Page | Locator,
  opts: { name: string; bucket: string; endpoint: string },
) {
  await scope.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'Amazon S3' }).click();

  await scope.getByPlaceholder('e.g. Company mail server').fill(opts.name);
  await scope.getByPlaceholder('my-company-assets').fill(opts.bucket);
  await scope.getByPlaceholder('ap-southeast-1').fill('us-east-1');
  const secrets = scope.locator('input[type="password"]');
  await secrets.nth(0).fill('test');
  await secrets.nth(1).fill('test');
  await scope.getByRole('button', { name: 'Advanced' }).click();
  await scope
    .getByPlaceholder('https://s3.amazonaws.com (leave blank for AWS)')
    .fill(opts.endpoint);
}

/** Connect a storage connection A through the connect form. Lands on its record page. */
async function connectStorageA(
  page: Page,
  opts: { name: string; bucket: string; endpoint: string },
) {
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);
  await fillS3Config(page, page, opts);
  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/);
}

/** Upload the fixture as the current user's avatar via /account (real clicks). */
async function uploadAvatar(page: Page, name: string): Promise<string> {
  await page.getByRole('button', { name: 'User menu' }).click();
  await page.getByRole('menuitem', { name: 'My Account' }).click();
  await page.waitForURL(/\/account$/);
  await page.locator('input[type="file"]').setInputFiles(FIXTURE);
  const dialog = page.getByRole('dialog');
  await expect(dialog.getByText('Crop avatar')).toBeVisible();
  await dialog.getByRole('button', { name: 'Save', exact: true }).click();
  await expect(dialog).toBeHidden({ timeout: 15_000 });
  const img = page.locator(`img[alt="${name}"]`).first();
  await expect(img).toBeVisible();
  const src = await img.getAttribute('src');
  if (!src) throw new Error('avatar img has no src');
  return src;
}

test.describe('Storage migration - wizard + Jobs + assets (live backend)', () => {
  test('AC-10-18 · test-gated Start: a failing bucket test never enables Start', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'gate');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    // A storage connection must exist for "Migrate storage" to appear.
    await connectStorageA(page, {
      name: `Source ${Date.now()}`,
      bucket: 'e2e-source',
      endpoint: 'http://localhost:9',
    });

    // The connection detail form "…" Actions menu → Migrate storage (visible
    // only with integrations.migrate_storage, which the tenant Admin holds).
    await page.getByRole('button', { name: 'Actions' }).click();
    const migrate = page.getByRole('menuitem', { name: 'Migrate storage' });
    await expect(migrate).toBeVisible();
    await migrate.click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Migrate storage')).toBeVisible();

    // Responsive: the wizard is usable + the step strip renders at 375px.
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(dialog.getByText('New bucket', { exact: true })).toBeVisible();
    await expect(dialog.getByText('Confirm', { exact: true })).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });

    // Step 1 - configure candidate bucket B pointed at a CLOSED port.
    await fillS3Config(page, dialog, {
      name: `Target ${Date.now()}`,
      bucket: 'e2e-target',
      endpoint: 'http://localhost:9',
    });
    await dialog.getByRole('button', { name: 'Next' }).click();

    // Step 2 - Test. Before it runs, Next is disabled; the probe fails with the
    // honest transport error and Next STAYS disabled (foolproof-UI, AC-10-18).
    const next = dialog.getByRole('button', { name: 'Next' });
    await expect(next).toBeDisabled();
    await dialog.getByRole('button', { name: 'Test bucket' }).click();
    await expect(dialog.getByText(/Could not access bucket|could not be verified|failed/i)).toBeVisible(
      { timeout: 15_000 },
    );
    await expect(next).toBeDisabled();
  });

  test('AC-10-19 · Jobs surfaces reachable by real navigation (drawer + /jobs list)', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'jobs');
    await loginTenantAdmin(page, tenant);

    // Header "Jobs" activity trigger (aria-label icon button) opens the drawer.
    await page.locator('button[aria-label="Jobs"]').click();
    const drawer = page.getByRole('dialog');
    await expect(drawer.getByText('Jobs', { exact: true })).toBeVisible();
    await page.keyboard.press('Escape');

    // Sidebar → /jobs history list on the Resource shell: Type column + status
    // segments render (empty state is fine - this asserts the surface exists).
    await page.locator('a[href="/jobs"]').first().click();
    await page.waitForURL(/\/jobs$/);
    await expect(page.getByRole('columnheader', { name: 'Type' })).toBeVisible();
    await expect(page.getByRole('columnheader', { name: 'Status' })).toBeVisible();
    // Status segments render as the "View segment" SearchSelect (N-way).
    await page.getByRole('combobox', { name: 'View segment' }).click();
    await expect(page.getByRole('option', { name: 'Needs review' })).toBeVisible();
    await page.keyboard.press('Escape');

    // Responsive: list usable at 375px and 1280px (no clipped controls).
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(page.getByRole('columnheader', { name: 'Type' })).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 900 });
    await expect(page.getByRole('columnheader', { name: 'Type' })).toBeVisible();
  });

  test('AC-10-21/22 · full migration A→B → job done → assets resolve', async ({
    page,
    request,
  }) => {
    const motoUp = await request
      .get(MOTO)
      .then((r) => r.status() < 500)
      .catch(() => false);
    test.skip(
      !motoUp,
      `moto S3 not reachable at ${MOTO} - happy-path migration deferred (offline).`,
    );

    const tenant = await provisionTenant(request, 'go');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    // Connect storage A (moto mig-source) - new uploads now land on A.
    await connectStorageA(page, {
      name: `Source ${Date.now()}`,
      bucket: SRC_BUCKET,
      endpoint: MOTO,
    });

    // Upload an avatar → lands on A. Assert it RESOLVES (200) before migrating.
    const avatarSrc = await uploadAvatar(page, tenant.name);
    await expect((await request.get(avatarSrc)).status()).toBe(200);

    // Open the migration wizard from the storage connection's "…" menu.
    await openIntegrations(page);
    await page.getByText(/^Source /).first().click();
    // Row-click carries a ?ctx=…&i= record-nav query, so don't anchor on $.
    await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+/);
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Migrate storage' }).click();

    const dialog = page.getByRole('dialog');
    const targetName = `Target ${Date.now()}`;

    // Step 1 - configure B (moto mig-target).
    await fillS3Config(page, dialog, {
      name: targetName,
      bucket: DST_BUCKET,
      endpoint: MOTO,
    });
    await dialog.getByRole('button', { name: 'Next' }).click();

    // Step 2 - Test passes → Next enables.
    await dialog.getByRole('button', { name: 'Test bucket' }).click();
    await expect(dialog.getByText(/Bucket verified/i)).toBeVisible({ timeout: 15_000 });
    await dialog.getByRole('button', { name: 'Next' }).click();

    // Step 3 - typed-confirm gates Start.
    const start = dialog.getByRole('button', { name: 'Start migration' });
    await expect(start).toBeDisabled();
    await dialog.getByPlaceholder(targetName).fill(targetName);
    await expect(start).toBeEnabled();
    await start.click();

    // The Jobs drawer opens with the migration job; eager execution means it is
    // already terminal. Open its detail page.
    const jobsDrawer = page.getByRole('dialog');
    await expect(jobsDrawer.getByText('Storage migration')).toBeVisible({ timeout: 15_000 });
    await jobsDrawer.getByText('Storage migration').first().click();
    await page.waitForURL(/\/jobs\/[\w-]+$/);

    // Poll the detail until Done (POLL_MS handles a real async worker too).
    await expect(page.getByText('Done', { exact: true }).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/Failed assets/)).toHaveCount(0);

    // AC-10-21: the PRE-EXISTING avatar still resolves (now from B) - zero 404.
    await expect((await request.get(avatarSrc)).status()).toBe(200);

    // AC-10-22: a NEW upload made after the migration also resolves (lands on B).
    const newSrc = await uploadAvatar(page, tenant.name);
    await expect((await request.get(newSrc)).status()).toBe(200);
  });
});
