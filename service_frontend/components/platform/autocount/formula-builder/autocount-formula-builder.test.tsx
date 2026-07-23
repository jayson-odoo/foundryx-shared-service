import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { AutocountFormulaTestResult } from '@/types/autocount';
import { AutocountFormulaBuilder } from './autocount-formula-builder';

function passThroughServer(formula: string, value: unknown): Promise<AutocountFormulaTestResult> {
  // Stand-in "server" that agrees with the client for the boolean formula.
  const ok = String(value) === 'T';
  return Promise.resolve({ ok: true, output: ok, error: null });
}

function renderBuilder(over: Partial<React.ComponentProps<typeof AutocountFormulaBuilder>> = {}) {
  const onApply = vi.fn();
  const onOpenChange = vi.fn();
  render(
    <AutocountFormulaBuilder
      open
      onOpenChange={onOpenChange}
      value=""
      onApply={onApply}
      onServerTest={passThroughServer}
      {...over}
    />,
  );
  return { onApply, onOpenChange };
}

describe('AutocountFormulaBuilder (AC-16-11..15)', () => {
  it('pre-fills the formula from the value prop (preset pre-fill)', () => {
    renderBuilder({ value: 'if(value == "T", true, false)' });
    expect(screen.getByLabelText('Formula expression')).toHaveValue('if(value == "T", true, false)');
  });

  it('inserts a searched function at the caret (AC-16-13)', () => {
    renderBuilder();
    fireEvent.change(screen.getByLabelText('Search functions'), { target: { value: 'upper' } });
    fireEvent.click(screen.getByText('upper(text)'));
    expect(screen.getByLabelText('Formula expression')).toHaveValue('upper()');
  });

  it('shows the function reference when a function is selected (AC-16-15)', () => {
    renderBuilder();
    fireEvent.change(screen.getByLabelText('Search functions'), { target: { value: 'contains' } });
    fireEvent.click(screen.getByText('contains(text, sub)'));
    const ref = screen.getByTestId('function-reference');
    expect(ref).toHaveTextContent('contains(text, sub)');
    expect(ref).toHaveTextContent('True when text contains sub.');
    expect(ref).toHaveTextContent('sub');
  });

  it('blocks Apply on an invalid formula (front gate, AC-16-11)', () => {
    renderBuilder({ value: 'value' });
    const apply = screen.getByRole('button', { name: 'Apply' });
    expect(apply).toBeEnabled();
    fireEvent.change(screen.getByLabelText('Formula expression'), { target: { value: 'upper(' } });
    expect(screen.getByTestId('formula-status')).toHaveTextContent(/./);
    expect(apply).toBeDisabled();
  });

  it('applies a valid formula and closes', () => {
    const { onApply, onOpenChange } = renderBuilder({ value: 'value' });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledWith('value');
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it('shows a contextual note when provided (e.g. the Decimal precision caveat)', () => {
    renderBuilder({ value: 'number(value)', note: 'The Decimal preset keeps exact money precision.' });
    expect(screen.getByTestId('formula-note')).toHaveTextContent(/exact money precision/i);
  });

  it('surfaces the date-format tool on the Date category (AC-16-14)', () => {
    renderBuilder({ initialCategory: 'Date' });
    expect(screen.getByLabelText('Date input format')).toBeInTheDocument();
    expect(screen.getByLabelText('Date output format')).toBeInTheDocument();
  });

  it('shows a live output and a server parity check in the Testing tab (AC-16-20/21)', async () => {
    const onServerTest = vi.fn(passThroughServer);
    renderBuilder({ value: 'if(value == "T", true, false)', onServerTest });
    await userEvent.click(screen.getByRole('tab', { name: 'Testing' }));
    fireEvent.change(screen.getByLabelText('Mock input value'), { target: { value: 'T' } });
    // Live client output.
    expect(screen.getByTestId('client-output')).toHaveTextContent('true');
    // Server parity check.
    fireEvent.click(screen.getByRole('button', { name: /check on server/i }));
    await waitFor(() =>
      expect(screen.getByTestId('server-output')).toHaveTextContent(/matches the client preview/i),
    );
    expect(onServerTest).toHaveBeenCalledWith('if(value == "T", true, false)', 'T');
  });

  it('shows the failure, not a blank, for a bad mock value (AC-16-20)', async () => {
    renderBuilder({ value: 'number(value)' });
    await userEvent.click(screen.getByRole('tab', { name: 'Testing' }));
    fireEvent.change(screen.getByLabelText('Mock input value'), { target: { value: 'abc' } });
    expect(screen.getByTestId('client-output')).toHaveTextContent(/expected a number/i);
  });
});
