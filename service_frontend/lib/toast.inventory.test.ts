/**
 * AC-DLA-51 - the one toast standard (ported from Sorento's M6-04, this
 * repo's equivalent).
 *
 * `lib/toast.ts` wraps sonner so a success/info/warning clears itself
 * (4000ms) and an error waits for the reader to dismiss it (`duration:
 * Infinity` + a close button). The wrapper only holds that promise while it
 * is the ONLY door to sonner: a file that imports `toast` straight from
 * `'sonner'` gets neither default, and the mistake is invisible until
 * someone notices a toast vanished mid-read or never went away.
 *
 * Three legitimate direct importers: `components/ui/sonner.tsx` (mounts
 * sonner's `<Toaster>`), `lib/toast.ts` itself (the wrapper), and
 * `components/platform/resource-actions/deferred-toast.tsx` (the T5 grace-
 * window countdown toast - it needs `toast.custom`/`toast.dismiss` with a
 * fixed `id` + `duration` sonner's own API shape, predates this wrapper, and
 * is explicitly named in AC-DLA-51's text). Everything else, including test
 * files, goes through the wrapper so a mocked `sonner` module cannot
 * silently diverge from what the app actually calls.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');

// This file itself necessarily contains the guarded-against pattern (it is
// the pattern's own description + regex) - exclude it from the corpus it
// scans, the same self-exclusion trick this repo's other retirement-guard
// test uses for itself.
const THIS_FILE = 'lib/toast.inventory.test.ts';

const ALLOWED_DIRECT_IMPORTERS = new Set([
  'lib/toast.ts',
  'components/ui/sonner.tsx',
  'components/platform/resource-actions/deferred-toast.tsx',
  // `branding.test.tsx` mocks 'sonner' AND imports its `toast` back in to
  // assert against the mock directly (the component under test goes
  // through the wrapper - the test needs the underlying spy). Every OTHER
  // wrapper/mount/countdown TEST asserts via captured `vi.fn()`s from its
  // `vi.mock('sonner', () => ...)` factory instead, so none of them import
  // 'sonner' as a statement and none needs a slot here.
  'components/platform/branding/branding.test.tsx',
]);

/** Every `.ts`/`.tsx` under the app, tests included - a mock is a call site too. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const roots = ['app', 'components', 'hooks', 'lib', 'providers', 'services'];
  const walk = (dir: string) => {
    const full = path.join(repoRoot, dir);
    if (!fs.existsSync(full)) return;
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(entryPath);
      } else if (/\.(ts|tsx)$/.test(entry.name)) {
        out.push(entryPath);
      }
    }
  };
  for (const root of roots) walk(root);
  return out;
}

function importsSonnerDirectly(relFile: string): boolean {
  const src = fs.readFileSync(path.join(repoRoot, relFile), 'utf8');
  return /from ['"]sonner['"]/.test(src);
}

describe('AC-DLA-51 toast standard - one door to sonner', () => {
  it('no file outside the three allowed importers imports from sonner directly', () => {
    const offenders = sourceFiles().filter(
      (file) =>
        file !== THIS_FILE && !ALLOWED_DIRECT_IMPORTERS.has(file) && importsSonnerDirectly(file),
    );
    expect(offenders).toEqual([]);
  });

  it('every allowlisted importer still exists and still imports sonner directly (the allowlist cannot grow stale)', () => {
    for (const file of ALLOWED_DIRECT_IMPORTERS) {
      const full = path.join(repoRoot, file);
      expect(fs.existsSync(full), `${file} should exist`).toBe(true);
      expect(importsSonnerDirectly(file), `${file} should import from sonner`).toBe(true);
    }
  });
});
