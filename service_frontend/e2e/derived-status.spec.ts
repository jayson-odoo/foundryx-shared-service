import { expect, test, type Page } from '@playwright/test';

/**
 * Sprint-4/03 Phase C — Derived / computed status, full stack (real clicks).
 *
 * Journey (plan slice 3 E2E): on a form's OWN scoped status graph, open the
 * seeded Submit edge → switch its Trigger to Automatic → the role gate
 * disappears (system-fired) and Conditions become required → saving with no
 * condition is blocked → add a condition + save → the canvas renders the edge
 * as an AUTO edge (⚡ prefix) → reopening shows Automatic with the role gate
 * still hidden → switching back to Manual restores the role gate.
 *
 * Isolation (methodology §7): scoped-graph edits mutate tenant state → a
 * DEDICATED tenant via the operator API (setup only); names timestamped.
 *
 * NOTE: a true derived AUTO-ADVANCE (child change → owner re-evaluates) needs a
 * domain consumer with aggregate facts (Cluster D/F) and is proven in the
 * backend suite (tests/test_status_engine.py); this E2E covers the authoring
 * UX + canvas rendering that live in the app today.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const HOST = process.env.E2E_HOST ?? 'localhost:3001';

const STAMP = Date.now();
const SLUG = `e2e-derived-${STAMP}`;
const ADMIN_EMAIL = `admin-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const FORM_NAME = `Derived Flow ${STAMP}`;

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.${HOST}${pathname}`;
}

// EMS event built in beforeAll for the Slice-5/6 journeys (details edit + simulate).
let adminToken = '';
let eventId = '';
const EVENT_END = '2026-12-31'; // future vs real "today" → stays Draft until simulated

async function apiLogin(
  request: import('@playwright/test').APIRequestContext,
  email: string,
  password: string,
  tenantSlug: string,
): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email, password, tenantSlug },
  });
  expect(res.ok()).toBeTruthy();
  return (await res.json()).access_token;
}

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'));
}

async function openSubmitEdgeDrawer(page: Page) {
  // SVG edge labels need a dispatched click (Playwright hit-testing misses).
  await page.getByText(/Submit/, { exact: false }).first().dispatchEvent('click');
  await page.getByTestId('edge-toolbar').getByRole('button', { name: 'Edit' }).click();
  await expect(page.getByText(/Transition — Draft → Submitted/)).toBeVisible();
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Derived status — live stack (sprint-4/03 Phase C)', () => {
  test.beforeAll(async ({ request }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Derived ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Derived Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status()).toBe(201);
    const tenantId = (await provision.json()).id;

    // Install EMS on the dedicated tenant (operator), then build an event with a
    // time-based auto edge for the Slice-5/6 journeys — all API setup.
    const op = { Authorization: `Bearer ${platformToken}` };
    const install = await request.post(
      `${API}/platform/tenants/${tenantId}/modules/ems/install`,
      { headers: op },
    );
    expect(install.ok()).toBeTruthy();

    adminToken = await apiLogin(request, ADMIN_EMAIL, ADMIN_PASSWORD, SLUG);
    const ah = { Authorization: `Bearer ${adminToken}` };
    const type = await (
      await request.post(`${API}/ems/project-types`, { headers: ah, data: { name: 'Conf' } })
    ).json();
    const tmpl = await (
      await request.post(`${API}/ems/project-templates`, {
        headers: ah,
        data: { typeId: type.id, name: 'Standard' },
      })
    ).json();
    const event = await (
      await request.post(`${API}/ems/projects`, {
        headers: ah,
        data: { templateId: tmpl.id, title: `E2E Event ${STAMP}` },
      })
    ).json();
    eventId = event.id;
    // Future end date → "Days since End Date >= 0" is false today (stays Draft).
    await request.patch(`${API}/ems/projects/${eventId}`, {
      headers: ah,
      data: { endDate: EVENT_END },
    });
    // Author the time-based auto edge Draft→Active on the project graph.
    const graph = await (
      await request.get(`${API}/statuses?entityType=project`, { headers: ah })
    ).json();
    const sid = Object.fromEntries(
      graph.statuses.map((s: { id: string; label: string }) => [s.label, s.id]),
    );
    const edge = await request.post(`${API}/statuses/transitions`, {
      headers: ah,
      data: {
        entityType: 'project',
        fromStatusId: sid['Draft'],
        toStatusId: sid['Active'],
        label: 'Auto on end',
        triggerMode: 'auto',
        conditionsJson: {
          kind: 'group',
          combinator: 'and',
          rules: [{
            kind: 'condition',
            fact: 'record.endDate.daysSince',
            operator: 'gte',
            valueKind: 'literal',
            value: 0,
          }],
        },
      },
    });
    expect(edge.status()).toBe(201);
  });

  test('auto-edge authoring: toggle → role gate hides → required conditions → ⚡ canvas', async ({
    page,
  }) => {
    await login(page);

    // Create a form (its scoped Draft→Submitted graph is seeded on save).
    await page.goto(tenantUrl('/forms/new'));
    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByRole('textbox', { name: 'Form name' }).fill(FORM_NAME);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page).toHaveURL(/\/forms\/(?!new)[0-9a-f-]+/);

    // Flow tab → Edit (global toggle gates the canvas).
    await page.getByRole('tab', { name: 'Flow' }).click();
    await expect(page.getByTestId('entity-flow')).toBeVisible();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();

    // ---- Switch the Submit edge to Automatic ----
    await openSubmitEdgeDrawer(page);
    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Who can perform it')).toBeVisible(); // manual: role gate shown
    await dialog.getByRole('combobox').filter({ hasText: /Manual/ }).click();
    await page.getByRole('option', { name: /Automatic/ }).click();
    // Role gate disappears (system-fired); conditions become required.
    await expect(dialog.getByText('Who can perform it')).toHaveCount(0);
    await expect(dialog.getByText('Conditions *')).toBeVisible();

    // Saving with no condition is blocked.
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(
      dialog.getByText('An automatic transition needs at least one condition.'),
    ).toBeVisible();

    // Add a condition + save.
    await dialog.getByRole('button', { name: 'Add condition' }).click();
    await dialog.getByRole('textbox', { name: 'Value' }).fill('auto@example.com');
    await dialog.getByRole('button', { name: 'Save', exact: true }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    // ---- Canvas renders the edge as AUTO (⚡ prefix) ----
    await expect(page.getByText('⚡ Submit', { exact: false })).toBeVisible();

    // ---- Reopen: Automatic persisted, role gate still hidden ----
    await openSubmitEdgeDrawer(page);
    await expect(
      page.getByRole('dialog').getByRole('combobox').filter({ hasText: /Automatic/ }),
    ).toBeVisible();
    await expect(page.getByRole('dialog').getByText('Who can perform it')).toHaveCount(0);

    // ---- Back to Manual restores the role gate ----
    await page.getByRole('dialog').getByRole('combobox').filter({ hasText: /Automatic/ }).click();
    await page.getByRole('option', { name: /Manual/ }).click();
    await expect(page.getByRole('dialog').getByText('Who can perform it')).toBeVisible();
  });

  // AC-03-44 (Slice 5) — Event Details edit round-trip: open the event, edit a
  // field + a date, save, reload → persisted; the Events list shows the date.
  test('event Details edit: set fields/date → save → persists + list column', async ({
    page,
  }) => {
    await login(page);
    await page.goto(tenantUrl(`/ems/events/${eventId}`));
    await expect(page.getByRole('tab', { name: 'Details' })).toBeVisible();
    await page.getByRole('button', { name: 'Edit', exact: true }).click();

    await page.getByLabel('Brief').fill('Flagship conference');
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    // Wait for the save to settle (form returns to read mode) before reloading,
    // so the PATCH isn't aborted by the navigation.
    await expect(page.getByRole('button', { name: 'Edit', exact: true })).toBeVisible();

    // Reload → the edited value persisted on the Details tab.
    await page.goto(tenantUrl(`/ems/events/${eventId}`));
    await expect(page.getByText('Flagship conference')).toBeVisible();
    // The end date (set in setup) shows on the Details tab + the list column.
    await expect(page.getByText(EVENT_END)).toBeVisible();
    await page.goto(tenantUrl('/ems/events'));
    // The End column renders the date (proves the Start/End columns shipped).
    await expect(page.getByRole('cell', { name: EVENT_END })).toBeVisible();
  });

  // AC-03-54 (Slice 6) — admin date-simulation: fast-forward "now" past the
  // event's end date → Preview lists the would-advance event → Apply advances it.
  test('simulate date: preview → apply advances the event as-of a future date', async ({
    page,
    request,
  }) => {
    await login(page);
    await page.goto(tenantUrl('/settings/statuses/project'));
    await page.getByRole('button', { name: 'Actions' }).click();
    await page.getByRole('menuitem', { name: 'Simulate date' }).click();

    const dialog = page.getByRole('dialog');
    await expect(dialog.getByText('Simulate date — Event')).toBeVisible();
    // As-of a date AFTER the event end → "Days since End Date >= 0" becomes true.
    await dialog.getByLabel('As-of date').fill('2027-01-15');
    await dialog.getByRole('button', { name: 'Preview' }).click();

    // Dry-run lists the would-advance event (Draft → Active), persists nothing.
    await expect(dialog.getByText(`E2E Event ${STAMP}`)).toBeVisible();
    await expect(dialog.getByText('Draft → Active')).toBeVisible();
    const beforeApply = await request.get(`${API}/ems/projects/${eventId}`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    const draftStatus = (await beforeApply.json()).statusId;

    // Apply → commits the transition.
    await dialog.getByRole('button', { name: 'Apply' }).click();
    await expect(page.getByRole('dialog')).toHaveCount(0);

    const after = await request.get(`${API}/ems/projects/${eventId}`, {
      headers: { Authorization: `Bearer ${adminToken}` },
    });
    const newStatus = (await after.json()).statusId;
    expect(newStatus).not.toBe(draftStatus); // advanced (Draft → Active)
  });
});
