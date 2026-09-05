/**
 * AC-DLA-54: `ListSearchInput` - the leading icon swaps to a settling
 * indicator while the debounced (200ms) value trails the typed value, and
 * shows a clear button once there's a value.
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

describe('ListSearchInput', () => {
  it('shows the plain search icon and no clear button when empty', () => {
    render(<Controlled />);
    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Clear search' })).not.toBeInTheDocument();
  });

  it('shows the settling indicator while typed text has not settled, then the clear button', () => {
    render(<Controlled />);
    const input = screen.getByRole('textbox', { name: 'Search' });

    fireEvent.change(input, { target: { value: 'ora' } });
    expect(screen.getByTestId('list-search-settling')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.queryByTestId('list-search-settling')).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Clear search' })).toBeInTheDocument();
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
