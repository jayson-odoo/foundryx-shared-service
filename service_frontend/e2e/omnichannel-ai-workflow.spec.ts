import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Plan sprint-4/17 - omnichannel × AI Agent workflow nodes (AC-OA-22/23),
 * against the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Real clicks.
 *
 * Journey ① (AC-OA-22) runs on the DEFAULT tenant: the dev-seeded demo
 * workflow ("Demo: classify & reply", seeded by `seed_demo_ai_workflow` when
 * ENVIRONMENT=development) fires on an inbound webhook to the sandbox channel
 * `chn-demo`; the AI Agent node classifies via the stub LLM (no key needed)
 * and the reply lands in the conversation. Isolation: the inbound uses a
 * UNIQUE timestamped phone, so a NEW contact/thread is created - assertions
 * scope to it and never touch the seeded cnt-001..005 threads.
 *
 * Journey ② (AC-OA-23) provisions a DEDICATED tenant (spec-isolation rule),
 * installs omnichannel + creates an AI agent via API (setup), then builds the
 * whole workflow through real palette/drawer clicks and publishes it.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-oa17-${STAMP}`;
const ADMIN_EMAIL = `admin-oa17-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function token(
  request: APIRequestContext,
  email: string,
  password: string,
  slug?: string,
): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email, password, ...(slug ? { tenantSlug: slug } : {}) },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).access_token;
}

async function login(page: Page, email: string, password: string, base?: string) {
  await page.goto(base ? `${base}/signin` : '/signin');
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

function inboundPayload(phone: string, text: string) {
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
              contacts: [{ wa_id: phone, profile: { name: 'OA17 E2E' } }],
              messages: [
                {
                  id: `wamid.oa17-${Date.now()}`,
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

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Omnichannel × AI Agent workflow (plan sprint-4/17)', () => {
  test('① inbound demo message → seeded AI workflow run → reply in the thread (AC-OA-22)', async ({
    page,
    request,
  }) => {
    // Unique contact so parallel specs / seeded threads are untouched.
    const phone = `60177${STAMP.toString().slice(-8)}`;

    // Deliver the inbound via the dev webhook-simulation path (fast-ACK +
    // eager inline processing → the seeded workflow runs synchronously).
    const whRes = await request.post(`${API}/omnichannel/webhooks/chn-demo`, {
      data: inboundPayload(phone, 'My booking needs to move to Saturday, please help'),
    });
    expect(whRes.ok(), await whRes.text()).toBeTruthy();

    // The run shows SUCCESS in the demo workflow's Logs tab (real clicks from
    // the workflows list - users don't know ids).
    await login(page, 'demo@example.com', 'demo1234');
    await page.goto('/workflows');
    await page.getByText('Demo: classify & reply').first().click();
    await page.waitForURL(/\/workflows\/[^/]+/);
    await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByTestId('workflow-runs')).toContainText('Success', { timeout: 30_000 });

    // The reply bubble landed in the NEW contact's conversation.
    await page.goto('/omnichannel/inbox');
    await page.getByText('OA17 E2E', { exact: false }).first().click();
    await expect(page.getByText('logged this as', { exact: false }).first()).toBeVisible({
      timeout: 30_000,
    });
  });

  test('② build trigger → AI Agent → Send Message via real clicks and publish (AC-OA-23)', async ({
    page,
    request,
  }) => {
    // Dedicated tenant + omnichannel install + an AI agent (API setup; the
    // flow under test - building the workflow - is real clicks).
    const platformToken = await token(request, 'platform@example.com', 'platform1234', 'platform');
    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E OA17 ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status(), await provision.text()).toBe(201);

    const adminToken = await token(request, ADMIN_EMAIL, ADMIN_PASSWORD, SLUG);
    const auth = { Authorization: `Bearer ${adminToken}` };
    const install = await request.post(`${API}/app-store/modules/omnichannel/install`, {
      headers: auth,
    });
    expect(install.ok(), await install.text()).toBeTruthy();
    const agentRes = await request.post(`${API}/ai/agents`, {
      headers: auth,
      data: { name: `Classifier ${STAMP}`, description: '', model: 'stub-model-1' },
    });
    expect(agentRes.ok(), await agentRes.text()).toBeTruthy();

    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD, `http://${SLUG}.localhost:3001`);

    // Create a workflow through the UI.
    await page.goto(tenantUrl('/workflows'));
    await page.getByRole('button', { name: /new workflow/i }).click();
    await page.getByLabel(/name/i).first().fill(`OA17 flow ${STAMP}`);
    await page.getByRole('button', { name: /^(Save|Create)$/ }).first().click();
    await page.waitForURL(/\/workflows\/(?!new)[^/]+/, { timeout: 30_000 });

    // Enter edit mode, then click-to-add the three nodes from the palette.
    await page.getByRole('button', { name: /^Edit$/ }).click();
    await page.getByTestId('palette-search').fill('omnichannel');
    await page.getByTestId('palette-omnichannel.message_received').click();
    await page.getByTestId('palette-search').fill('AI Agent');
    await page.getByTestId('palette-ai_agent.run').click();
    await page.getByTestId('palette-search').fill('Send Message');
    await page.getByTestId('palette-omnichannel.send_message').click();

    // Configure the AI Agent node: pick the agent, instructions, input, params.
    await page.locator('[data-node-type="ai_agent.run"]').click();
    await page.getByLabel('Agent').click();
    await page.getByText(`Classifier ${STAMP}`, { exact: false }).first().click();
    await page.getByLabel('Instructions').fill('Classify the message intent.');
    await page.getByLabel('Message', { exact: true }).fill('{{ trigger.message.text }}');
    await page.getByTestId('add-output-param').click();
    await page.getByLabel('Parameter 1 key').fill('intent');

    // Configure Send Message: contact ref + a message referencing the AI output.
    await page.locator('[data-node-type="omnichannel.send_message"]').click();
    await page.getByLabel('Contact').fill('{{ trigger.contact.id }}');
    await page.getByLabel('Message', { exact: true }).fill('Classified.');

    // Wire trigger → AI → send (React Flow handle drags via page.mouse are
    // driven by the shared connect helper pattern; nodes target by testid).
    // The canvas connect helper lives in the slice-09 spec - reuse its approach.
    const canvas = page.getByTestId('flow-canvas');
    await expect(canvas).toBeVisible();
    const connect = async (fromType: string, toType: string) => {
      const from = page.locator(`[data-node-type="${fromType}"] .react-flow__handle-bottom`).first();
      const to = page.locator(`[data-node-type="${toType}"] .react-flow__handle-top`).first();
      const fb = await from.boundingBox();
      const tb = await to.boundingBox();
      if (!fb || !tb) throw new Error('handle not visible');
      await page.mouse.move(fb.x + fb.width / 2, fb.y + fb.height / 2);
      await page.mouse.down();
      await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2, { steps: 12 });
      await page.mouse.up();
    };
    await connect('omnichannel.message_received', 'ai_agent.run');
    await connect('ai_agent.run', 'omnichannel.send_message');

    // Publish - the validator passes (trigger + required config + wired graph).
    await page.getByRole('button', { name: /^Save$/ }).click();
    await page.getByRole('button', { name: /publish/i }).click();
    await expect(page.getByText(/published|version 1/i).first()).toBeVisible({ timeout: 30_000 });
  });
});
