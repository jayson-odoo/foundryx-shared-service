import { describe, expect, it } from 'vitest';
import { MENU_SIDEBAR } from './menu.config';
import type { MenuConfig } from './types';

// Owner ruling 15 Nov (lane FEEDBACK-RENAME): no menu label or path says idea.
function walk(items: MenuConfig, out: { title?: string; path?: string }[] = []) {
  for (const i of items) {
    out.push({ title: i.title, path: i.path });
    if (i.children) walk(i.children as MenuConfig, out);
  }
  return out;
}

describe('sidebar menu: feedback wording', () => {
  const entries = walk(MENU_SIDEBAR);

  it('no title or path mentions idea / ideation', () => {
    for (const e of entries) {
      expect(e.title ?? '').not.toMatch(/idea/i);
      expect(e.path ?? '').not.toMatch(/idea/i);
    }
  });

  it('has a Feedback section pointing at /feedback', () => {
    expect(entries.some((e) => e.title === 'Feedback' && !e.path)).toBe(true);
    expect(entries.find((e) => e.path === '/feedback')?.title).toBe('All feedback');
    expect(entries.some((e) => e.path === '/feedback/board')).toBe(true);
  });
});
