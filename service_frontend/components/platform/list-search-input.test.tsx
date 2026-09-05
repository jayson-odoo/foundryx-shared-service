/**
 * AC-DLA-54 + T6 fix round 1 item 7: `ListSearchInput` - the leading icon
 * swaps to a settling indicator only once `settling || busy` has been
 * continuously true for >= 250ms (the delay gate); fast typing / sub-250ms
 * fetches never flash it, and the shown spinner clears immediately once the
 * gate condition goes false. Also covers the clear button.
 */
import { useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ListSearchInput } from './list-search-input';

beforeEach(() => {
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

function Controlled() {
  const [value, setValue] = useState('');
  return <ListSearchInput value={value} onChange={setValue} ariaLabel="Search" />;
}

function ControlledWithBusy({ busy }: { busy: boolean }) {
  const [value, setValue] = useState('');
  return <ListSearchInput value={value} onChange={setValue} ariaLabel="Search" busy={busy} />;
}

describe('ListSearchInput', () => {
  it('shows the plain search icon and no clear button when empty', () => {
    render(<Controlled />);
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
  });

  it('a single keystroke that settles within 200ms never shows the spinner (delay gate absorbs it)', () => {
    render(<Controlled />);
    const input = screen.getByRole('textbox', { name: 'Search' });

    fireEvent.change(input, { target: { value: 'ora' } });
    // No flash right away.
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();

    // The 200ms search debounce settles well before the 250ms show-delay.
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument();
  });

  it('settling that persists past the 250ms delay gate shows the spinner, then clears immediately once it settles', () => {
    render(<Controlled />);
    const input = screen.getByRole('textbox', { name: 'Search' });

    // Keep re-typing before each 200ms debounce window elapses so `settling`
    // stays continuously true from t=0 - the gate below is timed off that.
    fireEvent.change(input, { target: { value: 'o' } });
    act(() => {
      vi.advanceTimersByTime(100); // t=100
    });
    fireEvent.change(input, { target: { value: 'or' } });
    act(() => {
      vi.advanceTimersByTime(100); // t=200
    });
    fireEvent.change(input, { target: { value: 'ora' } });

    // Gate hasn't elapsed yet (250ms since `settling` first went true at t=0).
    act(() => {
      vi.advanceTimersByTime(40); // t=240
    });
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(10); // t=250 - gate elapses
    });
    expect(screen.getByTestId('list-search-settling')).toBeInTheDocument();

    // The 'ora' debounce (armed at t=200) settles at t=400 - `settling` goes
    // false and the spinner must vanish on that same tick, not after
    // ANOTHER 250ms wait.
    act(() => {
      vi.advanceTimersByTime(150); // t=400
    });
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
  });

  it('a `busy` signal held for >= 250ms with no typing also shows the spinner', () => {
    const { rerender } = render(<ControlledWithBusy busy={false} />);
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();

    rerender(<ControlledWithBusy busy={true} />);
    act(() => {
      vi.advanceTimersByTime(249);
    });
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(screen.getByTestId('list-search-settling')).toBeInTheDocument();

    rerender(<ControlledWithBusy busy={false} />);
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
  });

  it('spinner persists while busy stays true even after settling flips false (the fetch outlasts the debounce)', () => {
    const { rerender } = render(<ControlledWithBusy busy={true} />);
    // No typing at all - `busy` alone carries `active` past the 250ms gate.
    act(() => {
      vi.advanceTimersByTime(250);
    });
    expect(screen.getByTestId('list-search-settling')).toBeInTheDocument();

    // `settling` is already false the whole time here (no typing happened),
    // so this asserts the spinner is driven by `busy`, not by `settling`
    // lingering true - the exact regression this case guards.
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(screen.getByTestId('list-search-settling')).toBeInTheDocument();

    // Only when `busy` itself goes false does the spinner clear.
    rerender(<ControlledWithBusy busy={false} />);
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
  });

  it('clear button resets the value', () => {
    render(<Controlled />);
    const input = screen.getByRole('textbox', { name: 'Search' }) as HTMLInputElement;
    fireEvent.change(input, { target: { value: 'ora' } });
    act(() => {
      vi.advanceTimersByTime(200);
    });
    fireEvent.click(screen.getByRole('button', { name: 'Clear search' }));
    expect(input.value).toBe('');
  });
});
