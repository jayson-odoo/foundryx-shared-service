/**
 * AC-DLA-62 (T7) - the header's ActivityTriggers group (Uploads/Imports/
 * Jobs/Downloads, 4 extra icons with no wrap/shrink protection) overlapped
 * the hamburger + apps-menu drawer triggers and overflowed the 375px
 * viewport (live-measured: the group's buttons spanned x=133..505 against a
 * 375px-wide header). Gated behind the same `!mobileMode` check Search
 * already uses in this file - a source-level guard so a future edit can't
 * silently drop the gate back to always-on.
 */
import fs from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

describe('AC-DLA-62 header ActivityTriggers mobile overlap fix', () => {
  it('ActivityTriggers is gated behind !mobileMode, same as SearchDialog', () => {
    const src = fs.readFileSync(
      path.join(__dirname, 'header.tsx'),
      'utf8',
    );
    expect(src).toMatch(/\{!mobileMode\s*&&\s*<ActivityTriggers\s*\/>\}/);
  });
});
