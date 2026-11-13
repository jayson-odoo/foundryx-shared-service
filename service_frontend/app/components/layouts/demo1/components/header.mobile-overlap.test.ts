/**
 * AC-DLA-62 (T7) - the header's ActivityTriggers group (Uploads/Imports/
 * Jobs/Downloads, 4 extra icons with no wrap/shrink protection) overlapped
 * the hamburger + apps-menu drawer triggers and overflowed the 375px
 * viewport (live-measured: the group's buttons spanned x=133..505 against a
 * 375px-wide header).
 *
 * Fix round 1: hiding the whole group behind `!mobileMode` silently dropped
 * the Uploads/Downloads drawers on mobile entirely, with no other way to
 * reach them. Instead `ActivityTriggers` renders always, narrowed to
 * `only={['uploads', 'downloads']}` on mobile (Imports/Jobs stay reachable
 * via the sidebar drawer's own menu entries) - a source-level guard so a
 * future edit can't silently drop the mobile set back to the full four (the
 * overlap regression) or to zero (the drawers-vanish regression).
 *
 * Fitting Uploads+Downloads back in also needed the header's own logo/gap
 * budget fixed (a broken-image alt-text fallback was inflating the mobile
 * logo to ~87px; `compact` sheds the invisible coarse-pointer touch pad on
 * the mobile topbar icons so a tighter gap does not create touch-target
 * overlap) - pinned below alongside the ActivityTriggers gate itself.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

describe('AC-DLA-62 header ActivityTriggers mobile overlap fix', () => {
  it('ActivityTriggers always renders, narrowed to uploads+downloads (compact) on mobile', () => {
    const src = fs.readFileSync(path.join(__dirname, 'header.tsx'), 'utf8');
    expect(src).toMatch(
      /<ActivityTriggers[\s\S]{0,80}only=\{mobileMode \? \[['"]uploads['"], ['"]downloads['"]\] : undefined\}[\s\S]{0,80}compact=\{mobileMode\}/,
    );
    // Never gated back behind !mobileMode (that regression dropped the
    // Uploads/Downloads drawers on mobile with no replacement).
    expect(src).not.toMatch(/\{!mobileMode\s*&&\s*<ActivityTriggers/);
  });

  it('the mobile logo has a fixed pixel width (a broken-image alt-text fallback must not inflate it)', () => {
    const src = fs.readFileSync(path.join(__dirname, 'header.tsx'), 'utf8');
    expect(src).toMatch(/alt="mini-logo"/);
    expect(src).not.toMatch(/className="h-\[25px\] w-full"/);
  });

  it('the mobile topbar gap tightens and its icon buttons go compact (size="sm") to fit', () => {
    const src = fs.readFileSync(path.join(__dirname, 'header.tsx'), 'utf8');
    expect(src).toMatch(/mobileMode \? 'gap-1' : 'gap-3'/);
    expect(src).toMatch(/size=\{mobileMode \? 'sm' : undefined\}/);
  });
});
