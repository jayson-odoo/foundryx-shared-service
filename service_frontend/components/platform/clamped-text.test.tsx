import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { TooltipProvider } from '@/components/ui/tooltip';
import { ClampedText } from './clamped-text';

/** A detached element measures 0, like a real browser; a connected clamped one
 * overflows. Observer callbacks can be fired by hand. */
const callbacks: Array<() => void> = [];

beforeEach(() => {
  callbacks.length = 0;
  vi.stubGlobal(
    'ResizeObserver',
    class {
      private cb: () => void;
      constructor(cb: () => void) {
        this.cb = cb;
      }
      observe() {
        callbacks.push(this.cb);
      }
      unobserve() {}
      disconnect() {
        const i = callbacks.indexOf(this.cb);
        if (i >= 0) callbacks.splice(i, 1);
      }
    },
  );
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return this.isConnected ? 40 : 0;
  });
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockImplementation(function (this: HTMLElement) {
    return this.isConnected ? 13 : 0;
  });
});

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('ClampedText', () => {
  it('stays a tooltip trigger after a resize once it truncates (no remount onto a detached element)', () => {
    render(
      <TooltipProvider>
        <ClampedText text="showroom-display-unit-cracked-front-glass.jpg" lines={1} />
      </TooltipProvider>,
    );
    act(() => {
      callbacks.slice().forEach((cb) => cb());
    });
    const p = screen.getByText('showroom-display-unit-cracked-front-glass.jpg');
    expect(p).toHaveAttribute('data-slot', 'tooltip-trigger');
  });

  it('short text is plain (no tooltip trigger)', () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(13);
    render(
      <TooltipProvider>
        <ClampedText text="a.png" lines={1} />
      </TooltipProvider>,
    );
    expect(screen.getByText('a.png')).not.toHaveAttribute('data-slot');
  });
});
