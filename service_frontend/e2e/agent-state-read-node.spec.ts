import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Plan sprint-4/20 - read-only "Read Agent State" workflow node
 * (`ai_agent.read_state`), against the LIVE stack (Next :3001 → FastAPI :8001
 * → Postgres). Real clicks for every product surface.
 *
 * Isolation (methodology §7): building + publishing + running a workflow
 * mutates tenant state, so the whole journey runs on a DEDICATED tenant
 * provisioned via the operator API (setup only - the flow under test, the
 * workflow build itself, stays real clicks). Every created name/tenant slug
 * is timestamped.
 *
 * Journey: a manual-triggered, serialized workflow with a stateful `ai_agent.run`
 * node (stub LLM, no key needed) feeds a `Read Agent State` node, which feeds
 * an IF node routing on `nodes.<readNode>.exists`, which feeds a Send email
 * node whose body is populated via the dynamic-content picker from the read
 * node's accumulated `task` field. Covers AC-ASR-01/02/03/10/12/13 (+14 by
 * inspection - no instructional copy on the node's catalog description).
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-asr20-${STAMP}`;
const ADMIN_EMAIL = `admin-asr20-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const WF_NAME = `Read agent state ${STAMP}`;
const SESSION_KEY = `asr20-${STAMP}`;
const TASK_MESSAGE = 'Launch the landing page';
const TO_ADDRESS = 'read-agent-e2e@example.com';

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

async function login(page: Page, email: string, password: string) {
  await page.goto(tenantUrl('/signin'));
  await page.waitForLoadState('networkidle');
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  const submit = page.getByRole('button', { name: /sign in/i });
  await expect(submit).toBeEnabled({ timeout: 30_000 });
  await submit.click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), { timeout: 30_000 });
}

async function openWorkflows(page: Page) {
  // The sidebar's "Workflows" heading and its "All workflows" child link both
  // render via the terminology plural for `workflow` ("Workflows" by default,
  // no override on this fresh tenant), so both share the accessible name
  // "Workflows" - disambiguate the child anchor by its href.
  const link = page.locator('a[href="/workflows"]').first();
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: 'Workflows', exact: true }).first().click();
    await expect(link).toBeVisible();
  }
  await link.click();
  await page.waitForURL(/\/workflows$/);
}

/** Palette sections are collapsed by default - search surfaces the item. */
async function addNode(page: Page, term: string, type: string) {
  await page.getByTestId('palette-search').fill(term);
  await expect(page.getByTestId(`palette-${type}`)).toBeVisible();
  await page.getByTestId(`palette-${type}`).click();
  await page.getByTestId('palette-search').fill('');
  // Newly dropped nodes can land outside the visible viewport - Fit View
  // before any handle-drag so bounding boxes are accurate; the fit is
  // CSS-animated (300ms), so settle before reading positions.
  await page.getByRole('button', { name: /fit view/i }).click();
  await page.waitForTimeout(400);
}

/** Wire a source handle to a target handle, retrying the drag once if React
 * Flow didn't register an edge (canvas pan/zoom settle timing is flaky). */
async function connectHandles(
  page: Page,
  fromSelector: string,
  toType: string,
  expectedEdgeCount: number,
) {
  const from = page.locator(fromSelector).first();
  const to = page.locator(`[data-node-type="${toType}"] [data-testid="target-handle"]`).first();
  const drag = async () => {
    await from.scrollIntoViewIfNeeded();
    await to.scrollIntoViewIfNeeded();
    const fb = (await from.boundingBox())!;
    const tb = (await to.boundingBox())!;
    await page.mouse.move(fb.x + fb.width / 2, fb.y + fb.height / 2);
    await page.mouse.move(fb.x + fb.width / 2, fb.y + fb.height / 2);
    await page.mouse.down();
    await page.mouse.move(fb.x + fb.width / 2 + 5, fb.y + fb.height / 2 + 5, { steps: 3 });
    await page.mouse.move(tb.x + tb.width / 2, tb.y + tb.height / 2, { steps: 12 });
    await page.mouse.up();
  };
  await drag();
  try {
    await expect(page.locator('.react-flow__edge')).toHaveCount(expectedEdgeCount, {
      timeout: 3_000,
    });
  } catch {
    await drag();
    await expect(page.locator('.react-flow__edge')).toHaveCount(expectedEdgeCount, {
      timeout: 5_000,
    });
  }
}

/** Wire one node's (single) source handle to another's target handle. */
async function connect(page: Page, fromType: string, toType: string, expectedEdgeCount: number) {
  await connectHandles(
    page,
    `[data-node-type="${fromType}"] [data-testid="source-handle"]`,
    toType,
    expectedEdgeCount,
  );
}

/** Wire an IF node's TRUE port to another node's target handle. */
async function connectIfTrue(page: Page, toType: string, expectedEdgeCount: number) {
  await connectHandles(
    page,
    '[data-node-type="if"] [data-testid="source-handle-true"]',
    toType,
    expectedEdgeCount,
  );
}

async function expectNoDocumentOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Read Agent State workflow node (plan sprint-4/20)', () => {
  test.beforeAll(async ({ request }) => {
    const platformToken = await token(request, 'platform@example.com', 'platform1234', 'platform');
    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E ASR20 ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status(), await provision.text()).toBe(201);

    const adminToken = await token(request, ADMIN_EMAIL, ADMIN_PASSWORD, SLUG);
    // A connection-less agent only stubs when NOTHING is configured anywhere
    // (tenant OR platform) - this environment carries a real platform LLM
    // connection (ideation's grill key), so bind the agent to a dev-flagged
    // connection (`credentials.dev`) to force the deterministic stub with no
    // real key (mirrors the seeded demo workflow's stub-connection pattern).
    const connRes = await request.post(`${API}/integrations/connections`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: {
        provider: 'gemini',
        name: `E2E stub LLM ${STAMP}`,
        config: {},
        credentials: { apiKey: 'e2e-dummy', dev: 'true' },
      },
    });
    expect(connRes.ok(), await connRes.text()).toBeTruthy();
    const connectionId = (await connRes.json()).id;

    const agentRes = await request.post(`${API}/ai/agents`, {
      headers: { Authorization: `Bearer ${adminToken}` },
      data: { name: `Tracker ${STAMP}`, description: '', model: 'stub-model-1', connectionId },
    });
    expect(agentRes.ok(), await agentRes.text()).toBeTruthy();
  });

  test('build → publish → run: Read Agent State exposes accumulated fields and an IF routes on them (AC-ASR-01/02/03/10/12/13)', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    await openWorkflows(page);
    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();

    // ---- Manual trigger with 2 run inputs ----
    await addNode(page, 'manual', 'manual');
    await page.locator('[data-node-type="manual"]').click();
    await page.getByTestId('add-manual-input').click();
    await page.getByLabel('Input 1 key').fill('sessionId');
    await page.getByLabel('Input 1 label').fill('Session');
    await page.getByTestId('add-manual-input').click();
    await page.getByLabel('Input 2 key').fill('message');
    await page.getByLabel('Input 2 label').fill('Message');

    // ---- AC-ASR-01: the palette lists "Read Agent State" (core, Actions) ----
    // Add it now, unwired - it has no upstream agent yet.
    await addNode(page, 'Read Agent State', 'ai_agent.read_state');
    await expect(page.locator('[data-node-type="ai_agent.read_state"]')).toBeVisible();

    // ---- AC-ASR-02 (empty case): no structural ancestor -> empty picker,
    // never a free-text id (the field is a picker, not an Input). ----
    await page.locator('[data-node-type="ai_agent.read_state"]').click();
    const agentPicker = page.getByRole('combobox', { name: 'Agent' });
    await agentPicker.click();
    await expect(page.getByRole('option')).toHaveCount(0);
    await expect(page.getByText('No matches.')).toBeVisible();
    await page.keyboard.press('Escape');

    // ---- Stateful AI Agent node, wired from the trigger ----
    await addNode(page, 'AI Agent', 'ai_agent.run');
    await connect(page, 'manual', 'ai_agent.run', 1);

    await page.locator('[data-node-type="ai_agent.run"]').click();
    await page.getByRole('combobox', { name: 'Agent' }).click();
    await page.getByText(`Tracker ${STAMP}`, { exact: false }).first().click();
    await page.getByLabel('Instructions').fill('Track the reported task.');
    await page.getByLabel('Message', { exact: true }).fill('{{ trigger.input.message }}');
    await page.getByTestId('add-output-param').click();
    await page.getByLabel('Parameter 1 key').fill('task');
    await expect(page.getByLabel('Parameter 1 required')).toBeChecked();
    await page.getByLabel('Parameter 1 stateful').check();

    // ---- Wire the AI Agent into Read Agent State ----
    await connect(page, 'ai_agent.run', 'ai_agent.read_state', 2);

    // Node ids (from the canvas card's own testid) so the "task" output can be
    // told apart from the AI Agent node's OWN "task" output further upstream
    // (both legitimately expose a key named "task" - one node apart).
    const readTestId = await page
      .locator('[data-node-type="ai_agent.read_state"]')
      .getAttribute('data-testid');
    const readNodeId = readTestId?.replace('workflow-node-', '');
    if (!readNodeId) throw new Error('Read Agent State node id missing');

    // ---- AC-ASR-02 (positive case): the picker now lists the upstream
    // stateful agent, and selecting it is possible. ----
    await page.locator('[data-node-type="ai_agent.read_state"]').click();
    await page.getByRole('combobox', { name: 'Agent' }).click();
    await expect(page.getByRole('option', { name: 'AI Agent' })).toBeVisible();
    await page.getByRole('option', { name: 'AI Agent' }).click();

    // ---- IF node routing on nodes.<readNode>.exists ----
    await addNode(page, 'condition', 'if');
    await connect(page, 'ai_agent.read_state', 'if', 3);

    await page.locator('[data-node-type="if"]').click();
    await expect(page.getByTestId('if-conditions')).toBeVisible();
    await page.getByRole('button', { name: /add condition/i }).click();
    await page.getByRole('combobox', { name: 'Fact' }).click();
    await page.getByPlaceholder('Search fields…').fill('exists');
    // AC-ASR-03: the read node's reserved diagnostic is exposed as a fact.
    await expect(page.getByRole('option', { name: 'State exists' })).toBeVisible();
    await page.getByRole('option', { name: 'State exists' }).click();
    await expect(page.getByRole('combobox', { name: 'Operator' })).toHaveText(/is yes/);

    // ---- Send email (custom) as the TRUE branch, body from the dynamic-
    // content picker (AC-ASR-03: nodes.<readNode>.task is now offered). ----
    await addNode(page, 'send email', 'email.send');
    await connectIfTrue(page, 'email.send', 4);

    await page.locator('[data-node-type="email.send"]').click();
    await page.locator('button[aria-label="Email type"]').click();
    await page.getByRole('option', { name: 'Write a custom email' }).click();
    await page.getByLabel('Subject').fill('Read Agent State result');
    await page.getByLabel('To', { exact: true }).fill(TO_ADDRESS);
    const bodyField = page.getByLabel('Body');
    await bodyField.fill('Recorded task: ');
    const dynamicTrigger = bodyField.locator('..').getByTestId('dynamic-content-trigger');
    await expect(dynamicTrigger).toHaveCount(1);
    await dynamicTrigger.click();
    // The AI Agent node ALSO exposes a "task" output of its own (transient,
    // one node closer) - target the READ node's copy specifically by id.
    const taskPath = `nodes.${readNodeId}.task`;
    const taskItem = page.getByTestId(`dynamic-content-${taskPath}`);
    await expect(taskItem).toHaveCount(1);
    await taskItem.click();
    await expect(bodyField).toHaveValue(new RegExp(`\\{\\{ ${taskPath} \\}\\}`));

    // ---- Settings: name, serialized execution keyed by the manual input ----
    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByLabel('Workflow name').fill(WF_NAME);
    await page.getByRole('combobox', { name: 'Execution mode' }).click();
    await page.getByRole('option', { name: 'Serialized by key' }).click();
    await page.getByLabel('Correlation key').fill('{{ trigger.input.sessionId }}');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    const saveToast = page.locator('[data-sonner-toast]').first();
    if (await saveToast.isVisible({ timeout: 5_000 }).catch(() => false)) {
      const toastText = await saveToast.innerText().catch(() => '');
      if (/fail|required|error/i.test(toastText)) {
        throw new Error(`Save was rejected: ${toastText}`);
      }
    }
    // Match a real created id, never the literal "new" segment (a loose
    // `[^/]+` would trivially "match" the pre-save URL and race ahead).
    await page.waitForURL(/\/workflows\/(?!new)[^/?]+/, { timeout: 30_000 });

    // ---- Publish succeeds with a valid Read Agent State selection
    // (AC-ASR-10 happy path; the reject path is covered by BE/FE unit tests) ----
    await page.getByRole('tab', { name: 'Editor' }).click();
    await expect(page.getByTestId('workflow-publish')).toBeVisible({ timeout: 15_000 });
    await page.getByTestId('workflow-publish').click();
    await expect(page.getByTestId('unpublished-badge')).toHaveCount(0);
    await page.getByRole('tab', { name: 'Settings' }).click();
    await expect(page.getByTestId('current-version')).toContainText('v1');

    // ---- Run it ----
    await page.getByRole('tab', { name: 'Editor' }).click();
    await page.getByTestId('workflow-run').click();
    await page.getByTestId('run-input-sessionId').fill(SESSION_KEY);
    await page.getByTestId('run-input-message').fill(TASK_MESSAGE);
    await page.getByTestId('run-dialog-submit').click();

    // ---- Logs: success, correlation key, and the read node's output
    // (accepted fields + diagnostics) inspectable (AC-ASR-12) ----
    await page.getByRole('tab', { name: 'Logs' }).click();
    const runs = page.getByTestId('workflow-runs');
    await expect(runs).toContainText('Success', { timeout: 30_000 });
    await expect(page.getByTestId('run-correlation-key')).toContainText(SESSION_KEY);

    await page.locator('[data-node-type="ai_agent.read_state"]').click();
    const inspector = page.getByTestId('node-inspector');
    await expect(inspector).toBeVisible();
    await expect(inspector).toContainText('"task"');
    await expect(inspector).toContainText(TASK_MESSAGE);
    await expect(inspector).toContainText('"exists": true');
    await expect(inspector).toContainText('"stateRevision"');

    // ---- The IF routed to the TRUE branch: the Send email node executed
    // (AC-ASR-13 "routes correctly") ----
    await page.locator('[data-node-type="email.send"]').click();
    await expect(page.getByTestId('node-inspector')).toContainText(/success/i);

    await expectNoDocumentOverflow(page);

    // ---- Verify at mobile width too (AC-ASR-13) ----
    await page.setViewportSize({ width: 375, height: 812 });
    await page.getByRole('tab', { name: 'Editor' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();
    await expectNoDocumentOverflow(page);
    await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByTestId('workflow-runs')).toBeVisible();
    await expectNoDocumentOverflow(page);
  });
});
