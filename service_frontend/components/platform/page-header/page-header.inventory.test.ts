/**
 * AC-DLA-27/D6: `PageHeader` is the ONE page-title header. This inventory
 * pins the retirement of the two things it replaces (`ToolbarPageTitle` and
 * hand-rolled `<h1>` sites) plus AC-DLA-35's ban on a raw record-id fragment
 * standing in for a real title.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..', '..', '..');
const read = (rel: string) => fs.readFileSync(path.join(repoRoot, rel), 'utf8');

function walk(dirs: string[], exclude: string[] = []): string[] {
  const out: string[] = [];
  const visit = (dir: string) => {
    const full = path.join(repoRoot, dir);
    if (!fs.existsSync(full)) return;
    for (const entry of fs.readdirSync(full, { withFileTypes: true })) {
      const entryPath = path.join(dir, entry.name);
      if (exclude.some((ex) => entryPath === ex || entryPath.startsWith(`${ex}/`))) continue;
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

/**
 * The app-chrome surface `PageHeader` governs: `app/(protected)` (the shell
 * every real page lives under) plus the shared platform/common components.
 * Deliberately excludes pre-auth/public/embed route groups (no sidebar, no
 * app shell, never had `ToolbarPageTitle` either) and the unused Metronic
 * demo layouts `demo1..demo10` (kept only as reference, never routed to).
 */
const H1_SWEEP_DIRS = ['app/(protected)', 'app/components/partials', 'components/platform', 'components/common'];

/**
 * Sites where a raw `<h1` is allowed outside `page-header.tsx` - starts
 * empty (AC-DLA-27); a future exception is added here with a reason, never
 * silently.
 */
const H1_ALLOWLIST: string[] = [];

describe('AC-DLA-27 PageHeader is the one page-title header', () => {
  it('app/toolbar.tsx no longer exports ToolbarPageTitle (Toolbar/ToolbarActions/ToolbarHeading stay)', () => {
    const src = read('app/components/partials/common/toolbar.tsx');
    expect(src).not.toContain('ToolbarPageTitle');
    expect(src).toContain('export');
    expect(src).toMatch(/\bToolbar\b/);
    expect(src).toMatch(/\bToolbarActions\b/);
  });

  it('zero ToolbarPageTitle references anywhere under app/ or components/', () => {
    const offenders = walk(['app', 'components']).filter((f) => read(f).includes('ToolbarPageTitle'));
    expect(offenders).toEqual([]);
  });

  it('zero raw <h1 outside page-header.tsx and the (empty) allowlist', () => {
    const offenders = walk(H1_SWEEP_DIRS)
      .filter((f) => f !== 'components/platform/page-header/page-header.tsx')
      .filter((f) => !H1_ALLOWLIST.includes(f))
      .filter((f) => /<h1[\s>]/.test(read(f)));
    expect(offenders).toEqual([]);
  });

  it('the allowlist starts empty', () => {
    expect(H1_ALLOWLIST).toEqual([]);
  });

  it('every <PageHeader under app/(protected) has a <Container ancestor in the same file (fix round 1)', () => {
    // Source-level check, not a real AST ancestor walk: a page rendering
    // PageHeader OUTSIDE its Container (a sibling in a Fragment, say) put
    // the title ~16/24px left of the card instead of aligned with it - the
    // regression this pins. Assumes at most one Container "region" per
    // file (true for every offender this fixed); a file with multiple
    // disjoint Container blocks would need a real AST check instead.
    const offenders = walk(["app/(protected)"]).filter((f) => {
      const src = read(f);
      const headerAt = src.indexOf('<PageHeader');
      if (headerAt === -1) return false;
      const containerOpenAt = src.indexOf('<Container');
      const containerCloseAt = src.lastIndexOf('</Container>');
      if (containerOpenAt === -1 || containerCloseAt === -1) return true;
      return !(headerAt > containerOpenAt && headerAt < containerCloseAt);
    });
    expect(offenders).toEqual([]);
  });

  it('no title renders a raw id fragment (id.slice(/id.substring() fallback, AC-DLA-35)', () => {
    const offenders = walk(['app', 'components']).filter((f) => {
      const src = read(f);
      return /title=\{[^}]*\.id\.(slice|substring)\(/.test(src) || /<h1[^>]*>[\s\S]{0,60}\.id\.(slice|substring)\(/.test(src);
    });
    expect(offenders).toEqual([]);
  });
});
