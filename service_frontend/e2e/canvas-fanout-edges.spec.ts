import { expect, test, type APIRequestContext, type Page } from '@playwright/test';

/**
 * Plan sprint-4/21 - workflow canvas fan-out edges (AC-FAN-01/02/05/08),
 * against the LIVE stack (Next :3001 → FastAPI :8001 → Postgres). Real clicks
 * for every product surface - the workflow is built entirely via the
 * palette/canvas/drawer, never navigated to by URL.
 *
 * A node's output port used to allow only ONE outgoing edge (`addEdge`
 * replaced any existing edge on the same port). This slice lets it fan out to
 * multiple targets: the executor already ran every out-edge, so the fix is
 * frontend-only (`lib/workflow-doc.ts addEdge` + multi-select edge delete).
 *
 * Isolation: a DEDICATED tenant (methodology §7), matching the precedent set
 * by `e2e/workflows.spec.ts` / `e2e/agent-state-read-node.spec.ts` - building
 * a brand-new, uniquely-named workflow does not itself mutate anyone else's
 * rows, but a fresh tenant keeps this spec's runs isolated from concurrent
 * suite activity on the shared default tenant. Every created name/slug
 * /address is timestamped.
 */
const API = process.env.NEXT_PUBLIC_BACKEND_API_URL ?? 'http://localhost:8001';
const STAMP = Date.now();
const SLUG = `e2e-fan21-${STAMP}`;
const ADMIN_EMAIL = `admin-fan21-${STAMP}@example.com`;
const ADMIN_PASSWORD = 'E2eStart1!';
const WF_NAME = `Fan-out edges ${STAMP}`;
const SOURCE_TO = `fanout-source-${STAMP}@e2e.example`;
const TARGET1_TO = `fanout-target1-${STAMP}@e2e.example`;
const TARGET2_TO = `fanout-target2-${STAMP}@e2e.example`;

function tenantUrl(pathname: string): string {
  return `http://${SLUG}.localhost:3001${pathname}`;
}

async function login(page: Page) {
  await page.goto(tenantUrl('/signin'));
  await page.waitForLoadState('networkidle');
  await page.getByPlaceholder('Your email').fill(ADMIN_EMAIL);
  await page.getByPlaceholder('Your password').fill(ADMIN_PASSWORD);
  const submit = page.getByRole('button', { name: /sign in/i });
  await expect(submit).toBeEnabled({ timeout: 30_000 });
  await submit.click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), { timeout: 30_000 });
}

async function openWorkflows(page: Page) {
  // The sidebar heading and its child link can share the accessible name
  // "Workflows" (terminology-driven plural) - disambiguate by href.
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

function nodeSourceHandle(nodeId: string) {
  return `[data-testid="workflow-node-${nodeId}"] [data-testid="source-handle"]`;
}
function nodeTargetHandle(nodeId: string) {
  return `[data-testid="workflow-node-${nodeId}"] [data-testid="target-handle"]`;
}

/** Wire a source handle to a target handle, retrying the drag once if React
 * Flow didn't register an edge (canvas pan/zoom settle timing is flaky). */
async function connectHandles(
  page: Page,
  fromSelector: string,
  toSelector: string,
  expectedEdgeCount: number,
) {
  const from = page.locator(fromSelector).first();
  const to = page.locator(toSelector).first();
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

async function connectByIds(
  page: Page,
  fromNodeId: string,
  toNodeId: string,
  expectedEdgeCount: number,
) {
  await connectHandles(
    page,
    nodeSourceHandle(fromNodeId),
    nodeTargetHandle(toNodeId),
    expectedEdgeCount,
  );
}

/** Configure an email.send node as a bare custom email (no template/connection
 * needed - the outbox dev-console-logs with nothing configured). */
async function configureCustomEmail(page: Page, nodeId: string, to: string, subject: string) {
  await page.locator(`[data-testid="workflow-node-${nodeId}"]`).click();
  await page.locator('button[aria-label="Email type"]').click();
  await page.getByRole('option', { name: 'Write a custom email' }).click();
  await page.getByLabel('Subject').fill(subject);
  await page.getByLabel('Body').fill(`Body for ${subject}`);
  await page.getByLabel('To', { exact: true }).fill(to);
}

/** Compute the on-screen midpoint of a React Flow edge's SVG path and click it
 * (an edge's bounding-box center is not guaranteed to sit ON a bent
 * smoothstep path, so this walks the actual path geometry). React Flow's
 * default `aria-label` for an edge with no custom label is
 * `Edge from <source> to <target>` - reliable even though edge ids are
 * client-generated random strings. */
async function selectEdge(page: Page, fromNodeId: string, toNodeId: string) {
  const label = `Edge from ${fromNodeId} to ${toNodeId}`;
  const edge = page.locator(`[aria-label="${label}"]`);
  await expect(edge).toHaveCount(1);
  const point = await edge.evaluate((el) => {
    const path = el.querySelector('path') as SVGPathElement | null;
    if (!path) throw new Error('edge path element not found');
    const length = path.getTotalLength();
    const p = path.getPointAtLength(length / 2);
    const ctm = path.getScreenCTM();
    if (!ctm) throw new Error('edge path has no screen CTM');
    return {
      x: ctm.a * p.x + ctm.c * p.y + ctm.e,
      y: ctm.b * p.x + ctm.d * p.y + ctm.f,
    };
  });
  await page.mouse.click(point.x, point.y);
  await expect(edge).toHaveClass(/selected/, { timeout: 5_000 });
}

async function expectNoDocumentOverflow(page: Page) {
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
    ),
  ).toBe(true);
}

/** A viewport resize triggers the app's own resize-driven layout logic
 * (sidebar collapse/mobile-drawer classes) asynchronously - reading layout
 * metrics in the same tick races it. Settle briefly, matching the buffer an
 * intervening click/assertion gives other specs' 375px checks. */
async function setViewportAndSettle(page: Page, size: { width: number; height: number }) {
  await page.setViewportSize(size);
  await page.waitForTimeout(300);
}

test.describe.configure({ mode: 'serial', timeout: 180_000 });

test.describe('Workflow canvas fan-out edges (plan sprint-4/21)', () => {
  test.beforeAll(async ({ request }: { request: APIRequestContext }) => {
    const platformLogin = await request.post(`${API}/auth/login`, {
      data: { email: 'platform@example.com', password: 'platform1234', tenantSlug: 'platform' },
    });
    expect(platformLogin.ok(), await platformLogin.text()).toBeTruthy();
    const platformToken = (await platformLogin.json()).access_token;

    const provision = await request.post(`${API}/platform/tenants`, {
      headers: { Authorization: `Bearer ${platformToken}` },
      data: {
        name: `E2E Fan-out 21 ${STAMP}`,
        slug: SLUG,
        adminName: 'E2E Fan-out Admin',
        adminEmail: ADMIN_EMAIL,
        adminPassword: ADMIN_PASSWORD,
      },
    });
    expect(provision.status(), await provision.text()).toBe(201);
  });

  test('build → both edges render, persist through save/reload, both branches execute, one edge is independently removable', async ({
    page,
  }) => {
    await setViewportAndSettle(page, { width: 1280, height: 900 });
    await login(page);
    await openWorkflows(page);

    // ---- Build: trigger -> source action -> TWO downstream actions ----
    await page.getByRole('button', { name: 'New workflow' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();

    await addNode(page, 'manual', 'manual');
    const triggerId = (
      await page.locator('[data-node-type="manual"]').first().getAttribute('data-testid')
    )?.replace('workflow-node-', '');
    if (!triggerId) throw new Error('trigger node id missing');

    // Source node (the one whose single output port will fan out).
    await addNode(page, 'send email', 'email.send');
    const sourceId = (
      await page.locator('[data-node-type="email.send"]').first().getAttribute('data-testid')
    )?.replace('workflow-node-', '');
    if (!sourceId) throw new Error('source node id missing');
    await connectByIds(page, triggerId, sourceId, 1);
    await configureCustomEmail(page, sourceId, SOURCE_TO, 'Source');

    // First downstream target.
    await addNode(page, 'send email', 'email.send');
    const target1Id = (
      await page.locator('[data-node-type="email.send"]').nth(1).getAttribute('data-testid')
    )?.replace('workflow-node-', '');
    if (!target1Id) throw new Error('target1 node id missing');
    await configureCustomEmail(page, target1Id, TARGET1_TO, 'Target 1');
    await connectByIds(page, sourceId, target1Id, 2);

    // Second downstream target - wired from the SAME source output handle
    // that already feeds target1 (this is the fan-out under test: AC-FAN-01).
    await addNode(page, 'send email', 'email.send');
    const target2Id = (
      await page.locator('[data-node-type="email.send"]').nth(2).getAttribute('data-testid')
    )?.replace('workflow-node-', '');
    if (!target2Id) throw new Error('target2 node id missing');
    await configureCustomEmail(page, target2Id, TARGET2_TO, 'Target 2');
    await connectByIds(page, sourceId, target2Id, 3);

    // AC-FAN-01: BOTH edges from the source's single output port render as
    // distinct React Flow edges (not one replacing the other).
    await expect(page.locator('.react-flow__edge')).toHaveCount(3);
    await expect(
      page.locator(`[aria-label="Edge from ${sourceId} to ${target1Id}"]`),
    ).toHaveCount(1);
    await expect(
      page.locator(`[aria-label="Edge from ${sourceId} to ${target2Id}"]`),
    ).toHaveCount(1);

    // AC-FAN-02 (supplementary UI check - the authoritative case is the
    // frontend unit test `lib/workflow-doc.test.ts`): re-dragging an EXACT
    // duplicate connection does not add a second identical edge.
    await connectByIds(page, sourceId, target1Id, 3);

    await expectNoDocumentOverflow(page);

    // Mobile verification of the fan-out rendering itself (both edges from
    // the one source port) while the graph is fully connected.
    await setViewportAndSettle(page, { width: 375, height: 812 });
    await expect(page.locator('.react-flow__edge')).toHaveCount(3);
    await expectNoDocumentOverflow(page);
    await setViewportAndSettle(page, { width: 1280, height: 900 });

    // ---- Save (creates the workflow) ----
    await page.getByRole('tab', { name: 'Settings' }).click();
    await page.getByLabel('Workflow name').fill(WF_NAME);
    await page.getByRole('button', { name: 'Save', exact: true }).click();
    await page.waitForURL(/\/workflows\/(?!new)[^/?]+/, { timeout: 30_000 });

    // ---- Reload: AC-FAN-08 persistence - both edges survive a fresh load ----
    await page.reload();
    await page.getByRole('tab', { name: 'Editor' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();
    await expect(page.locator('.react-flow__edge')).toHaveCount(3);
    await expect(
      page.locator(`[aria-label="Edge from ${sourceId} to ${target1Id}"]`),
    ).toHaveCount(1);
    await expect(
      page.locator(`[aria-label="Edge from ${sourceId} to ${target2Id}"]`),
    ).toHaveCount(1);

    // ---- Run: AC-FAN-08 - a run executes BOTH downstream branches ----
    // (Run executes the DRAFT directly - no publish needed.) The backend
    // execution guarantee itself is locked by
    // `test_fan_out_action_two_edges_both_downstream_succeed` +
    // `test_if_true_port_fans_out_to_two_targets` (AC-FAN-06); here we drive
    // it end-to-end through real clicks per AC-FAN-08.
    // The manual trigger declares no run inputs and no redis/code side
    // effects, so `onRun` skips the confirmation dialog and runs immediately
    // (see `use-workflow-form.tsx onRun`).
    await page.getByTestId('workflow-run').click();

    await page.getByRole('tab', { name: 'Logs' }).click();
    const runs = page.getByTestId('workflow-runs');
    await expect(runs).toContainText('Success', { timeout: 30_000 });

    await page.locator(`[data-testid="workflow-node-${sourceId}"]`).click();
    await expect(page.getByTestId('node-inspector')).toContainText('success');

    await page.locator(`[data-testid="workflow-node-${target1Id}"]`).click();
    await expect(page.getByTestId('node-inspector')).toContainText('success');

    await page.locator(`[data-testid="workflow-node-${target2Id}"]`).click();
    await expect(page.getByTestId('node-inspector')).toContainText('success');

    await expectNoDocumentOverflow(page);

    // Mobile verification of the Logs/run-replay surface (read-only - the
    // graph is fully connected and published-clean at this point, matching
    // the precedent in `e2e/agent-state-read-node.spec.ts`).
    await setViewportAndSettle(page, { width: 375, height: 812 });
    await expect(page.getByTestId('workflow-runs')).toBeVisible();
    await expectNoDocumentOverflow(page);
    await setViewportAndSettle(page, { width: 1280, height: 900 });

    // ---- Delete one edge: AC-FAN-05 - only that edge is removed, the other
    // fan-out edge from the same port remains. ----
    await page.getByRole('tab', { name: 'Editor' }).click();
    await expect(page.getByTestId('workflow-canvas')).toBeVisible();
    // The reload left the form in its default READ view (global Edit
    // toggle) - edge deletion (like any canvas mutation) needs edit mode.
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByRole('complementary').getByText('Read-only workflow.')).toHaveCount(0);
    // Clear any leftover node selection first - the canvas' own Delete/
    // Backspace listener removes the currently-selected NODE, which would
    // otherwise fire alongside React Flow's edge deletion on the same
    // keypress (both are bound to the same document keydown).
    await page.getByTestId('flow-canvas').click({ position: { x: 5, y: 5 } });

    await selectEdge(page, sourceId, target1Id);
    await page.keyboard.press('Delete');

    await expect(page.locator('.react-flow__edge')).toHaveCount(2);
    await expect(
      page.locator(`[aria-label="Edge from ${sourceId} to ${target1Id}"]`),
    ).toHaveCount(0);
    await expect(
      page.locator(`[aria-label="Edge from ${sourceId} to ${target2Id}"]`),
    ).toHaveCount(1);
    // The nodes themselves must still be present - only the edge was removed.
    await expect(page.locator(`[data-testid="workflow-node-${sourceId}"]`)).toBeVisible();
    await expect(page.locator(`[data-testid="workflow-node-${target1Id}"]`)).toBeVisible();
    await expect(page.locator(`[data-testid="workflow-node-${target2Id}"]`)).toBeVisible();

    await expectNoDocumentOverflow(page);

    // AC-FAN-05 at mobile width too - the surviving edge/nodes still render
    // correctly (edit mode, with the expected "not connected to the trigger"
    // publish-issue banner for the now-orphaned target1 - deleting a fan-out
    // edge's only inbound connection to a node is an inherent, expected
    // consequence of independent removal, not a bug).
    await setViewportAndSettle(page, { width: 375, height: 812 });
    await expect(page.locator('.react-flow__edge')).toHaveCount(2);
    await expect(page.locator(`[data-testid="workflow-node-${target2Id}"]`)).toBeVisible();
    await expectNoDocumentOverflow(page);
  });
});
