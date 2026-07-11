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

/**
 * Slice 2 — correlated trace (AC-DLC-19). A consumer sends a WhatsApp message via
 * the public gateway (through the dev channel `chn-demo`, which STUBS Meta so no
 * Graph traffic leaves the box). That single consumption yields TWO legs sharing
 * ONE trace: the `inbound_api` POST /messages row and the `outbound_meta`
 * graph:send row. The FLOW under test = a developer OPENING the inbound row and
 * seeing both correlated legs on the Trace timeline (real clicks). Generating the
 * consumption (reopen a window + gateway-send) is precondition setup via the API.
 *
 * Covers AC-DLC-14/15 (outbound Meta row + shared trace), AC-DLC-18 (timeline
 * renders the legs), AC-DLC-19 (end-to-end real-click), + responsive.
 */
type TraceSeed = { traceId: string; wamid: string; workspaceId: string };

async function seedTracedSend(): Promise<TraceSeed> {
  const api = await pwRequest.newContext({ baseURL: BACKEND });
  const loginRes = await api.post('/auth/login', {
    data: { email: 'demo@example.com', password: 'demo1234' },
  });
  expect(loginRes.ok(), await loginRes.text()).toBeTruthy();
  const token = (await loginRes.json()).access_token as string;
  const auth = { Authorization: `Bearer ${token}` };

  // Find the workspace that owns the dev channel `chn-demo` (Meta-stubbed).
  const wsRes = await api.get('/omnichannel/workspaces', { headers: auth });
  expect(wsRes.ok(), await wsRes.text()).toBeTruthy();
  const workspaces = (await wsRes.json()).data as Array<{ id: string }>;
  let workspaceId = '';
  for (const ws of workspaces) {
    const chRes = await api.get(`/omnichannel/channels?workspaceId=${ws.id}`, { headers: auth });
    if (!chRes.ok()) continue;
    const channels = (await chRes.json()).data as Array<{ id: string }>;
    if (channels.some((c) => c.id === 'chn-demo')) {
      workspaceId = ws.id;
      break;
    }
  }
  expect(workspaceId, 'dev channel chn-demo must be present (restore it if trashed)').toBeTruthy();

  // Reopen a 24h window: POST a unique inbound message to chn-demo. A fresh,
  // timestamped phone means a new/re-stitched contact each run (no residue).
  const phone = `60199${Date.now().toString().slice(-9)}`;
  const nowSec = Math.floor(Date.now() / 1000);
  const inbound = {
    object: 'whatsapp_business_account',
    entry: [
      {
        id: 'waba-e2e',
        changes: [
          {
            field: 'messages',
            value: {
              messaging_product: 'whatsapp',
              contacts: [{ wa_id: phone, profile: { name: 'DLC E2E Trace' } }],
              messages: [
                {
                  id: `wamid.e2e-in-${Date.now()}`,
                  from: phone,
                  timestamp: String(nowSec),
                  type: 'text',
                  text: { body: 'open my window' },
                },
              ],
            },
          },
        ],
      },
    ],
  };
  const whRes = await api.post('/omnichannel/webhooks/chn-demo', { data: inbound });
  expect(whRes.ok(), await whRes.text()).toBeTruthy();

  // Mint a workspace API key + make the real gateway send (dev-stubbed Meta).
  const mintRes = await api.post(`/omnichannel/workspaces/${workspaceId}/api-keys`, {
    headers: auth,
    data: { name: `dlc-trace-e2e-${Date.now()}` },
  });
  expect(mintRes.ok(), await mintRes.text()).toBeTruthy();
  const fullKey = (await mintRes.json()).fullKey as string;

  let sent = false;
  for (let i = 0; i < 8 && !sent; i++) {
    const gwRes = await api.post('/api/v1/omnichannel/messages', {
      headers: { Authorization: `Bearer ${fullKey}` },
      data: { to: phone, type: 'text', text: { body: 'DLC E2E traced send' } },
    });
    if (gwRes.status() === 202) {
      sent = true;
    } else {
      // Window may still be settling from the async inbound processing.
      await new Promise((r) => setTimeout(r, 500));
    }
  }
  expect(sent, 'gateway send should be accepted (202) once the window is open').toBeTruthy();

  // Read back the inbound_api POST /messages row's trace + confirm the
  // outbound_meta leg shares it (the correlation this journey visualises).
  let traceId = '';
  let wamid = '';
  for (let i = 0; i < 12 && !(traceId && wamid); i++) {
    const logs = await api.get(
      '/integration-logs?page=0&page_size=20&sort_by=created_at&sort_dir=desc',
      { headers: auth },
    );
    expect(logs.ok(), await logs.text()).toBeTruthy();
    const rows = (await logs.json()).data as Array<{
      source: string;
      traceId: string;
      operation: string;
      externalRef: string | null;
    }>;
    const inboundSend = rows.find(
      (r) => r.source === 'inbound_api' && r.operation === 'POST /messages',
    );
    if (inboundSend?.traceId) {
      const outbound = rows.find(
        (r) => r.source === 'outbound_meta' && r.traceId === inboundSend.traceId,
      );
      if (outbound) {
        traceId = inboundSend.traceId;
        wamid = outbound.externalRef ?? '';
      }
    }
    if (!(traceId && wamid)) await new Promise((r) => setTimeout(r, 400));
  }
  expect(traceId, 'inbound_api POST /messages row should be recorded').toBeTruthy();
  expect(wamid, 'an outbound_meta leg should share the inbound trace').toBeTruthy();
  await api.dispose();
  return { traceId, wamid, workspaceId };
}

test.describe('Developer Logs trace (Slice 2)', () => {
  let seed: TraceSeed;

  test.beforeAll(async () => {
    seed = await seedTracedSend();
  });

  test('AC-DLC-19/18: trace timeline shows the correlated inbound + outbound legs', async ({
    page,
  }) => {
    await login(page);

    // Navigate by REAL clicks to Developers → Logs.
    const logsLink = page.getByRole('link', { name: 'Logs', exact: true });
    if (!(await logsLink.isVisible().catch(() => false))) {
      await page.getByText('Developers', { exact: true }).click();
    }
    await logsLink.click();
    await expect(page).toHaveURL(/\/developers\/logs$/);

    // Find the inbound POST /messages row for our unique trace and open it.
    await page.getByPlaceholder(/Search operation, trace/i).fill(seed.traceId);
    const inboundRow = page.getByRole('row').filter({ hasText: 'POST /messages' });
    await expect(inboundRow.first()).toBeVisible({ timeout: 10_000 });
    await inboundRow.first().click();
    await expect(page).toHaveURL(/\/developers\/logs\/[\w-]+(\?|$)/);
    await expect(page.getByText(`Trace ${seed.traceId}`)).toBeVisible();

    // AC-DLC-18: the Trace tab renders the timeline with BOTH legs, each with a
    // source badge + latency + status. Inbound API (POST /messages) + Outbound
    // (graph:send) — the end-to-end correlated picture for one consumption.
    await page.getByRole('tab', { name: /Trace/i }).click();
    const timeline = page.getByTestId('trace-timeline');
    await expect(timeline).toBeVisible();
    const legs = timeline.getByRole('listitem');
    await expect(legs).toHaveCount(2);
    await expect(timeline.getByText('Inbound API')).toBeVisible();
    await expect(timeline.getByText('Outbound')).toBeVisible();
    await expect(timeline.getByText('POST /messages')).toBeVisible();
    await expect(timeline.getByText('graph:send')).toBeVisible();
    // Both legs carry a status badge; at least the successful send is shown.
    await expect(timeline.getByText('Success').first()).toBeVisible();

    // Clicking the outbound leg navigates to that leg's detail (same trace).
    await timeline.getByText('graph:send').click();
    await expect(page).toHaveURL(/\/developers\/logs\/[\w-]+(\?|$)/);
    await expect(page.getByText(`Trace ${seed.traceId}`)).toBeVisible();
    // The outbound leg's detail surfaces the wamid as its external ref.
    await expect(page.getByText(seed.wamid).first()).toBeVisible();
  });

  test('AC-DLC-19: trace timeline responsive at 375px and 1280px', async ({ page }) => {
    await login(page);
    const logsLink = page.getByRole('link', { name: 'Logs', exact: true });
    if (!(await logsLink.isVisible().catch(() => false))) {
      await page.getByText('Developers', { exact: true }).click();
    }
    await logsLink.click();
    await page.getByPlaceholder(/Search operation, trace/i).fill(seed.traceId);
    const inboundRow = page.getByRole('row').filter({ hasText: 'POST /messages' });
    await expect(inboundRow.first()).toBeVisible({ timeout: 10_000 });
    await inboundRow.first().click();
    await page.getByRole('tab', { name: /Trace/i }).click();
    await expect(page.getByTestId('trace-timeline')).toBeVisible();

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
        path: `/private/tmp/claude-501/-Users-tehjayson-Documents-foundryx-foundryx-shared-service/80e7ad94-f293-461e-a342-c2b76c6b38a9/scratchpad/dlc-trace-${tag}.png`,
        fullPage: true,
      });
    }
  });
});
