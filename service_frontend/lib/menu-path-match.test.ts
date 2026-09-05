/**
 * The sidebar is how the user knows where they are, so "which entry is highlighted" is a
 * correctness question, not a cosmetic one (ported from Sorento, AC-DLA-72).
 */
import { describe, it, expect } from 'vitest';
import { collectMenuPaths, isUnderPath, matchesMenuPath } from './menu-path-match';
import type { MenuConfig } from '@/config/types';

const MENU: MenuConfig = [
  { title: 'Dashboards', path: '/' },
  {
    title: 'Supply Chain',
    children: [
      { title: 'Dashboard', path: '/scm' },
      { title: 'Reorder Planning', path: '/scm/reorder' },
      { title: 'Sales Orders', path: '/scm/sales-orders' },
    ],
  },
];

const paths = collectMenuPaths(MENU);
const active = (pathname: string) => paths.filter((p) => matchesMenuPath(p, pathname, paths));

describe('collectMenuPaths', () => {
  it('reaches paths nested inside groups', () => {
    expect(paths).toEqual(['/', '/scm', '/scm/reorder', '/scm/sales-orders']);
  });
});

describe('isUnderPath', () => {
  it('accepts the page itself and anything below it', () => {
    expect(isUnderPath('/scm/sales-orders', '/scm/sales-orders')).toBe(true);
    expect(isUnderPath('/scm/sales-orders', '/scm/sales-orders/abc')).toBe(true);
  });

  it('stops at a segment boundary, so a same-prefix sibling is not "below"', () => {
    // `startsWith` alone said yes here, which is a different page entirely.
    expect(isUnderPath('/scm', '/scm-archive')).toBe(false);
  });
});

describe('matchesMenuPath', () => {
  it('highlights exactly one entry on a section landing page', () => {
    expect(active('/scm')).toEqual(['/scm']);
  });

  it('highlights the specific page, not the section landing page above it', () => {
    // The reported bug: both were highlighted, so the sidebar named a page the user was not on.
    expect(active('/scm/sales-orders')).toEqual(['/scm/sales-orders']);
    expect(active('/scm/reorder')).toEqual(['/scm/reorder']);
  });

  it('keeps the list page highlighted on a record under it', () => {
    expect(active('/scm/sales-orders/6f2c-id')).toEqual(['/scm/sales-orders']);
  });

  it('falls back to the section when the page has no entry of its own', () => {
    // `/scm/policies` is hidden for this user, so Dashboard is the nearest thing they can see.
    expect(active('/scm/policies')).toEqual(['/scm']);
  });

  it('never lets the root entry swallow every page', () => {
    expect(active('/scm')).not.toContain('/');
  });

  it('is decided against the visible menu, so a hidden entry suppresses nothing', () => {
    // Sales Orders filtered out by permission: the user still gets a highlight, on the section.
    const visible = ['/', '/scm', '/scm/reorder'];
    expect(
      visible.filter((p) => matchesMenuPath(p, '/scm/sales-orders', visible)),
    ).toEqual(['/scm']);
  });
});
