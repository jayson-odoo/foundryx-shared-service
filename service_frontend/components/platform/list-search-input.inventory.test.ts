/**
 * AC-DLA-54 - `list-search-input.tsx` is adopted by `ResourceList` and the
 * palette search; `SearchSelect`/`MultiSelect` (built on the shared
 * `Command`/`CommandInput` primitive) stay on `useDebounce`/`value` for
 * their own filtering, with no leading-icon settling indicator on
 * `CommandInput` (T6 fix round 1 item 8 - cmdk filters synchronously, so
 * there is nothing to indicate; `command.test.tsx` covers the static icon).
 * Zero hand-rolled search `setTimeout` debounce remains anywhere.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

describe('AC-DLA-54 list-search-input adoption', () => {
  it('ResourceList imports ListSearchInput', () => {
    const src = read('components/platform/resource-list/resource-list.tsx');
    expect(src).toContain("from '@/components/platform/list-search-input'");
    expect(src).toContain('<ListSearchInput');
  });

  it('the palette search imports ListSearchInput', () => {
    const src = read('components/platform/palette/collapsible-palette.tsx');
    expect(src).toContain("from '@/components/platform/list-search-input'");
    expect(src).toContain('<ListSearchInput');
  });

  it('SearchSelect and MultiSelect control CommandInput (so it can settle)', () => {
    const searchSelect = read('components/platform/search-select/search-select.tsx');
    const multiSelect = read('components/platform/multi-select/multi-select.tsx');
    expect(searchSelect).toMatch(/<CommandInput[\s\S]*?value=\{query\}/);
    expect(multiSelect).toMatch(/<CommandInput[\s\S]*?value=\{query\}/);
  });

  it('zero hand-rolled setTimeout search debounce remains (useDebounce is the only mechanism)', () => {
    const roots = ['app', 'components', 'hooks'];
    const offenders: string[] = [];
    const walk = (dir: string) => {
      const full = path.join(repoRoot, dir);
      if (!fs.existsSync(full)) return;
      for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
        const entryPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          if (entry.name === 'node_modules' || entry.name === '.next') continue;
          walk(entryPath);
        } else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.includes('.test.')) {
          if (entryPath.endsWith('hooks/use-debounce.ts')) continue;
          const src = fs.readFileSync(path.join(repoRoot, entryPath), 'utf8');
          // A setTimeout whose callback sets something search/query-named -
          // the hand-rolled-debounce shape this AC bans.
          if (/setTimeout\([^)]*=>\s*set(Search|Query|DebouncedSearch|DebouncedQuery)/s.test(src)) {
            offenders.push(entryPath);
          }
        }
      }
    };
    for (const root of roots) walk(root);
    expect(offenders).toEqual([]);
  });
});
