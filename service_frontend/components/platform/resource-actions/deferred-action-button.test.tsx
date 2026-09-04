/**
 * AC-DLA-44: `DeferredCountdown` - the `scaleX` fill arms ONCE (a double-rAF,
 * not re-armed by the 1s label tick), the `role="timer"` label ticks every
 * 1000ms, Cancel fires `onCancel` (and is disabled once lapsed), and reduced
 * motion renders the live fraction with no transition.
 */
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const useReducedMotionMock = vi.fn(() => false);
vi.mock('@/lib/motion', () => ({
  useReducedMotion: () => useReducedMotionMock(),
}));

import { DeferredCountdown } from './deferred-action-button';

function isoInMs(ms: number): string {
  return new Date(Date.now() + ms).toISOString();
}

beforeEach(() => {
  useReducedMotionMock.mockReturnValue(false);
  vi.useFakeTimers({ toFake: ['setTimeout', 'setInterval', 'requestAnimationFrame', 'Date'] });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe('DeferredCountdown', () => {
  it('renders the verb + remaining seconds as a role="timer" label', () => {
    render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(10_000)}
        windowSeconds={10}
        onCancel={vi.fn()}
      />,
    );
    const timer = screen.getByRole('timer');
    expect(timer.textContent).toBe('Deleting in 10s');
  });

  it('bulk copy names the count and noun (D13)', () => {
    render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(8_000)}
        windowSeconds={8}
        count={12}
        noun="users"
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole('timer').textContent).toBe('Deleting 12 users in 8s');
  });

  it('the label ticks down once per 1000ms', () => {
    render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(3_000)}
        windowSeconds={3}
        onCancel={vi.fn()}
      />,
    );
    expect(screen.getByRole('timer').textContent).toBe('Deleting in 3s');
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.getByRole('timer').textContent).toBe('Deleting in 2s');
  });

  it('arms the scaleX fill transition ONCE via a double rAF, not on every 1s tick', () => {
    render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(10_000)}
        windowSeconds={10}
        onCancel={vi.fn()}
      />,
    );
    const bar = screen.getByTestId('deferred-countdown-bar');
    // Before the double rAF fires, the bar sits at the live fraction with no
    // transition.
    expect(bar.style.transitionProperty).toBe('');

    act(() => {
      vi.advanceTimersToNextFrame(); // first rAF
    });
    act(() => {
      vi.advanceTimersToNextFrame(); // second rAF
    });
    expect(bar.style.transform).toBe('scaleX(0)');
    expect(bar.style.transitionProperty).toBe('transform');
    expect(bar.style.transitionTimingFunction).toBe('linear');
    const armedDuration = bar.style.transitionDuration;

    // A 1s label tick must NOT re-arm the transition (same duration string).
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(bar.style.transitionDuration).toBe(armedDuration);
  });

  it('reduced motion renders the live fraction with no transition, stepping with the label', () => {
    useReducedMotionMock.mockReturnValue(true);
    render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(4_000)}
        windowSeconds={4}
        onCancel={vi.fn()}
      />,
    );
    const bar = screen.getByTestId('deferred-countdown-bar');
    expect(bar.style.transitionProperty).toBe('');
    expect(bar.className).toContain('motion-reduce:transition-none');
    expect(bar.style.transform).toBe('scaleX(1)');

    act(() => {
      vi.advanceTimersByTime(1000);
    });
    // A quarter of the window has passed - the live fraction steps down.
    expect(bar.style.transform).not.toBe('scaleX(1)');
  });

  it('Cancel fires onCancel before the window closes, and is disabled once lapsed', () => {
    const onCancel = vi.fn();
    const { rerender } = render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(5_000)}
        windowSeconds={5}
        onCancel={onCancel}
      />,
    );
    screen.getByRole('button', { name: 'Cancel' }).click();
    expect(onCancel).toHaveBeenCalledTimes(1);

    rerender(
      <DeferredCountdown
        verb="Deleting"
        commitAt={new Date(Date.now() - 1000).toISOString()}
        windowSeconds={5}
        onCancel={onCancel}
      />,
    );
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    const cancelBtn = screen.getByRole('button', { name: 'Cancel' }) as HTMLButtonElement;
    expect(cancelBtn.disabled).toBe(true);
  });

  it('Escape does not cancel - no keydown handler is wired', () => {
    const onCancel = vi.fn();
    render(
      <DeferredCountdown
        verb="Deleting"
        commitAt={isoInMs(5_000)}
        windowSeconds={5}
        onCancel={onCancel}
      />,
    );
    act(() => {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    });
    expect(onCancel).not.toHaveBeenCalled();
  });
});
