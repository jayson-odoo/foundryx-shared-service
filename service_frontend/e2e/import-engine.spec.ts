import { expect, test, type Page } from '@playwright/test';

/**
 * Import engine E2E (plan sprint-3/09, F8 Phase C) — real user clicks against
 * the LIVE stack (Next :3001 → FastAPI :8001 → Postgres).
 *
 * Dedicated provisioned tenant (mutates the Users list). Journey: Users →
 * Import → upload a file with one bad row → map → validate → results show the
 * bad row → commit the valid set → the user appears in /users. Both viewports.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const STAMP = Date.now();
const SLUG = `e2e-import-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const GOOD_EMAIL = `imported-${STAMP}@e2e.com`;

const tenantUrl = (p: string) => `http://${SLUG}.localhost:3001${p}`;

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/signin'));
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Import engine — live stack (plan sprint-3/09 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const pl = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    const token = (await pl.json()).access_token;
    const res = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${token}` },
      data: {
        name: `E2E Import ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Import Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(res.status()).toBe(201);
  });

  test('① import users via the wizard (bad row reported, valid row lands)', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/user-management/users'));

    // Open the wizard.
    await page.getByRole('button', { name: /^import$/i }).click();
    await expect(page.getByRole('dialog')).toBeVisible();

    // Upload a CSV: one good row + one bad-email row.
    const csv = `Email,Name\n${GOOD_EMAIL},Imported One\nnotanemail,Bad Row\n`;
    await page.setInputFiles('input[type="file"]', {
      name: 'users.csv',
      mimeType: 'text/csv',
      buffer: Buffer.from(csv),
    });
    await page.getByRole('button', { name: /upload & map/i }).click();

    // Mapping page — auto-mapped; just validate.
    await page.waitForURL(/\/imports\/.+\/mapping/);
    await page.getByRole('button', { name: /^validate$/i }).click();

    // Results page — 1 valid, 1 invalid, the bad row shown.
    await page.waitForURL(/\/imports\/[^/]+$/);
    await expect(page.getByText('1 valid', { exact: true })).toBeVisible();
    await expect(page.getByText('1 invalid', { exact: true })).toBeVisible();
    // The offending cell is reported (row 3, column email, the problem).
    await expect(page.getByText(/not a valid email/i)).toBeVisible();

    // Mobile viewport stays coherent.
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(page.getByRole('button', { name: /import 1 valid/i })).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 800 });

    // Commit the valid set (1 skipped).
    await page.getByRole('button', { name: /import 1 valid/i }).click();
    await expect(page.getByText(/imported 1 created/i)).toBeVisible({ timeout: 15_000 });

    // The good user now appears in /users.
    await page.goto(tenantUrl('/user-management/users'));
    await page.getByPlaceholder(/search/i).first().fill(GOOD_EMAIL);
    await expect(page.getByText(GOOD_EMAIL)).toBeVisible({ timeout: 10_000 });
  });
});
