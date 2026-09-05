/**
 * AC-DLA-60 - the Metronic `demo2`-`demo10` layouts (D8, plan-review-confirmed
 * dead demo: deleted, not migrated) and their `app/(protected)/components/`
 * dashboard content pages are gone for good; only `demo1` is mounted
 * (`app/(protected)/layout.tsx` hardcodes `Demo1Layout`). A guard test so a
 * future `npm install`/copy-paste can't quietly resurrect one.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..', '..');
const DELETED_DEMO_NUMBERS = [2, 3, 4, 5, 6, 7, 8, 9, 10];

describe('AC-DLA-60 demo2-10 stay deleted', () => {
  it('app/components/layouts/demoN does not exist for N in 2..10', () => {
    for (const n of DELETED_DEMO_NUMBERS) {
      const dir = path.join(repoRoot, 'app', 'components', 'layouts', `demo${n}`);
      expect(fs.existsSync(dir), `app/components/layouts/demo${n} should not exist`).toBe(false);
    }
  });

  it('app/(protected)/components/demoN does not exist for N in 2..10', () => {
    for (const n of DELETED_DEMO_NUMBERS) {
      const dir = path.join(repoRoot, 'app', '(protected)', 'components', `demo${n}`);
      expect(fs.existsSync(dir), `app/(protected)/components/demo${n} should not exist`).toBe(false);
    }
  });

  it('only demo1 remains under app/components/layouts', () => {
    const dir = path.join(repoRoot, 'app', 'components', 'layouts');
    const entries = fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory());
    expect(entries.map((e) => e.name)).toEqual(['demo1']);
  });

  it('only demo1 remains under app/(protected)/components', () => {
    const dir = path.join(repoRoot, 'app', '(protected)', 'components');
    const entries = fs.readdirSync(dir, { withFileTypes: true }).filter((e) => e.isDirectory());
    expect(entries.map((e) => e.name)).toEqual(['demo1']);
  });

  it('the protected shell hardcodes Demo1Layout, not a settings.layout switch', () => {
    const src = fs.readFileSync(path.join(repoRoot, 'app', '(protected)', 'layout.tsx'), 'utf8');
    expect(src).toContain('Demo1Layout');
    expect(src).not.toMatch(/settings\.layout\s*===\s*'demo[2-9]/);
  });
});
