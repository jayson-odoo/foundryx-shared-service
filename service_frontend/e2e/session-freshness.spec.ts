import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Session freshness + menu hygiene (plan sprint-2/06 D8/D9) — Phase C E2E.
 *
 * D8: revoking a permission on the user's role must take effect on the next
 * page refresh WITHOUT a re-login — the protected layout's use-session-sync
 * probes /auth/me and update()s the NextAuth session on drift; the menu
 * filter (plan 05 BL-014) then prunes the gated entries.
 *
 * D9: "Workspace Settings" is renamed to "Settings"; the Metronic demo's
 * dead User-Management entries (Permissions/Account/Logs/Settings — routes
 * that never existed) are gone.
 *
 * Spec isolation: dedicated tenant — this MUTATES the Admin role's grants;
 * doing that to the default tenant would 403 every concurrent spec.
 */

const API = 'http://localhost:8001';

async function provisionTenant(request: APIRequestContext) {
  const slug = `e2e-fresh-${Date.now()}`;
  const login = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  const token = (await login.json()).access_token as string;
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name: `E2E Freshness ${Date.now()}`,
      slug,
      adminName: 'Fresh Admin',
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

/** Revoke every integrations.* grant from the tenant's Admin role via the API
 * (role editing itself is covered by roles-permissions.spec — the flow under
 * test here is the refresh-freshness, which stays real clicks). */
async function revokeIntegrations(
  request: APIRequestContext,
  t: { slug: string; email: string; password: string },
) {
  const login = await request.post(`${API}/auth/login`, {
    data: { email: t.email, password: t.password, tenantSlug: t.slug },
  });
  const token = (await login.json()).access_token as string;
  const headers = { Authorization: `Bearer ${token}` };

  // NB: /roles pagination is 0-based.
  const roles = await (await request.get(`${API}/roles?page=0&page_size=50`, { headers })).json();
  const admin = roles.data.find((r: { name: string }) => r.name === 'Admin');
  const detail = await (await request.get(`${API}/roles/${admin.id}`, { headers })).json();
  const kept = (detail.permissionKeys as string[]).filter(
    (k) => !k.startsWith('integrations.'),
  );
  const res = await request.patch(`${API}/roles/${admin.id}`, {
    headers,
    data: { permissionKeys: kept },
  });
  if (!res.ok()) throw new Error(`revoke failed: ${await res.text()}`);
}

test.describe('Session freshness + menu hygiene (live backend)', () => {
  test('revoked permission prunes the menu + page on refresh, no re-login (D8)', async ({
    page,
    request,
  }) => {
    const tenant = await provisionTenant(request);
    await loginTenantAdmin(page, tenant);

    // Baseline: the entry is there and the page opens.
    await page.getByText('Settings', { exact: true }).first().click();
    const link = page.getByRole('link', { name: 'Integrations', exact: true });
    await expect(link).toBeVisible();
    await link.click();
    await page.waitForURL(/\/settings\/integrations$/);
    await expect(page.getByRole('button', { name: 'Connect integration' })).toBeVisible();

    // Revoke behind the session's back, then refresh — use-session-sync
    // pulls fresh permissions; the menu filter prunes the entry.
    await revokeIntegrations(request, tenant);
    await page.reload();

    await expect(
      page.getByRole('link', { name: 'Integrations', exact: true }),
    ).toBeHidden({ timeout: 15_000 });

    // The page guard stays the boundary: direct navigation lands on the
    // friendly NoPermission page, never a raw 403.
    await page.goto(`http://${tenant.slug}.localhost:3001/settings/integrations`);
    await expect(page.getByText('You don’t have access to this page')).toBeVisible();
  });

  test('Settings rename + dead demo entries are gone (D9)', async ({ page, request }) => {
    const tenant = await provisionTenant(request);
    await loginTenantAdmin(page, tenant);

    // Renamed section exists…
    await expect(page.getByText('Settings', { exact: true }).first()).toBeVisible();
    // …the old name is gone.
    await expect(page.getByText('Workspace Settings', { exact: true })).toHaveCount(0);

    // User Management carries ONLY the real entries — the Metronic demo's
    // dead links (404 routes) were pruned.
    await page.getByText('User Management', { exact: true }).click();
    await expect(page.getByRole('link', { name: 'Users', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Roles', exact: true })).toBeVisible();
    for (const dead of ['Permissions', 'Account', 'Logs']) {
      await expect(
        page
          .locator('[data-slot="sidebar"], aside')
          .first()
          .getByRole('link', { name: dead, exact: true }),
      ).toHaveCount(0);
    }
  });
});
