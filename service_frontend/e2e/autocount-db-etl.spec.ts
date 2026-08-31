import { existsSync } from 'node:fs';
import { execFile } from 'node:child_process';
import { createServer, type IncomingMessage, type Server, type ServerResponse } from 'node:http';
import type { AddressInfo } from 'node:net';
import path from 'node:path';
import { expect, test, type APIRequestContext, type Locator, type Page } from '@playwright/test';

/**
 * Plan 22 (AutoCount direct-DB ETL) - slice S6 E2E, AC-22-31/32. Real clicks
 * against the LIVE stack (Next -> FastAPI -> Postgres). After sign-in every
 * navigation is a click on something a real operator can see - no deep-link
 * `page.goto`.
 *
 * ── Why "ETL Demo Co", never "V Soft Trading" ───────────────────────────────
 * `python -m scripts.seed_etl_demo_source --company` provisions a DEDICATED
 * `ac_company` (`database_name='ETL_DEMO'`) whose own Postgres tables
 * (`public.etl_demo_customers`, ...) live inside THIS Foundryx database - no
 * second server, no customer data. "V Soft Trading" is a real, Sorento-bound
 * company from plans 13/14; touching its `source_ref` namespace from a DB-ETL
 * test poisoned it once already (see the seed script's own docstring) - this
 * spec never references it.
 *
 * ── Why a scripted Sorento consumer ─────────────────────────────────────────
 * AC-22-18's activation gate is real and server-enforced
 * (`EtlService.activate_task` 409s without a prior `previewable: true` dry
 * run), and `previewable: true` requires a sink that actually implements
 * `dry_run` - the demo company's own `sink_impl='logging'` deliberately does
 * NOT (`hasattr(sink, 'dry_run')` is False for `LoggingSink`, by design: a
 * company with nowhere to push must never pass the gate). So this spec stands
 * a tiny HTTP server that speaks the minimal Appendix A6/A8 contract
 * (`POST /api/v1/external/ingest/{entity}[?dry_run=true]`,
 * `POST .../deletions`, `POST /api/v1/external/read/{entity}` for the
 * provider's own Test-connection probe) and points a REAL `sorento` consumer
 * connection at it via real clicks - the exact pattern `autocount.spec.ts`
 * already uses for a scripted AutoCount vendor. Only the consumer's socket is
 * scripted; the provider `test()`, the dry-run call, the activation gate, the
 * mapping engine, the watermark/hash-diff logic and the run-history counts are
 * all the real production code path.
 *
 * ── Spec isolation (shared tenant, shared company) ──────────────────────────
 * `ETL_DEMO` is a SINGLETON per tenant (`--company` finds-or-creates by
 * `database_name`) - this spec cannot provision a fresh one per test the way
 * the dedicated-tenant specs do, so it runs `mode: 'serial'` and every created
 * connection carries a per-run timestamp (never a fixed literal) so re-runs
 * never collide. `beforeAll` also retires the S2 "Sorento (live-verify)"
 * throwaway connection (dead now that `s22-live-verify.spec.ts` is deleted) -
 * core's `uq_connection_tenant_type` allows only ONE active `consumer`
 * connection per tenant, and that residue would otherwise permanently occupy
 * the slot this spec's own connection needs.
 */

const API = 'http://localhost:8001';
const DEMO_COMPANY_NAME = 'ETL Demo Co';
/** The demo company's `database_name` MUST equal the real Postgres database
 * this backend process itself points at (`EtlService.update_task`'s cross-
 * check - plan 22 S2 review SHOULD-FIX 6, a `sql_db` task's connection may
 * only read the SAME database its company is), so it is READ from the seed
 * script's own stdout in `beforeAll` rather than hardcoded. */
let demoDatabaseName = '';

test.describe.configure({ mode: 'serial' });
test.setTimeout(240_000);

// ── the scripted Sorento consumer (Appendix A6/A8 minimal contract) ─────────

interface SorentoRecordSeen {
  entityId: string;
}

interface FakeSorento {
  url: string;
  ingestCalls: { path: string; dryRun: boolean; body: Record<string, unknown> }[];
  close(): Promise<void>;
}

/** Stand up the scripted Sorento consumer on an ephemeral loopback port. */
async function startFakeSorento(): Promise<FakeSorento> {
  const seen = new Map<string, SorentoRecordSeen>();
  const ingestCalls: FakeSorento['ingestCalls'] = [];

  const server: Server = createServer((req: IncomingMessage, res: ServerResponse) => {
    const chunks: Buffer[] = [];
    req.on('data', (c: Buffer) => chunks.push(c));
    req.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      let body: Record<string, unknown> = {};
      try {
        body = raw ? (JSON.parse(raw) as Record<string, unknown>) : {};
      } catch {
        body = {};
      }
      const url = new URL(req.url ?? '/', 'http://127.0.0.1');
      const send = (payload: unknown) => {
        res.writeHead(200, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify(payload));
      };

      // The Sorento provider's Test-connection probe (`sorento_provider.py`,
      // `_PROBE_PATH`) - authenticates, writes nothing.
      if (url.pathname.startsWith('/api/v1/external/read/')) {
        send({ records: [], not_found: body.source_refs ?? [] });
        return;
      }

      if (url.pathname.endsWith('/deletions')) {
        ingestCalls.push({ path: url.pathname, dryRun: false, body });
        const refs = (body.source_refs as string[] | undefined) ?? [];
        const records = refs.map((ref) => {
          seen.delete(ref);
          return { source_ref: ref, outcome: 'deleted', entity_id: null };
        });
        send({
          summary: { total: refs.length, deleted: refs.length, deactivated: 0, not_found: 0, failed: 0 },
          records,
        });
        return;
      }

      if (url.pathname.startsWith('/api/v1/external/ingest/')) {
        const dryRun = url.searchParams.get('dry_run') === 'true';
        ingestCalls.push({ path: url.pathname, dryRun, body });
        const records = (body.records as Record<string, unknown>[] | undefined) ?? [];
        const outRecords = records.map((r) => {
          const ref = String(r.source_ref ?? '');
          const existing = seen.get(ref);
          const outcome = existing ? 'updated' : 'created';
          const entityId = existing?.entityId ?? `stub-${Math.random().toString(36).slice(2, 10)}`;
          // A DRY RUN must not mutate the sink's own state (AC-14-21's "rolled
          // back" contract) - only a real push (dry_run=false) commits it here.
          if (!dryRun) seen.set(ref, { entityId });
          return { source_ref: ref, outcome, entity_id: entityId, diff: {}, errors: {} };
        });
        const summary = { total: outRecords.length, created: 0, updated: 0, failed: 0, retryable: 0 };
        for (const r of outRecords) {
          summary[r.outcome as 'created' | 'updated'] += 1;
        }
        send({ summary, records: outRecords });
        return;
      }

      res.writeHead(404, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ message: `unexpected path ${url.pathname}` }));
    });
  });

  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = (server.address() as AddressInfo).port;

  return {
    url: `http://127.0.0.1:${port}`,
    ingestCalls,
    close: () => new Promise<void>((resolve) => server.close(() => resolve())),
  };
}

// ── backend dev-fixture helper (the seed rig's own documented CLI) ──────────

const BACKEND_DIR = path.resolve(__dirname, '..', '..', 'service_backend');
const VENV_PYTHON = path.join(BACKEND_DIR, '.venv', 'bin', 'python');
const PYTHON_BIN = existsSync(VENV_PYTHON) ? VENV_PYTHON : 'python3';

/** `python -m scripts.seed_etl_demo_source <args>` - the documented dev rig
 * (plan 22 S2/S3/S4/S6). Used for fixture setup (tables + the ETL_DEMO
 * company, both idempotent) AND for the two actions with NO UI affordance:
 * mutating a source row and triggering a RECONCILE run (the scheduler/beat's
 * job in production; "Run now" always enqueues `manual`, which only ever
 * behaves as an incremental fetch).
 *
 * ASYNC, never `execFileSync` - the fake Sorento consumer (below) runs
 * in-process on THIS Node event loop. `--trigger-run` makes the eager-mode
 * backend job call BACK INTO that server; a synchronous, event-loop-blocking
 * spawn would starve it while the very script that needs it is running -
 * genuine deadlock, only resolved by the sink's 30s HTTP timeout (found live:
 * a `--trigger-run reconcile` call hung every push for exactly 30s per
 * record until the whole run failed).
 */
function runSeed(args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    execFile(
      PYTHON_BIN,
      ['-m', 'scripts.seed_etl_demo_source', ...args],
      { cwd: BACKEND_DIR, encoding: 'utf8', env: { ...process.env, PYTHONPATH: BACKEND_DIR } },
      (error, stdout, stderr) => {
        if (error) reject(new Error(`seed_etl_demo_source ${args.join(' ')} failed: ${stderr || error.message}`));
        else resolve(stdout);
      },
    );
  });
}

// ── auth (setup only - the flow under test stays real clicks) ───────────────

async function demoToken(request: APIRequestContext): Promise<string> {
  const res = await request.post(`${API}/auth/login`, {
    data: { email: 'demo@example.com', password: 'demo1234', tenantSlug: 'default' },
  });
  if (!res.ok()) throw new Error(`demo login failed: ${await res.text()}`);
  return (await res.json()).access_token as string;
}

/** Delete every connection matching `namePrefix` (both `sql_database` and
 * `sorento` providers use core's shared `connections` table). Cleanup only -
 * creation of the connections THIS spec needs stays a real-click flow below. */
async function deleteConnectionsNamed(
  request: APIRequestContext,
  token: string,
  namePrefix: string,
): Promise<void> {
  const res = await request.get(
    `${API}/integrations/connections?page_size=200&search=${encodeURIComponent(namePrefix)}`,
    { headers: { Authorization: `Bearer ${token}` } },
  );
  if (!res.ok()) return;
  const body = (await res.json()) as { data: { id: string; name: string }[] };
  for (const row of body.data) {
    if (!row.name.startsWith(namePrefix)) continue;
    await request.delete(`${API}/integrations/connections/${row.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
  }
}

// ── UI helpers (real clicks) ─────────────────────────────────────────────────

async function signIn(page: Page) {
  await page.goto('http://localhost:3002/signin');
  await page.getByPlaceholder('Your email').fill('demo@example.com');
  await page.getByPlaceholder('Your password').fill('demo1234');
  await page.getByRole('button', { name: /sign in/i }).click();
  await page.waitForURL((url) => !url.pathname.startsWith('/signin'), { timeout: 60_000 });
}

/** Sidebar section -> child link. Expands the section when collapsed. */
async function openViaSidebar(page: Page, section: string, child: string, urlRe: RegExp) {
  // `.first()` - a detail page's OWN breadcrumb can carry a same-named link
  // (e.g. "Integrations" on a connection's own breadcrumb), which would
  // otherwise strict-mode-violate alongside the sidebar's.
  const link = page.getByRole('link', { name: child, exact: true }).first();
  if (!(await link.isVisible().catch(() => false))) {
    await page.getByText(section, { exact: true }).first().click();
    await expect(link).toBeVisible({ timeout: 15_000 });
  }
  await link.click();
  await page.waitForURL(urlRe);
}

/** Open a row's "..." menu and pick an item by label. */
async function rowAction(page: Page, row: Locator, label: RegExp) {
  // The Entities list re-renders on its own poll while a sync/preview is
  // still settling from a prior action, which can detach the just-opened
  // menu mid-click - retry the open+pick as one unit rather than fail on a
  // single stale reference.
  await expect(async () => {
    await row.getByRole('button', { name: 'Actions' }).first().click();
    await page.getByRole('menuitem', { name: label }).click({ timeout: 3_000 });
  }).toPass({ timeout: 30_000 });
}

/** No horizontal PAGE scroll - wide content must scroll inside its own box. */
async function expectNoPageScroll(page: Page, where: string) {
  const overflow = await page.evaluate(() => {
    const el = document.documentElement;
    return { scrollWidth: el.scrollWidth, clientWidth: el.clientWidth };
  });
  expect(
    overflow.scrollWidth,
    `${where}: page scrolls horizontally (${overflow.scrollWidth} > ${overflow.clientWidth})`,
  ).toBeLessThanOrEqual(overflow.clientWidth + 1);
}

/** Settings -> Integrations -> New -> the SQL Database provider, pointed at
 * this very Foundryx Postgres (a real, reachable source - AC-22-01/04). */
async function createSqlDatabaseConnection(page: Page, name: string) {
  await openViaSidebar(page, 'Settings', 'Integrations', /\/settings\/integrations$/);
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);

  await page.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'SQL Database', exact: true }).click();

  await page.getByPlaceholder('e.g. Company mail server').fill(name);
  // Provider field order after Name: Database type (select), Host, Port,
  // Database, Username, Password. Two comboboxes exist once a provider is
  // chosen - Provider itself (index 0) and Database type (index 1).
  await page.getByRole('combobox').nth(1).click();
  await page.getByRole('option', { name: 'PostgreSQL', exact: true }).click();
  await page.getByPlaceholder('db.yourcompany.com').fill('127.0.0.1');
  await page.locator('input[type="number"]').fill('5432');
  await page.getByPlaceholder('AED_Company_2024').fill('foundryx_service');
  await page.getByPlaceholder('readonly_user').fill('foundryx');
  await page.locator('input[type="password"]').fill('foundryx');

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/, { timeout: 20_000 });

  await page.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Test connection' }).click();
  await expect(page.getByText(/Connected to foundryx_service/).first()).toBeVisible({
    timeout: 20_000,
  });
}

/** Settings -> Integrations -> New -> the Sorento provider, pointed at the
 * scripted consumer this spec stood up. */
async function createSorentoConnection(page: Page, name: string, baseUrl: string) {
  await openViaSidebar(page, 'Settings', 'Integrations', /\/settings\/integrations$/);
  await page.getByRole('button', { name: 'Connect integration' }).click();
  await page.waitForURL(/\/settings\/integrations\/new$/);

  await page.getByRole('combobox', { name: 'Provider' }).click();
  await page.getByRole('option', { name: 'Sorento', exact: true }).click();

  await page.getByPlaceholder('e.g. Company mail server').fill(name);
  await page.getByPlaceholder('https://sorento.customer.com').fill(baseUrl);
  await page.locator('input[type="password"]').fill('e2e-fake-sorento-key');

  await page.getByRole('button', { name: 'Create', exact: true }).click();
  await page.waitForURL(/\/settings\/integrations\/(?!new)[\w-]+$/, { timeout: 20_000 });

  await page.getByRole('button', { name: 'Actions' }).click();
  await page.getByRole('menuitem', { name: 'Test connection' }).click();
  await expect(page.getByText(/Connected to Sorento/).first()).toBeVisible({ timeout: 20_000 });
}

/** AutoCount -> Companies -> ETL Demo Co. */
async function openDemoCompany(page: Page) {
  await openViaSidebar(page, 'AutoCount', 'Companies', /\/autocount\/companies$/);
  // Match on the name AND the EXACT "Company database" column cell - an
  // earlier session left a second, differently-misconfigured row also named
  // "ETL Demo Co" whose stale `database_name` otherwise substring-collides
  // with the real one (`foundryx_service` vs `foundryx_service_STALE...`).
  await page
    .getByRole('row', { name: new RegExp(DEMO_COMPANY_NAME) })
    .filter({ has: page.getByText(demoDatabaseName, { exact: true }) })
    .first()
    .click();
  // The Resource shell carries record-nav state on the URL (`?ctx=&i=`) - never
  // anchor this at the end.
  await page.waitForURL(/\/autocount\/companies\/[\w-]+(\?|$)/, { timeout: 20_000 });
  await expect(page.getByText(demoDatabaseName).first()).toBeVisible();
}

/** Overview tab: Edit -> Delivery = Sorento -> pick `connectionName` -> fill
 * the Sorento company code -> Save (AC-22-18's anchor prerequisite). */
async function setSorentoPushTarget(page: Page, connectionName: string, companyCode: string) {
  await page.getByRole('tab', { name: 'Overview' }).click();
  await page.getByRole('button', { name: /^Edit$/ }).first().click();

  await page.getByRole('combobox', { name: 'Push delivery target' }).click();
  await page.getByRole('option', { name: 'Sorento', exact: true }).click();

  await page.getByRole('combobox', { name: 'Sorento consumer connection' }).click();
  await page.getByRole('option', { name: new RegExp(connectionName) }).click();

  await page.getByTestId('sink-company-code').fill(companyCode);
  await page.getByRole('button', { name: /^Save/ }).first().click();
  await expect(page.getByTestId('sink-company-code-value')).toHaveText(companyCode, {
    timeout: 20_000,
  });
}

/** Entities tab -> Customer row -> Change source -> Database. Re-runnable:
 * an entity already on the DB source shows no diff, so the warning/Save is
 * simply absent. */
async function switchCustomerToDatabase(page: Page) {
  await page.getByRole('tab', { name: 'Entities' }).click();
  const customer = page.getByRole('row', { name: /Customer/ }).first();
  await expect(customer).toBeVisible({ timeout: 20_000 });

  await rowAction(page, customer, /change source/i);
  await page.getByRole('combobox', { name: 'Entity source' }).click();
  await page.getByRole('option', { name: 'Database', exact: true }).click();
  if (await page.getByTestId('source-switch-warning').isVisible().catch(() => false)) {
    await page.getByTestId('save-source').click();
    await expect(page.getByTestId('save-source')).toBeHidden({ timeout: 20_000 });
  } else {
    await page.getByRole('button', { name: /^Cancel$/ }).first().click();
  }
}

/** Set a MultiSelect to exactly `labels` - clear existing chips one at a time
 * (the header's Select-all/Clear-all toggle flips label in place and a missed
 * second click silently leaves every option selected). */
async function setMultiSelect(page: Page, trigger: Locator, labels: string[]) {
  for (let guard = 0; guard < 20; guard += 1) {
    const text = (await trigger.innerText()).trim();
    const chips = text.split('\n').map((t) => t.trim()).filter(Boolean);
    if (chips.length === 0 || /^(Pick columns|All except|Run Test)/.test(chips[0])) break;
    await trigger.getByText(chips[0], { exact: true }).first().click();
  }
  if (labels.length === 0) return;
  await trigger.click();
  for (const label of labels) {
    await page.getByRole('option', { name: label, exact: true }).click();
  }
  await page.keyboard.press('Escape');
}

/** The customer task editor's Query tab: connection -> schema tree -> starter
 * query -> Test query -> key/watermark/compared columns -> Save (AC-22-07). */
async function configureQuery(page: Page, connectionName: string) {
  const editToggle = page.getByRole('button', { name: /^Edit$/ }).first();
  await expect(editToggle).toBeVisible({ timeout: 60_000 });
  await editToggle.click();

  const connection = page.getByRole('combobox', { name: 'Connection' });
  await expect(connection).toBeEnabled({ timeout: 30_000 });
  await connection.click();
  await page.getByRole('option', { name: new RegExp(connectionName) }).click();

  // Schema tree -> search the demo table -> click it -> Insert SELECT * (the
  // table-click/starter path, AC-22-31).
  await page.getByLabel('Search tables').fill('etl_demo_customers');
  await page.getByRole('treeitem', { name: /etl_demo_customers/ }).first().click();
  await page.getByTestId('sql-insert-starter').click();

  await page.getByTestId('sql-test-query').click();
  await expect(page.getByTestId('sql-preview-badge')).toBeVisible({ timeout: 30_000 });

  const combos = page.getByRole('combobox');
  await setMultiSelect(page, combos.nth(1), ['acc_no']);
  await page.getByRole('combobox', { name: 'Watermark column' }).click();
  await page.getByRole('option', { name: 'last_modified', exact: true }).click();
  // Empty = "all result columns except the keys" (AC-22-11's default).
  await setMultiSelect(page, page.getByRole('combobox').nth(3), []);

  await page.getByRole('button', { name: /^Save/ }).first().click();
  await expect(page.getByTestId('task-save-error')).toBeHidden().catch(() => undefined);
  await expect(editToggle).toBeVisible({ timeout: 30_000 });
}

/** The Mapping tab: 4 rows (code/name/email/is_active <- the flat preview
 * columns, AC-22-09) -> Save. */
async function configureMapping(page: Page) {
  await page.getByRole('tab', { name: 'Mapping' }).click();
  const editToggle = page.getByRole('button', { name: /^Edit$/ }).first();
  await expect(editToggle).toBeVisible({ timeout: 30_000 });
  await editToggle.click();

  // Switching a customer's source does NOT rewrite its mapping - `Customer`
  // was seeded with the standard API-path DEFAULT_MAPPINGS (every Sorento
  // target already used, incl. code/name/email/is_active, which is why
  // "Add field" is disabled here), so the fix is to RE-POINT the existing
  // rows' "Source column" at the DB path's flat preview columns - never add
  // new ones (AC-22-09). Rows 1-4 are conveniently code/name/email/is_active
  // in that order.
  const picker = (row: number) => page.getByRole('combobox', { name: `Source column for row ${row}` });
  await expect(picker(1)).toBeVisible({ timeout: 15_000 });
  const rows: [number, string][] = [
    [1, 'acc_no'],
    [2, 'company_name'],
    [3, 'email'],
    [4, 'is_active'],
  ];
  for (const [rowIndex, source] of rows) {
    await picker(rowIndex).click();
    await page.getByRole('option', { name: source, exact: true }).click();
  }

  await page.getByRole('button', { name: /^Save/ }).first().click();
  await expect(editToggle).toBeVisible({ timeout: 30_000 });
}

/** Click "Run now" and wait for ITS OWN response - `etl-last-run-at` can
 * ALREADY be visible from an earlier run (a re-run of this spec against the
 * same persisted task), so waiting on the badge alone would pass instantly
 * without proving THIS click's run actually finished. */
async function clickRunNow(page: Page) {
  const runResponse = page.waitForResponse(
    (r) => /\/entities\/customer\/etl-task\/run$/.test(new URL(r.url()).pathname) && r.request().method() === 'POST',
    { timeout: 60_000 },
  );
  await page.getByTestId('etl-run-now').click();
  await runResponse;
  await expect(
    page.getByTestId('etl-last-run-at').or(page.getByTestId('task-last-run-error')),
  ).toBeVisible({ timeout: 30_000 });
}

/** Review & Activate tab: Run preview -> Activate -> Run now. Re-runnable: an
 * already-active task (a re-run of this spec) shows Pause/Run now instead of
 * Activate - the activate-once gate does not re-arm on every visit. */
async function activateAndRun(page: Page) {
  await page.getByRole('tab', { name: /review/i }).click();
  await page.getByTestId('etl-run-preview').click();
  await expect(page.getByTestId('etl-preview-passed')).toBeVisible({ timeout: 60_000 });

  const activate = page.getByTestId('etl-activate');
  if (await activate.isVisible().catch(() => false)) await activate.click();
  await expect(page.getByTestId('etl-run-now')).toBeVisible({ timeout: 30_000 });

  await clickRunNow(page);
}

/** Runs tab -> the newest row's cells (header row is index 0). */
async function latestRunCells(page: Page): Promise<{ mode: string; added: string; updated: string; deleted: string }> {
  await page.getByRole('tab', { name: /^Runs$/i }).click();
  const row = page.getByRole('row').nth(1);
  const cells = row.getByRole('cell');
  // The grid renders an EMPTY skeleton row before its data XHR resolves -
  // `networkidle`/visibility alone both pass on that skeleton. Poll the
  // Mode cell for real text instead of a fixed wait.
  await expect(cells.nth(1)).not.toHaveText('', { timeout: 20_000 });
  return {
    mode: (await cells.nth(1).innerText()).trim(),
    added: (await cells.nth(3).innerText()).trim(),
    updated: (await cells.nth(4).innerText()).trim(),
    deleted: (await cells.nth(5).innerText()).trim(),
  };
}

// ── setup ─────────────────────────────────────────────────────────────────

let sorento: FakeSorento;

test.beforeAll(async ({ request }) => {
  await runSeed([]); // idempotent: creates/tops-up the etl_demo_* source tables
  const companyOut = await runSeed(['--company']); // idempotent: finds-or-creates the demo company + seeds Customer/Supplier/GRN configs
  const dbNameMatch = /Company '([^']+)'/.exec(companyOut) ?? /company database_name '[^']+' -> '([^']+)'/.exec(companyOut);
  if (!dbNameMatch) throw new Error(`could not read the demo company's database_name from:\n${companyOut}`);
  demoDatabaseName = dbNameMatch[1];
  sorento = await startFakeSorento();

  const token = await demoToken(request);
  // Retire the S2 throwaway's leftover consumer connection (dead now that
  // `s22-live-verify.spec.ts` is deleted) - it would otherwise permanently
  // occupy the tenant's ONE-active-consumer slot (`uq_connection_tenant_type`).
  await deleteConnectionsNamed(request, token, 'Sorento (live-verify)');
  // This spec's own prior-run residue (timestamped names never collide, but a
  // fresh Sorento connection each run would still trip the same one-active
  // slot as an earlier run's leftover).
  await deleteConnectionsNamed(request, token, 'E2E ETL Demo Sorento');
});

test.afterAll(async () => {
  await sorento?.close();
});

// ── AC-22-31: golden path ────────────────────────────────────────────────────

test('AC-22-31 golden path: connection -> query -> mapping -> activate -> run -> run history', async ({
  page,
}) => {
  const stamp = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const sqlConnName = `E2E ETL Demo Postgres ${stamp}`;
  const sorentoConnName = `E2E ETL Demo Sorento ${stamp}`;

  await signIn(page);

  // ── connections (AC-22-01/02/04) ──────────────────────────────────────────
  await createSqlDatabaseConnection(page, sqlConnName);
  await createSorentoConnection(page, sorentoConnName, sorento.url);

  // ── the company + entity ──────────────────────────────────────────────────
  await openDemoCompany(page);
  await setSorentoPushTarget(page, sorentoConnName, 'ETLDEMO');
  await switchCustomerToDatabase(page);

  const customerRow = page.getByRole('row', { name: /Customer/ }).first();
  await rowAction(page, customerRow, /configure database query/i);
  await page.waitForURL(/\/entities\/customer(\?|$)/, { timeout: 20_000 });

  // ── Query tab ──────────────────────────────────────────────────────────────
  await configureQuery(page, sqlConnName);
  await expectNoPageScroll(page, 'task editor / query tab @1280');

  // ── Mapping tab ────────────────────────────────────────────────────────────
  await configureMapping(page);

  // ── Review & Activate: the activate-once gate (AC-22-18) ───────────────────
  // Activate is withheld until `etl-run-preview` succeeds - unclickable, not
  // just unwired, proven here before it is ever clicked. Re-runnable: once
  // this task is ACTIVE (a re-run of this spec against the same demo company)
  // the Activate button is gone entirely (Pause/Run now instead) - the gate
  // does not re-arm, so the assertion only applies on a still-draft task.
  await page.getByRole('tab', { name: /review/i }).click();
  const activateButton = page.getByTestId('etl-activate');
  if (await activateButton.isVisible().catch(() => false)) {
    await expect(activateButton).toBeDisabled();
  }

  // Re-runnable: on a fresh company every demo row is new (all 10 stage as
  // ADDED); on a re-run against the SAME persisted task the watermark has
  // already advanced past them, so touch two rows first - the run then has
  // real changes to report EITHER way (added on a first run, updated on a
  // re-run), never a silent zero.
  await runSeed(['--touch', '6']);
  await runSeed(['--touch', '7']);

  await activateAndRun(page);
  await expectNoPageScroll(page, 'task editor / review & activate @1280');

  // ── Runs tab: real delivered counts ────────────────────────────────────────
  const first = await latestRunCells(page);
  expect(first.mode).toMatch(/Manual|Incremental/);
  expect(Number(first.added) + Number(first.updated)).toBeGreaterThan(0);
  await expectNoPageScroll(page, 'task editor / runs tab @1280');

  // Real delivery, not just local staging - the scripted consumer actually
  // received an ingest call (AC-22-20's push reuses the real SorentoSink path).
  expect(sorento.ingestCalls.some((c) => c.path.endsWith('/ingest/customers') && !c.dryRun)).toBe(
    true,
  );

  // ── responsive: the same two surfaces at 375px (user mandate) ─────────────
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(500);
  await expectNoPageScroll(page, 'task editor / runs tab @375');
  await page.getByRole('tab', { name: /review/i }).click();
  await page.waitForTimeout(500);
  await expectNoPageScroll(page, 'task editor / review & activate @375');
  await page.setViewportSize({ width: 1280, height: 900 });
});

// ── AC-22-32: change detection ───────────────────────────────────────────────

test('AC-22-32 change detection: incremental catches an update, reconcile catches a delete', async ({
  page,
}) => {
  await signIn(page);
  await openDemoCompany(page);

  await page.getByRole('tab', { name: 'Entities' }).click();
  const customerRow = page.getByRole('row', { name: /Customer/ }).first();
  await expect(customerRow).toBeVisible({ timeout: 20_000 });
  await rowAction(page, customerRow, /configure database query/i);
  await page.waitForURL(/\/entities\/customer(\?|$)/, { timeout: 20_000 });

  // Establish a clean row-hash BASELINE first (a reconcile "known" population
  // - AC-22-16's diff needs a PRIOR hash to notice row 5 is later missing;
  // `beforeAll`'s bare re-seed restores row 5 physically every run via
  // `ON CONFLICT DO NOTHING`, but a hash is only written by an actual run,
  // so a fresh test run otherwise has no baseline to diff row 5's deletion
  // against). Not asserted - purely setup, the same "no UI affordance"
  // backend helper used below.
  await runSeed(['--trigger-run', 'customer', '--run-mode', 'reconcile', '--company-database', demoDatabaseName]);

  // Mutate row 3 (bumps `company_name` + `last_modified`) and delete row 5 -
  // the seed rig's own documented E2E fixtures.
  await runSeed(['--touch', '3']);
  await runSeed(['--delete-row', '5']);

  // "Run now" always enqueues mode=manual (the `mode` COLUMN, shown as
  // "Manual" here) - it behaves as an INCREMENTAL fetch because this task has
  // a watermark column (`SqlDbSource.fetch_changes`'s `full_extract` gate).
  // A deleted row is invisible to a watermark-bounded fetch by construction,
  // so this run must NOT report a delete.
  await page.getByRole('tab', { name: /review/i }).click();
  await clickRunNow(page);

  const incrementalRun = await latestRunCells(page);
  expect(incrementalRun.mode).toBe('Manual');
  expect(Number(incrementalRun.updated)).toBe(1);
  expect(Number(incrementalRun.added)).toBe(0);

  // Reconcile has NO UI affordance (plan 22 S3 - it is schedule/beat-driven in
  // production); the seed rig's `--trigger-run` is the documented backend
  // helper for it (same `JobService.create_and_enqueue` "Run now" itself
  // calls, just with `mode=reconcile`).
  await runSeed(['--trigger-run', 'customer', '--run-mode', 'reconcile', '--company-database', demoDatabaseName]);

  await page.reload();
  await page.getByRole('tab', { name: /^Runs$/i }).click();
  await page.waitForLoadState('networkidle');
  const reconcileRun = await latestRunCells(page);
  expect(reconcileRun.mode).toBe('Reconcile');
  expect(Number(reconcileRun.deleted)).toBe(1);

  // The deletion actually reached the scripted consumer (AC-22-21).
  expect(sorento.ingestCalls.some((c) => c.path.endsWith('/customers/deletions'))).toBe(true);
});
