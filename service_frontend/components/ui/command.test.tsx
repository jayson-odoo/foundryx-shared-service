/**
 * AC-DLA-22 / T3 fix round 1 finding 4 - `CommandDialog` defaults to
 * `motion={false}` (opt IN to the spring, never opt out). A command palette
 * is the frequency table's one absolute no-animate surface, and there was no
 * call site in the repo passing `motion={false}` to make that true on its
 * own - the default itself has to carry it.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { CommandDialog, CommandInput, CommandList } from './command';

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
 * T6 fix round 1 item 8 (supersedes the old AC-DLA-54 settling-indicator
 * coverage here) - cmdk filters synchronously, so `CommandInput` no longer
 * swaps its leading icon at all; it always renders the static Search glyph.
 */
describe('CommandInput leading icon (T6 fix round 1 item 8)', () => {
  it('always renders the static Search glyph, never a settling spinner', () => {
    render(
      <CommandDialog open>
        <CommandInput aria-label="Search" />
        <CommandList />
      </CommandDialog>,
    );
    expect(document.querySelector('[cmdk-input-wrapper] svg.lucide-search')).toBeInTheDocument();
    expect(screen.queryByTestId('command-input-settling')).not.toBeInTheDocument();
  });
});
