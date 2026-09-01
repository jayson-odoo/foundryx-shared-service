import { expect, test, type Page } from '@playwright/test';

/**
 * Plan sprint-3/02 Phase C - Form engine slice 2, full stack (real clicks).
 *
 * Journeys (plan §TDD E2E ⑤/⑥):
 *   ⑤ Open the form's PUBLIC link logged-out on the tenant subdomain → fill +
 *     submit anonymously → success state. (The honeypot is injected at render;
 *     a real user never fills it.)
 *   ⑥ A workflow with a `form.submitted` trigger + `email.send` using
 *     `trigger.answers.*` fires → a run appears in the workflow's Logs, and the
 *     confirmation mail (merged subject) lands in the Email log.
 *
 * Setup is operator/admin API (deterministic - the builder + workflow editor
 * are real-click-covered by slice 1 / the workflow specs; dnd-kit drags aren't
 * Playwright-drivable). Dedicated tenant; names timestamped (methodology §7).
 * The fill runs in a logged-OUT context (the public surface needs no auth).
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const STAMP = Date.now();
const SLUG = `e2e-pubwf-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@e2e.com`;
const ADMIN_PASSWORD = 'E2eStart1!';

let formSlug = '';
let formId = '';
let workflowId = '';

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Form engine slice 2 - public surface + form.submitted (Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const plat = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    const platToken = (await plat.json()).access_token;
    const prov = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platToken}` },
      data: { name: `E2E PubWF ${STAMP}`, slug: SLUG, adminName: 'Admin', adminEmail: ADMIN_EMAIL, adminPassword: ADMIN_PASSWORD },
    });
    expect(prov.status()).toBe(201);

    const login = await request.post(`${API}/auth/login`, {
      data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG },
    });
    const token = (await login.json()).access_token;
    const auth = { Authorization: `Bearer ${token}` };

    // A published PUBLIC form (name + email).
    const form = await (await request.post(`${API}/forms`, { headers: auth, data: { name: 'Community Signup', access: 'public' } })).json();
    formId = form.id;
    formSlug = form.slug;
    const doc = {
      schemaVersion: 1,
      pages: [{ id: 'p1', title: 'Signup', sections: [{ id: 's1', fields: [
        { id: 'f1', type: 'text', key: 'name', label: 'Full name', required: true },
        { id: 'f2', type: 'email', key: 'email', label: 'Email', required: true },
      ] }] }],
    };
    await request.patch(`${API}/forms/${formId}`, { headers: auth, data: { draftDefinition: doc } });
    expect((await request.post(`${API}/forms/${formId}/publish`, { headers: auth })).status()).toBe(200);

    // A form.submitted workflow → email.send merging trigger.answers.*.
    const wdoc = {
      schemaVersion: 1,
      nodes: [
        { id: 'trg', kind: 'trigger', type: 'form.submitted', config: { formId }, position: { x: 0, y: 0 } },
        { id: 'a', kind: 'action', type: 'email.send', config: { mode: 'custom', to: '{{ trigger.answers.email }}', subject: 'Welcome {{ trigger.answers.name }}', body: 'Thanks!', name: 'Confirm' }, position: { x: 0, y: 120 } },
      ],
      edges: [{ id: 'e', source: 'trg', target: 'a', sourcePort: 'out' }],
    };
    const wf = await (await request.post(`${API}/workflows`, { headers: auth, data: { name: 'Signup Confirm', description: '', draftDefinition: wdoc } })).json();
    workflowId = wf.id;
    await request.post(`${API}/workflows/${workflowId}/publish`, { headers: auth });
    await request.post(`${API}/workflows/${workflowId}/active`, { headers: auth, data: { isActive: true } });
  });

  // ⑤ - anonymous, logged OUT.
  test.describe('anonymous public fill', () => {
    test.use({ storageState: { cookies: [], origins: [] } });

    test('⑤ fills + submits the public form logged-out → success', async ({ page }) => {
      await page.goto(tenantUrl(`/public/forms/${formSlug}`));
      await expect(page.getByRole('heading', { name: 'Community Signup' })).toBeVisible();
      await page.getByRole('textbox', { name: 'Full name' }).fill('Ada Lovelace');
      await page.getByRole('textbox', { name: 'Email' }).fill('ada@example.com');
      await page.getByRole('button', { name: 'Submit' }).click();
      await expect(page.getByTestId('fill-success')).toBeVisible();
    });
  });

  // ⑥ - the trigger fired; verify the run in Logs + the merged mail in the Email log.
  test('⑥ form.submitted workflow ran and the merged confirmation mail is enqueued', async ({ page, request }) => {
    await login(page);

    await page.goto(tenantUrl(`/workflows/${workflowId}`));
    await page.getByRole('tab', { name: 'Logs' }).click();
    await expect(page.getByText(/success/i).first()).toBeVisible();

    // The merged confirmation mail landed in the Email log (subject carries the name).
    const login2 = await request.post(`${API}/auth/login`, { data: { email: ADMIN_EMAIL, password: ADMIN_PASSWORD, tenantSlug: SLUG } });
    const token = (await login2.json()).access_token;
    const emails = await (await request.get(`${API}/emails?page=0&page_size=10`, { headers: { Authorization: `Bearer ${token}` } })).json();
    const mine = emails.data.find((m: { toEmail: string }) => m.toEmail === 'ada@example.com');
    expect(mine?.subject).toBe('Welcome Ada Lovelace');
  });
});

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}
