import {
  expect,
  test,
  type APIRequestContext,
  type Locator,
  type Page,
} from '@playwright/test';

/** Sprint-4/18 — an isolated tenant exercises the editor's synthetic inbound
 * event through a stub AI Agent and a dev-sandbox send. API calls create only
 * prerequisites; every feature interaction and navigation is a real click. */

const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

interface Fixture {
  slug: string;
  adminEmail: string;
  adminPassword: string;
  workflowId: string;
  workflowName: string;
  contactName: string;
  channelName: string;
  expectedReplyPrefix: string;
}

interface AuthResponse {
  access_token: string;
}

interface IdResponse {
  id: string;
}

interface WorkspaceResponse {
  data: Array<{ id: string }>;
}

interface RunResponse {
  id: string;
}

function headers(token: string) {
  return { Authorization: `Bearer ${token}` };
}

async function token(
  request: APIRequestContext,
  email: string,
  password: string,
  slug?: string,
): Promise<string> {
  const response = await request.post(`${API}/auth/login`, {
    data: { email, password, ...(slug ? { tenantSlug: slug } : {}) },
  });
  expect(response.ok(), await response.text()).toBeTruthy();
  return ((await response.json()) as AuthResponse).access_token;
}

function inboundPayload(phone: string, contactName: string, message: string) {
  return {
    object: 'whatsapp_business_account',
    entry: [
      {
        id: 'waba-e2e',
        changes: [
          {
            field: 'messages',
            value: {
              messaging_product: 'whatsapp',
              contacts: [{ wa_id: phone, profile: { name: contactName } }],
              messages: [
                {
                  id: `wamid.oa18-setup-${Date.now()}`,
                  from: phone,
                  timestamp: String(Math.floor(Date.now() / 1000)),
                  type: 'text',
                  text: { body: message },
                },
              ],
            },
          },
        ],
      },
    ],
  };
}

async function provisionFixture(
  request: APIRequestContext,
  viewportName: string,
): Promise<Fixture> {
  const stamp = `${Date.now()}-${Math.floor(Math.random() * 10_000)}`;
  const slug = `e2e-oa18-${viewportName}-${stamp}`.slice(0, 62);
  const adminEmail = `admin-${slug}@example.com`;
  const adminPassword = 'E2eStart1!';
  const workflowName = `OA18 test flow ${viewportName} ${stamp}`;
  const channelName = `OA18 ${viewportName} sandbox`;
  const contactName = `OA18 ${viewportName} contact`;
  const expectedReplyPrefix = `OA18 ${viewportName} AI reply`;

  const platformToken = await token(
    request,
    'platform@example.com',
    'platform1234',
    'platform',
  );
  const provision = await request.post(`${API}/platform/tenants`, {
    headers: headers(platformToken),
    data: {
      name: `OA18 ${viewportName} ${stamp}`,
      slug,
      adminName: 'OA18 Admin',
      adminEmail,
      adminPassword,
    },
  });
  expect(provision.status(), await provision.text()).toBe(201);

  const adminToken = await token(request, adminEmail, adminPassword, slug);
  const auth = headers(adminToken);
  const install = await request.post(
    `${API}/app-store/modules/omnichannel/install`,
    {
      headers: auth,
    },
  );
  expect(install.ok(), await install.text()).toBeTruthy();

  const workspaces = await request.get(
    `${API}/omnichannel/workspaces?page_size=25`,
    {
      headers: auth,
    },
  );
  expect(workspaces.ok(), await workspaces.text()).toBeTruthy();
  const workspaceId = ((await workspaces.json()) as WorkspaceResponse).data[0]
    ?.id;
  expect(workspaceId).toBeTruthy();

  const channelResponse = await request.post(
    `${API}/omnichannel/onboarding/oauth-callback`,
    {
      headers: auth,
      data: {
        workspaceId,
        code: `dev-${stamp}`,
        wabaId: `waba-${stamp}`,
        phoneNumberId: `pn-${stamp}`,
        displayPhoneNumber: `+60${stamp.replace(/\D/g, '').slice(-9)}`,
        businessName: channelName,
      },
    },
  );
  expect(channelResponse.status(), await channelResponse.text()).toBe(201);
  const channelId = ((await channelResponse.json()) as IdResponse).id;

  const contactPhone = `6018${stamp.replace(/\D/g, '').slice(-7)}`;
  const setupInbound = await request.post(
    `${API}/omnichannel/webhooks/${channelId}`,
    {
      data: inboundPayload(
        contactPhone,
        contactName,
        'Sandbox contact setup message',
      ),
    },
  );
  expect(setupInbound.ok(), await setupInbound.text()).toBeTruthy();

  const agentResponse = await request.post(`${API}/ai/agents`, {
    headers: auth,
    data: {
      name: `OA18 Stub Agent ${stamp}`,
      description: '',
      connectionId: null,
      model: 'stub-model-1',
      temperature: 0,
      skillIds: [],
      isEnabled: true,
    },
  });
  expect(agentResponse.status(), await agentResponse.text()).toBe(201);
  const agentId = ((await agentResponse.json()) as IdResponse).id;

  const workflowResponse = await request.post(`${API}/workflows`, {
    headers: auth,
    data: {
      name: workflowName,
      description: 'Isolated editor test-trigger E2E.',
      draftDefinition: {
        schemaVersion: 1,
        nodes: [
          {
            id: 'trigger_inbound',
            kind: 'trigger',
            type: 'omnichannel.message_received',
            config: { channelId },
            position: { x: 0, y: 0 },
          },
          {
            id: 'ai_classify',
            kind: 'action',
            type: 'ai_agent.run',
            config: {
              agentId,
              instructions: 'Classify the customer message.',
              inputText: '{{ trigger.message.text }}',
              outputParams: [
                {
                  key: 'intent',
                  type: 'string',
                  description: 'Customer intent',
                  required: true,
                },
              ],
            },
            position: { x: 320, y: 0 },
          },
          {
            id: 'send_reply',
            kind: 'action',
            type: 'omnichannel.send_message',
            config: {
              contactId: '{{ trigger.contact.id }}',
              message: `${expectedReplyPrefix}: {{ nodes.ai_classify.intent }}`,
            },
            position: { x: 640, y: 0 },
          },
        ],
        edges: [
          {
            id: 'edge_1',
            source: 'trigger_inbound',
            target: 'ai_classify',
            sourcePort: 'out',
          },
          {
            id: 'edge_2',
            source: 'ai_classify',
            target: 'send_reply',
            sourcePort: 'out',
          },
        ],
      },
    },
  });
  expect(workflowResponse.status(), await workflowResponse.text()).toBe(201);
  const workflowId = ((await workflowResponse.json()) as IdResponse).id;

  const optionsDeadline = Date.now() + 20_000;
  let sourceReady = false;
  while (Date.now() < optionsDeadline) {
    const options = await request.get(
      `${API}/workflows/${workflowId}/test-options`,
      {
        headers: auth,
      },
    );
    if (options.ok()) {
      const body = (await options.json()) as {
        omnichannelTestSources: Array<{ contactName: string }>;
      };
      if (
        body.omnichannelTestSources.some(
          (source) => source.contactName === contactName,
        )
      ) {
        sourceReady = true;
        break;
      }
    }
    await new Promise((resolve) => setTimeout(resolve, 250));
  }
  expect(
    sourceReady,
    'sandbox contact should become available as workflow test data',
  ).toBe(true);

  return {
    slug,
    adminEmail,
    adminPassword,
    workflowId,
    workflowName,
    contactName,
    channelName,
    expectedReplyPrefix,
  };
}

async function login(page: Page, fixture: Fixture) {
  await page.goto(`http://${fixture.slug}.localhost:3001/signin`);
  await page.waitForLoadState('networkidle');
  await page.getByPlaceholder('Your email').fill(fixture.adminEmail);
  await page.getByPlaceholder('Your password').fill(fixture.adminPassword);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), {
    timeout: 30_000,
  });
}

async function navigation(page: Page, mobile: boolean): Promise<Locator> {
  if (!mobile) return page.locator('.sidebar');
  await page.getByRole('button', { name: 'Open navigation' }).click();
  const sheet = page.getByRole('dialog');
  await expect(sheet).toBeVisible();
  return sheet;
}

async function openMenuDestination(
  page: Page,
  mobile: boolean,
  section: string,
  path: string,
) {
  const menu = await navigation(page, mobile);
  const destinationLink = menu.locator(`a[href="${path}"]`);
  if (!(await destinationLink.isVisible().catch(() => false))) {
    const sectionButton = menu.getByRole('button', {
      name: section,
      exact: true,
    });
    await expect(sectionButton).toHaveCount(1);
    if (mobile) await sectionButton.press('Enter');
    else await sectionButton.click();
  }
  await expect(destinationLink).toBeVisible();
  if (mobile) await destinationLink.press('Enter');
  else await destinationLink.click();
}

async function expectNoDocumentOverflow(page: Page) {
  expect(
    await page.evaluate(
      () =>
        document.documentElement.scrollWidth <=
        document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

for (const viewport of [
  { name: 'desktop', width: 1280, height: 800, mobile: false },
  { name: 'mobile', width: 375, height: 812, mobile: true },
]) {
  test(`${viewport.name}: editor test data → stub AI → sandbox reply`, async ({
    page,
    request,
  }) => {
    const fixture = await provisionFixture(request, viewport.name);
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await login(page, fixture);

    await openMenuDestination(page, viewport.mobile, 'Workflows', '/workflows');
    await expect(page).toHaveURL(/\/workflows$/);
    const workflowRow = page
      .getByRole('row')
      .filter({ hasText: fixture.workflowName });
    await expect(workflowRow).toHaveCount(1);
    await workflowRow.click();
    await page.waitForURL(new RegExp(`/workflows/${fixture.workflowId}`));
    await page.getByRole('tab', { name: 'Editor' }).click();
    await page.getByTestId('workflow-run').click();

    await expect(
      page.getByRole('heading', { name: 'Test workflow' }),
    ).toBeVisible();
    await expect(page.getByRole('combobox', { name: 'Channel' })).toContainText(
      fixture.channelName,
    );
    await page.getByRole('combobox', { name: 'Contact' }).click();
    const contactOption = page
      .getByRole('option')
      .filter({ hasText: fixture.contactName });
    await expect(contactOption).toHaveCount(1);
    await contactOption.click();
    await page
      .getByLabel('Message')
      .fill(`Please classify my Saturday booking request — ${viewport.name}`);
    await expect(page.getByTestId('test-side-effects-warning')).toContainText(
      'call the configured AI model and send a message',
    );
    await expectNoDocumentOverflow(page);

    const runResponsePromise = page.waitForResponse((response) => {
      const request = response.request();
      return (
        request.method() === 'POST' &&
        new URL(response.url()).pathname.endsWith(
          `/workflows/${fixture.workflowId}/run`,
        )
      );
    });
    await page.getByTestId('run-dialog-submit').click();
    const runResponse = await runResponsePromise;
    expect(runResponse.ok(), await runResponse.text()).toBeTruthy();
    const runId = ((await runResponse.json()) as RunResponse).id;

    await page.getByRole('tab', { name: 'Logs' }).click();
    const runRow = page.getByTestId(`run-row-${runId}`);
    await expect(runRow).toContainText('Success', { timeout: 30_000 });
    await runRow.click();
    await expect(page.getByTestId('run-replay')).toContainText(
      'draft · event · test',
    );
    await expectNoDocumentOverflow(page);

    await openMenuDestination(
      page,
      viewport.mobile,
      'Omnichannel',
      '/omnichannel/inbox',
    );
    await expect(page).toHaveURL(/\/omnichannel\/inbox$/);
    const thread = page.getByTestId('thread-list').getByRole('button', {
      name: new RegExp(fixture.contactName),
    });
    await expect(thread).toHaveCount(1);
    await thread.click();
    const sandboxReply = page
      .getByTestId('bubble-agent')
      .filter({ hasText: fixture.expectedReplyPrefix });
    await expect(sandboxReply).toHaveCount(1, { timeout: 30_000 });
    await expect(sandboxReply).toBeVisible();
    await expectNoDocumentOverflow(page);
  });
}
