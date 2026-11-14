import { describe, expect, it } from 'vitest';
import { MENU_SIDEBAR, MENU_MEGA, MENU_MEGA_MOBILE } from './menu.config';
import type { MenuItem } from './types';

function find(items: MenuItem[], pred: (i: MenuItem) => boolean, acc: MenuItem[] = []): MenuItem[] {
  for (const i of items) {
    if (pred(i)) acc.push(i);
    if (i.children) find(i.children, pred, acc);
  }
  return acc;
}

describe('Claude connector menu entry (AC-19-60)', () => {
  for (const [name, menu] of [
    ['MENU_SIDEBAR', MENU_SIDEBAR],
    ['MENU_MEGA', MENU_MEGA],
    ['MENU_MEGA_MOBILE', MENU_MEGA_MOBILE],
  ] as const) {
    it(`${name} carries "Claude connector" tagged connector.read + module connector`, () => {
      const hits = find(menu as MenuItem[], (i) => i.path === '/settings/claude-connector');
      expect(hits.length).toBeGreaterThan(0);
      for (const h of hits) {
        expect(h.title).toBe('Claude connector');
        expect(h.permission).toBe('connector.read');
        expect(h.module).toBe('connector');
      }
    });
  }
});
