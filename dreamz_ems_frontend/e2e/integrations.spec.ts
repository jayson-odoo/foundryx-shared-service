import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Integrations on the Resource shell (plan sprint-2/06 D6) — Phase C E2E
 * against the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Real user
 * clicks. The card grid + wizard are gone — list + full-page form like every
 * entity.
 *
 * Storage probes are kept OFFLINE-deterministic: the S3 card's advanced
 * Endpoint URL points at localhost:9 (closed port), so the probe fails with
 * the honest transport error and never needs internet or real creds.
 *
 * Spec isolation: each test provisions a DEDICATED tenant via the operator
 * API (connections are unique per (tenant, type) since D7 — sharing the
 * default tenant would collide across parallel specs).
 */

const API = 'http://localhost:8001';

async function provisionTenant(request: APIRequestContext, tag: string) {
  const slug = `e2e-int-${tag}-${Date.now()}`;
  const login = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  const token = (await login.json()).access_token as string;
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E Integrations ${tag} ${Date.now()}`,
      slug,
      adminName: 'Integration Admin',
      adminEmail: `admin-${slug}@example.com`,
      adminPassword: 'ChangeMe1!',
    },
  });
  if (!res.ok()) throw new Error(`tenant provisioning failed: ${await res.text()}`);
  return { slug, email: `admin-${slug}@example.com`, password: 'ChangeMe1!' };
}

async function loginTenantAdmin(page: Page, t: { slug: string; email: string; password: string }) {
  await page.goto(`http://${t.slug}.localhost:3001/signin`);
  await page.getByPlaceholder('Your email').fill(t.email);
  await page.getByPlaceholder('Your password').fill(t.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Sidebar: Settings (renamed from "Workspace Settings", D9) → Integrations. */
async function openIntegrations(page: Page) {
  const link = page.getByRole('link', { name: 'Integrations', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Settings', { exact: true }).first().click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/settings\/integrations$/);
}

/** Create an S3 connection through the form. Returns after save lands on the record page. */
async function createS3Connection(
  page: Page,
  opts: { name?: string; endpoint?: string } = {},
) {
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);

  await page.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'Amazon S3' }).click();

  if (opts.name) {
    await page.getByPlaceholder('e.g. Company mail server').fill(opts.name);
  }
  await page.getByPlaceholder('my-company-assets').fill('e2e-bucket');
  await page.getByPlaceholder('ap-southeast-1').fill('us-east-1');
  // FormRow labels aren't wired to inputs (no htmlFor) — target the secret
  // inputs by type; field order follows the provider schema.
  const secrets = page.locator('input[type="password"]');
  await secrets.nth(0).fill('AKIAFAKEFAKEFAKEFAKE');
  await secrets.nth(1).fill('fake-secret-fake-secret-fake-secret');

  // Advanced → offline-deterministic endpoint (closed port).
  await page.getByRole('button', { name: 'Advanced' }).click();
  await page
    .getByPlaceholder('https://s3.amazonaws.com (leave blank for AWS)')
    .fill(opts.endpoint ?? 'http://localhost:9');

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/);
}

test.describe('Integrations — Resource shell (live backend)', () => {
  test('list page loads on the shell with the create button', async ({ page, request }) => {
    const tenant = await provisionTenant(request, 'load');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    await expect(page.getByRole('button', { name: 'Connect integration' })).toBeVisible();
    await expect(page.getByPlaceholder('Search integrations…')).toBeVisible();
  });

  test('create S3 → UNVERIFIED, Test surfaces the honest probe error → Error', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'probe');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    await createS3Connection(page);

    // Saved but never tested — UNVERIFIED shouts until the first pass (D6).
    await expect(page.getByText('Unverified')).toBeVisible();

    // Form "…" actions → Test connection → honest transport error, no
    // sugar-coating: head_bucket against localhost:9 cannot connect.
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Test connection' }).click();
    // Message lands in BOTH the toast and the Health card — assert the first.
    await expect(page.getByText(/Could not access bucket/).first()).toBeVisible({ timeout: 15_000 });

    // Status flips to Error and the message lands in the Health card.
    await expect(page.getByText('Error', { exact: true }).first()).toBeVisible();
  });

  test('edit keeps stored secrets when left blank (write-only contract)', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'keep');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    await createS3Connection(page, { name: 'Keep Test' });

    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    // Secrets render as blank-to-keep placeholders — leave them untouched.
    await expect(
      page.getByPlaceholder('•••••••• (leave blank to keep)').first(),
    ).toBeVisible();
    const name = page.getByPlaceholder('e.g. Company mail server');
    await name.fill('Keep Test Renamed');
    await page.getByRole('button', { name: 'Save', exact: true }).click();

    // Saves clean — NO "Required" on the untouched secret fields.
    await expect(page.getByText('Connection saved.')).toBeVisible();
    await expect(page.getByText('Required', { exact: true })).toHaveCount(0);
    await expect(
      page.getByRole('heading', { name: 'Keep Test Renamed' }),
    ).toBeVisible();
  });

  test('second storage connection is refused — one per type (D7, 409)', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'dupe');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    await createS3Connection(page, { name: 'First Storage' });
    await page.getByRole('link', { name: 'Back to integrations' }).click();
    await page.waitForURL(/\/settings\/integrations$/);

    // Attempt a SECOND storage connection (R2 this time) → server 409.
    await page.getByRole('button', { name: 'Connect integration' }).click();
    await page.getByRole('combobox', { name: 'Provider' }).click();
    await page.getByRole('option', { name: 'Cloudflare R2' }).click();
    await page.getByPlaceholder('23f8c4ed…').fill('0123456789abcdef0123456789abcdef');
    await page.getByPlaceholder('my-company-assets').fill('e2e-bucket-2');
    const secrets = page.locator('input[type="password"]');
    await secrets.nth(0).fill('fake');
    await secrets.nth(1).fill('fake');
    await page.getByRole('button', { name: 'Create', exact: true }).click();

    await expect(page.getByText(/already exists/)).toBeVisible();
  });

  test('disconnect routes through the confirm and removes the row', async ({ page, request }) => {
    const tenant = await provisionTenant(request, 'del');
    await loginTenantAdmin(page, tenant);
    await openIntegrations(page);

    await createS3Connection(page, { name: 'Doomed Connection' });
    await page.getByRole('link', { name: 'Back to integrations' }).click();
    await page.waitForURL(/\/settings\/integrations$/);
    await expect(page.getByText('Doomed Connection')).toBeVisible();

    await page.getByRole('button', { name: 'Actions' }).first().click();
    await page.getByRole('menuitem', { name: 'Disconnect' }).click();
    await expect(page.getByText('Disconnect this integration?')).toBeVisible();
    await page.getByRole('button', { name: 'Disconnect', exact: true }).click();

    await expect(page.getByText('Doomed Connection')).toHaveCount(0);
  });
});
