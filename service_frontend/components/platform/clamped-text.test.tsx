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

  it('one line cuts a long unbreakable string with an ellipsis', () => {
    render(
      <TooltipProvider>
        <ClampedText text="https://consumer.example.com/a-very-long-receiver-path" lines={1} />
      </TooltipProvider>,
    );
    const el = screen.getByText(/consumer\.example\.com/);
    expect(el.className).toContain('text-ellipsis');
    expect(el.className).toContain('whitespace-nowrap');
    expect(el.className).not.toContain('line-clamp-1');
  });

  it('a one-line string that only overflows sideways still gets the full-text tooltip', () => {
    vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockReturnValue(13);
    vi.spyOn(HTMLElement.prototype, 'scrollWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.isConnected ? 400 : 0;
    });
    vi.spyOn(HTMLElement.prototype, 'clientWidth', 'get').mockImplementation(function (this: HTMLElement) {
      return this.isConnected ? 120 : 0;
    });
    render(
      <TooltipProvider>
        <ClampedText text="https://consumer.example.com/hooks/lead-capture" lines={1} />
      </TooltipProvider>,
    );
    expect(screen.getByText(/hooks\/lead-capture/)).toHaveAttribute('data-slot', 'tooltip-trigger');
  });

  it('several lines still clamp and wrap long words', () => {
    render(
      <TooltipProvider>
        <ClampedText text="Long title" lines={2} />
      </TooltipProvider>,
    );
    expect(screen.getByText('Long title').className).toContain('line-clamp-2');
    expect(screen.getByText('Long title').className).toContain('break-words');
  });
});
