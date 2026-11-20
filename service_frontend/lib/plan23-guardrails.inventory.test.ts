/**
 * AC-DLA-64 - the plan 23 (design-language alignment) guardrail-test
 * inventory. Asserts that every test file the T8 UAC names EXISTS and
 * NAMES its own AC id somewhere in its source (a `describe`/`it` title, a
 * doc comment, or both) - so a future rename/move/deletion of any of these
 * guardrails fails loudly here instead of silently dropping coverage.
 *
 * This is a meta-test over source files, not a re-run of each test's own
 * assertions (those already run under `npm test` as their own files).
 *
 * `components/ui/ui-table.inventory.test.ts`: AC-DLA-64's own text says
 * `components/platform/resource-list/ui-table.inventory.test.ts`, but T7
 * (which built the DataGrid migration this test guards) put it under
 * `components/ui/` instead - alongside the other primitive-level
 * inventories (`a11y-guardrails`, `pressed-class`, `tabs`, `data-grid`),
 * which is where a "no raw `<table>`/`ui/table` importer" check actually
 * belongs (it scans `app/**` + `components/platform/**`, so its own home
 * under `components/ui/` is correct - that tree is explicitly EXCLUDED from
 * the scan as "the primitives themselves, not product consumers"). Kept at
 * T7's location; this comment is the disclosed path deviation the T8 brief
 * asked for.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');

interface GuardrailFile {
  /** Repo-relative path (service_frontend as root). */
  path: string;
  /** The AC id this file's source must contain. */
  acId: string;
}

const GUARDRAIL_FILES: GuardrailFile[] = [
  { path: 'css/design-tokens.test.ts', acId: 'AC-DLA-01' },
  { path: 'lib/motion.test.ts', acId: 'AC-DLA-19' },
  // components/ui/*.inventory.test.ts - row-open, tabs, scroller,
  // a11y-guardrails, pressed-class, deleted-components.
  { path: 'components/ui/data-grid-table.rowHref.test.tsx', acId: 'AC-DLA-14' },
  { path: 'components/ui/tabs.inventory.test.ts', acId: 'AC-DLA-12' },
  { path: 'components/ui/data-grid.inventory.test.ts', acId: 'AC-DLA-13' },
  { path: 'components/ui/a11y-guardrails.inventory.test.ts', acId: 'AC-DLA-59' },
  { path: 'components/ui/pressed-class.inventory.test.ts', acId: 'AC-DLA-58' },
  { path: 'components/ui/deleted-motion-components.guard.test.ts', acId: 'AC-DLA-25' },
  { path: 'components/platform/page-header/page-header.inventory.test.ts', acId: 'AC-DLA-27' },
  { path: 'app/(protected)/loading-inventory.test.tsx', acId: 'AC-DLA-48' },
  { path: 'lib/toast.inventory.test.ts', acId: 'AC-DLA-51' },
  {
    path: 'components/platform/resource-actions/confirm-carve-outs.inventory.test.ts',
    acId: 'AC-DLA-43',
  },
  // See the file-level comment above - T7's actual location, not the UAC
  // text's literal path.
  { path: 'components/ui/ui-table.inventory.test.ts', acId: 'AC-DLA-56' },
  { path: 'lib/white-label.guard.test.ts', acId: 'AC-DLA-71' },
  { path: 'app/components/layouts/deleted-layouts.guard.test.ts', acId: 'AC-DLA-60' },
];

describe('AC-DLA-64 - the guardrail-test inventory exists, names its AC id, and runs under npm test', () => {
  it.each(GUARDRAIL_FILES)('$path exists and contains $acId', ({ path: rel, acId }) => {
    const full = path.join(repoRoot, rel);
    expect(fs.existsSync(full), `${rel} should exist`).toBe(true);
    const src = fs.readFileSync(full, 'utf8');
    expect(src.includes(acId), `${rel} should contain ${acId}`).toBe(true);
  });

  it('the inventory itself is not empty (a silently-emptied list would pass every it.each above)', () => {
    expect(GUARDRAIL_FILES.length).toBeGreaterThanOrEqual(15);
  });
});
