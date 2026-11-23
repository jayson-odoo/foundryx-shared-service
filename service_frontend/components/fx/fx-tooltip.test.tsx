/**
 * The fx tooltip: placement, delay, repeat suppression and touch hold.
 */
import type { ReactNode } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { FxProvider } from '@/providers/fx-provider';
import { FxTooltip, placeFxTip } from './fx-tooltip';
import { FxIconAction } from './actions/icon-action';

function On({ children }: { children: ReactNode }) {
  return (
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {children}
    </FxProvider>
  );
}

const rect = (top: number, height = 44) =>
  ({ top, bottom: top + height, left: 100, right: 144, height, width: 44 }) as DOMRect;

describe('placeFxTip', () => {
  const vp = { width: 1280, height: 800 };
  it('starts at the pointer and sits above the element', () => {
    const pos = placeFxTip(
      { x: 130, y: 222, rect: rect(200), touch: false },
      { width: 80, height: 30 },
      vp,
    );
    expect(pos.left).toBe(130);
    expect(pos.top + 30).toBeLessThanOrEqual(222 - 26);
  });
  it('centres on the pointer, then moves left, near the right edge', () => {
    const pos = placeFxTip(
      { x: 1250, y: 222, rect: rect(200), touch: false },
      { width: 80, height: 30 },
      vp,
    );
    expect(pos.left).toBe(1250 - 80);
  });
  it('goes below when there is no room above', () => {
    const pos = placeFxTip(
      { x: 130, y: 22, rect: rect(0), touch: false },
      { width: 80, height: 30 },
      vp,
    );
    expect(pos.top).toBeGreaterThanOrEqual(22 + 26);
  });
  it('on touch, centres about 40px above the finger', () => {
    const pos = placeFxTip(
      { x: 300, y: 400, rect: rect(380), touch: true },
      { width: 80, height: 30 },
      vp,
    );
    expect(pos.left).toBe(260);
    expect(pos.top).toBe(400 - 40 - 30);
  });
});

describe('FxTooltip', () => {
  beforeEach(() => {
    vi.useFakeTimers({
      toFake: [
        'setTimeout',
        'clearTimeout',
        'requestAnimationFrame',
        'cancelAnimationFrame',
      ],
    });
  });
  afterEach(() => vi.useRealTimers());

  it('shows after the 0.3 s delay and hides on leaving', () => {
    render(
      <On>
        <FxIconAction label="Export CSV" icon="csv-down" />
      </On>,
    );
    const button = screen.getByRole('button', { name: 'Export CSV' });
    fireEvent.pointerEnter(button, { pointerType: 'mouse', clientX: 5, clientY: 5 });
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(screen.queryByRole('tooltip')).toBeNull();
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByRole('tooltip')).toHaveTextContent('Export CSV');
    fireEvent.pointerLeave(button, { pointerType: 'mouse' });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('never shows when it repeats the words already on the element', () => {
    render(
      <On>
        <FxTooltip label="Contacts">
          <button type="button">Contacts</button>
        </FxTooltip>
      </On>,
    );
    fireEvent.pointerEnter(screen.getByRole('button'), { pointerType: 'mouse' });
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(screen.queryByRole('tooltip')).toBeNull();
  });

  it('on touch, a 0.5 s press shows it and the release does not press', () => {
    const onClick = vi.fn();
    render(
      <On>
        <FxIconAction label="Send reminder" icon="reminder" onClick={onClick} />
      </On>,
    );
    const button = screen.getByRole('button', { name: 'Send reminder' });
    fireEvent.pointerDown(button, { pointerType: 'touch', clientX: 50, clientY: 50 });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.getByRole('tooltip')).toHaveTextContent('Send reminder');
    fireEvent.pointerUp(button, { pointerType: 'touch' });
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('keyboard focus keeps the label in the button for screen readers and focus', () => {
    render(
      <On>
        <FxIconAction label="Statement of account" icon="soa" />
      </On>,
    );
    expect(
      screen.getByRole('button', { name: 'Statement of account' }),
    ).toHaveTextContent('Statement of account');
  });
});
