import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Phase B-i slice 4 — Idea → Business Requirement (real clicks, AC-BI-30..36).
 *
 * Journey: sign in → ideas board → Suggest clusters → select ideas →
 * Promote to BR (bulk) → lands on the Grill tab → send a turn → Generate →
 * review the populated Details → Promote to ready.
 *
 * Determinism (AC-BI-12/36): a fresh tenant gets a DEV-cred LLM connection so
 * the offline stub answers — zero key, zero network. The stub fills every BR
 * field on Generate (partial-emit schema is all-strings), so promote's
 * completeness gate passes.
 *
 * Isolation (methodology §7): ideation mutates shared board/BR state → a
 * DEDICATED tenant via the operator API (setup only). Names timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-ideation-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const PRODUCT = `Sorento CRM ${STAMP}`;
const IDEA_A = `Checkout page loads slowly ${STAMP}`;
const IDEA_B = `Checkout page is slow to load ${STAMP}`;

const PORT = process.env.E2E_PORT ?? '3001';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:${PORT}${pathname}`;
}

async function adminToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).access_token;
}

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

function ideaRow(page: Page, text: string) {
  return page.getByRole('row', { name: new RegExp(text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')) });
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Ideation — Idea → BR (plan Phase B-i S4)', () => {
  test.beforeAll(async ({ request }) => {
    // Provision a dedicated tenant.
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Ideation ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Ideation Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status(), await provision.text()).toBe(201);

    const token = await adminToken(request);
    const auth = { Authorization: `Bearer ${token}` };

    // Install omnichannel (ideation's dependency).
    const installOmni = await request.post(`${API}/app-store/modules/omnichannel/install`, { headers: auth });
    expect(installOmni.ok(), await installOmni.text()).toBeTruthy();

    // A DEV-cred LLM connection FIRST → the tenant's OWN connection, so the grill
    // agent binds to it at install time and the offline stub answers
    // deterministically (not any real platform LLM).
    const conn = await request.post(`${API}/integrations/connections`, {
      headers: auth,
      data: {
        provider: 'gemini',
        name: 'Dev LLM',
        config: {},
        credentials: { apiKey: 'x', dev: 'true' },
      },
    });
    expect(conn.status(), await conn.text()).toBe(201);

    // Now install ideation — seed_grill_agent binds the "Ideation grill" agent to
    // the tenant's own dev connection (→ stub) + grants the module keys (incl.
    // .promote / clusters.manage) to this tenant's Admin.
    const installIdeation = await request.post(`${API}/app-store/modules/ideation/install`, { headers: auth });
    expect(installIdeation.ok(), await installIdeation.text()).toBeTruthy();

    // A product + two near-identical ideas (trigram-similar → a cluster).
    const product = await request.post(`${API}/products`, {
      headers: auth,
      data: { name: PRODUCT, kind: 'software' },
    });
    expect(product.status(), await product.text()).toBe(201);
    const productId = (await product.json()).id;

    for (const problem of [IDEA_A, IDEA_B]) {
      const idea = await request.post(`${API}/ideation/ideas`, {
        headers: auth,
        data: { productId, problem, rawText: problem },
      });
      expect(idea.status(), await idea.text()).toBe(201);
    }
  });

  test('① promote ideas → grill → generate → promote to ready', async ({ page }) => {
    await login(page);
    await page.goto(tenantUrl('/ideation/ideas'));

    // Cluster suggestions surface (AC-BI-30/31) — smoke: the on-demand panel
    // opens without blocking the board (degrades gracefully).
    await page.getByRole('button', { name: /suggest clusters/i }).click();
    await expect(page.getByText('Suggested clusters')).toBeVisible();

    // Select the two ideas → bulk Promote to BR (AC-BI-32).
    await expect(ideaRow(page, IDEA_A)).toBeVisible();
    await ideaRow(page, IDEA_A).getByRole('checkbox').check();
    await ideaRow(page, IDEA_B).getByRole('checkbox').check();
    await page.getByRole('button', { name: 'Bulk actions' }).click();
    await page.getByRole('menuitem', { name: 'Promote to BR' }).click();

    // Lands on the new BR's Grill tab (AC-BI-32).
    await page.waitForURL(/\/ideation\/business-requirements\/.*tab=grill/);
    await expect(page.getByPlaceholder('Message the grill')).toBeVisible();

    // Send one grill turn (AC-BI-22) — the stub replies.
    await page.getByPlaceholder('Message the grill').fill('Customers report the checkout is very slow.');
    await page.getByRole('button', { name: 'Send' }).click();
    await expect(page.getByText('Customers report the checkout is very slow.')).toBeVisible();

    // Generate — the human ends the grill; extraction fills the BR (AC-BI-24/26).
    await page.getByRole('button', { name: 'Generate' }).click();
    await expect(page.getByText('Requirement generated from the grill.')).toBeVisible({ timeout: 30_000 });

    // Review the populated Details (AC-BI-18/24).
    await page.getByRole('tab', { name: 'Details' }).click();
    await expect(page.getByText(/\[stub:/).first()).toBeVisible();

    // Promote to ready via the graph-driven form action (AC-BI-34). The label is
    // the bare target status "Ready"; the edge is .promote-gated server-side.
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Ready' }).click();

    // The BR reached ready (subtitle renders the server status label).
    await expect(page.getByText(/Ready ·/)).toBeVisible({ timeout: 15_000 });
  });

  test('② the journey is usable at 375px and 1280px', async ({ page }) => {
    await login(page);

    for (const size of [
      { width: 375, height: 800 },
      { width: 1280, height: 900 },
    ]) {
      await page.setViewportSize(size);
      await page.goto(tenantUrl('/ideation/ideas'));
      await expect(ideaRow(page, IDEA_A).first()).toBeVisible();
      // No horizontal overflow of the document at either width.
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow).toBeLessThanOrEqual(2);
    }
  });
});
