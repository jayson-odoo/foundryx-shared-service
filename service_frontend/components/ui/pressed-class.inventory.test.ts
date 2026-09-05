/**
 * AC-DLA-58 - every raw `<button` under `app/(protected)` and
 * `components/platform` either imports the shared `Button` primitive (which
 * already carries `PRESSED_CLASS` unconditionally, `button.tsx`) or the file
 * itself imports `PRESSED_CLASS` from `primitive-classes` and threads it into
 * the tag's own className. Checked at file granularity (not per-tag): a file
 * mixing `Button` with a couple of hand-rolled `<button>`s for a bespoke
 * shape still needs `PRESSED_CLASS` imported for those, since importing
 * `Button` alone proves nothing about a SEPARATE raw tag in the same file.
 *
 * Baseline (T7 sweep, before fixes): 17 files. All fixed this slice - the
 * allowlist starts and stays empty; a future genuine exception needs a named
 * reason here, not a silent add.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');
const ALLOWLIST: string[] = [];

function sourceFiles(): string[] {
  const out: string[] = [];
  const roots = ['app/(protected)', 'components/platform'];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (entry.name.endsWith('.tsx') && !entry.name.includes('.test.')) {
        out.push(full);
      }
    }
  };
  for (const root of roots) walk(path.join(repoRoot, root));
  return out;
}

describe('AC-DLA-58 raw <button carries pressed feedback', () => {
  it('every file with a raw <button imports Button or PRESSED_CLASS (allowlist empty)', () => {
    const allowed = new Set(ALLOWLIST.map((f) => path.join(repoRoot, f)));
    const offenders = sourceFiles().filter((f) => {
      if (allowed.has(f)) return false;
      const src = fs.readFileSync(f, 'utf8');
      if (!/<button(\s|>)/.test(src)) return false;
      const hasButtonImport = /from ['"]@\/components\/ui\/button['"]/.test(src);
      const hasPressedClass = /PRESSED_CLASS/.test(src);
      return !hasButtonImport && !hasPressedClass;
    });
    expect(offenders.map((f) => f.replace(repoRoot + path.sep, ''))).toEqual([]);
  });
});
