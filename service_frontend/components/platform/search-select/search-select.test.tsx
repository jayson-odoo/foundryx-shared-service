/**
 * SearchSelect - the system-wide searchable single-select (user mandate:
 * every data-driven dropdown is searchable like the user/role pickers).
 */
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SearchSelect } from './search-select';

const OPTIONS = [
  { value: 'a', label: 'Active' },
  { value: 'b', label: 'Archived' },
  { value: 'p', label: 'Pending Review' },
];

describe('SearchSelect', () => {
  it('filters options by search and selects on click', async () => {
    const onChange = vi.fn();
    render(<SearchSelect options={OPTIONS} value={null} onChange={onChange} />);

    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'pend' } });
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Pending Review'));
    expect(onChange).toHaveBeenCalledWith('p');
  });

  it('shows the selected label and the empty state', () => {
    render(<SearchSelect options={OPTIONS} value="b" onChange={vi.fn()} />);
    expect(screen.getByRole('combobox')).toHaveTextContent('Archived');

    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'zzz' } });
    expect(screen.getByText('No matches.')).toBeInTheDocument();
  });

  it('commits a typed custom value when allowCustom is set', () => {
    const onChange = vi.fn();
    render(<SearchSelect options={OPTIONS} value={null} onChange={onChange} allowCustom />);
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'Data.0.X' } });
    // The create item is offered instead of the empty state.
    expect(screen.queryByText('No matches.')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Use "Data.0.X"'));
    expect(onChange).toHaveBeenCalledWith('Data.0.X');
  });

  it('renders a custom (unlisted) value verbatim on the trigger', () => {
    render(<SearchSelect options={OPTIONS} value="Data.0.X" onChange={vi.fn()} allowCustom />);
    expect(screen.getByRole('combobox')).toHaveTextContent('Data.0.X');
  });

  it('post-approval N1: with onQueryChange set, cmdk does NOT client-filter the given options - a server page must render as-is', () => {
    const onQueryChange = vi.fn();
    render(<SearchSelect options={OPTIONS} value={null} onChange={vi.fn()} onQueryChange={onQueryChange} />);
    fireEvent.click(screen.getByRole('combobox'));
    // Typing something that matches NOTHING by substring must still show every
    // option the caller passed - the server is the filter now, not cmdk.
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'zzz-no-match' } });
    expect(onQueryChange).toHaveBeenCalledWith('zzz-no-match');
    expect(screen.getByText('Active')).toBeInTheDocument();
    expect(screen.getByText('Archived')).toBeInTheDocument();
    expect(screen.getByText('Pending Review')).toBeInTheDocument();
  });

  it('without onQueryChange, cmdk still client-filters as before (no regression)', () => {
    render(<SearchSelect options={OPTIONS} value={null} onChange={vi.fn()} />);
    fireEvent.click(screen.getByRole('combobox'));
    fireEvent.change(screen.getByPlaceholderText('Search…'), { target: { value: 'zzz-no-match' } });
    expect(screen.queryByText('Active')).not.toBeInTheDocument();
  });
});
