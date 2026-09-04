/**
 * AC-DLA-13: `DataGrid` defaults (`headerSticky: true`, `columnsResizable:
 * true`, `columnsMovable: true`, sticky header uses `--z-sticky-content`),
 * the scroller (`overflow-x-auto overscroll-x-contain`, fade, mobile pin,
 * `tabular-nums`), the resize handle's pointer capture, and the "zero list
 * wraps DataGridTable in a ScrollArea" inventory. Source-scan tests, this
 * repo's established idiom for a property of the whole tree (see
 * `css/design-tokens.test.ts`).
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

describe('AC-DLA-13 DataGrid defaults + scroller + pinned column + tabular-nums', () => {
  it('DataGrid defaults headerSticky/columnsResizable/columnsMovable to true', () => {
    const src = read('components/ui/data-grid.tsx');
    const defaultsBlock = src.match(/tableLayout:\s*\{([\s\S]*?)\},\n\s*tableClassNames/)?.[1] ?? '';
    expect(defaultsBlock).toMatch(/headerSticky:\s*true/);
    expect(defaultsBlock).toMatch(/columnsResizable:\s*true/);
    expect(defaultsBlock).toMatch(/columnsMovable:\s*true/);
  });

  it('the sticky header class references the named z-scale token, not a bare number', () => {
    const src = read('components/ui/data-grid.tsx');
    expect(src).toContain('z-(--z-sticky-content)');
  });

  it('DataGridTableBase owns an overflow-x-auto overscroll-x-contain scroller with a right-edge fade', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toContain('overflow-x-auto');
    expect(src).toContain('overscroll-x-contain');
    expect(src).toContain('useHorizontalOverflow');
  });

  it('the table body carries tabular-nums', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toMatch(/data-slot="data-grid-table"[\s\S]{0,400}tabular-nums/);
  });

  it('the resize handle captures the pointer', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toMatch(/DataGridTableHeadRowCellResize[\s\S]{0,600}setPointerCapture/);
  });

  it('under sm the first non-select column pins left (head + body cells)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toContain('max-sm:sticky');
  });

  it('every grid-item wrapper around DataGridTableBase carries min-w-0 (else the PAGE scrolls sideways, not the grid)', () => {
    // `CardTable` is `display: grid`; a grid item defaults to `min-width:
    // auto` and refuses to shrink below the table's intrinsic width without
    // this - caught live on Users at 375 (jsdom has no real layout to catch
    // it, hence the explicit source-scan here).
    for (const file of [
      'components/ui/data-grid-table.tsx',
      'components/ui/data-grid-table-dnd.tsx',
      'components/ui/data-grid-table-dnd-rows.tsx',
    ]) {
      expect(read(file), file).toContain('className="relative min-w-0"');
    }
  });

  it('zero list under components/platform/** wraps DataGridTableDnd/DataGridTableDndRows/DataGridTable in a ScrollArea', () => {
    const offenders = walk(['components/platform'])
      .filter((f) => {
        const src = read(f);
        if (!src.includes('<ScrollArea')) return false;
        return /<ScrollArea[^]*?<DataGridTable(Dnd|DndRows)?[\s/]/.test(src) && /<\/ScrollArea>/.test(src);
      })
      .map((f) => f.replace(repoRoot + path.sep, ''));
    expect(offenders).toEqual([]);
  });
});
