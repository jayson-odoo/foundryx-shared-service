import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { LookupsEditor } from './lookups-editor';
import type { AutocountLookupSpec } from '@/types/autocount';

function probe() {
  return { columnsByKey: {}, loadingKeys: {}, errorsByKey: {}, run: vi.fn() };
}

function itemUomLookup(): AutocountLookupSpec {
  return {
    path: '/itemuombypage',
    as: 'uom',
    on: [
      { local: 'ItemCode', remote: 'ItemCode' },
      { local: 'BaseUOM', remote: 'UOM', match: 'casefold_trim' },
    ],
    fields: [{ remote: 'Price', as: 'BaseUOMPrice' }],
  };
}

describe('LookupsEditor (AC-10-09)', () => {
  it('no lookups configured reads as an explicit empty state', () => {
    render(
      <LookupsEditor
        editing
        lookups={[]}
        onChange={vi.fn()}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    expect(screen.getByText('No lookups configured.')).toBeInTheDocument();
  });

  it('Add lookup appends a numbered row; Remove removes it', () => {
    const onChange = vi.fn();
    const { rerender } = render(
      <LookupsEditor
        editing
        lookups={[]}
        onChange={onChange}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    fireEvent.click(screen.getByTestId('lookups-add'));
    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ path: '', as: 'lookup1' })]);

    rerender(
      <LookupsEditor
        editing
        lookups={[itemUomLookup()]}
        onChange={onChange}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    expect(screen.getByTestId('lookup-row-0')).toBeInTheDocument();
    expect(screen.getByText('#1')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('lookup-remove-0'));
    expect(onChange).toHaveBeenCalledWith([]);
  });

  it('reorder moves a lookup and re-numbers evaluation order', () => {
    const onChange = vi.fn();
    const second: AutocountLookupSpec = { path: '/itembypage', as: 'item', on: [{ local: 'ItemCode', remote: 'ItemCode' }], fields: [] };
    render(
      <LookupsEditor
        editing
        lookups={[itemUomLookup(), second]}
        onChange={onChange}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    fireEvent.click(screen.getByLabelText('Move lookup 2 up'));
    expect(onChange).toHaveBeenCalledWith([second, itemUomLookup()]);
  });

  it('a later lookup may join on an EARLIER lookup own alias (multi-hop, AC-10-02)', () => {
    const onChange = vi.fn();
    const second: AutocountLookupSpec = {
      path: '/other',
      as: 'x',
      on: [{ local: '', remote: '' }],
      fields: [],
    };
    render(
      <LookupsEditor
        editing
        lookups={[itemUomLookup(), second]}
        onChange={onChange}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    // The FIRST lookup carries TWO join pairs of its own (ItemCode<->ItemCode,
    // BaseUOM<->UOM), so the second lookup's single "local" picker is the
    // THIRD one in document order.
    const localPickers = screen.getAllByLabelText('Local column');
    expect(localPickers).toHaveLength(3);
    fireEvent.click(localPickers[2]);
    expect(screen.getByRole('option', { name: 'BaseUOMPrice' })).toBeInTheDocument();
  });

  it('an alias colliding with a source column shows the inline 422', () => {
    const lookup: AutocountLookupSpec = {
      path: '/itemuombypage',
      as: 'uom',
      on: [{ local: 'ItemCode', remote: 'ItemCode' }],
      fields: [{ remote: 'Price', as: 'ItemCode' }],
    };
    render(
      <LookupsEditor
        editing
        lookups={[lookup]}
        onChange={vi.fn()}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    expect(screen.getByText(/already a source column/)).toBeInTheDocument();
  });

  it('a Test probes the remote columns for THIS row only', () => {
    const run = vi.fn();
    render(
      <LookupsEditor
        editing
        lookups={[itemUomLookup()]}
        onChange={vi.fn()}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={{ columnsByKey: {}, loadingKeys: {}, errorsByKey: {}, run }}
      />,
    );
    fireEvent.click(screen.getByTestId('lookup-test-0'));
    expect(run).toHaveBeenCalledWith('lookup:0', 'conn-1', '/itemuombypage');
  });

  it('shows the combined Test per-lookup matched/missed as a SAMPLE (BL-SS-222)', () => {
    render(
      <LookupsEditor
        editing
        lookups={[itemUomLookup()]}
        onChange={vi.fn()}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
        lookupResults={[{ alias: 'uom', matched: 48, missed: 2 }]}
      />,
    );
    expect(screen.getByTestId('lookup-result-0')).toHaveTextContent('Sample: 48 matched');
    expect(screen.getByTestId('lookup-result-0')).toHaveTextContent('2 missed');
  });

  it('read-only when not editing - no Add/Remove/Test controls', () => {
    render(
      <LookupsEditor
        editing={false}
        lookups={[itemUomLookup()]}
        onChange={vi.fn()}
        sourceColumns={['ItemCode']}
        connectionId="conn-1"
        columnsProbe={probe()}
      />,
    );
    expect(screen.queryByTestId('lookups-add')).not.toBeInTheDocument();
    expect(screen.queryByTestId('lookup-remove-0')).not.toBeInTheDocument();
  });
});
