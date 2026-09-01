import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import path from 'node:path';

import { expect, test, request as pwRequest, type APIRequestContext, type Page } from '@playwright/test';
import { SignJWT } from 'jose';

/**
 * Developer Logs / Integration Activity console - Slice 1 E2E (sprint-4/12).
 *
 * Real user clicks against the live stack (Next :3001 → FastAPI :8001 →
 * Postgres). The FLOW under test = a developer VIEWING the inbound-API activity
 * log and its redacted detail. Generating the row (mint a workspace API key +
 * make a real gateway call) is precondition setup via the operator/API - that
 * is not the flow being asserted, so API setup is acceptable.
 *
 * Covers AC-DLC-13 (real-click journey), AC-DLC-04 (redaction visible in the
 * detail - no plaintext key), AC-DLC-10/11 (Resource-shell list + read-only
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

    // AC-DLC-10: Resource-shell list - search narrows to our unique trace.
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

    // AC-DLC-04: the Payloads tab shows the redacted request - masked
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
 * Slice 2 - correlated trace (AC-DLC-19). A consumer sends a WhatsApp message via
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
    // (graph:send) - the end-to-end correlated picture for one consumption.
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

/**
 * Slice 3 - retention settings + embed logging (AC-DLC-23/24). Real user clicks
 * against the live stack. Two independent journeys:
 *
 *  ① AC-DLC-23 - a developer navigates Developers → Logs → Log settings, sets a
 *     retention window, saves, and the value persists across a reload. On the
 *     `default` tenant (benign: no beat runs in the E2E stack, and the value is
 *     kept high enough to never prune a recently-seeded row). Verified 375+1280.
 *  ② AC-DLC-24 - an `embed_session` row with a TYPED error renders with the Embed
 *     source badge + its visible error code, in the list AND the detail. To get a
 *     real failing exchange WITHOUT touching the default tenant's live embed-config
 *     connection (depended on by omnichannel-embed*.spec), a DEDICATED tenant is
 *     provisioned, given its OWN omnichannel_shared connection (operator/python
 *     seed), and a genuine `POST /embed/session` with a mismatched parentOrigin is
 *     driven → `origin_not_allowed`. The FLOW under test (viewing the row) is real
 *     clicks; generating it is precondition setup.
 */

async function operatorToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${BACKEND}/auth/login`, {
    data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).access_token as string;
}

const tenantHost = (slug: string) => `http://${slug}.localhost:3001`;

async function loginAt(page: Page, base: string, email: string, password: string) {
  await page.goto(`${base}/signin`);
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** Real clicks: expand the Developers section (if collapsed), then click a child. */
async function gotoDevelopersChild(page: Page, name: RegExp | string, urlRe: RegExp) {
  const link = page.getByRole('link', { name, exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText('Developers', { exact: true }).click();
  }
  await link.click();
  await expect(page).toHaveURL(urlRe);
}

test.describe('Developer Logs retention settings (Slice 3)', () => {
  test('AC-DLC-23: set retention → save → persists across reload (375 + 1280)', async ({
    page,
  }) => {
    // A distinctive, always-safe value (>> any seeded row's age in days) so the
    // save is provably NOT a stale default read, and no prune could touch data.
    const value = 40 + (Date.now() % 120); // 40..159

    await loginAt(page, 'http://localhost:3001', 'demo@example.com', 'demo1234');

    // Navigate by REAL clicks to Developers → Log settings.
    await gotoDevelopersChild(page, 'Log settings', /\/developers\/logs\/settings$/);

    const input = page.getByLabel('Keep developer logs for (days)');
    await expect(input).toBeVisible();
    await input.fill(String(value));
    await page.getByRole('button', { name: /^Save$/ }).click();
    await expect(page.getByText('Log retention saved.')).toBeVisible();

    // Persisted across a hard reload (round-trips the backend PUT→GET).
    await page.reload();
    await expect(page.getByLabel('Keep developer logs for (days)')).toHaveValue(String(value));

    // Responsive - the form reflows with no horizontal scroll at both widths.
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
      await expect(page.getByLabel('Keep developer logs for (days)')).toHaveValue(String(value));
      await page.screenshot({
        path: `/private/tmp/claude-501/-Users-tehjayson-Documents-foundryx-foundryx-shared-service/80e7ad94-f293-461e-a342-c2b76c6b38a9/scratchpad/dlc-settings-${tag}.png`,
        fullPage: true,
      });
    }
  });
});

type EmbedSeed = { slug: string; email: string; password: string; connectionId: string; secret: string };

/** Provision a dedicated tenant + its own omnichannel_shared connection, then drive
 * a real failing /embed/session (origin_not_allowed) → one embed_session error row
 * in that tenant's console. Fully isolated from the default tenant's embed config. */
async function seedEmbedError(request: APIRequestContext): Promise<EmbedSeed> {
  const ts = Date.now();
  const slug = `e2e-dlc-embed-${ts}`;
  const email = `admin-${slug}@example.com`;
  const password = 'ChangeMe1!';
  const token = await operatorToken(request);
  const prov = await request.post(`${BACKEND}/platform/tenants`, {
    headers: { Authorization: `Bearer ${token}` },
    data: { name: `E2E DLC Embed ${ts}`, slug, adminName: 'DLC Admin', adminEmail: email, adminPassword: password },
  });
  expect(prov.status(), await prov.text()).toBe(201);

  // Seed the dedicated tenant's embed connection (operator python helper; cwd =
  // service_backend, its venv). Non-destructive: a fresh tenant has no existing
  // omnichannel_shared row so the one-active-per-provider index is never touched.
  const secret = `e2e-dlc-embed-secret-${ts}-${randomUUID()}`;
  const connectionId = `e2e-dlc-embed-conn-${ts}`;
  const backendDir = path.resolve(__dirname, '..', '..', 'service_backend');
  const venvPy = path.join(backendDir, '.venv', 'bin', 'python');
  const py = existsSync(venvPy) ? venvPy : 'python';
  const script = path.join(__dirname, 'helpers', 'seed_embed_connection_for_tenant.py');
  const out = execFileSync(
    py,
    [script, '--tenant-slug', slug, '--secret', secret, '--origin', 'https://consumer.example', '--connection-id', connectionId],
    { cwd: backendDir, encoding: 'utf8', env: { ...process.env, PYTHONPATH: backendDir } },
  );
  const jsonLine = out.split('\n').find((l) => l.includes('"connectionId"'));
  expect(jsonLine, `seed helper should print connection JSON; got:\n${out}`).toBeTruthy();
  expect((JSON.parse(jsonLine!) as { connectionId: string }).connectionId).toBe(connectionId);

  // Mint a valid HS256 assertion (passes signature/aud/exp/iat/jti) but POST with a
  // parentOrigin NOT in allowedOrigins → the exchange reaches the origin check and
  // fails origin_not_allowed (403), recording ONE embed_session error row.
  const now = Math.floor(Date.now() / 1000);
  const assertion = await new SignJWT({
    workspaceId: 'ws-e2e',
    scope: 'inbox',
    name: 'DLC Embed Agent',
    caps: ['reply'],
    allowedOrigins: ['https://consumer.example'],
  })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuer(connectionId)
    .setSubject('dlc-agent-1')
    .setAudience('omnichannel-embed')
    .setIssuedAt(now)
    .setExpirationTime(now + 900)
    .setJti(randomUUID())
    .sign(new TextEncoder().encode(secret));

  const exch = await request.post(`${BACKEND}/embed/session`, {
    data: { assertion, parentOrigin: 'https://evil.example' },
  });
  expect(exch.status(), await exch.text()).toBe(403);
  expect((await exch.json()).error.code).toBe('origin_not_allowed');
  return { slug, email, password, connectionId, secret };
}

/**
 * Detail enhancements (sprint-4/12 follow-up) - three additions on the log detail:
 *  ① Body capture - the Payloads tab shows the REAL request body (message text
 *     visible, Authorization masked) + the response body (no "No payload captured").
 *  ② Workspace name + clickable - Overview "Workspace" shows the resolved NAME
 *     ("General"), clickable to the workspace page; the trace id switches tabs.
 *  ③ Record-nav - ‹ N / M › prev/next pager navigates between neighbouring rows.
 *
 * Reuses `seedTracedSend` (a JSON gateway POST /messages → an inbound_api row
 * with a JSON body + a resolvable workspace). Real clicks for the flow.
 */
test.describe('Developer Logs detail enhancements', () => {
  // Serial: the three journeys share ONE read-only seed and each logs in - running
  // them in parallel pumps the shared 127.0.0.1 login throttle + races the list
  // search. Serial keeps them deterministic (file-level isolation is unaffected).
  test.describe.configure({ mode: 'serial' });
  let seed: TraceSeed;

  test.beforeAll(async () => {
    seed = await seedTracedSend();
  });

  async function openInboundDetail(page: Page) {
    await login(page);
    const logsLink = page.getByRole('link', { name: 'Logs', exact: true });
    if (!(await logsLink.isVisible().catch(() => false))) {
      await page.getByText('Developers', { exact: true }).click();
    }
    await logsLink.click();
    await expect(page).toHaveURL(/\/developers\/logs$/);
    await page.getByPlaceholder(/Search operation, trace/i).fill(seed.traceId);
    const inboundRow = page.getByRole('row').filter({ hasText: 'POST /messages' });
    await expect(inboundRow.first()).toBeVisible({ timeout: 10_000 });
    await inboundRow.first().click();
    await expect(page).toHaveURL(/\/developers\/logs\/[\w-]+(\?|$)/);
    await expect(page.getByText(`Trace ${seed.traceId}`)).toBeVisible();
  }

  test('① body capture: Payloads tab shows request + response bodies, token masked', async ({
    page,
  }) => {
    await openInboundDetail(page);
    await page.getByRole('tab', { name: /Payloads/i }).click();

    // Request body - the message text is visible, the Authorization header masked.
    await expect(page.getByText('DLC E2E traced send')).toBeVisible();
    await expect(page.getByText('"authorization": "***"')).toBeVisible();
    // Response body captured - no longer "No payload captured" for the JSON send.
    await expect(page.getByText('"status": "queued"')).toBeVisible();
    const body = (await page.textContent('body')) ?? '';
    expect(body).not.toContain('No payload captured');
  });

  test('② workspace shows a name + is clickable, trace id switches to the Trace tab', async ({
    page,
  }) => {
    await openInboundDetail(page);

    // Overview "Workspace" resolves the human NAME (not a raw uuid) + links out.
    const wsLink = page.getByRole('link', { name: 'General' });
    await expect(wsLink).toBeVisible();
    await expect(wsLink).toHaveAttribute('href', new RegExp(`/omnichannel/settings/workspaces/${seed.workspaceId}`));
    await wsLink.click();
    await expect(page).toHaveURL(new RegExp(`/omnichannel/settings/workspaces/${seed.workspaceId}`));

    // Back to the detail: clicking the trace id switches to the Trace tab.
    await page.goBack();
    await expect(page.getByText(`Trace ${seed.traceId}`)).toBeVisible();
    await page.getByRole('button', { name: seed.traceId }).first().click();
    await expect(page.getByTestId('trace-timeline')).toBeVisible();
  });

  test('③ record-nav: ‹ N / M › moves to a neighbouring row (375 + 1280)', async ({ page }) => {
    await openInboundDetail(page);
    // The detail id is the stable identity (the pushed nav URL drops the ?ctx
    // record-nav query - compare by id, not the full URL).
    const idOf = (u: string) => new URL(u).pathname.split('/').pop();
    const firstId = idOf(page.url());

    // The pager renders "N / M" with Prev/Next buttons (reused inlineNav).
    await expect(page.getByText(/^\d+ \/ \d+$/)).toBeVisible();
    await page.getByRole('button', { name: 'Next' }).click();
    await expect(page).toHaveURL(/\/developers\/logs\/[\w-]+(\?|$)/);
    await expect.poll(() => idOf(page.url())).not.toBe(firstId);
    // Prev returns to the original row (circular, deterministic neighbours).
    await page.getByRole('button', { name: 'Previous' }).click();
    await expect.poll(() => idOf(page.url())).toBe(firstId);

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
      await expect(page.getByText(/^\d+ \/ \d+$/)).toBeVisible();
      await page.screenshot({
        path: `/private/tmp/claude-501/-Users-tehjayson-Documents-foundryx-foundryx-shared-service/80e7ad94-f293-461e-a342-c2b76c6b38a9/scratchpad/dlc-enh-nav-${tag}.png`,
        fullPage: true,
      });
    }
  });
});

test.describe('Developer Logs embed error (Slice 3)', () => {
  let seed: EmbedSeed;

  test.beforeAll(async ({ request }) => {
    seed = await seedEmbedError(request);
  });

  test('AC-DLC-24: embed_session error row renders with the Embed badge + error code', async ({
    page,
  }) => {
    // View as the DEDICATED tenant's admin (its console has exactly the one row).
    await loginAt(page, tenantHost(seed.slug), seed.email, seed.password);

    // Real clicks → Developers → Logs.
    await gotoDevelopersChild(page, /^Logs$/, /\/developers\/logs$/);

    // The list row shows the Embed source badge + the typed error code inline.
    const row = page.getByRole('row').filter({ hasText: 'embed:session' });
    await expect(row.first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('Embed').first()).toBeVisible();
    await expect(page.getByText('origin_not_allowed').first()).toBeVisible();

    // Open the read-only detail - the error code is surfaced (data-testid pin).
    await row.first().click();
    await expect(page).toHaveURL(/\/developers\/logs\/[\w-]+(\?|$)/);
    await expect(page.getByTestId('log-error-code')).toHaveText('origin_not_allowed');
    // Overview shows the Embed source; NO raw assertion / embedSecret on the page.
    const body = (await page.textContent('body')) ?? '';
    expect(body).toContain('Embed');
    expect(body).not.toContain(seed.secret);

    // Responsive check at both widths.
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
        path: `/private/tmp/claude-501/-Users-tehjayson-Documents-foundryx-foundryx-shared-service/80e7ad94-f293-461e-a342-c2b76c6b38a9/scratchpad/dlc-embed-${tag}.png`,
        fullPage: true,
      });
    }
  });
});
