import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Avatar self-service (plan sprint-2/06 D5) — Phase C E2E against the LIVE
 * stack. Upload → crop → save on /account, then verify the avatar renders in
 * the header AND the users list. No storage connection exists on the fresh
 * tenant, so this exercises the LOCAL fallback (StorageService local backend
 * → /public/avatars/{id} route).
 *
 * Spec isolation: dedicated tenant — mutating the demo admin's avatar would
 * bleed into every concurrent spec's header.
 */

const API = 'http://localhost:8001';
const FIXTURE = 'public/media/foundryx/foundryx-logo.png';

async function provisionTenant(request: APIRequestContext, tag: string) {
  const slug = `e2e-avatar-${tag}-${Date.now()}`;
  const login = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  const token = (await login.json()).access_token as string;
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E Avatar ${Date.now()}`,
      slug,
      adminName: 'Ava Tester',
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

test.describe('Avatar — upload → crop → renders everywhere (live backend)', () => {
  test('uploads via /account and shows in header + users list', async ({ page, request }) => {
    const tenant = await provisionTenant(request, 'up');
    await loginTenantAdmin(page, tenant);

    // Real-user route: header avatar → user menu → My Account.
    await page.getByRole('button', { name: 'User menu' }).click();
    await page.getByRole('menuitem', { name: 'My Account' }).click();
    await page.waitForURL(/\/account$/);

    // Pick a file straight into the hidden input (the pen badge opens the
    // same picker); the crop dialog sits between pick and upload.
    await page.locator('input[type="file"]').setInputFiles(FIXTURE);
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Crop avatar')).toBeVisible();
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dialog).toBeHidden({ timeout: 15_000 });

    // The avatar slot now renders an IMAGE (not initials) from the public
    // avatar route, version-busted.
    const accountAvatar = page.locator(`img[alt="Ava Tester"]`).first();
    await expect(accountAvatar).toBeVisible();
    await expect(accountAvatar).toHaveAttribute('src', /\/public\/avatars\/.+\?v=/);

    // Header (session catches up via update()) — image in the topbar.
    await expect(
      page.getByRole('button', { name: 'User menu' }).locator('img'),
    ).toBeVisible({ timeout: 15_000 });

    // Users list renders the same avatar in the row.
    await page.getByText('User Management', { exact: true }).click();
    await page.getByRole('link', { name: 'Users', exact: true }).click();
    await page.waitForURL(/\/user-management\/users$/);
    await expect(
      page.locator(`img[src*="/public/avatars/"]`).first(),
    ).toBeVisible();
  });

  test('remove returns the slot to initials', async ({ page, request }) => {
    const tenant = await provisionTenant(request, 'rm');
    await loginTenantAdmin(page, tenant);

    await page.getByRole('button', { name: 'User menu' }).click();
    await page.getByRole('menuitem', { name: 'My Account' }).click();
    await page.waitForURL(/\/account$/);

    await page.locator('input[type="file"]').setInputFiles(FIXTURE);
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(dialog).toBeHidden({ timeout: 15_000 });
    await expect(page.locator(`img[alt="Ava Tester"]`).first()).toBeVisible();

    // With an avatar set, the pen badge opens a menu: Change / Remove.
    await page.getByRole('button', { name: 'Edit avatar' }).click();
    await page.getByRole('menuitem', { name: 'Remove photo' }).click();

    await expect(page.locator(`img[alt="Ava Tester"]`)).toHaveCount(0, { timeout: 15_000 });
  });
});
