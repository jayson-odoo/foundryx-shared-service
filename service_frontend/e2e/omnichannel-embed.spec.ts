import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { existsSync } from 'node:fs';
import path from 'node:path';

import { expect, test, type APIRequestContext, type Page } from '@playwright/test';
import { SignJWT } from 'jose';

/**
 * Omnichannel embed host (sprint-4/11) E2E - AC-11H-21 + AC-11H-12..17.
 *
 * A test harness POSES AS THE CONSUMER PARENT: it serves a real parent page that
 * mounts the chromeless `/embed/omnichannel/*` iframe, runs the postMessage
 * handshake (responds to `ready` with a validly-signed `init { assertion }`
 * targeted to - and origin-validated against - the shared-service origin), and
 * drives the reused conversation UI with REAL CLICKS via `frameLocator`.
 *
 * Setup (operator-side, allowed): a python helper seeds an `omnichannel_shared`
 * connection with a KNOWN `embedSecret` + `allowedOrigins`, reusing the dev demo
 * inbox (threads cnt-001..005 on the dev-cred `chn-demo` channel so replies never
 * hit Graph). The spec MINTS the HS256 assertion in-process with `jose`.
 *
 * Parent origin = the shared-service origin (baseURL, http://localhost:3001):
 * same-origin framing means `frame-ancestors http://localhost:3001` permits it,
 * and the parent/widget postMessage origin checks both resolve to that origin.
 */

const AUD = 'omnichannel-embed';
const PARENT_PATH = '/e2e-embed-parent';

// The shared-service origin the parent lives on + the connection allows.
const SHARED_ORIGIN = 'http://localhost:3001';

interface SeedResult {
  connectionId: string;
  workspaceId: string;
  workspaceName: string;
  contactId: string;
  contactName: string;
  embedSecret: string;
  allowedOrigins: string[];
}

let seed: SeedResult;

// ── operator-side seed (dedicated connection row; non-destructive) ───────────
function runSeed(): SeedResult {
  const backendDir = path.resolve(__dirname, '..', '..', 'service_backend');
  const venvPy = path.join(backendDir, '.venv', 'bin', 'python');
  const py = existsSync(venvPy) ? venvPy : 'python';
  const script = path.join(__dirname, 'helpers', 'seed_embed_connection.py');
  const secret = `e2e-embed-secret-${Date.now()}-${randomUUID()}`;
  const out = execFileSync(
    py,
    [
      script,
      '--secret',
      secret,
      '--origin',
      SHARED_ORIGIN,
      '--connection-id',
      `e2e-embed-conn-${Date.now()}`,
      '--contact-id',
      'cnt-001',
    ],
    { cwd: backendDir, encoding: 'utf8' },
  );
  const line = out.trim().split('\n').filter(Boolean).pop() ?? '{}';
  return JSON.parse(line) as SeedResult;
}

// ── assertion minting (contract §2, HS256 over the connection embedSecret) ───
async function mintAssertion(opts: {
  scope: string;
  caps: string[];
  name?: string;
  sub?: string;
  allowedOrigins?: string[];
  workspaceId?: string;
}): Promise<string> {
  const now = Math.floor(Date.now() / 1000);
  const key = new TextEncoder().encode(seed.embedSecret);
  return new SignJWT({
    workspaceId: opts.workspaceId ?? seed.workspaceId,
    scope: opts.scope,
    name: opts.name ?? 'E2E Ext Agent',
    caps: opts.caps,
    allowedOrigins: opts.allowedOrigins ?? [SHARED_ORIGIN],
  })
    .setProtectedHeader({ alg: 'HS256' })
    .setIssuer(seed.connectionId)
    .setSubject(opts.sub ?? 'ems-agent-1')
    .setAudience(AUD)
    .setIssuedAt(now)
    .setExpirationTime(now + 900)
    .setJti(randomUUID())
    .sign(key);
}

// ── the real consumer parent page (served via route interception) ────────────
function parentHtml(mode: 'thread' | 'inbox', assertion: string, connectionId: string): string {
  const src = `/embed/omnichannel/${mode}?c=${encodeURIComponent(connectionId)}`;
  const theme = { primary: '#0aa06e' };
  return `<!doctype html><html><head><meta charset="utf-8"><title>E2E parent</title>
<style>html,body{margin:0;height:100%}#w{width:100%;height:100vh;border:0;display:block}</style>
</head><body>
<iframe id="w" src="${src}"></iframe>
<script>
  var FRAME = document.getElementById('w');
  var SHARED = location.origin;
  var ASSERTION = ${JSON.stringify(assertion)};
  var THEME = ${JSON.stringify(theme)};
  window.__activity = [];
  window.__resize = [];
  window.addEventListener('message', function (e) {
    // Origin-validate BOTH directions (contract §5) - never accept '*'.
    if (e.origin !== SHARED) return;
    if (!FRAME.contentWindow || e.source !== FRAME.contentWindow) return;
    var d = e.data;
    if (!d || d.v !== 1) return;
    if (d.type === 'ready') {
      FRAME.contentWindow.postMessage(
        { v: 1, type: 'init', payload: { assertion: ASSERTION, theme: THEME, colorScheme: 'light' } },
        SHARED,
      );
    } else if (d.type === 'activity') {
      window.__activity.push(d.payload);
    } else if (d.type === 'resize') {
      window.__resize.push(d.payload);
    }
  });
</script>
</body></html>`;
}

async function mountParent(
  page: Page,
  mode: 'thread' | 'inbox',
  assertion: string,
  connectionId: string,
): Promise<void> {
  await page.route(`**${PARENT_PATH}`, (route) =>
    route.fulfill({
      status: 200,
      contentType: 'text/html; charset=utf-8',
      body: parentHtml(mode, assertion, connectionId),
    }),
  );
  await page.goto(`${SHARED_ORIGIN}${PARENT_PATH}`);
}

test.beforeAll(() => {
  seed = runSeed();
  expect(seed.connectionId, 'seed produced a connection id').toBeTruthy();
  expect(seed.contactId).toBe('cnt-001');
});

test.describe('Omnichannel embed host', () => {
  // AC-11H-21 + AC-11H-12/13/16 - the embedded thread round-trip.
  test('embedded thread: renders, replies (attributed to the external agent)', async ({
    page,
    request,
  }) => {
    const agentName = `E2E Agent ${Date.now()}`;
    const assertion = await mintAssertion({
      scope: `thread:${seed.contactId}`,
      caps: ['reply', 'assign', 'note'],
      name: agentName,
      sub: 'ems-agent-round-trip',
    });
    await mountParent(page, 'thread', assertion, seed.connectionId);

    const frame = page.frameLocator('#w');
    // AC-11H-12/13: boots bare, handshakes, paints the reused conversation UI.
    await expect(frame.getByTestId('composer')).toBeVisible({ timeout: 20_000 });
    // AC-11H-16: it IS the same rich <ConversationDrawer> (message bubbles etc.).
    await expect(frame.getByTestId('bubble-contact').first()).toBeVisible();

    // Real-click reply.
    const replyText = `embed reply ${Date.now()}`;
    await frame.getByTestId('message-input').fill(replyText);
    await frame.getByTestId('message-send').click();
    await expect(
      frame.getByTestId('bubble-agent').filter({ hasText: replyText }),
    ).toBeVisible({ timeout: 15_000 });

    // Attribution is server-side truth (AC-11H-02): a fresh exchange (same sub)
    // reads the thread back and the agent message carries the external identity.
    const token = await exchange(request, {
      scope: `thread:${seed.contactId}`,
      caps: ['reply'],
      name: agentName,
      sub: 'ems-agent-round-trip',
    });
    const msgs = await request.get(
      `${apiBase()}/omnichannel/contacts/${seed.contactId}/messages`,
      { headers: { Authorization: `Bearer ${token}` } },
    );
    expect(msgs.ok(), await msgs.text()).toBeTruthy();
    const body = (await msgs.json()) as Array<{
      body?: string;
      senderName?: string;
      senderExternalAgentId?: string | null;
      senderId?: string | null;
      senderType?: string;
    }>;
    const mine = body.find((m) => m.body === replyText);
    expect(mine, 'the UI-sent reply is stored').toBeTruthy();
    expect(mine!.senderType).toBe('AGENT');
    expect(mine!.senderName).toBe(agentName);
    expect(mine!.senderExternalAgentId).toBeTruthy();
    expect(mine!.senderId ?? null).toBeNull();
  });

  // AC-11H-21 (read_only refusal) + AC-11H-11 - backend is the boundary.
  test('read_only token: reply is refused server-side, surfaced in the widget', async ({ page }) => {
    const assertion = await mintAssertion({
      scope: `thread:${seed.contactId}`,
      caps: ['read_only'],
      sub: 'ems-agent-readonly',
    });
    await mountParent(page, 'thread', assertion, seed.connectionId);

    const frame = page.frameLocator('#w');
    await expect(frame.getByTestId('composer')).toBeVisible({ timeout: 20_000 });

    await frame.getByTestId('message-input').fill(`should be refused ${Date.now()}`);
    await frame.getByTestId('message-send').click();
    // The write 403s server-side (the widget can't bypass it) → error surfaces,
    // no agent bubble is created for this attempt.
    await expect(frame.getByTestId('send-error')).toBeVisible({ timeout: 15_000 });
  });

  // AC-11H-21 (wrong-origin) - the widget refuses an init whose assertion does
  // not name the parent origin (no session exchange, no paint).
  test('wrong-origin assertion is rejected by the widget (no session)', async ({ page }) => {
    const assertion = await mintAssertion({
      scope: `thread:${seed.contactId}`,
      caps: ['reply'],
      allowedOrigins: ['https://evil.example'], // NOT the parent origin
      sub: 'ems-agent-wrong-origin',
    });
    await mountParent(page, 'thread', assertion, seed.connectionId);

    const frame = page.frameLocator('#w');
    // Widget stays on the loader; the conversation never paints.
    await expect(frame.getByLabel('Loading')).toBeVisible({ timeout: 10_000 });
    await expect(frame.getByTestId('composer')).toHaveCount(0);
  });

  // AC-11H-15 - frame-ancestors clickjacking guard (server-emitted CSP).
  test('embed route emits frame-ancestors from the connection allowedOrigins', async ({
    request,
  }) => {
    const good = await request.get(
      `/embed/omnichannel/thread?c=${encodeURIComponent(seed.connectionId)}`,
    );
    const csp = good.headers()['content-security-policy'] ?? '';
    expect(csp).toContain('frame-ancestors');
    expect(csp).toContain(SHARED_ORIGIN);

    // Unknown / absent connection → fail closed with 'none' (no framing).
    const bad = await request.get('/embed/omnichannel/thread?c=does-not-exist');
    expect(bad.headers()['content-security-policy'] ?? '').toContain("frame-ancestors 'none'");

    const none = await request.get('/embed/omnichannel/thread');
    expect(none.headers()['content-security-policy'] ?? '').toContain("frame-ancestors 'none'");
  });

  // AC-11H-17 - responsive at 375 AND 1280 (thread + inbox), no h-scroll.
  for (const width of [375, 1280]) {
    test(`thread embed reflows at ${width}px (no horizontal scroll)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      const assertion = await mintAssertion({
        scope: `thread:${seed.contactId}`,
        caps: ['reply'],
        sub: `ems-agent-resp-t-${width}`,
      });
      await mountParent(page, 'thread', assertion, seed.connectionId);
      const frame = page.frameLocator('#w');
      await expect(frame.getByTestId('composer')).toBeVisible({ timeout: 20_000 });
      await assertNoHScroll(page);
    });

    test(`inbox embed reflows at ${width}px (no horizontal scroll)`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      const assertion = await mintAssertion({
        scope: 'inbox',
        caps: ['reply'],
        sub: `ems-agent-resp-i-${width}`,
      });
      await mountParent(page, 'inbox', assertion, seed.connectionId);
      const frame = page.frameLocator('#w');
      // The embed inbox renders the reused ThreadList (deterministic demo rows).
      await expect(frame.getByTestId('thread-row-cnt-001')).toBeVisible({ timeout: 20_000 });
      await assertNoHScroll(page);
    });
  }
});

// ── helpers ──────────────────────────────────────────────────────────────────
function apiBase(): string {
  return process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
}

/** Exchange a freshly-minted assertion directly at /embed/session (with the
 * required Origin header) for a scoped access token - the backend-truth path. */
async function exchange(
  request: APIRequestContext,
  opts: { scope: string; caps: string[]; name?: string; sub?: string },
): Promise<string> {
  const assertion = await mintAssertion(opts);
  const res = await request.post(`${apiBase()}/embed/session`, {
    data: { assertion },
    headers: { Origin: SHARED_ORIGIN, 'Content-Type': 'application/json' },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return ((await res.json()) as { accessToken: string }).accessToken;
}

/** The embed iframe document must not scroll horizontally at any viewport. */
async function assertNoHScroll(page: Page): Promise<void> {
  const frame = page.frames().find((f) => f.url().includes('/embed/omnichannel/'));
  expect(frame, 'embed frame is present').toBeTruthy();
  const overflow = await frame!.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, 'no horizontal overflow').toBeLessThanOrEqual(1);
}
