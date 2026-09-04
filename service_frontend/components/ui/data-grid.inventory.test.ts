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

  it('the sticky header class references the named z-scale token, one step above pinned body cells (T2 fix round 2)', () => {
    const src = read('components/ui/data-grid.tsx');
    expect(src).toContain('z-(--z-sticky-header)');
    expect(src).not.toContain('z-(--z-sticky-content)');
  });

  it('the mobile-pinned HEADER cell shares the sticky thead z step; the mobile-pinned BODY cell stays one below (T2 fix round 2 - else the pinned body column paints over the header on scroll)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toMatch(/MOBILE_PIN_CLASS_HEAD\s*=[\s\S]{0,200}z-\(--z-sticky-header\)/);
    expect(src).toMatch(/MOBILE_PIN_CLASS_BODY\s*=[\s\S]{0,300}z-\(--z-sticky-content\)/);
  });

  it('DataGridTableBase owns an overflow-x-auto overscroll-x-contain scroller with a right-edge fade', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toContain('overflow-x-auto');
    expect(src).toContain('overscroll-x-contain');
    expect(src).toContain('useHorizontalOverflow');
  });

  it('the scroller is vertically bounded on the SAME element that scrolls sideways (fix round 1: headerSticky is a no-op otherwise - position:sticky sticks to whichever ancestor actually scrolls)', () => {
    const dataGridSrc = read('components/ui/data-grid.tsx');
    expect(dataGridSrc).toContain('max-h-(--grid-max-h) overflow-y-auto');
    expect(dataGridSrc).toMatch(/scroller\?:\s*string/);
    const tableSrc = read('components/ui/data-grid-table.tsx');
    expect(tableSrc).toMatch(
      /data-slot="data-grid-scroller"[\s\S]{0,120}className=\{cn\('overflow-x-auto overscroll-x-contain', props\.tableClassNames\?\.scroller\)\}/,
    );
  });

  it('--grid-max-h is defined in config.reui.css', () => {
    const css = read('css/config.reui.css');
    expect(css).toMatch(/--grid-max-h:\s*calc\(/);
  });

  it('the right-edge fade is an always-mounted opacity overlay, never conditionally rendered (fix round 1)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).not.toMatch(/\{isFading\s*&&\s*\(/);
    expect(src).toMatch(/data-slot="data-grid-fade"[\s\S]{0,80}data-fade=\{isFading\}/);
    expect(src).toMatch(/opacity-0 transition-opacity duration-\(--duration-fast\) ease-\(--ease-standard\) data-\[fade=true\]:opacity-100/);
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

  it('the mobile-pin column selector generalises past select-only (fix round 1): skips id select/__drag and meta reorderable:false/utility:true', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toMatch(/function firstDataColumnIndex[\s\S]{0,400}findIndex/);
    expect(src).toContain("column.id === 'select' || column.id === '__drag'");
    expect(src).toContain('meta?.reorderable === false');
    expect(src).toContain('meta?.utility === true');
    // The `utility` meta field is declared on ColumnMeta so a caller can opt
    // a structural column out without also lying about `reorderable`.
    const gridSrc = read('components/ui/data-grid.tsx');
    expect(gridSrc).toMatch(/utility\?:\s*boolean/);
  });

  it('the pinned cell carries the row-select drag column exemption already used by resource-list.tsx rowReorder lists', () => {
    // `__drag` (resource-list.tsx's grip column, id: '__drag') already sets
    // meta: { reorderable: false } - confirms the mobile pin skips it via
    // the SAME convention every fixed/action column in the app already uses.
    const resourceListSrc = read('components/platform/resource-list/resource-list.tsx');
    expect(resourceListSrc).toMatch(/id:\s*'__drag'/);
    expect(resourceListSrc).toMatch(/id:\s*'__drag'[\s\S]{0,400}meta:\s*\{\s*reorderable:\s*false\s*\}/);
  });

  it('the pinned cell background matches its row state via group-* variants, using OPAQUE pre-mixed tokens not the row\'s own translucent colour (fix round 1; opacity T2 fix round 3)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toContain('group-hover:max-sm:bg-(--pinned-cell-hover)');
    expect(src).toContain('group-data-[state=selected]:max-sm:bg-(--pinned-cell-selected)');
    expect(src).toContain('group-odd:max-sm:bg-(--pinned-cell-striped)');
    // The row itself carries `group` so the pinned cell has an ancestor to
    // key off - both the header row and the shared body-row class builder.
    // The ROW stays translucent (blends into its ancestor surface) - only the
    // PINNED CELL needs the opaque token, since it alone sits over unrelated
    // scrolled-under content rather than a card/dialog backdrop.
    expect(src).toContain("'group bg-muted/40'");
    expect(src).toContain("'group hover:bg-muted/40 data-[state=selected]:bg-muted/50'");
  });

  it('the pinned cell striped legs are gated on tableLayout.stripped (T2 fix round 2 - a non-stripped list must not darken odd rows)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    expect(src).toMatch(/isMobilePinned && props\.tableLayout\?\.stripped && MOBILE_PIN_CLASS_BODY_STRIPED/);
  });

  it('the mobile-pinned HEADER cell is fully opaque (T2 fix round 3 - a translucent bg-muted/40 let the scrolled-under header text of another column show through the sticky cell)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    const declaration = src.match(/const MOBILE_PIN_CLASS_HEAD =[\s\S]{0,200};/)?.[0] ?? '';
    expect(declaration).toContain('max-sm:bg-muted!');
    expect(declaration).not.toContain('bg-muted/40');
  });

  it('the mobile-pinned BODY cell wraps its children in a non-sticky clipping wrapper (T2 fix round 3 - a sticky table cell does not reliably clip overflow, letting long content bleed into the next column)', () => {
    const src = read('components/ui/data-grid-table.tsx');
    const declaration = src.match(/const MOBILE_PIN_CONTENT_CLASS_BODY =[\s\S]{0,120};/)?.[0] ?? '';
    expect(declaration).toContain('max-sm:overflow-hidden');
    expect(declaration).toContain('max-sm:truncate');
    // `content` (T4, AC-DLA-29) - `children` wrapped in the primary cell's
    // `<a href>` when the row is linkable, `children` unchanged otherwise -
    // is what the mobile-pin wrapper carries now, not raw `children`.
    expect(src).toMatch(
      /isMobilePinned \? <div className=\{MOBILE_PIN_CONTENT_CLASS_BODY\}>\{content\}<\/div> : content/,
    );
  });

  it('the pinned-cell hover/selected/striped tokens pre-mix their alpha against --background into a solid colour (T2 fix round 3)', () => {
    const css = read('css/config.reui.css');
    expect(css).toMatch(/--pinned-cell-hover:\s*color-mix\(in oklab, var\(--muted\) 40%, var\(--background\)\)/);
    expect(css).toMatch(/--pinned-cell-selected:\s*color-mix\(in oklab, var\(--muted\) 50%, var\(--background\)\)/);
    expect(css).toMatch(/--pinned-cell-striped:\s*color-mix\(in oklab, var\(--muted\) 90%, var\(--background\)\)/);
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

  /**
   * Fix round 1 widens the walk to `app/**` too (was `components/platform`
   * only). The 14 genuine hits are ALL `account/**` Metronic demo pages plus
   * the `demo1/light-sidebar` showcase team - dead code slated for wholesale
   * deletion in T7 (AC-DLA-57/60), not touched here. A new offender anywhere
   * else in the tree still fails the build.
   */
  const SCROLL_AREA_AROUND_GRID_ALLOWLIST = new Set([
    'app/(protected)/components/demo1/light-sidebar/components/teams.tsx',
    'app/(protected)/account/security/current-sessions/components/current-sessions.tsx',
    'app/(protected)/account/security/device-management/components/device.tsx',
    'app/(protected)/account/security/backup-and-recovery/components/backup.tsx',
    'app/(protected)/account/security/allowed-ip-addresses/components/ip-addresses.tsx',
    'app/(protected)/account/security/security-log/components/security-log.tsx',
    'app/(protected)/account/appearance/components/api-integrations.tsx',
    'app/(protected)/account/api-keys/components/api-integrations.tsx',
    'app/(protected)/account/members/permissions-toggle/components/members.tsx',
    'app/(protected)/account/members/team-members/components/members.tsx',
    'app/(protected)/account/members/teams/components/teams.tsx',
    'app/(protected)/account/members/team-info/components/members.tsx',
    'app/(protected)/account/billing/history/components/invoicing.tsx',
    'app/(protected)/account/invite-a-friend/components/invites.tsx',
  ]);

  it('zero list under app/** or components/platform/** wraps DataGridTableDnd/DataGridTableDndRows/DataGridTable in a ScrollArea, outside the recorded account/**+demo1 allowlist (deleted in T7)', () => {
    const offenders = walk(['app', 'components/platform'])
      .filter((f) => {
        const src = read(f);
        if (!src.includes('<ScrollArea')) return false;
        return /<ScrollArea[^]*?<DataGridTable(Dnd|DndRows)?[\s/]/.test(src) && /<\/ScrollArea>/.test(src);
      })
      .map((f) => f.replace(repoRoot + path.sep, ''))
      .filter((f) => !SCROLL_AREA_AROUND_GRID_ALLOWLIST.has(f));
    expect(offenders).toEqual([]);
  });

  it('records the ScrollArea-around-grid allowlist as exactly 14 files', () => {
    expect(SCROLL_AREA_AROUND_GRID_ALLOWLIST.size).toBe(14);
    for (const f of SCROLL_AREA_AROUND_GRID_ALLOWLIST) {
      expect(fs.existsSync(path.join(repoRoot, f)), f).toBe(true);
    }
  });
});
