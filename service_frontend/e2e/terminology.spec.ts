import { expect, test, type Page } from '@playwright/test';

/**
 * Terminology E2E (plan sprint-3/08, F10 Phase C) - real user clicks against
 * the LIVE stack (Next :3001 → FastAPI :8001 → Postgres).
 *
 * Each spec provisions a DEDICATED timestamped tenant (suite runs
 * fullyParallel; renaming the default tenant's labels would change every
 * concurrent spec's UI). Verifies both desktop (1280) and mobile (375).
 *
 * ① rename Form → Survey → assert sidebar + /forms title + create button read
 *    "Survey(s)" with NO reload → Reset → reverts.
 * ② a second tenant is unaffected (isolation).
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const STAMP = Date.now();
const SLUG = `e2e-term-${STAMP}`;
const SLUG_B = `e2e-term-b-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_EMAIL_B = `admin-b-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

const tenantUrl = (slug: string, pathname: string) =>
  `http://${slug}.localhost:3001${pathname}`;

async function provision(request: any, slug: string, email: string, name: string) {
  const platformLogin = await request.post(`${API}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  expect(platformLogin.ok()).toBeTruthy();
  const token = (await platformLogin.json()).access_token;
  const res = await request.post(`${API}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: {
      name,
      slug,
      adminName: `${name} Admin`,
      adminEmail: email,
      adminPassword: ADMIN_PASSWORD,
    },
  });
  expect(res.status()).toBe(201);
}

async function login(page: Page, slug: string, email: string) {
  await page.goto(tenantUrl(slug, '/signin'));
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Terminology - live stack (plan sprint-3/08 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    await provision(request, SLUG, ADMIN_EMAIL, `E2E Term ${STAMP}`);
    await provision(request, SLUG_B, ADMIN_EMAIL_B, `E2E Term B ${STAMP}`);
  });

  test('① rename Form → Survey, surfaces follow, then Reset reverts', async ({
    page,
  }) => {
    await login(page, SLUG, ADMIN_EMAIL);

    // Rename via Settings → Terminology.
    await page.goto(tenantUrl(SLUG, '/settings/terminology'));
    await page
      .getByRole('row', { name: /form/i })
      .first()
      .getByRole('button', { name: /edit/i })
      .click();
    await page.getByLabel(/singular/i).fill('Survey');
    await page.getByLabel(/plural/i).fill('Surveys');
    await page.getByRole('button', { name: /^save$/i }).click();
    // Wait for the PUT + store refresh to settle (dialog closes on success) so
    // the navigation can't cancel the in-flight save.
    await expect(page.getByRole('dialog')).toBeHidden();

    // /forms list title + create button read "Survey(s)" - NO reload.
    await page.goto(tenantUrl(SLUG, '/forms'));
    await expect(
      page.getByRole('heading', { name: /surveys/i, level: 1 }),
    ).toBeVisible();
    await expect(
      page.getByRole('button', { name: /new survey/i }),
    ).toBeVisible();
    // Sidebar leaf (the active /forms route keeps its group expanded) follows.
    await expect(
      page.getByRole('link', { name: /surveys/i }).first(),
    ).toBeVisible();

    // Mobile viewport - still coherent.
    await page.setViewportSize({ width: 375, height: 800 });
    await expect(
      page.getByRole('button', { name: /new survey/i }),
    ).toBeVisible();
    await page.setViewportSize({ width: 1280, height: 800 });

    // Reset reverts.
    await page.goto(tenantUrl(SLUG, '/settings/terminology'));
    const surveyRow = page.getByRole('row', { name: /survey/i }).first();
    await surveyRow.getByRole('button', { name: /reset/i }).click();
    // The "Renamed" badge clears once the DELETE + refresh settle.
    await expect(page.getByText('Renamed')).toHaveCount(0);
    await page.goto(tenantUrl(SLUG, '/forms'));
    await expect(page.getByRole('heading', { name: /forms/i, level: 1 })).toBeVisible();
    await expect(
      page.getByRole('button', { name: /new form/i }),
    ).toBeVisible();
  });

  test('② a second tenant is unaffected (isolation)', async ({ page }) => {
    // Tenant A renamed Form→Survey in test ①, then reset. Rename again so the
    // override exists, then assert B still says Form.
    await login(page, SLUG, ADMIN_EMAIL);
    await page.goto(tenantUrl(SLUG, '/settings/terminology'));
    await page
      .getByRole('row', { name: /form/i })
      .first()
      .getByRole('button', { name: /edit/i })
      .click();
    await page.getByLabel(/singular/i).fill('Survey');
    await page.getByLabel(/plural/i).fill('Surveys');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByRole('dialog')).toBeHidden();

    // Tenant B (fresh context) still reads "Forms".
    await page.context().clearCookies();
    await login(page, SLUG_B, ADMIN_EMAIL_B);
    await page.goto(tenantUrl(SLUG_B, '/forms'));
    await expect(page.getByRole('heading', { name: /forms/i, level: 1 })).toBeVisible();
    await expect(
      page.getByRole('button', { name: /new form/i }),
    ).toBeVisible();
  });
});
