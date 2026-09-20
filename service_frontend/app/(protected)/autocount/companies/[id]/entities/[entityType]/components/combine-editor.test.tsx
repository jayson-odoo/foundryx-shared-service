import { fireEvent, render, screen } from '@testing-library/react';
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
