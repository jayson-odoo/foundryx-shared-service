import { expect, test, request as pwRequest, type Page } from '@playwright/test';

/**
 * Developer Logs / Integration Activity console — Slice 1 E2E (sprint-4/12).
 *
 * Real user clicks against the live stack (Next :3001 → FastAPI :8001 →
 * Postgres). The FLOW under test = a developer VIEWING the inbound-API activity
 * log and its redacted detail. Generating the row (mint a workspace API key +
 * make a real gateway call) is precondition setup via the operator/API — that
 * is not the flow being asserted, so API setup is acceptable.
 *
 * Covers AC-DLC-13 (real-click journey), AC-DLC-04 (redaction visible in the
 * detail — no plaintext key), AC-DLC-10/11 (Resource-shell list + read-only
 * detail), AC-DLC-12 (responsive 375px + 1280px).
 */

const BACKEND = 'http://localhost:8001';

type Seed = { traceId: string; fullKey: string; operation: string };

async function login(page: Page) {
  await page.goto('/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Precondition: mint an API key + make a real gateway call, then read back the
 * freshly-recorded inbound_api row's trace id (unique, deterministic assertion
 * target under fullyParallel). */
async function seedInboundRow(): Promise<Seed> {
  const api = await pwRequest.newContext({ baseURL: BACKEND });
  const loginRes = await api.post('/auth/login', {
    data: { email: 'demo@example.com', password: 'demo1234' },
  });
  expect(loginRes.ok(), await loginRes.text()).toBeTruthy();
  const token = (await loginRes.json()).access_token as string;
  const auth = { Authorization: `Bearer ${token}` };

  const wsRes = await api.get('/omnichannel/workspaces', { headers: auth });
  expect(wsRes.ok(), await wsRes.text()).toBeTruthy();
  const workspaceId = (await wsRes.json()).data[0].id as string;

  const mintRes = await api.post(`/omnichannel/workspaces/${workspaceId}/api-keys`, {
    headers: auth,
    data: { name: `dlc-e2e-${Date.now()}` },
  });
  expect(mintRes.ok(), await mintRes.text()).toBeTruthy();
  const fullKey = (await mintRes.json()).fullKey as string;
  expect(fullKey).toContain('fxw_live_');

  // Real public-gateway call → records ONE inbound_api row (Authorization header
  // redacted). 200 (empty contacts list) is the clean-success path.
  const gwRes = await api.get('/api/v1/omnichannel/contacts', {
    headers: { Authorization: `Bearer ${fullKey}` },
  });
  expect(gwRes.status(), await gwRes.text()).toBe(200);

  // Read back the newest inbound_api row for its (server-minted) trace id.
  let traceId = '';
  for (let i = 0; i < 10 && !traceId; i++) {
    const logs = await api.get('/integration-logs?page=0&page_size=5&sort_by=created_at&sort_dir=desc', {
      headers: auth,
    });
    expect(logs.ok(), await logs.text()).toBeTruthy();
    const rows = (await logs.json()).data as Array<{
      source: string;
      traceId: string;
      operation: string;
    }>;
    const mine = rows.find((r) => r.source === 'inbound_api' && r.operation === 'GET /contacts');
    if (mine) traceId = mine.traceId;
    else await new Promise((r) => setTimeout(r, 400));
  }
  expect(traceId, 'inbound_api row should have been recorded').toBeTruthy();
  await api.dispose();
  return { traceId, fullKey, operation: 'GET /contacts' };
}

test.describe('Developer Logs console (Slice 1)', () => {
  let seed: Seed;

  test.beforeAll(async () => {
    seed = await seedInboundRow();
  });

  test('AC-DLC-13/04/10/11: view the inbound-API row and its redacted detail', async ({
    page,
  }) => {
    await login(page);

    // Navigate by REAL clicks: expand the "Developers" section, click "Logs".
    const logsLink = page.getByRole('link', { name: 'Logs', exact: true });
    if (!(await logsLink.isVisible().catch(() => false))) {
      await page.getByText('Developers', { exact: true }).click();
    }
    await logsLink.click();
    await expect(page).toHaveURL(/\/developers\/logs$/);

    // AC-DLC-10: Resource-shell list — search narrows to our unique trace.
    await page.getByPlaceholder(/Search operation, trace/i).fill(seed.traceId);
    const row = page.getByRole('row').filter({ hasText: seed.operation });
    await expect(row.first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Inbound API').first()).toBeVisible();
    await expect(page.getByText('Success').first()).toBeVisible();

    // AC-DLC-11: open the read-only detail via a real row click.
    await row.first().click();
    await expect(page).toHaveURL(/\/developers\/logs\/[\w-]+(\?|$)/);
    await expect(page.getByText(`Trace ${seed.traceId}`)).toBeVisible();
    // No Edit toggle on a historical log row.
    await expect(page.getByRole('button', { name: /^Edit$/ })).toHaveCount(0);

    // AC-DLC-04: the Payloads tab shows the redacted request — masked
    // Authorization, and NO plaintext API key anywhere on the page.
    await page.getByRole('tab', { name: /Payloads/i }).click();
    await expect(page.getByText('"authorization": "***"')).toBeVisible();
    const body = (await page.textContent('body')) ?? '';
    expect(body).not.toContain(seed.fullKey);
    expect(body).not.toContain(seed.fullKey.replace('fxw_live_', ''));
  });

  test('AC-DLC-12: responsive at 375px and 1280px', async ({ page }) => {
    await login(page);
    const logsLink = page.getByRole('link', { name: 'Logs', exact: true });
    if (!(await logsLink.isVisible().catch(() => false))) {
      await page.getByText('Developers', { exact: true }).click();
    }
    await logsLink.click();
    await expect(page).toHaveURL(/\/developers\/logs$/);
    await page.getByPlaceholder(/Search operation, trace/i).fill(seed.traceId);
    await expect(page.getByText('Inbound API').first()).toBeVisible({ timeout: 10_000 });

    for (const [w, h, tag] of [
      [1280, 800, 'desktop'],
      [375, 812, 'mobile'],
    ] as const) {
      await page.setViewportSize({ width: w, height: h });
      await page.waitForTimeout(300);
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `no horizontal scroll at ${tag} (${w}px)`).toBeLessThanOrEqual(2);
      await page.screenshot({
        path: `/private/tmp/claude-501/-Users-tehjayson-Documents-foundryx-foundryx-shared-service/80e7ad94-f293-461e-a342-c2b76c6b38a9/scratchpad/dlc-list-${tag}.png`,
        fullPage: true,
      });
    }
  });
});
