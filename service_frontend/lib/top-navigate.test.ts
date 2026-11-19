import { describe, expect, it, vi } from 'vitest';

import { navigateTop, type NavWindow } from './top-navigate';

function makeWin(framed: boolean, topThrows = false): { win: NavWindow; top: NavWindow } {
  const win = { location: { assign: vi.fn() }, open: vi.fn() } as unknown as NavWindow;
  win.self = win;
  let top: NavWindow = win;
  if (framed) {
    const loc: { assign: ReturnType<typeof vi.fn>; href?: string } = { assign: vi.fn() };
    if (topThrows) {
      Object.defineProperty(loc, 'href', {
        set() {
          throw new Error('blocked');
        },
      });
    }
    top = { location: loc, open: vi.fn(), top: null } as unknown as NavWindow;
    top.self = top;
  }
  win.top = top;
  return { win, top };
}

describe('navigateTop', () => {
  it('navigates this window when not framed', () => {
    const { win } = makeWin(false);
    navigateTop('https://crm.example.test/feedback/board/t', win);
    expect(win.location.assign).toHaveBeenCalledWith('https://crm.example.test/feedback/board/t');
  });

  it('navigates the top window when framed, never this frame', () => {
    const { win, top } = makeWin(true);
    navigateTop('https://crm.example.test/feedback/board/t', win);
    expect(top.location.href).toBe('https://crm.example.test/feedback/board/t');
    expect(win.location.assign).not.toHaveBeenCalled();
  });

  it('opens a new tab when the browser blocks top navigation', () => {
    const { win } = makeWin(true, true);
    navigateTop('https://crm.example.test/feedback/board/t', win);
    expect(win.open).toHaveBeenCalledWith('https://crm.example.test/feedback/board/t', '_blank', 'noopener');
    expect(win.location.assign).not.toHaveBeenCalled();
  });
});
