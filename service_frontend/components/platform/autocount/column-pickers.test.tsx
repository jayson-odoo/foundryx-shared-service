import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ColumnChips, ColumnPickers } from './column-pickers';

describe('ColumnChips', () => {
  it('renders each value as a chip', () => {
    render(<ColumnChips values={['ItemCode', 'AccNo']} empty="-" />);
    expect(screen.getByText('ItemCode')).toBeInTheDocument();
    expect(screen.getByText('AccNo')).toBeInTheDocument();
  });

  it('renders the empty text when there is nothing picked', () => {
    render(<ColumnChips values={[]} empty="None" />);
    expect(screen.getByText('None')).toBeInTheDocument();
  });
});

const OPTIONS = [
  { label: 'ItemCode', value: 'ItemCode' },
  { label: 'Description', value: 'Description' },
  { label: 'LastModified', value: 'LastModified' },
];

describe('ColumnPickers (sprint-5/08 D13 - shared by the SQL and API branches)', () => {
  it('read mode renders chips, never a picker', () => {
    render(
      <ColumnPickers
        editing={false}
        keyOptions={OPTIONS}
        watermarkOptions={[{ label: 'None', value: '' }, ...OPTIONS]}
        comparedOptions={OPTIONS}
        keyValue={['ItemCode']}
        onKeyChange={vi.fn()}
        watermarkValue="LastModified"
        onWatermarkChange={vi.fn()}
        comparedValue={[]}
        onComparedChange={vi.fn()}
        pickersEnabled
      />,
    );
    expect(screen.getByText('ItemCode')).toBeInTheDocument();
    expect(screen.getByText('LastModified')).toBeInTheDocument();
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
  });

  it('edit mode disables every picker until pickersEnabled (a preview has run)', () => {
    render(
      <ColumnPickers
        editing
        keyOptions={[]}
        watermarkOptions={[]}
        comparedOptions={[]}
        keyValue={[]}
        onKeyChange={vi.fn()}
        watermarkValue=""
        onWatermarkChange={vi.fn()}
        comparedValue={[]}
        onComparedChange={vi.fn()}
        pickersEnabled={false}
      />,
    );
    expect(screen.getByRole('combobox', { name: 'Watermark column' })).toBeDisabled();
  });

  it('fires onKeyChange/onWatermarkChange when a picker changes', async () => {
    const onWatermarkChange = vi.fn();
    render(
      <ColumnPickers
        editing
        keyOptions={OPTIONS}
        watermarkOptions={[{ label: 'None', value: '' }, ...OPTIONS]}
        comparedOptions={OPTIONS}
        keyValue={['ItemCode']}
        onKeyChange={vi.fn()}
        watermarkValue=""
        onWatermarkChange={onWatermarkChange}
        comparedValue={[]}
        onComparedChange={vi.fn()}
        pickersEnabled
      />,
    );
    fireEvent.click(screen.getByRole('combobox', { name: 'Watermark column' }));
    fireEvent.click(await screen.findByRole('option', { name: 'LastModified' }));
    expect(onWatermarkChange).toHaveBeenCalledWith('LastModified');
  });

  it('surfaces per-field errors', () => {
    render(
      <ColumnPickers
        editing
        keyOptions={OPTIONS}
        watermarkOptions={OPTIONS}
        comparedOptions={OPTIONS}
        keyValue={[]}
        onKeyChange={vi.fn()}
        watermarkValue=""
        onWatermarkChange={vi.fn()}
        comparedValue={[]}
        onComparedChange={vi.fn()}
        pickersEnabled
        fieldErrors={{ keyColumns: 'Pick at least one key column.' }}
      />,
    );
    expect(screen.getByText('Pick at least one key column.')).toBeInTheDocument();
  });
});
