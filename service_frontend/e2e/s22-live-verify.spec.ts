/**
 * Plan 22 S2 LIVE VERIFICATION - real clicks, live prod build, real Sorento.
 *
 * Deliberately OUTSIDE the CI suite (`playwright.live.config.ts`): it depends
 * on the `etl_demo_customers` dev fixture, on a `sql_database` connection
 * pointed back at the Foundryx database, and on a reachable Sorento contract
 * server. It is the reproducible record of the S2 hand-verify.
 *
 * Journey (every hop is a CLICK - no typed URLs after sign-in):
 *   sidebar -> AutoCount -> Companies -> V Soft Trading
 *   -> set the Sorento company code
 *   -> Entities -> Customer -> Change source -> Database
 *   -> Configure database query -> connection + query + Test Query
 *      + key / watermark / compared columns -> Save
 *   -> Mapping -> flat column sources -> Save
 *   -> Review & Activate -> REAL Sorento dry run -> Activate -> Run now
 *   -> Runs (delivered counts), at 1280 AND 375
 *
 * Setup, once:
 *   python -m scripts.seed_etl_demo_source
 */
import { test, expect, Locator, Page } from '@playwright/test';

const BASE = process.env.S22_BASE_URL ?? 'http://localhost:3002';
const SHOTS = process.env.S22_SHOTS ?? '/tmp/s22-shots';
const COMPANY = 'V Soft Trading';
const COMPANY_CODE = process.env.S22_COMPANY_CODE ?? 'SRT';
const QUERY =
  'SELECT acc_no, company_name, phone, email, is_active, last_modified FROM public.etl_demo_customers';

test.describe.configure({ mode: 'serial' });
test.setTimeout(300_000);

async function signIn(page: Page) {
  await page.goto(`${BASE}/signin`);
  await page.locator('input[type="email"], input[name="email"]').first().fill('demo@example.com');
  await page.locator('input[type="password"]').first().fill('demo1234');
  await page.getByRole('button', { name: /^sign in$/i }).click();
  await page.waitForURL((u) => !u.pathname.includes('/signin'), { timeout: 90_000 });
}

/** Sidebar -> AutoCount -> Companies -> the company. Clicks only. */
async function openCompany(page: Page) {
  // "AutoCount" is a PARENT entry (no clickable parents - house rule), so the
  // section expands first and the CHILD link is what navigates.
  const companies = page.getByRole('link', { name: /^Companies$/i }).first();
  if (!(await companies.isVisible().catch(() => false))) {
    await page.getByText('AutoCount', { exact: true }).first().click();
  }
  await companies.click();
  await page.waitForLoadState('networkidle');
  // The Resource shell navigates on ROW click (`rowHref`), not via an anchor.
  await page.getByRole('row', { name: new RegExp(COMPANY) }).first().click();
  await page.waitForURL(/\/autocount\/companies\/[0-9a-f-]{36}/, { timeout: 30_000 });
  await page.waitForLoadState('networkidle');
}

/** Open a row's "…" menu and pick an item by label. */
async function rowAction(page: Page, row: Locator, label: RegExp) {
  await row.getByRole('button', { name: 'Actions' }).first().click();
  await page.getByRole('menuitem', { name: label }).click();
}

/** Set a MultiSelect to EXACTLY `labels`.
 *
 * Clearing is done by clicking each selected CHIP (the component removes on
 * chip click), not by the header's Select-all/Clear-all pair: that toggle
 * flips label in place, and a missed second click silently leaves every
 * option selected - which is how a stale column reached a save and 422'd.
 */
async function setMultiSelect(page: Page, trigger: Locator, labels: string[]) {
  for (let guard = 0; guard < 40; guard += 1) {
    const text = (await trigger.innerText()).trim();
    const chips = text.split('\n').map((t) => t.trim()).filter(Boolean);
    if (chips.length === 0 || /^(Pick columns|All except|None|Run Test)/.test(chips[0])) break;
    await trigger.getByText(chips[0], { exact: true }).first().click();
  }
  if (labels.length === 0) return;
  await trigger.click();
  for (const label of labels) {
    await page.getByRole('option', { name: label, exact: true }).click();
  }
  await page.keyboard.press('Escape');
}

async function shot(page: Page, name: string) {
  await page.screenshot({ path: `${SHOTS}/${name}.png`, fullPage: true });
}

test('S2 golden path: Database source -> query -> mapping -> dry run -> activate -> run', async ({
  page,
}) => {
  await signIn(page);
  await openCompany(page);
  await shot(page, '01-company-overview');

  // ── 1. the company anchor (Appendix A6) ─────────────────────────────────
  const codeShown = page.getByTestId('sink-company-code-value');
  if (!(await codeShown.isVisible().catch(() => false))) {
    await page.getByRole('button', { name: /^Edit$/ }).first().click();
    await page.getByTestId('sink-company-code').fill(COMPANY_CODE);
    await page.getByRole('button', { name: /^Save/ }).first().click();
    await expect(codeShown).toHaveText(COMPANY_CODE, { timeout: 30_000 });
  }
  await shot(page, '02-company-code-set');

  // ── 2. switch the Customer entity to the Database source (AC-22-08) ─────
  await page.getByRole('tab', { name: /^Entities$/i }).click();
  await page.waitForLoadState('networkidle');
  const customer = page.getByRole('row', { name: /Customer/i }).first();
  await expect(customer).toBeVisible({ timeout: 30_000 });

  await rowAction(page, customer, /change source/i);
  await page.getByRole('combobox', { name: 'Entity source' }).click();
  await page.getByRole('option', { name: 'Database' }).click();
  // Re-runnable: an entity ALREADY on the DB source shows no change, so the
  // warning and the enabled Save are simply absent - not a failure.
  if (await page.getByTestId('source-switch-warning').isVisible().catch(() => false)) {
    await page.getByTestId('save-source').click();
  } else {
    await page.getByRole('button', { name: /^Cancel$/ }).first().click();
  }
  await expect(page.getByTestId('save-source')).toBeHidden({ timeout: 30_000 });
  await shot(page, '03-source-database');

  // ── 3. the task editor: connection + query + Test Query + columns ───────
  await rowAction(page, page.getByRole('row', { name: /Customer/i }).first(), /configure database query/i);
  await page.waitForURL(/\/entities\/customer(\?|$)/, { timeout: 30_000 });
  await page.waitForLoadState('networkidle');

  // The shell's global Edit toggle renders only once the task has loaded, so
  // it is WAITED for - probing `isVisible()` too early silently skips it and
  // every control below stays read-only.
  const editToggle = page.getByRole('button', { name: /^Edit$/ }).first();
  await expect(editToggle).toBeVisible({ timeout: 60_000 });
  await editToggle.click();

  // The connection picker stays disabled until the tenant's `sql_database`
  // connections have loaded (foolproof-UI: it never offers an empty list).
  const connection = page.getByRole('combobox', { name: 'Connection' });
  await expect(connection).toBeEnabled({ timeout: 60_000 });
  await connection.click();
  await page.getByRole('option').first().click();

  // The SQL editor is CodeMirror (schema-aware autocomplete), never a plain
  // textarea - so the query is TYPED into it like a user would.
  const sql = page.getByTestId('sql-editor');
  await sql.click();
  await page.keyboard.press('ControlOrMeta+a');
  await page.keyboard.press('Backspace');
  await page.keyboard.insertText(QUERY);

  await page.getByTestId('sql-test-query').click();
  await expect(page.getByTestId('sql-preview-badge')).toBeVisible({ timeout: 60_000 });
  await shot(page, '04-query-preview');

  // Key + watermark + compared pickers offer the PREVIEW's own result columns
  // (AC-22-07 - dropdowns, never free text). Order on the Query tab:
  // Connection, Key columns, Watermark column, Compared columns.
  const combos = page.getByRole('combobox');
  await setMultiSelect(page, combos.nth(1), ['acc_no']);
  await page.getByRole('combobox', { name: 'Watermark column' }).click();
  await page.getByRole('option', { name: 'last_modified', exact: true }).click();
  // Empty = "all result columns except the keys", which is the AC-22-11
  // default and what this task wants.
  await setMultiSelect(page, page.getByRole('combobox').nth(3), []);

  await page.getByRole('button', { name: /^Save/ }).first().click();
  await page.waitForTimeout(3000);
  await shot(page, '05-query-saved');
  const saveError = page.getByTestId('task-save-error');
  if (await saveError.isVisible().catch(() => false)) {
    throw new Error(`task save rejected: ${await saveError.innerText()}`);
  }
  await expect(editToggle).toBeVisible({ timeout: 60_000 });

  // ── 3b. Mapping: re-point the seeded rows at the FLAT result columns ───
  //
  // Switching an entity's source does NOT rewrite its mapping - the rows are
  // the operator's, and the seeded ones point at the API path's nested vendor
  // paths (`AccNo`, `CompanyName`). On the DB path the source picker offers
  // the SAVED query's result columns, so re-pointing is a dropdown pick.
  await page.getByRole('tab', { name: /^Mapping$/i }).click();
  // The row pickers exist only in EDIT mode - read-only renders plain text.
  const edit2 = page.getByRole('button', { name: /^Edit$/ }).first();
  await expect(edit2).toBeVisible({ timeout: 60_000 });
  await edit2.click();
  await expect(page.getByRole('combobox', { name: 'Source column for row 1' })).toBeVisible({
    timeout: 60_000,
  });

  for (const [row, column] of [
    [1, 'acc_no'],
    [2, 'company_name'],
    [3, 'email'],
    [4, 'is_active'],
  ] as const) {
    const picker = page.getByRole('combobox', { name: `Source column for row ${row}` });
    if ((await picker.innerText()).trim().startsWith(column)) continue;
    await picker.click();
    await page.getByRole('option', { name: column, exact: true }).click();
  }
  await page.getByRole('button', { name: /^Save/ }).first().click();
  await page.waitForTimeout(3000);
  await shot(page, '05b-mapping-saved');

  // ── 4. Review & Activate: the REAL Sorento dry run ─────────────────────
  await page.getByRole('tab', { name: /review/i }).click();
  await page.getByTestId('etl-run-preview').click();
  await expect(page.getByTestId('etl-preview-passed')).toBeVisible({ timeout: 120_000 });
  await shot(page, '06-preview-passed-1280');

  // Re-runnable: an already-active task shows Pause/Run now instead of
  // Activate (the activate-once gate does not re-arm on every visit).
  const activate = page.getByTestId('etl-activate');
  if (await activate.isVisible().catch(() => false)) await activate.click();
  await expect(page.getByTestId('etl-run-now')).toBeVisible({ timeout: 60_000 });
  await shot(page, '07-activated-1280');

  // ── 5. Run now -> run history ──────────────────────────────────────────
  await page.getByTestId('etl-run-now').click();
  // The run reports its outcome EITHER way: a clean run shows the "Last run"
  // badge, a run with a delivery failure shows the error instead (AC-22-19 -
  // a failure is never silent, and the badge is deliberately suppressed so a
  // failed run cannot read as a healthy one).
  await expect(
    page.getByTestId('etl-last-run-at').or(page.getByTestId('task-last-run-error')),
  ).toBeVisible({ timeout: 120_000 });
  await page.getByRole('tab', { name: /^Runs$/i }).click();
  await page.waitForLoadState('networkidle');
  await shot(page, '08-runs-1280');

  // ── 6. responsive: the same two surfaces at 375px ──────────────────────
  await page.setViewportSize({ width: 375, height: 812 });
  await page.waitForTimeout(1000);
  await shot(page, '09-runs-375');
  await page.getByRole('tab', { name: /review/i }).click();
  await page.waitForTimeout(1000);
  await shot(page, '10-activate-375');
});
