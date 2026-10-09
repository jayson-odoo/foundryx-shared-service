import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { MultiSelect } from './multi-select';

const options = [
  { label: 'Admin', value: 'a' },
  { label: 'Member', value: 'm' },
];

describe('MultiSelect', () => {
  it('shows selected values as pills', () => {
    render(<MultiSelect options={options} value={['a']} onChange={() => {}} />);
    expect(screen.getByText('Admin')).toBeInTheDocument();
  });

  it('"Select all" selects every option', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MultiSelect options={options} value={[]} onChange={onChange} />);

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByText('Select all'));

    expect(onChange).toHaveBeenCalledWith(['a', 'm']);
  });

  it('"Clear all" empties the selection when all are selected', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<MultiSelect options={options} value={['a', 'm']} onChange={onChange} />);

    await user.click(screen.getByRole('combobox'));
    await user.click(screen.getByText('Clear all'));

    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('post-approval N1: with onQueryChange set, cmdk does NOT client-filter the given options - a server page must render as-is', async () => {
    const user = userEvent.setup();
    const onQueryChange = vi.fn();
    render(<MultiSelect options={options} value={[]} onChange={() => {}} onQueryChange={onQueryChange} />);

    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByPlaceholderText('Search…'), 'zzz-no-match');

    expect(onQueryChange).toHaveBeenCalledWith('zzz-no-match');
    expect(screen.getByText('Admin')).toBeInTheDocument();
    expect(screen.getByText('Member')).toBeInTheDocument();
  });

  it('without onQueryChange, cmdk still client-filters as before (no regression)', async () => {
    const user = userEvent.setup();
    render(<MultiSelect options={options} value={[]} onChange={() => {}} />);

    await user.click(screen.getByRole('combobox'));
    await user.type(screen.getByPlaceholderText('Search…'), 'zzz-no-match');

    expect(screen.queryByText('Admin')).not.toBeInTheDocument();
  });
});
