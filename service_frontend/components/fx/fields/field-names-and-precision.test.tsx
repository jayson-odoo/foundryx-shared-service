/**
 * Foundation follow-up, owner re-test (switch on):
 * - the stepper never lets binary residue reach the field, onChange or the
 *   form: every button, arrow-key and hold-to-repeat value is rounded to the
 *   field's precision (6.5 at step 0.01, then + is exactly 6.51);
 * - a labelled field is named by its visible label, never by its
 *   placeholder (FxField + every fx control), placeholder only last.
 */
import { act, fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState, type ReactNode } from 'react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { decimalsOf, roundTo, snapToStep, stepValue } from '@/lib/fx/fields';
import { FxProvider } from '@/providers/fx-provider';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { MultiSelect } from '@/components/platform/multi-select';
import { SearchSelect } from '@/components/platform/search-select';
import { FX_HOLD_DELAY_MS, FX_HOLD_REPEAT_MS } from '@/components/fx/fields/fx-stepper';
import {
  FxDateField,
  FxField,
  FxMoneyField,
  FxStepper,
  fxControlName,
} from '@/components/fx/fields';

function renderOn(ui: ReactNode) {
  return render(
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {ui}
    </FxProvider>,
  );
}

/** A stepper that keeps its own value, like a form does. */
function Held(props: { start: number; step: number; min?: number; max?: number; precision?: number; onChange: (n: number) => void }) {
  const [value, setValue] = useState(props.start);
  return (
    <FxStepper
      aria-label="Tax %"
      value={value}
      min={props.min ?? 0}
      max={props.max ?? 100}
      step={props.step}
      precision={props.precision}
      onChange={(n) => {
        setValue(n);
        props.onChange(n);
      }}
    />
  );
}

const plus = () => screen.getByRole('button', { name: 'Increase' });
const minus = () => screen.getByRole('button', { name: 'Decrease' });
function press(button: HTMLElement) {
  fireEvent.pointerDown(button);
  fireEvent.pointerUp(button);
}

afterEach(() => {
  vi.useRealTimers();
});

describe('stepper precision: no float residue', () => {
  it('6.5 at step 0.01, then + is exactly 6.51, then 6.52', () => {
    const onChange = vi.fn();
    renderOn(<Held start={6.5} step={0.01} onChange={onChange} />);
    press(plus());
    expect(onChange).toHaveBeenLastCalledWith(6.51);
    expect(onChange.mock.lastCall?.[0]).toBe(6.51);
    expect(screen.getByRole('spinbutton', { name: 'Tax %' })).toHaveValue('6.51');
    press(plus());
    expect(onChange.mock.lastCall?.[0]).toBe(6.52);
    press(minus());
    press(minus());
    press(minus());
    expect(onChange.mock.lastCall?.[0]).toBe(6.49);
    expect(screen.getByRole('spinbutton', { name: 'Tax %' })).toHaveValue('6.49');
  });

  it('a typed 6.5 at step 0.01, then the arrow keys', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<Held start={6} step={0.01} onChange={onChange} />);
    const box = screen.getByRole('spinbutton', { name: 'Tax %' });
    await user.clear(box);
    await user.type(box, '6.5');
    await user.tab();
    expect(onChange.mock.lastCall?.[0]).toBe(6.5);
    await user.click(box);
    await user.keyboard('{ArrowUp}');
    expect(onChange.mock.lastCall?.[0]).toBe(6.51);
    await user.keyboard('{ArrowDown}{ArrowDown}');
    expect(onChange.mock.lastCall?.[0]).toBe(6.49);
  });

  it('across the 0.1 / 0.2 / 0.3 boundaries every value is exact', () => {
    const onChange = vi.fn();
    renderOn(<Held start={0} step={0.1} onChange={onChange} />);
    for (let i = 0; i < 12; i += 1) press(plus());
    expect(onChange.mock.calls.map(([n]) => n)).toEqual([
      0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1, 1.1, 1.2,
    ]);
    onChange.mockClear();
    for (let i = 0; i < 4; i += 1) press(minus());
    expect(onChange.mock.calls.map(([n]) => n)).toEqual([1.1, 1, 0.9, 0.8]);
  });

  it('hold-to-repeat values are exact too', () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    renderOn(<Held start={0.2} step={0.1} onChange={onChange} />);
    fireEvent.pointerDown(plus());
    act(() => {
      vi.advanceTimersByTime(FX_HOLD_DELAY_MS);
    });
    for (let i = 0; i < 3; i += 1) {
      act(() => {
        vi.advanceTimersByTime(FX_HOLD_REPEAT_MS);
      });
    }
    fireEvent.pointerUp(plus());
    const seen = onChange.mock.calls.map(([n]) => n);
    expect(seen.length).toBeGreaterThanOrEqual(4);
    seen.forEach((n, i) => expect(n).toBe(roundTo(0.2 + 0.1 * (i + 1), 1)));
    expect(seen.slice(0, 4)).toEqual([0.3, 0.4, 0.5, 0.6]);
  });

  it('step 1 from 6.5 still goes to 7 and 6', () => {
    const onChange = vi.fn();
    const { unmount } = renderOn(<Held start={6.5} step={1} onChange={onChange} />);
    press(plus());
    expect(onChange.mock.lastCall?.[0]).toBe(7);
    unmount();
    renderOn(<Held start={6.5} step={1} onChange={onChange} />);
    press(minus());
    expect(onChange.mock.lastCall?.[0]).toBe(6);
  });

  it('min and max still clamp', () => {
    const onChange = vi.fn();
    const { unmount } = renderOn(<Held start={99.99} step={0.01} max={100} onChange={onChange} />);
    press(plus());
    expect(onChange.mock.lastCall?.[0]).toBe(100);
    expect(plus()).toBeDisabled();
    unmount();
    renderOn(<Held start={0.01} step={0.01} min={0} onChange={onChange} />);
    press(minus());
    expect(onChange.mock.lastCall?.[0]).toBe(0);
    expect(minus()).toBeDisabled();
  });

  it('a stored 32-bit value shows and steps at the field precision', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<Held start={6.510000228881836} step={0.01} precision={4} onChange={onChange} />);
    const box = screen.getByRole('spinbutton', { name: 'Tax %' });
    expect(box).toHaveValue('6.51');
    expect(box).toHaveAttribute('aria-valuenow', '6.51');
    // Leaving the field untouched sends nothing new.
    await user.click(box);
    await user.tab();
    expect(onChange).not.toHaveBeenCalled();
    press(plus());
    expect(onChange.mock.lastCall?.[0]).toBe(6.52);
    press(minus());
    press(minus());
    expect(onChange.mock.lastCall?.[0]).toBe(6.5);
  });

  it('a typed value keeps its decimals up to the precision, not snapped', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<Held start={6} step={1} precision={2} onChange={onChange} />);
    const box = screen.getByRole('spinbutton', { name: 'Tax %' });
    await user.clear(box);
    await user.type(box, '6.555');
    await user.tab();
    expect(onChange.mock.lastCall?.[0]).toBe(6.56);
    await user.clear(box);
    await user.type(box, '6.5');
    await user.tab();
    expect(onChange.mock.lastCall?.[0]).toBe(6.5);
  });

  it('the pure helpers', () => {
    expect(decimalsOf(0.01)).toBe(2);
    expect(decimalsOf(1)).toBe(0);
    expect(decimalsOf(1e-7)).toBe(7);
    expect(roundTo(6.510000228881836, 2)).toBe(6.51);
    expect(roundTo(0.1 + 0.2, 2)).toBe(0.3);
    expect(roundTo(1.005, 2)).toBe(1.01);
    expect(roundTo(-2.345, 2)).toBe(-2.35);
    expect(stepValue(6.5, 1, 0, 100, 0.01)).toBe(6.51);
    expect(stepValue(0.2, 1, 0, 1, 0.1)).toBe(0.3);
    expect(stepValue(0.3, -1, 0, 1, 0.1)).toBe(0.2);
    // A grid that starts on a decimal keeps the start's decimals.
    expect(stepValue(1.5, 1, 0.5, 10, 1)).toBe(2.5);
    expect(snapToStep(2.4, 0.5, 10, 1)).toBe(2.5);
  });
});

describe('a labelled field is named by its visible label', () => {
  const options = [
    { label: 'VIP', value: 'vip' },
    { label: 'Lead', value: 'lead' },
  ];

  it('text field and text area', () => {
    renderOn(
      <>
        <FxField label="Name">
          <Input placeholder="Spring promo" />
        </FxField>
        <FxField label="Notes">
          <Textarea placeholder="Anything else" />
        </FxField>
      </>,
    );
    const name = screen.getByRole('textbox', { name: 'Name' });
    expect(screen.getByText('Name')).toHaveAttribute('for', name.id);
    expect(screen.getByRole('textbox', { name: 'Notes' })).toBeInTheDocument();
  });

  it('searchable dropdowns', () => {
    renderOn(
      <>
        <FxField label="Labels">
          <MultiSelect options={options} value={[]} onChange={vi.fn()} placeholder="Pick labels" />
        </FxField>
        <FxField label="Channel">
          <SearchSelect options={options} value={null} onChange={vi.fn()} placeholder="Pick one" />
        </FxField>
      </>,
    );
    expect(screen.getByRole('combobox', { name: 'Labels' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Channel' })).toBeInTheDocument();
  });

  it('date, money and stepper', () => {
    renderOn(
      <>
        <FxField label="Send on">
          <FxDateField value={null} onChange={vi.fn()} placeholder="20 Nov 2026" today="2026-11-18" />
        </FxField>
        <FxField label="Price">
          <FxMoneyField
            value={null}
            onChange={vi.fn()}
            currency="MYR"
            currencies={['MYR', 'USD']}
            onCurrencyChange={vi.fn()}
          />
        </FxField>
        <FxField label="Seats">
          <FxStepper value={2} onChange={vi.fn()} />
        </FxField>
      </>,
    );
    expect(screen.getByRole('textbox', { name: 'Send on' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Price' })).toBeInTheDocument();
    // The currency picker inside keeps its own name and its own id.
    const currency = screen.getByRole('combobox', { name: 'Currency' });
    expect(currency.id).not.toBe(screen.getByRole('textbox', { name: 'Price' }).id);
    expect(screen.getByRole('spinbutton', { name: 'Seats' })).toBeInTheDocument();
  });

  it('points the control at its message', () => {
    renderOn(
      <FxField label="Name" message="Enter a name">
        <Input />
      </FxField>,
    );
    const box = screen.getByRole('textbox', { name: 'Name' });
    expect(box).toHaveAccessibleDescription('Enter a name');
  });

  it('own names win, the placeholder is the last resort', () => {
    renderOn(
      <>
        <FxField label="Labels">
          <MultiSelect ariaLabel="Contact labels" options={options} value={[]} onChange={vi.fn()} />
        </FxField>
        <SearchSelect options={options} value={null} onChange={vi.fn()} placeholder="Pick a team" />
      </>,
    );
    expect(screen.getByRole('combobox', { name: 'Contact labels' })).toBeInTheDocument();
    expect(screen.getByRole('combobox', { name: 'Pick a team' })).toBeInTheDocument();
  });

  it('naming order (pure)', () => {
    const field = { controlId: 'c', labelId: 'c-label' };
    expect(fxControlName({ ariaLabel: 'A', placeholder: 'P' }, field)).toMatchObject({ id: 'c', 'aria-label': 'A' });
    expect(fxControlName({ placeholder: 'P' }, field)).toMatchObject({ id: 'c', 'aria-labelledby': 'c-label' });
    expect(fxControlName({ id: 'x', placeholder: 'P' }, null)).toEqual({ id: 'x' });
    expect(fxControlName({ placeholder: 'P' }, null)).toMatchObject({ 'aria-label': 'P' });
  });
});
