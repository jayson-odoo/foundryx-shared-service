/**
 * AC-DLA-12: `TabsList` defaults to `variant="line"`; the two-part inventory
 * pins the exhaustive set of `variant="default"` sites (the segmented
 * two/three-option switches this repo actually has, found by grep - see the
 * T2 test report for the ruling on `resource-list.tsx`'s Active|Trashed and
 * card/list controls, which are `ToggleGroup`, not `TabsList`, so they carry
 * no pin at all).
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

function walk(dirs: string[]): string[] {
  const out: string[] = [];
  const visit = (dir: string) => {
    const full = path.join(repoRoot, dir);
    if (!fs.existsSync(full)) return;
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const entryPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        visit(entryPath);
      } else if (/\.tsx?$/.test(entry.name) && !entry.name.includes('.test.')) {
        out.push(entryPath);
      }
    }
  };
  for (const dir of dirs) visit(dir);
  return out;
}

describe('AC-DLA-12 tabs default variant + segmented keepers', () => {
  it('tabsListVariants and the context both default to variant "line"', () => {
    const src = read('components/ui/tabs.tsx');
    // Both cva blocks' defaultVariants.
    const defaultVariantHits = src.match(/defaultVariants:\s*\{[\s\S]{0,220}?variant:\s*'line'/g) ?? [];
    expect(defaultVariantHits.length).toBeGreaterThanOrEqual(2);
    expect(src).toMatch(/React\.createContext<TabsContextType>\(\{\s*variant:\s*'line'/);
    expect(src).toMatch(/variant = 'line'/);
  });

  it('TabsList base class scrolls horizontally with a hidden scrollbar', () => {
    const src = read('components/ui/tabs.tsx');
    expect(src).toContain('overflow-x-auto');
    expect(src).toContain('[scrollbar-width:none]');
    expect(src).toContain('useHorizontalOverflow');
  });

  it('the right-edge fade is an always-mounted opacity overlay, never mask-image toggling (AC-DLA-14 fix round 1)', () => {
    const src = read('components/ui/tabs.tsx');
    expect(src).not.toContain('[mask-image:');
    expect(src).toMatch(/data-slot="tabs-fade"[\s\S]{0,120}data-fade=\{isFading\}/);
    expect(src).toMatch(/opacity-0 transition-opacity duration-\(--duration-fast\) data-\[fade=true\]:opacity-100/);
  });

  it('TabsTrigger uses an inset, zero-offset focus ring (fix round 1: the scroller clips an outer ring)', () => {
    const src = read('components/ui/tabs.tsx');
    expect(src).toMatch(/focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring focus-visible:ring-offset-0/);
  });

  it('TabsTrigger carries PRESSED_CLASS', () => {
    const src = read('components/ui/tabs.tsx');
    expect(src).toContain('PRESSED_CLASS');
  });

  /** Every real TabsList `variant="default"` pin found in the tree, minus tabs.tsx itself. */
  const KEEPERS = [
    'components/platform/autocount/formula-builder/autocount-formula-builder.tsx',
    'app/(protected)/omnichannel/inbox/components/thread-list.tsx',
  ];

  it.each(KEEPERS)('%s pins TabsList variant="default"', (file) => {
    expect(read(file)).toMatch(/<TabsList[^>]*variant="default"/);
  });

  it('no TabsList site outside the recorded keepers pins variant="default"', () => {
    const offenders = walk(['app', 'components'])
      .filter((f) => f !== 'components/ui/tabs.tsx' && f !== 'components/ui/tabs.inventory.test.ts')
      .filter((f) => !KEEPERS.includes(f))
      .filter((f) => /<TabsList[^>]*variant="default"/.test(read(f)));
    expect(offenders).toEqual([]);
  });

  it('records the keeper count as exactly 2 (T2 ruling)', () => {
    expect(KEEPERS.length).toBe(2);
  });
});
