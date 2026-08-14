import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Plan sprint-2/09 Phase C - triggers/actions, full stack (real clicks).
 *
 * The flow under test is "a real domain event fires a published workflow → a
 * run appears in Logs". The WORKFLOW is built via the API (setup, like the
 * tenant provisioning); the TRIGGERING action - creating a Role in the UI - is
 * real clicks, as is the Logs assertion.
 *
 * Preconditions: frontend :3001 + backend :8001 on the plan-09 branch, migrated
 * + seeded. The dev backend runs Celery eager, so event runs execute inline.
 *
 * Isolation (methodology §7): a DEDICATED tenant per run; names timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';

const STAMP = Date.now();
const SLUG = `e2e-wf09-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const WF_NAME = `Role notifier ${STAMP}`;

let workflowId = '';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function token(request: APIRequestContext, email: string, password: string, slug?: string): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email, password, ...(slug ? { tenantSlug: slug } : {}) },
  });
  expect(res.ok(), await res.text()).toBeTruthy();
  return (await res.json()).access_token;
}

async function login(page: Page, email: string, password: string) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(email);
  await page.getByPlaceholder('Your password').fill(password);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

/** entity.created(role) → IF(always true) → email.send(custom). */
function roleWorkflowDoc() {
  return {
    schemaVersion: 1,
    nodes: [
      { id: 'trg', kind: 'trigger', type: 'entity.created', config: { entityType: 'role', name: 'Role created' }, position: { x: 0, y: 0 } },
      { id: 'cond', kind: 'if', type: 'if', config: { conditions: null, name: 'Always' }, position: { x: 0, y: 120 } },
      { id: 'mail', kind: 'action', type: 'email.send', config: { mode: 'custom', to: 'e2e@example.com', subject: 'New role {{ trigger.record.name }}', body: 'A role was created.', name: 'Notify' }, position: { x: 0, y: 240 } },
    ],
    edges: [
      { id: 'e1', source: 'trg', target: 'cond', sourcePort: 'out' },
      { id: 'e2', source: 'cond', target: 'mail', sourcePort: 'true' },
    ],
  };
}

test.describe.configure({ mode: 'serial', timeout: 120_000 });

test.describe('Workflow triggers - live stack (plan sprint-2/09 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    // Dedicated tenant via the operator API.
    const platformToken = await token(request, 'platform@example.com', 'platform1234', 'platform');
    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: { name: `E2E WF09 ${STAMP}`, slug: SLUG, adminName: 'E2E Admin', adminEmail: ADMIN_EMAIL, adminPassword: ADMIN_PASSWORD },
    });
    expect(provision.status(), await provision.text()).toBe(201);

    // Build + publish + activate the event workflow via the tenant admin API.
    const adminToken = await token(request, ADMIN_EMAIL, ADMIN_PASSWORD, SLUG);
    const auth = { Authorization: `Bearer ${adminToken}` };
    const created = await request.post(`${API}/workflows`, {
      headers: auth,
      data: { name: WF_NAME, description: 'Event-triggered', draftDefinition: roleWorkflowDoc() },
    });
    expect(created.ok(), await created.text()).toBeTruthy();
    workflowId = (await created.json()).id;

    const published = await request.post(`${API}/workflows/${workflowId}/publish`, { headers: auth });
    expect(published.ok(), await published.text()).toBeTruthy();
    const activated = await request.post(`${API}/workflows/${workflowId}/active`, { headers: auth, data: { isActive: true } });
    expect(activated.ok(), await activated.text()).toBeTruthy();
  });

  test('creating a role fires the entity.created workflow → run in Logs', async ({ page }) => {
    await login(page, ADMIN_EMAIL, ADMIN_PASSWORD);

    // Real clicks: create a Role (fires role.created → matches the workflow).
    await page.goto(tenantUrl('/user-management/roles/new'));
    await page.getByPlaceholder('e.g. Event Manager').fill(`E2E Role ${STAMP}`);
    await page.getByPlaceholder('e.g. Event Manager').blur();
    await page.getByRole('button', { name: /^(Save|Create)$/ }).first().click();
    // Save must navigate AWAY from /new to the created role's detail.
    await page.waitForURL(/\/user-management\/roles\/(?!new)[^/]+/, { timeout: 30_000 });

    // The event run executed inline - it shows in the workflow's Logs.
    await page.goto(tenantUrl(`/workflows/${workflowId}`));
    await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByTestId('workflow-runs')).toContainText('Success', { timeout: 30_000 });

    // Open the run → the email action ran on the IF true branch.
    await page.getByTestId('workflow-runs').getByText('Success').first().click();
    await expect(page.getByTestId('flow-canvas')).toBeVisible();
  });
});
