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
        sampleRows={[]}
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
        sampleRows={[]}
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
        sampleRows={[]}
        onServerTest={serverTest}
      />,
    );
    fireEvent.click(screen.getByText('Add drop rule'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ drop: [{ name: '', formula: '', listRows: false }] }),
    );
  });

  it('Test runs the client-side funnel over the sample rows and renders it', () => {
    const combine = {
      ...emptyCombine(),
      groupBy: ['ItemCode'],
      measure: 'qty',
      measures: [{ source: 'qty', op: 'sum' as const, alias: 'qty' }],
      drop: [{ name: 'zero', formula: 'qty == 0' }],
    };
    render(
      <CombineEditor
        editing
        combine={combine}
        onChange={vi.fn()}
        columnOptions={['ItemCode', 'qty']}
        sampleRows={[
          { ItemCode: 'A', qty: 5 },
          { ItemCode: 'B', qty: 0 },
        ]}
        onServerTest={serverTest}
      />,
    );
    fireEvent.click(screen.getByTestId('combine-test'));
    const funnel = screen.getByTestId('combine-funnel');
    expect(funnel).toHaveTextContent('2 in');
    expect(funnel).toHaveTextContent('zero: 1 dropped');
    expect(funnel).toHaveTextContent('1 out');
  });

  it('Test is disabled with no sample rows to run against', () => {
    render(
      <CombineEditor
        editing
        combine={emptyCombine()}
        onChange={vi.fn()}
        columnOptions={[]}
        sampleRows={[]}
        onServerTest={serverTest}
      />,
    );
    expect(screen.getByTestId('combine-test')).toBeDisabled();
  });

  it('read-only when not editing - no Enable/Add controls', () => {
    render(
      <CombineEditor
        editing={false}
        combine={emptyCombine()}
        onChange={vi.fn()}
        columnOptions={[]}
        sampleRows={[]}
        onServerTest={serverTest}
      />,
    );
    expect(screen.queryByTestId('combine-enable')).not.toBeInTheDocument();
    expect(screen.queryByText('Add drop rule')).not.toBeInTheDocument();
  });
});
