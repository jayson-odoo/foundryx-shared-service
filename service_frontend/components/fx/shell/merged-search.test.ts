/**
 * Owner's local check: on wider screens, once the top bar merges into the
 * page header, its search box drew over the breadcrumb. The title column was
 * sized from a 140px basis and could be squeezed below its longest crumb (a
 * crumb is an inline-flex item and never gets narrower than its longest
 * word), so the crumb ran under the full-width search. Merged, the search
 * now takes only the room left, narrows, then folds to its icon; the frozen
 * header row glides on the page header's own curve. Layout is not computed
 * in jsdom, so this pins the rules themselves (the browser check covers the
 * look).
 */
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const css = readFileSync(join(__dirname, '../../../css/demos/demo1.css'), 'utf8').replace(/\s+/g, ' ');

const MERGED = ":root[data-fx='on'] [data-fx-header]:has(> [data-fx-header-merge] > .fx-search-box)";

describe('merged search in the page header', () => {
  it('keeps the title and crumbs whole and on one line with the search and actions', () => {
    expect(css).toContain(`${MERGED} { flex-wrap: nowrap; }`);
    expect(css).toContain(`${MERGED} > :first-child { flex: 0 1 auto; min-width: min-content; }`);
  });

  it('gives the search only the free room, up to its full width', () => {
    expect(css).toContain(
      ":root[data-fx='on'] [data-fx-header-merge]:has(> .fx-search-box) { flex: 1 1 0; min-width: 2.25rem; justify-content: flex-end; container: fx-merge / inline-size; }",
    );
    expect(css).toContain(
      ":root[data-fx='on'] [data-fx-header-merge] > .fx-search-box button { width: 100%; max-width: 16rem; }",
    );
  });

  it('folds the search to its icon button when there is no room', () => {
    expect(css).toMatch(
      /@container fx-merge \(max-width: 8rem\) \{ :root\[data-fx='on'\] \[data-fx-header-merge\] > \.fx-search-box button \{ width: 2\.25rem;[^}]*\} :root\[data-fx='on'\] \[data-fx-header-merge\] > \.fx-search-box button > span \{ display: none; \} \}/,
    );
  });
});

describe('frozen header row under the page header', () => {
  it('glides on the same curve as the page header', () => {
    expect(css).toContain(
      ":root[data-fx='on'] [data-fx-list-head] { transition-timing-function: var(--fx-ease-in-out); }",
    );
  });
});
