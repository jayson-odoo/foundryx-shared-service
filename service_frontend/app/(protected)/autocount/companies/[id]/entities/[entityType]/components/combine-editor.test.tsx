import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { CombineEditor } from './combine-editor';
import { emptyCombine } from '@/lib/autocount-combine';

const serverTest = vi.fn().mockResolvedValue({ ok: true, output: null, error: null });

describe('CombineEditor (AC-10-82)', () => {
  it('is off by default - an explicit empty state, no hint copy', () => {
    render(
      <CombineEditor
        editing
        combine={null}
        onChange={vi.fn()}
        columnOptions={['ItemCode']}
        funnel={null}
        onServerTest={serverTest}
      />,
    );
    expect(screen.getByText('No combine step configured.')).toBeInTheDocument();
  });

  it('enabling the switch seeds an empty config', () => {
    const onChange = vi.fn();
    render(
      <CombineEditor
        editing
        combine={null}
        onChange={onChange}
        columnOptions={['ItemCode']}
        funnel={null}
        onServerTest={serverTest}
      />,
    );
    fireEvent.click(screen.getByTestId('combine-enable'));
    expect(onChange).toHaveBeenCalledWith(emptyCombine());
  });

  it('add-a-drop-rule appends an ordered row with its own "list dropped rows" switch', () => {
    const onChange = vi.fn();
    render(
      <CombineEditor
        editing
        combine={emptyCombine()}
        onChange={onChange}
        columnOptions={['qty']}
        funnel={null}
        onServerTest={serverTest}
      />,
    );
    fireEvent.click(screen.getByText('Add drop rule'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ drop: [{ name: '', formula: '', listRows: false }] }),
    );
  });

  it('no funnel section renders until the Source tab lands a server response (nothing to show yet)', () => {
    render(
      <CombineEditor
        editing
        combine={emptyCombine()}
        onChange={vi.fn()}
        columnOptions={[]}
        funnel={null}
        onServerTest={serverTest}
      />,
    );
    expect(screen.queryByTestId('combine-funnel')).not.toBeInTheDocument();
    // The editor never runs its own preview - no local Test control at all.
    expect(screen.queryByTestId('combine-test')).not.toBeInTheDocument();
  });

  it('renders the SERVER funnel passed down from the Source tab Test (AC-10-82)', () => {
    render(
      <CombineEditor
        editing
        combine={{
          ...emptyCombine(),
          groupBy: ['ItemCode'],
          measure: 'qty',
          measures: [{ source: 'qty', op: 'sum', alias: 'qty' }],
          drop: [{ name: 'zero', formula: 'qty == 0' }],
        }}
        onChange={vi.fn()}
        columnOptions={['ItemCode', 'qty']}
        funnel={{
          rowsIn: 2,
          excludedCount: 0,
          groups: 2,
          droppedByRule: { zero: 1 },
          rowsOut: 1,
          roundedCount: 0,
        }}
        onServerTest={serverTest}
      />,
    );
    const funnel = screen.getByTestId('combine-funnel');
    expect(funnel).toHaveTextContent('2 in');
    expect(funnel).toHaveTextContent('zero: 1 dropped');
    expect(funnel).toHaveTextContent('1 out');
  });

  // S5b-FE browser defect 1 (AC-10-76/77/79) - each formula stage only sees
  // the names it is allowed to reference, never the same flat set.
  describe('formula builder scope per stage (AC-10-76/77/79)', () => {
    const preFilled = {
      ...emptyCombine(),
      computed: [
        { alias: 'item_code', formula: 'trim(ItemCode)' },
        { alias: 'location_code', formula: 'trim(Location)' },
      ],
      require: [{ name: 'uom_rate', formula: 'true', reason: 'uom_rate_unresolved' }],
      groupBy: ['item_code', 'location_code'],
      carry: ['ItemBaseUOM', 'ItemDescription'],
      measure: 'qty',
      measures: [{ source: 'base_qty', op: 'sum' as const, alias: 'qty' }],
      drop: [
        { name: 'zero', formula: 'qty == 0', listRows: false },
        { name: 'negative', formula: 'qty < 0', listRows: true },
      ],
    };
    const columnOptions = ['ItemCode', 'Location', 'UOM', 'BalQty', 'ItemBaseUOM', 'ItemDescription', 'UomRate'];

    it('a drop rule offers post-group columns (groupBy + carry + measure alias), never a raw source column', () => {
      render(
        <CombineEditor
          editing
          combine={preFilled}
          onChange={vi.fn()}
          columnOptions={columnOptions}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      fireEvent.click(screen.getAllByText('Edit formula').at(-1) as HTMLElement);
      // The variable panel renders the column name twice per row (label +
      // token) - assert PRESENCE/ABSENCE via `getAllByText`/`queryAllByText`,
      // never the singular `getByText`, which would throw on the duplicate.
      const dialog = within(screen.getByRole('dialog'));
      expect(dialog.getAllByText('item_code').length).toBeGreaterThan(0);
      expect(dialog.getAllByText('location_code').length).toBeGreaterThan(0);
      expect(dialog.getAllByText('ItemDescription').length).toBeGreaterThan(0);
      expect(dialog.getAllByText('ItemBaseUOM').length).toBeGreaterThan(0);
      expect(dialog.getAllByText('qty').length).toBeGreaterThan(0);
      expect(dialog.queryAllByText('BalQty').length).toBe(0);
    });

    it('Apply is enabled for a drop rule formula referencing the measure alias (qty < 0)', () => {
      render(
        <CombineEditor
          editing
          combine={preFilled}
          onChange={vi.fn()}
          columnOptions={columnOptions}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      fireEvent.click(screen.getAllByText('Edit formula').at(-1) as HTMLElement);
      expect(screen.getByLabelText('Formula expression')).toHaveValue('qty < 0');
      expect(screen.getByTestId('formula-status')).toHaveTextContent(/valid formula/i);
      expect(screen.getByRole('button', { name: 'Apply' })).toBeEnabled();
    });

    it('computed[1] offers computed[0]\'s alias but never its own or a later alias', () => {
      render(
        <CombineEditor
          editing
          combine={preFilled}
          onChange={vi.fn()}
          columnOptions={columnOptions}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      // Second computed row's own "Edit formula" button.
      const editButtons = screen.getAllByText('Edit formula');
      fireEvent.click(editButtons[1]);
      const dialog = within(screen.getByRole('dialog'));
      expect(dialog.getAllByText('item_code').length).toBeGreaterThan(0);
      expect(dialog.queryAllByText('location_code').length).toBe(0);
    });

    // Confirm round 2 (S1) - after a combine-carrying Test the Source tab's
    // `columnOptions` comes from `preCombineColumns`, which by backend design
    // already CONTAINS every computed alias. The `Columns` group must still
    // be raw/lookup names only, so a computed alias can never reach a stage
    // that may not reference it (computed[0] referencing itself, or
    // computed[0] referencing a LATER alias - both save-time 422s).
    describe('columnOptions already carrying the computed aliases (post-Test)', () => {
      const withComputed = [...columnOptions, 'item_code', 'location_code'];

      it('computed[0] offers neither its own nor a later computed alias', () => {
        render(
          <CombineEditor
            editing
            combine={preFilled}
            onChange={vi.fn()}
            columnOptions={withComputed}
            funnel={null}
            onServerTest={serverTest}
          />,
        );
        fireEvent.click(screen.getAllByText('Edit formula')[0]);
        const dialog = within(screen.getByRole('dialog'));
        expect(dialog.queryAllByText('item_code').length).toBe(0);
        expect(dialog.queryAllByText('location_code').length).toBe(0);
        expect(dialog.getAllByText('ItemCode').length).toBeGreaterThan(0);
      });

      it('computed[1] offers computed[0]\'s alias exactly once - from the Computed group, never the Columns group', () => {
        render(
          <CombineEditor
            editing
            combine={preFilled}
            onChange={vi.fn()}
            columnOptions={withComputed}
            funnel={null}
            onServerTest={serverTest}
          />,
        );
        fireEvent.click(screen.getAllByText('Edit formula')[1]);
        const dialog = within(screen.getByRole('dialog'));
        expect(dialog.getAllByText('item_code').length).toBeGreaterThan(0);
        expect(dialog.queryAllByText('location_code').length).toBe(0);
      });

      it('a require rule still offers every computed alias', () => {
        render(
          <CombineEditor
            editing
            combine={preFilled}
            onChange={vi.fn()}
            columnOptions={withComputed}
            funnel={null}
            onServerTest={serverTest}
          />,
        );
        fireEvent.click(screen.getAllByText('Edit formula')[2]);
        const dialog = within(screen.getByRole('dialog'));
        expect(dialog.getAllByText('item_code').length).toBeGreaterThan(0);
        expect(dialog.getAllByText('location_code').length).toBeGreaterThan(0);
      });

      it('a drop rule is unchanged - post-group names only', () => {
        render(
          <CombineEditor
            editing
            combine={preFilled}
            onChange={vi.fn()}
            columnOptions={withComputed}
            funnel={null}
            onServerTest={serverTest}
          />,
        );
        fireEvent.click(screen.getAllByText('Edit formula').at(-1) as HTMLElement);
        const dialog = within(screen.getByRole('dialog'));
        expect(dialog.getAllByText('item_code').length).toBeGreaterThan(0);
        expect(dialog.getAllByText('qty').length).toBeGreaterThan(0);
        expect(dialog.queryAllByText('BalQty').length).toBe(0);
      });
    });

    it('a require rule offers every computed alias', () => {
      render(
        <CombineEditor
          editing
          combine={preFilled}
          onChange={vi.fn()}
          columnOptions={columnOptions}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      const editButtons = screen.getAllByText('Edit formula');
      // computed[0], computed[1], require[0] in DOM order.
      fireEvent.click(editButtons[2]);
      const dialog = within(screen.getByRole('dialog'));
      expect(dialog.getAllByText('item_code').length).toBeGreaterThan(0);
      expect(dialog.getAllByText('location_code').length).toBeGreaterThan(0);
    });
  });

  // AC-10-82 fix - the backend validator (combine.py ~line 501) requires the
  // designated `measure` to be a PRE-GROUP column (a source column or a
  // computed alias), never a `measures[].alias`; the picker must only offer
  // what the server will accept.
  describe('Designated measure picker (AC-10-82)', () => {
    it('offers source + computed columns, never measure aliases', () => {
      render(
        <CombineEditor
          editing
          combine={{
            ...emptyCombine(),
            computed: [{ alias: 'base_qty', formula: 'BalQty * 1' }],
            measures: [{ source: 'base_qty', op: 'sum', alias: 'qty' }],
          }}
          onChange={vi.fn()}
          columnOptions={['ItemCode', 'BalQty']}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      fireEvent.click(screen.getByLabelText('Designated measure'));
      expect(screen.getAllByText('BalQty').length).toBeGreaterThan(0);
      expect(screen.getAllByText('base_qty').length).toBeGreaterThan(0);
      expect(screen.queryAllByText('qty').length).toBe(0);
    });

    it('a legacy config.measure of "qty" (a measure alias) still displays rather than blanking', () => {
      render(
        <CombineEditor
          editing
          combine={{
            ...emptyCombine(),
            measure: 'qty',
            measures: [{ source: 'BalQty', op: 'sum', alias: 'qty' }],
          }}
          onChange={vi.fn()}
          columnOptions={['ItemCode', 'BalQty']}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      expect(screen.getByLabelText('Designated measure')).toHaveTextContent('qty');
    });

    it('saving picks a pre-group column (base_qty), matching the server contract', () => {
      const onChange = vi.fn();
      render(
        <CombineEditor
          editing
          combine={{
            ...emptyCombine(),
            computed: [{ alias: 'base_qty', formula: 'BalQty * 1' }],
          }}
          onChange={onChange}
          columnOptions={['ItemCode', 'BalQty']}
          funnel={null}
          onServerTest={serverTest}
        />,
      );
      fireEvent.click(screen.getByLabelText('Designated measure'));
      fireEvent.click(screen.getByText('base_qty'));
      expect(onChange).toHaveBeenCalledWith(
        expect.objectContaining({ measure: 'base_qty' }),
      );
    });
  });

  it('read-only when not editing - no Enable/Add controls', () => {
    render(
      <CombineEditor
        editing={false}
        combine={emptyCombine()}
        onChange={vi.fn()}
        columnOptions={[]}
        funnel={null}
        onServerTest={serverTest}
      />,
    );
    expect(screen.queryByTestId('combine-enable')).not.toBeInTheDocument();
    expect(screen.queryByText('Add drop rule')).not.toBeInTheDocument();
  });
});
