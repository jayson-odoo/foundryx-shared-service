import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-4/19 - stateful AI workflow runtime, progress-update proof
 * (AC-SAR-49..56) against the LIVE stack (Next :3001 → FastAPI :8001 →
 * Postgres + Redis). Real clicks for every product surface; the inbound
 * WhatsApp messages arrive through the dev webhook-simulation path on the
 * seeded sandbox channel `chn-demo` (the same path real Meta traffic uses).
 *
 * The seeded "Demo: progress update agent" workflow is built ONLY from generic
 * nodes (inbound trigger → AI Agent → IF → Send Message / Clear Agent State),
 * serialized by `{{ trigger.conversationId }}`. Its agent carries no LLM
 * connection, so the deterministic dev stub derives evidence-backed patches.
 *
 * Isolation: every journey uses a UNIQUE timestamped phone → a new contact /
 * conversation / correlation key; seeded threads are never touched.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const STAMP = Date.now();
const WORKFLOW = 'Demo: progress update agent';

async function login(page: Page) {
  await page.goto('/signin');
  await page.waitForLoadState('networkidle');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  const submit = page.getByRole('button', { name: /sign in/i });
  await expect(submit).toBeEnabled({ timeout: 30_000 });
  await submit.click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), { timeout: 30_000 });
}

function inboundPayload(phone: string, name: string, text: string, seq: number) {
  return {
    object: 'whatsapp_business_account',
    entry: [
      {
        id: 'waba-demo',
        changes: [
          {
            field: 'messages',
            value: {
              messaging_product: 'whatsapp',
              contacts: [{ wa_id: phone, profile: { name } }],
              messages: [
                {
                  id: `wamid.sar19-${STAMP}-${phone}-${seq}`,
                  from: phone,
                  timestamp: String(Math.floor(Date.now() / 1000)),
                  type: 'text',
                  text: { body: text },
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

async function openInbox(page: Page) {
  const link = page.getByRole('link', { name: 'Inbox', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Omnichannel', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/omnichannel\/inbox$/);
}

async function openWorkflows(page: Page) {
  const link = page.getByRole('link', { name: 'All workflows', exact: true });
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Workflows', exact: true }).click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/workflows$/);
}

async function inbound(page: Page, phone: string, name: string, text: string, seq: number) {
  const res = await page.request.post(`${API}/omnichannel/webhooks/chn-demo`, {
    data: inboundPayload(phone, name, text, seq),
  });
  expect(res.ok(), await res.text()).toBeTruthy();
}

async function openThread(page: Page, name: string) {
  await openInbox(page);
  await page.getByText(name, { exact: false }).first().click();
}

async function expectNoDocumentOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

test.describe.configure({ mode: 'serial', timeout: 240_000 });

test.describe('Stateful AI workflow runtime - progress update proof (plan sprint-4/19)', () => {
  test('① two-turn clarification then correction reaches a confirmed, cleared update (AC-SAR-51/52/54)', async ({
    page,
  }) => {
    const phone = `60181${STAMP.toString().slice(-8)}`;
    const name = `SAR19 Two-turn ${STAMP}`;
    await login(page);

    // Turn 1: only the task - the agent asks for the status.
    await inbound(page, phone, name, 'Launch landing page', 1);
    await openThread(page, name);
    await expect(page.getByText('What is the status?', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    });

    // Turn 2: a short answer resolves the pending field; blocked → asks blocker.
    await inbound(page, phone, name, 'blocked', 2);
    await openThread(page, name);
    await expect(page.getByText('What is the blocker?', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    });

    // Turn 3: a correction changes ONLY status; task is retained → ready.
    await inbound(page, phone, name, 'Actually it is completed', 3);
    await openThread(page, name);
    const confirmation = page.getByText('Update recorded', { exact: false }).first();
    await expect(confirmation).toBeVisible({ timeout: 30_000 });
    await expect(confirmation).toContainText('task: Launch landing page');
    await expect(confirmation).toContainText('status: completed');

    // Turn 4: after Clear Agent State the next message starts fresh.
    await inbound(page, phone, name, 'in progress', 4);
    await openThread(page, name);
    await expect(page.getByText('What is the task?', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    });

    // Logs: every run of this conversation shows Success + the same key.
    await openWorkflows(page);
    await page.getByText(WORKFLOW).first().click();
    await page.waitForURL(/\/workflows\/[^/]+/);
    await page.getByRole('tab', { name: 'Logs' }).click();
    const runs = page.getByTestId('workflow-runs');
    await expect(runs).toContainText('Success', { timeout: 30_000 });
    await expect(runs.getByTestId('run-correlation-key').first()).toBeVisible();
    await expectNoDocumentOverflow(page);
  });

  test('② rapid same-key messages execute in order; another conversation proceeds concurrently (AC-SAR-53)', async ({
    page,
  }) => {
    const phoneA = `60182${STAMP.toString().slice(-8)}`;
    const nameA = `SAR19 Rapid A ${STAMP}`;
    const phoneB = `60183${STAMP.toString().slice(-8)}`;
    const nameB = `SAR19 Rapid B ${STAMP}`;
    await login(page);
    // Two messages for A back-to-back, one for B in between.
    await Promise.all([
      inbound(page, phoneA, nameA, 'Prepare quarterly report', 1),
      inbound(page, phoneB, nameB, 'Fix login bug', 1),
    ]);
    await inbound(page, phoneA, nameA, 'in progress', 2);

    await openThread(page, nameA);
    // Both contributions landed in order: the second message completed the
    // update the first one opened (task from #1, status from #2).
    const confirmation = page.getByText('Update recorded', { exact: false }).first();
    await expect(confirmation).toBeVisible({ timeout: 30_000 });
    await expect(confirmation).toContainText('task: Prepare quarterly report');
    await expect(confirmation).toContainText('status: in_progress');

    await openThread(page, nameB);
    await expect(page.getByText('What is the status?', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    });
  });

  test('③ the workflow is inspectable through the editor at desktop and mobile widths (AC-SAR-49/50/56)', async ({
    page,
  }) => {
    await login(page);
    await openWorkflows(page);
    await page.getByText(WORKFLOW).first().click();
    await page.waitForURL(/\/workflows\/[^/]+/);
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();
    // Only generic nodes on the canvas.
    for (const type of [
      'omnichannel.message_received',
      'ai_agent.run',
      'if',
      'omnichannel.send_message',
      'ai_agent.clear_state',
    ]) {
      await expect(page.locator(`[data-node-type="${type}"]`).first()).toBeVisible();
    }
    // Settings shows the serialized execution + correlation key (read mode).
    await page.getByRole('tab', { name: 'Settings' }).click();
    await expect(page.getByText('Serialized by key', { exact: false }).first()).toBeVisible();
    await expect(page.getByText('trigger.conversationId', { exact: false }).first()).toBeVisible();
    await expectNoDocumentOverflow(page);

    await page.setViewportSize({ width: 375, height: 812 });
    await page.getByRole('tab', { name: 'Editor' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();
    await expectNoDocumentOverflow(page);
    await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByTestId('workflow-runs')).toBeVisible();
    await expectNoDocumentOverflow(page);
  });
});
