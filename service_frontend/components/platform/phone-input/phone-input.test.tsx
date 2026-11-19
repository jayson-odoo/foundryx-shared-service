import { useState } from 'react';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { PhoneInput, type PhoneInputMeta } from './phone-input';

/** Mirrors the CRM Dealer Access phone field (lane FEEDBACK-SHARE-SS-HOST).
 * Every number here is made up. */
function Harness({ onChange }: { onChange?: (e164: string, meta: PhoneInputMeta) => void }) {
  const [value, setValue] = useState('');
  return (
    <>
      <label htmlFor="p">Phone</label>
      <PhoneInput
        id="p"
        value={value}
        onChange={(e164, meta) => {
          setValue(e164);
          onChange?.(e164, meta);
        }}
      />
    </>
  );
}

describe('PhoneInput', () => {
  it('defaults to Malaysia with the MY placeholder', () => {
    render(<Harness />);
    expect(screen.getByRole('button', { name: 'Country: Malaysia (+60)' })).toBeInTheDocument();
    expect(screen.getByText('+60')).toBeInTheDocument();
    expect(screen.getByLabelText('Phone')).toHaveAttribute('placeholder', '12-345 6789');
    expect(screen.getByLabelText('Phone')).toHaveAttribute('type', 'tel');
  });

  it('formats as you type, drops the trunk 0 and emits E.164 + validity', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('Phone'), '0160000509');
    expect(screen.getByLabelText('Phone')).toHaveValue('16-000 0509');
    expect(onChange).toHaveBeenLastCalledWith('+60160000509', { valid: true, country: 'MY' });
  });

  it('typing an international prefix switches the country', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('Phone'), '+6581234567');
    expect(screen.getByRole('button', { name: 'Country: Singapore (+65)' })).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith('+6581234567', { valid: true, country: 'SG' });
  });

  it('shows the error only after blur, never while typing', async () => {
    render(<Harness />);
    const field = screen.getByLabelText('Phone');
    await userEvent.type(field, '0123');
    expect(screen.queryByRole('alert')).toBeNull();
    await userEvent.tab();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a complete phone number.');
  });

  it('the country picker is searchable and keeps the digits', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('Phone'), '81234567');
    await userEvent.click(screen.getByRole('button', { name: 'Country: Malaysia (+60)' }));
    await userEvent.type(screen.getByPlaceholderText('Search...'), 'singa');
    await userEvent.click(await screen.findByRole('option', { name: /Singapore/ }));
    expect(screen.getByRole('button', { name: 'Country: Singapore (+65)' })).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith('+6581234567', { valid: true, country: 'SG' });
  });

  it('an unmatched search says so', async () => {
    render(<Harness />);
    await userEvent.click(screen.getByRole('button', { name: 'Country: Malaysia (+60)' }));
    await userEvent.type(screen.getByPlaceholderText('Search...'), 'zzzz');
    expect(await screen.findByText('No results found.')).toBeInTheDocument();
  });

  it('a complete number settles on its own country for a shared calling code', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('Phone'), '+79161234567');
    expect(screen.getByRole('button', { name: 'Country: Russia (+7)' })).toBeInTheDocument();
    expect(onChange).toHaveBeenLastCalledWith('+79161234567', { valid: true, country: 'RU' });
  });

  it('keeps a leading 0 for countries without a trunk 0', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('Phone'), '+39 06 1234 5678');
    expect(onChange).toHaveBeenLastCalledWith('+390612345678', { valid: true, country: 'IT' });
  });

  it('an edit in the middle keeps the caret after the typed digit', async () => {
    render(<Harness />);
    const field = screen.getByLabelText('Phone') as HTMLInputElement;
    await userEvent.type(field, '160000509');
    expect(field).toHaveValue('16-000 0509');
    field.setSelectionRange(1, 1);
    await userEvent.type(field, '9', { initialSelectionStart: 1, initialSelectionEnd: 1 });
    expect(field.value.replace(/\D/g, '')).toBe('1960000509');
    expect(field.value.slice(0, field.selectionStart ?? 0).replace(/\D/g, '')).toBe('19');
  });

  it('deleting a separator deletes the digit before it', async () => {
    render(<Harness />);
    const field = screen.getByLabelText('Phone') as HTMLInputElement;
    await userEvent.type(field, '160000509');
    // Caret after the "-" (position 3), Backspace removes the separator.
    await userEvent.type(field, '{Backspace}', { initialSelectionStart: 3, initialSelectionEnd: 3 });
    expect(field.value.replace(/\D/g, '')).toBe('10000509');
  });
  // CRM rule (crew matrix s2): digits that start with the own calling code
  // read as international only when they are NOT also a valid national number.
  // In the UAE (+971) "97180070" is valid both ways, so it stays national.
  it('a valid national number that starts with the calling code stays national', async () => {
    const onChange = vi.fn();
    render(
      <>
        <label htmlFor="ae">Phone</label>
        <PhoneInput id="ae" value="" defaultCountry="AE" onChange={onChange} />
      </>,
    );
    await userEvent.type(screen.getByLabelText('Phone'), '97180070');
    expect(onChange).toHaveBeenLastCalledWith('+97197180070', expect.objectContaining({ country: 'AE' }));
  });

  it('digits that are only valid with the calling code read as international', async () => {
    const onChange = vi.fn();
    render(<Harness onChange={onChange} />);
    await userEvent.type(screen.getByLabelText('Phone'), '60123456789');
    expect(onChange).toHaveBeenLastCalledWith('+60123456789', { valid: true, country: 'MY' });
  });
});
