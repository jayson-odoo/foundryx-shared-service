/**
 * The frozen page header's offset is one variable, `--fx-head-top`, so
 * anything frozen under the page header (a list's header row) moves with it
 * when the top bar merges into the page header on scroll.
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(__dirname, '../../../css/demos/demo1.css'), 'utf8').replace(/\s+/g, ' ');

describe('frozen page header offset', () => {
  it('sits under the top bar, and at the very top once the bar has merged', () => {
    expect(css).toContain('--fx-head-top: calc(var(--header-height) + var(--shell-top-offset, 0px));');
    expect(css).toContain(
      ":root[data-fx='on']:has(.fx-topbar[data-merged]) { --fx-head-top: var(--shell-top-offset, 0px); }",
    );
  });

  it('moves the frozen page header by the same variable', () => {
    expect(css).toContain(
      ":root[data-fx='on'] body:has(.fx-topbar[data-merged]) [data-fx-header] { top: var(--fx-head-top); }",
    );
  });
});
