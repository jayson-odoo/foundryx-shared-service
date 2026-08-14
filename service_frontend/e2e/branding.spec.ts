import fs from 'node:fs';
import {
  expect,
  test,
  type APIRequestContext,
  type Page,
} from '@playwright/test';

/**
 * Tenant Branding E2E (plan sprint-2/03 Phase C) - real user clicks against
 * the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Backend must be up +
 * bootstrapped (`python -m scripts.bootstrap_db`).
 *
 * Each test provisions a DEDICATED timestamped tenant via the operator API
 * (suite runs fullyParallel - branding the default tenant would restyle every
 * concurrent spec's UI mid-run). The flows themselves are all real clicks.
 */

const API = 'http://localhost:8001';

// 1×1 transparent PNG - real magic bytes (the backend sniffs content).
const PNG = Buffer.from(
  '89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489' +
    '0000000d49444154789c6260000000060001a2c1a1bd0000000049454e44ae426082',
  'hex',
);

const PURPLE = '#7c3aed';
const PURPLE_RGB = 'rgb(124, 58, 237)';

interface E2ETenant {
  slug: string;
  name: string;
  email: string;
  password: string;
}

async function provisionTenant(
  request: APIRequestContext,
  kind: string,
): Promise<E2ETenant> {
  const ts = Date.now();
  const slug = `e2e-brand-${kind}-${ts}`;
  const name = `E2E Brandco ${kind} ${ts}`;
  const login = await request.post(`${API}/auth/login`, {
    data: {
      email: 'platform@example.com',
      password: 'platform1234',
      tenantSlug: 'platform',
    },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;

  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name,
      slug,
      adminName: 'Brand Admin',
      adminEmail: `admin-${slug}@example.com`,
      adminPassword: 'ChangeMe1!',
    },
  });
  expect(res.status(), await res.text()).toBe(201);
  return {
    slug,
    name,
    email: `admin-${slug}@example.com`,
    password: 'ChangeMe1!',
  };
}

async function login(
  page: Page,
  base: string,
  email: string,
  password: string,
) {
  await page.goto(`${base}/signin`);
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

const tenantHost = (slug: string) => `http://${slug}.localhost:3001`;

async function gotoBranding(page: Page) {
  const link = page.getByRole('link', { name: 'Branding', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Settings', { exact: true }).click();
  }
  await link.click();
  await expect(page).toHaveURL(/\/settings\/branding$/);
  await expect(
    page.getByText(
      'Your logo, slogan and colors across the sign-in page, browser tab and app',
    ),
  ).toBeVisible();
}

/** The asset card for a given title (Logo / Browser-tab icon / Sign-in illustration). */
const assetCard = (page: Page, title: string) =>
  page.locator('[data-slot="card"]', {
    has: page.getByText(title, { exact: true }),
  });

test.describe('Tenant Branding (live stack)', () => {
  test('tenant brands the workspace: logo + slogan + theme, applied live and on the sign-in page', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'self');
    await login(page, tenantHost(tenant.slug), tenant.email, tenant.password);
    await gotoBranding(page);

    // Upload a logo through the card's real file chooser.
    const chooserPromise = page.waitForEvent('filechooser');
    await assetCard(page, 'Logo')
      .getByRole('button', { name: 'Upload' })
      .click();
    const chooser = await chooserPromise;
    await chooser.setFiles({
      name: 'logo.png',
      mimeType: 'image/png',
      buffer: PNG,
    });
    await expect(page.getByText('Logo updated.')).toBeVisible();
    await expect(
      assetCard(page, 'Logo').getByRole('button', { name: 'Replace' }),
    ).toBeVisible();

    // Slogan + a primary-color override via the hex input.
    await page.getByLabel('Slogan').fill('Events, perfected.');
    await page.getByLabel('Primary hex value (light)').fill(PURPLE);

    // Draft preview reflects the pick before saving (scoped vars, app untouched).
    await expect(
      page.getByText(
        'Soft primary surface - banners, selected rows, highlights.',
      ),
    ).toBeVisible();

    await page.getByRole('button', { name: 'Save branding' }).click();
    await expect(page.getByText('Branding saved.')).toBeVisible();

    // The WHOLE app re-themes live (BrandingProvider applies the override on <html>)…
    await expect
      .poll(() =>
        page.evaluate(() =>
          document.documentElement.style.getPropertyValue('--foundryx-primary'),
        ),
      )
      .toBe(PURPLE);
    // …and the tab title flips to the tenant's name.
    await expect(page).toHaveTitle(tenant.name);

    // Template download reflects the saved override (download/upload roundtrip
    // beyond this is covered by unit tests on both layers).
    const downloadPromise = page.waitForEvent('download');
    await page.getByRole('button', { name: 'Download template' }).click();
    const download = await downloadPromise;
    const path = await download.path();
    const template = JSON.parse(fs.readFileSync(path!, 'utf8'));
    expect(template.light.primary).toBe(PURPLE);

    // Pre-auth sign-in page: tenant logo + slogan + themed button, no Foundryx leak.
    await page.goto(`${tenantHost(tenant.slug)}/signin`);
    await expect(page).toHaveTitle(tenant.name);
    const panelLogo = page.getByRole('img', { name: 'Logo' }).first();
    await expect(panelLogo).toBeVisible();
    expect(await panelLogo.getAttribute('src')).toContain(
      `/public/branding/${tenant.slug}/asset/logo`,
    );
    await expect(page.getByText('Events, perfected.')).toBeVisible();
    await expect(page.getByText('One platform, every conversation.')).toHaveCount(0);
    const signInButton = page.getByRole('button', { name: /sign in/i });
    await expect
      .poll(() =>
        signInButton.evaluate((el) => getComputedStyle(el).backgroundColor),
      )
      .toBe(PURPLE_RGB);
  });

  test('unbranded tenant gets stock Foundryx branding on its sign-in page', async ({
    page,
    request,
  }) => {
    // A fresh tenant with NO branding row - the default-fallback contract.
    // (Deliberately not the `default` tenant: local manual testing may have
    // branded it, and this suite must stay residue-proof.)
    const tenant = await provisionTenant(request, 'stock');
    await page.goto(`${tenantHost(tenant.slug)}/signin`);
    await expect(page.getByText('One platform, every conversation.')).toBeVisible();
    await expect(page).toHaveTitle(/Foundryx EMS/);
  });

  test('operator edits a tenant’s branding from the console Branding tab', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request, 'op');
    await login(
      page,
      'http://platform.localhost:3001',
      'platform@example.com',
      'platform1234',
    );

    // Click-nav: Platform → Tenants → the provisioned row → Branding tab.
    const tenantsLink = page
      .getByLabel('Tenant Management')
      .getByRole('link', { name: 'Tenants', exact: true });
    if (!(await tenantsLink.isVisible().catch(() => false))) {
      await page.getByText('Tenant Management', { exact: true }).click();
    }
    await tenantsLink.click();
    await expect(page).toHaveURL(/\/platform\/tenants$/);
    await page.getByPlaceholder('Search tenants…').fill(tenant.slug);
    const row = page.getByRole('row', { name: new RegExp(tenant.slug) });
    await expect(row).toBeVisible();
    // Outlast the trailing debounced refetch (row detaches mid-click otherwise).
    await page.waitForTimeout(800);
    // Rows navigate via router.push on click (no anchor) - click the name cell.
    await row.getByText(tenant.name).click();
    await expect(page).toHaveURL(/\/platform\/tenants\/.+/);

    await page.getByRole('tab', { name: 'Branding' }).click();
    await page.getByLabel('Slogan').fill('Operator set this.');
    await page.getByRole('button', { name: 'Save branding' }).click();
    await expect(page.getByText('Branding saved.')).toBeVisible();

    // The edit is live on the tenant's own pre-auth sign-in page; the
    // operator's console keeps stock Foundryx theming (edit targeted the OTHER
    // tenant - no cross-restyle).
    expect(
      await page.evaluate(() =>
        document.documentElement.style.getPropertyValue('--foundryx-primary'),
      ),
    ).toBe('');
    await page.goto(`${tenantHost(tenant.slug)}/signin`);
    await expect(page.getByText('Operator set this.')).toBeVisible();
    await expect(page).toHaveTitle(tenant.name);
  });
});
