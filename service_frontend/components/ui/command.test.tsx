/**
 * AC-DLA-22 / T3 fix round 1 finding 4 - `CommandDialog` defaults to
 * `motion={false}` (opt IN to the spring, never opt out). A command palette
 * is the frequency table's one absolute no-animate surface, and there was no
 * call site in the repo passing `motion={false}` to make that true on its
 * own - the default itself has to carry it.
 */
import { useState } from 'react';
import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { Command, CommandDialog, CommandInput, CommandList } from './command';

describe('CommandDialog defaults to motion={false} (AC-DLA-22)', () => {
  it('renders its DialogContent with data-motion="off" when no motion prop is passed', () => {
    render(
      <CommandDialog open>
        <CommandInput />
        <CommandList />
      </CommandDialog>,
    );

    const content = screen.getByRole('dialog', { hidden: true });
    expect(content).toHaveAttribute('data-motion', 'off');
  });

  it('does not carry data-motion when the caller explicitly opts into motion', () => {
    render(
      <CommandDialog open motion>
        <CommandInput />
        <CommandList />
      </CommandDialog>,
    );

    const content = screen.getByRole('dialog', { hidden: true });
    expect(content).not.toHaveAttribute('data-motion');
  });

  it('honours an explicit motion={false} the same as the default', () => {
    render(
      <CommandDialog open motion={false}>
        <CommandInput />
        <CommandList />
      </CommandDialog>,
    );

    const content = screen.getByRole('dialog', { hidden: true });
    expect(content).toHaveAttribute('data-motion', 'off');
  });
});

/**
 * AC-DLA-54 - a controlled `CommandInput` (SearchSelect/MultiSelect) gets
 * the same leading-icon settling indicator `ListSearchInput` shows.
 */
describe('CommandInput settling indicator (AC-DLA-54)', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function ControlledCommand() {
    const [value, setValue] = useState('');
    return (
      <Command>
        <CommandInput value={value} onValueChange={setValue} aria-label="Search" />
        <CommandList />
      </Command>
    );
  }

  it('shows the settling spinner while the debounced value trails, then clears', () => {
    render(<ControlledCommand />);
    const input = screen.getByRole('combobox', { hidden: true }) ?? screen.getByRole('textbox', { hidden: true });
    fireEvent.change(input, { target: { value: 'ora' } });
    expect(screen.getByTestId('command-input-settling')).toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(200);
    });

    expect(screen.queryByTestId('command-input-settling')).not.toBeInTheDocument();
  });

  it('an uncontrolled CommandInput never shows the settling spinner', () => {
    render(
      <Command>
        <CommandInput aria-label="Search" />
        <CommandList />
      </Command>,
    );
    const input = screen.getByRole('combobox', { hidden: true }) ?? screen.getByRole('textbox', { hidden: true });
    fireEvent.change(input, { target: { value: 'ora' } });
    expect(screen.queryByTestId('command-input-settling')).not.toBeInTheDocument();
  });
});
