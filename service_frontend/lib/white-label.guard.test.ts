/**
 * AC-DLA-71 - white-label leftovers guard. T7 fix round 1 item 1 deleted the
 * orphaned Metronic demo partials that rendered "Keenthemes Inc." and a
 * Docs/Purchase/FAQ/Support/License nav (`dropdown-menu-user.tsx`, the
 * `dropdown-menu-{1,2,5,6}` samples, `activities/*`, `common/faq.tsx`,
 * `dialogs/welcome-message-dialog.tsx` - every one had zero importers). This
 * pins that the strings themselves stay gone from the PRODUCT source tree
 * (`app/**`, `components/**`, source files only - not this test).
 *
 * "Metronic" gets a narrow, DISCLOSED allowlist for genuine build-note code
 * comments (never rendered UI copy) plus one already-tracked live-content
 * exception (BL-SS-057, out of this fix round's scope) - reported below, not
 * silently swept under. "Keenthemes"/"keenthemes"/"Purchase" get NO
 * allowlist: none of those strings has a legitimate reason to exist
 * anywhere in this codebase's product source.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

const repoRoot = path.join(__dirname, '..');
const ROOTS = ['app', 'components'];

/** Every `.tsx`/`.ts` under the scanned roots, tests excluded. */
function sourceFiles(): string[] {
  const out: string[] = [];
  const walk = (dir: string) => {
    if (!fs.existsSync(dir)) return;
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === 'node_modules' || entry.name === '.next') continue;
        walk(full);
      } else if (
        (entry.name.endsWith('.tsx') || entry.name.endsWith('.ts')) &&
        !entry.name.includes('.test.')
      ) {
        out.push(full);
      }
    }
  };
  for (const root of ROOTS) walk(path.join(repoRoot, root));
  return out;
}

function relPath(file: string): string {
  return file.replace(repoRoot + path.sep, '').split(path.sep).join('/');
}

/**
 * Metronic comment-only references - each is a `//`/`*` build-note code
 * comment (contrasting this shell with the upstream template, or naming the
 * origin of a pattern), never rendered UI copy a tenant user would see.
 */
const METRONIC_COMMENT_ALLOWLIST: { file: string; reason: string }[] = [
  {
    file: 'app/components/layouts/demo1/components/header.tsx',
    reason: 'build-note comments contrasting this shell with the upstream Metronic default',
  },
  {
    file: 'app/components/partials/topbar/user-dropdown-menu.tsx',
    reason: 'build-note comment naming the deleted Metronic demo deep-links this menu replaced',
  },
  {
    file: 'app/components/partials/topbar/notifications/item-6.tsx',
    reason: 'build-note comment citing the Metronic Launcher mockup this sample content is based on',
  },
  {
    file: 'components/platform/resource-form/resource-form.tsx',
    reason: 'build-note comment naming the AlertDialog pattern source',
  },
];

/**
 * Reported, not silently fixed here: this file still renders literal
 * "Metronic"/"MetronicNest" as VISIBLE badge labels in the demo1 dashboard's
 * Highlights widget - a real, live white-label leak beyond the
 * footer/menu-tree fix AC-DLA-71 targeted. Tracked as BL-SS-057 (dashboard
 * demo-content redesign - fake follower counts, a made-up Teams table -
 * deliberately out of scope for a copy/footer-sized fix).
 */
const METRONIC_LIVE_CONTENT_ALLOWLIST: { file: string; reason: string }[] = [
  {
    file: 'app/(protected)/components/demo1/light-sidebar/components/highlights.tsx',
    reason: 'BL-SS-057 dashboard demo-content redesign, deliberately out of this fix round scope',
  },
];

const METRONIC_ALLOWLIST = [...METRONIC_COMMENT_ALLOWLIST, ...METRONIC_LIVE_CONTENT_ALLOWLIST];

describe('AC-DLA-71 white-label leftovers stay gone', () => {
  it('no source file contains "Keenthemes", "keenthemes" or "Purchase" (no allowlist)', () => {
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const src = fs.readFileSync(file, 'utf8');
      if (/Keenthemes|keenthemes|Purchase/.test(src)) offenders.push(relPath(file));
    }
    expect(offenders).toEqual([]);
  });

  it('no source file contains "Metronic" outside the disclosed allowlist', () => {
    const allowed = new Set(METRONIC_ALLOWLIST.map((e) => e.file));
    const offenders: string[] = [];
    for (const file of sourceFiles()) {
      const rel = relPath(file);
      if (allowed.has(rel)) continue;
      const src = fs.readFileSync(file, 'utf8');
      if (/Metronic/.test(src)) offenders.push(rel);
    }
    expect(offenders).toEqual([]);
  });

  it('the disclosed allowlist entries still exist and still say Metronic (a stale entry should be pruned)', () => {
    for (const { file } of METRONIC_ALLOWLIST) {
      const full = path.join(repoRoot, file);
      expect(fs.existsSync(full), `${file} should exist`).toBe(true);
      expect(fs.readFileSync(full, 'utf8'), file).toMatch(/Metronic/);
    }
  });

  it('the orphaned Metronic demo partials are deleted', () => {
    const deleted = [
      'app/components/partials/topbar/dropdown-menu-user.tsx',
      'app/components/partials/dropdown-menu/dropdown-menu-1.tsx',
      'app/components/partials/dropdown-menu/dropdown-menu-2.tsx',
      'app/components/partials/dropdown-menu/dropdown-menu-5.tsx',
      'app/components/partials/dropdown-menu/dropdown-menu-6.tsx',
      'app/components/partials/common/faq.tsx',
      'app/components/partials/dialogs/welcome-message-dialog.tsx',
    ];
    for (const file of deleted) {
      expect(fs.existsSync(path.join(repoRoot, file)), `${file} should not exist`).toBe(false);
    }
    expect(
      fs.existsSync(path.join(repoRoot, 'app/components/partials/activities')),
      'app/components/partials/activities should not exist',
    ).toBe(false);
  });
});
