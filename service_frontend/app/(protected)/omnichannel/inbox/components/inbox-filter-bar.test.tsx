/** AC-IVE-21/48 - Show / Sort / Unreplied wiring. */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { DEFAULT_FILTERS } from '@/hooks/use-conversations';
import { InboxFilterBar } from './inbox-filter-bar';

describe('InboxFilterBar', () => {
  it('renders Show / Sort / Priority as searchable combobox triggers', () => {
    render(<InboxFilterBar filters={DEFAULT_FILTERS} setFilters={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: 'Show' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Sort' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Priority filter' })).toBeInTheDocument();
  });

  it('picking a Show option patches status', async () => {
    const setFilters = vi.fn();
    const user = userEvent.setup();
    render(<InboxFilterBar filters={DEFAULT_FILTERS} setFilters={setFilters} />);
    await user.click(screen.getByRole('combobox', { name: 'Show' }));
    await user.click(await screen.findByText('Open'));
    expect(setFilters).toHaveBeenCalledWith({ status: 'OPEN' });
  });

  it('picking a Sort option patches sort', async () => {
    const setFilters = vi.fn();
    const user = userEvent.setup();
    render(<InboxFilterBar filters={DEFAULT_FILTERS} setFilters={setFilters} />);
    await user.click(screen.getByRole('combobox', { name: 'Sort' }));
    await user.click(await screen.findByText('Longest waiting'));
    expect(setFilters).toHaveBeenCalledWith({ sort: 'longest_waiting' });
  });

  it('toggling Unreplied patches the boolean', async () => {
    const setFilters = vi.fn();
    const user = userEvent.setup();
    render(<InboxFilterBar filters={DEFAULT_FILTERS} setFilters={setFilters} />);
    await user.click(screen.getByRole('switch'));
    expect(setFilters).toHaveBeenCalledWith({ unreplied: true });
  });
});
