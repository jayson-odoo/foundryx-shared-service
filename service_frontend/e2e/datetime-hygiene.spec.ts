import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-2/05 Phase C — datetime hygiene + menu pruning, live stack.
 *
 * Journey 1: a user with a non-local timezone preference sees timestamps
 * shifted into that zone on a list (Users › Last Sign In), driven by the
 * Z-suffixed wire value formatted with Intl in the spec itself.
 *
 * Journey 2 (BL-014): menu items vanish for a role lacking the page's
 * `<resource>.read` — the dedicated tenant's Admin role is stripped down to
 * statuses.read + branding.read, then a fresh login renders the pruned menu.
 *
 * Spec isolation (methodology §7): journey 2 MUTATES the Admin role's grants,
 * so everything runs on a DEDICATED tenant provisioned via the operator API
 * (setup only — the flows under test stay real clicks). Timestamped names.
 * Serial: journey 2's stripped grants would break journey 1's Users page.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-dt-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

// UTC+14, no DST — the wall-clock time ALWAYS differs from any local zone.
const FAR_TZ = 'Pacific/Kiritimati';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function login(page: Page, email: string, password: string) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Real-user navigation: avatar (top-right) → "My Account". */
async function gotoMyAccount(page: Page) {
  await page.getByRole('button', { name: 'User menu' }).click();
  await page.getByRole('menuitem', { name: 'My Account' }).click();
  await expect(page).toHaveURL(/\/account$/);
}

async function adminToken(request: import('@playwright/test').APIRequestContext) {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).access_token as string;
}

/** "02 Jan 2026, 13:45" — mirrors lib/datetime.ts formatDateTime. */
function expectedDateTime(iso: string, timeZone: string): string {
  return new Intl.DateTimeFormat('en-GB', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    timeZone,
  }).format(new Date(iso));
}

test.describe.configure({ mode: 'serial', timeout: 120_000 });

test.describe('Datetime hygiene + menu pruning — live stack (plan sprint-2/05 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    // Operator provisions the dedicated tenant (plan 07 §7).
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: {
        email: 'platform@example.com',
        password: 'platform1234',
        tenantSlug: 'platform',
      },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Datetime ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Datetime Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);
  });

  test('timezone preference shifts list timestamps into the chosen zone', async ({
    page,
    request,
  }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    // ---- pick the far zone on My Account ----
    await gotoMyAccount(page);
    await page.getByRole('combobox', { name: 'Timezone' }).click();
    await page.getByPlaceholder('Search timezones…').fill('Kiritimati');
    await page.getByRole('option', { name: /Kiritimati/ }).click();
    await expect(page.getByText('Timezone saved.')).toBeVisible();

    // The wire value the cell must render — Z-suffixed (BL-012) and formatted
    // with Intl in FAR_TZ, exactly like lib/datetime.ts does.
    const token = await adminToken(request);
    const users = await request.get(`${API}/users`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(users.ok()).toBeTruthy();
    const admin = (await users.json()).data.find(
      (u: { email: string }) => u.email === ADMIN_EMAIL,
    );
    expect(admin.lastSignInAt.endsWith('Z')).toBeTruthy(); // UTC on the wire
    const expected = expectedDateTime(admin.lastSignInAt, FAR_TZ);

    // ---- real clicks: sidebar → User Management → Users ----
    await page.getByRole('button', { name: 'User Management' }).click();
    await page.getByRole('link', { name: 'Users', exact: true }).click();
    await expect(page).toHaveURL(/\/user-management\/users/);

    const adminRow = page.getByRole('row', { name: new RegExp(ADMIN_EMAIL) });
    await expect(adminRow).toContainText(expected);

    // The preference survives a reload (it lives on the user, not the tab).
    await gotoMyAccount(page);
    await page.reload();
    await expect(
      page.getByRole('combobox', { name: 'Timezone' }),
    ).toContainText('Kiritimati');
  });

  test('menu items vanish for a role lacking <resource>.read (BL-014)', async ({
    page,
    request,
  }) => {
    // ---- baseline: full Admin sees the gated entries ----
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);
    await expect(page.getByRole('button', { name: 'App Store' })).toBeVisible();
    await page.getByRole('button', { name: 'User Management' }).click();
    await expect(page.getByRole('link', { name: 'Users', exact: true })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Roles', exact: true })).toBeVisible();

    // ---- setup (API): strip the Admin role to statuses.read + branding.read ----
    const token = await adminToken(request);
    const roles = await request.get(`${API}/roles/options`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    expect(roles.ok()).toBeTruthy();
    const adminRole = (await roles.json()).find(
      (r: { name: string }) => r.name === 'Admin',
    );
    expect(adminRole).toBeTruthy();
    const strip = await request.patch(`${API}/roles/${adminRole.id}`, {
      headers: { Authorization: `Bearer ${token}` },
      data: { permissionKeys: ['statuses.read', 'branding.read'] },
    });
    expect(strip.ok()).toBeTruthy();

    // ---- fresh login → pruned menu (session perms are read at login) ----
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    // App Store's only child needs app_store.read → the parent disappears.
    await expect(page.getByRole('button', { name: 'App Store' })).toBeHidden();

    // User Management lost its dead demo children in sprint-2/06 — with
    // Users/Roles pruned it has ZERO visible children, so the PARENT
    // disappears too (filterMenu drops childless parents).
    await expect(
      page.getByRole('button', { name: 'User Management' }),
    ).toBeHidden();

    // Settings (renamed from "Workspace Settings" in sprint-2/06 D9):
    // granted reads stay, the rest vanish.
    await page.getByRole('button', { name: 'Settings', exact: true }).click();
    await expect(
      page.getByRole('link', { name: 'Statuses', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'Branding', exact: true }),
    ).toBeVisible();
    await expect(
      page.getByRole('link', { name: 'Integrations', exact: true }),
    ).toBeHidden();
    await expect(
      page.getByRole('link', { name: 'Rules', exact: true }),
    ).toBeHidden();

    // Backend stays the real boundary — the gated page 403s into the friendly
    // no-permission screen even on direct navigation.
    await page.goto(tenantUrl('/user-management/users'));
    await expect(page.getByText(/permission/i).first()).toBeVisible();
  });
});
