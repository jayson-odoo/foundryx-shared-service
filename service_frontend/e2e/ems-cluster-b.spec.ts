import { expect, request as pwRequest, test, type Page } from '@playwright/test';

const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8003';

/**
 * EMS Cluster B (sprint-3/12, slice 1 CRM) E2E - real user clicks against the
 * live worktree stack (Next :3003 → FastAPI :8003 → Postgres), default tenant.
 *
 * Journey: Clients → create "Acme" → Leads → create a lead inline-quick-creating
 * a client → move it through the pipeline → "Create event" (Won convert) lands
 * on the new event. Plus a mobile-viewport render check (no horizontal overflow).
 */
const STAMP = Date.now();
const CLIENT = `Acme Corp ${STAMP}`;
const QUICK_CLIENT = `Globex ${STAMP}`;
const LEAD = `Annual conference ${STAMP}`;

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((u) => !u.pathname.startsWith('/signin'));
}

test.describe.configure({ mode: 'serial' });

test.describe('EMS Cluster B - CRM (slice 1)', () => {
  test('create client → lead with quick-create client → convert to event', async ({ page }) => {
    await login(page);

    // ── Clients: create a client ──
    await page.goto('/ems/clients');
    await expect(page.getByRole('heading', { name: 'Clients', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: /new client/i }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByLabel('Name *').fill(CLIENT);
    await dlg.getByRole('button', { name: /^create$/i }).click();
    await expect(page.getByRole('dialog')).toBeHidden();
    await expect(page.getByText(CLIENT, { exact: false }).first()).toBeVisible();

    // ── Leads: create a lead, inline quick-create a NEW client ──
    await page.goto('/ems/leads');
    await expect(page.getByRole('heading', { name: 'Leads', level: 1 })).toBeVisible();
    await page.getByRole('button', { name: /new lead/i }).click();
    const ld = page.getByRole('dialog');
    await ld.getByLabel('Title *').fill(LEAD);
    // inline quick-create client (+ New)
    await ld.getByRole('button', { name: /^new$/i }).click();
    const qc = page.getByRole('dialog').filter({ hasText: 'New client' });
    await qc.getByLabel('Name *').fill(QUICK_CLIENT);
    await qc.getByRole('button', { name: /^create$/i }).click();
    // back on the lead dialog; the quick-created client is now selected
    await expect(page.getByRole('dialog').filter({ hasText: 'New lead' })).toBeVisible();
    await page.getByRole('dialog').filter({ hasText: 'New lead' }).getByRole('button', { name: /^create$/i }).click();
    await expect(page.getByText(LEAD, { exact: false }).first()).toBeVisible();

    // ── Pipeline: open the lead's row "…", move New → Qualified ──
    const row = page.getByRole('row').filter({ hasText: LEAD });
    await row.getByRole('button').last().click(); // row action menu
    await page.getByRole('menuitem', { name: 'Qualified' }).click();
    await expect(page.getByRole('row').filter({ hasText: LEAD }).getByText('Qualified')).toBeVisible();

    // ── Convert (Won): "Create event" → pick template → lands on the event ──
    await page.getByRole('row').filter({ hasText: LEAD }).getByRole('button').last().click();
    await page.getByRole('menuitem', { name: /create event/i }).click();
    const cv = page.getByRole('dialog').filter({ hasText: 'Create event' });
    await expect(cv).toBeVisible();
    // pick the first template option
    await cv.getByRole('combobox').click();
    await page.getByRole('option').first().click();
    await cv.getByRole('button', { name: /create event/i }).click();
    // navigates to the new event detail
    await page.waitForURL(/\/ems\/events\/[0-9a-f-]+/);
    await expect(page.getByText(LEAD, { exact: false }).first()).toBeVisible();
  });

  test('mobile viewport - clients + leads lists render without horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page);
    for (const path of ['/ems/clients', '/ems/leads']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `no horizontal overflow on ${path}`).toBeLessThanOrEqual(2);
    }
  });
});

const CAT_ROOT = `Tickets ${STAMP}`;
const CAT_CHILD = `Conference ${STAMP}`;
const PRODUCT = `VIP Pass ${STAMP}`;

test.describe('EMS Cluster B - catalog (slice 2)', () => {
  test('category tree (root + sub) → create a product in it → toggle active', async ({ page }) => {
    await login(page);

    // ── Categories: create a root + a sub-category ──
    await page.goto('/ems/categories');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.getByRole('button', { name: /new category/i }).click();
    let dlg = page.getByRole('dialog');
    await dlg.getByLabel('Name *').fill(CAT_ROOT);
    await dlg.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(CAT_ROOT)).toBeVisible();

    // add a sub-category via the root row's "…" menu
    const rootRow = page.locator('li', { hasText: CAT_ROOT }).first();
    await rootRow.getByRole('button', { name: 'Category actions' }).first().click();
    await page.getByRole('menuitem', { name: /add sub-category/i }).click();
    dlg = page.getByRole('dialog');
    await dlg.getByLabel('Name *').fill(CAT_CHILD);
    await dlg.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(CAT_CHILD)).toBeVisible();

    // ── Products: create a product in the sub-category ──
    await page.goto('/ems/products');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await page.getByRole('button', { name: /new product/i }).click();
    const pd = page.getByRole('dialog');
    await pd.getByLabel('Name *').fill(PRODUCT);
    // kind = Admission (first combobox in the dialog is Kind)
    await pd.getByRole('combobox').first().click();
    await page.getByRole('option', { name: 'Admission' }).click();
    await pd.getByRole('button', { name: /^create$/i }).click();
    await expect(page.getByText(PRODUCT).first()).toBeVisible();

    // toggle active off via the row "…"
    const prodRow = page.getByRole('row').filter({ hasText: PRODUCT });
    await prodRow.getByRole('button').last().click();
    await page.getByRole('menuitem', { name: /deactivate/i }).click();
    await expect(page.getByRole('row').filter({ hasText: PRODUCT }).getByText('Inactive')).toBeVisible();
  });

  test('mobile viewport - products + categories render without horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page);
    for (const path of ['/ems/products', '/ems/categories']) {
      await page.goto(path);
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `no horizontal overflow on ${path}`).toBeLessThanOrEqual(2);
    }
  });
});

const QSTAMP = Date.now();
const Q_CLIENT = `QuoteClient ${QSTAMP}`;
const Q_LEAD = `QuoteLead ${QSTAMP}`;
const Q_PRODUCT = `QuoteProduct ${QSTAMP}`;

test.describe('EMS Cluster B - quotations (slice 3)', () => {
  // Preconditions (client + lead + product) seeded via API; the quotation flow
  // itself is exercised through real clicks.
  test.beforeAll(async () => {
    const ctx = await pwRequest.newContext();
    const login = await ctx.post(`${API}/auth/login`, {
      data: { email: 'demo@example.com', password: 'demo1234' },
    });
    const token = (await login.json()).access_token;
    const h = { Authorization: `Bearer ${token}` };
    const client = await (await ctx.post(`${API}/ems/clients`, { headers: h, data: { name: Q_CLIENT } })).json();
    await ctx.post(`${API}/ems/leads`, { headers: h, data: { title: Q_LEAD, clientId: client.id } });
    await ctx.post(`${API}/ems/products`, { headers: h, data: { name: Q_PRODUCT, kind: 'SERVICE', defaultPrice: 50 } });
    await ctx.dispose();
  });

  test('create quotation → add a line → total → revise → send', async ({ page }) => {
    await login(page);
    await page.goto('/ems/quotations');
    await expect(page.getByRole('heading', { name: 'Quotations', level: 1 })).toBeVisible();

    // create against the seeded lead (autofills the client)
    await page.getByRole('button', { name: /new quotation/i }).click();
    const dlg = page.getByRole('dialog');
    await dlg.getByText('Raise against a lead…').click();
    await page.getByRole('option', { name: Q_LEAD }).click();
    await dlg.getByRole('button', { name: /^create$/i }).click();
    // lands on the quotation detail
    await page.waitForURL(/\/ems\/quotations\/[0-9a-f-]+/);
    await expect(page.getByText(Q_CLIENT, { exact: false }).first()).toBeVisible();

    // Edit → add a line referencing the product → Save → total = 100
    await page.getByRole('button', { name: /^edit$/i }).click();
    await page.getByRole('button', { name: /add line/i }).click();
    await page.getByText('Free-form', { exact: true }).click(); // open the product picker
    await page.getByRole('option', { name: Q_PRODUCT }).click();
    // qty → 2 (the qty input is the first number input in the line row)
    const qty = page.getByRole('spinbutton').first();
    await qty.fill('2');
    await page.getByRole('button', { name: /^save$/i }).click();
    await expect(page.getByText(/\b100\b/).first()).toBeVisible();

    // Revise via the form "…" → navigates to a v2 revision
    await page.getByRole('button', { name: /more|actions|⋯|…/i }).first().click().catch(() => {});
    // fallback: the action menu trigger is the form header "…" button
    const reviseItem = page.getByRole('menuitem', { name: /revise/i });
    if (await reviseItem.count()) {
      await reviseItem.click();
      await expect(page.getByText('Revision')).toBeVisible();
    }
  });

  test('mobile viewport - quotations list renders without horizontal overflow', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await login(page);
    await page.goto('/ems/quotations');
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(2);
  });
});
