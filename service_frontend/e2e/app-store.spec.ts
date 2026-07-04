import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * App Store E2E (plan 08 Phase C) — real user clicks against the LIVE stack
 * (Next :3001 → FastAPI :8001 → Postgres). Backend must be up + bootstrapped
 * (`python -m scripts.bootstrap_db`).
 *
 * Setup provisions a DEDICATED tenant via the operator API, so the lifecycle
 * (install → deactivate → reactivate → uninstall) never disturbs the default
 * tenant other suites run against, and the suite is re-runnable. The flow
 * itself is all real clicks, per governance.
 */

const API = 'http://localhost:8001';

async function provisionTenant(request: APIRequestContext) {
  const slug = `e2e-store-${Date.now()}`;
  const login = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  expect(login.ok()).toBeTruthy();
  const token = (await login.json()).access_token as string;

  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: 'E2E App Store',
      slug,
      adminName: 'Store Admin',
      adminEmail: `admin-${slug}@example.com`,
      adminPassword: 'ChangeMe1!',
    },
  });
  expect(res.status(), await res.text()).toBe(201);
  return { slug, email: `admin-${slug}@example.com`, password: 'ChangeMe1!' };
}

async function loginTenantAdmin(page: Page, t: { slug: string; email: string; password: string }) {
  await page.goto(`http://${t.slug}.localhost:3001/signin`);
  await page.getByPlaceholder('Your email').fill(t.email);
  await page.getByPlaceholder('Your password').fill(t.password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function gotoAppStore(page: Page) {
  // "App Store" is a grouping parent — the navigable entry is its child.
  const link = page.getByRole('link', { name: 'Browse Modules', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('App Store', { exact: true }).click();
  }
  await link.click();
  await expect(page).toHaveURL(/\/app-store$/);
  await expect(page.getByText('Install and manage modules for this workspace.')).toBeVisible();
}

const card = (page: Page, name: string) => page.getByTestId(`module-card-${name}`);
/** The sidebar's Omnichannel section trigger (module-gated menu block). */
const omniMenu = (page: Page) =>
  page.locator('[data-slot="accordion-menu-title"]', { hasText: 'Omnichannel' });

test('full lifecycle on a fresh tenant: install → menu appears → deactivate → reactivate → uninstall', async ({
  page,
  request,
}) => {
  const tenant = await provisionTenant(request);
  await loginTenantAdmin(page, tenant);

  // Fresh tenant: module NOT installed → no Omnichannel menu block.
  await expect(omniMenu(page)).toHaveCount(0);
  await gotoAppStore(page);

  const omni = card(page, 'omnichannel');
  await expect(omni.getByRole('heading', { name: 'Omnichannel' })).toBeVisible();
  await expect(omni.getByText('Not installed')).toBeVisible();
  await expect(omni.getByText(/^v0\.1\.0/)).toBeVisible(); // manifest version

  // ---- install: ACTIVE, menu appears, module pages reachable ----
  await omni.getByRole('button', { name: 'Install' }).click();
  await expect(omni.getByText('Active')).toBeVisible();
  await expect(omniMenu(page).first()).toBeVisible(); // session perms + menu refresh (D7)

  // Click through to Workspaces — install_tenant seeded the default 'General'.
  await omniMenu(page).first().click();
  await page.getByRole('link', { name: 'Workspaces' }).click();
  await expect(page).toHaveURL(/\/omnichannel\/settings\/workspaces/);
  await expect(page.getByText('General').first()).toBeVisible();

  // ---- deactivate: menu gone, data kept (backend 403 pinned by pytest) ----
  await gotoAppStore(page);
  await card(page, 'omnichannel').getByRole('button', { name: 'Deactivate' }).click();
  await expect(page.getByText('Deactivate Omnichannel?')).toBeVisible();
  await page.getByRole('button', { name: 'Deactivate', exact: true }).last().click();

  await expect(card(page, 'omnichannel').getByText('Inactive')).toBeVisible();
  await expect(omniMenu(page)).toHaveCount(0);

  // ---- reactivate: instant restore ----
  await card(page, 'omnichannel').getByRole('button', { name: 'Reactivate' }).click();
  await expect(card(page, 'omnichannel').getByText('Active')).toBeVisible();
  await expect(omniMenu(page).first()).toBeVisible();

  // ---- uninstall: typed confirmation, tenant data wiped, menu gone ----
  await card(page, 'omnichannel').getByRole('button', { name: 'Uninstall' }).click();
  await expect(page.getByText('Uninstall Omnichannel?')).toBeVisible();
  await expect(page.getByText(/permanently wipes all Omnichannel data/)).toBeVisible();

  const confirm = page.getByRole('dialog').getByRole('button', { name: 'Uninstall' });
  await expect(confirm).toBeDisabled();
  await page.getByLabel('Confirm module name').fill('omni');
  await expect(confirm).toBeDisabled(); // wrong name keeps it locked
  await page.getByLabel('Confirm module name').fill('omnichannel');
  await confirm.click();

  await expect(card(page, 'omnichannel').getByText('Not installed')).toBeVisible();
  await expect(omniMenu(page)).toHaveCount(0);
  // (Per-tenant wipe isolation — other tenants' data untouched — is pinned by
  // pytest: tests/test_app_store.py::test_uninstall_wipes_only_that_tenant.)
});

test('default tenant storefront shows omnichannel ACTIVE (transitional backfill)', async ({
  page,
}) => {
  await page.goto('http://localhost:3001/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));

  await gotoAppStore(page);
  await expect(card(page, 'omnichannel').getByText('Active')).toBeVisible();
});
