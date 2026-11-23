/**
 * Foundation follow-up from the first page wave, fields side: a typed
 * stepper value is not snapped to the step (FX-12), and the many-choice
 * dropdown has an accessible name (FX-19). Switch on.
 */
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';
import { describe, expect, it, vi } from 'vitest';
import { FX_DEFAULT_THEME } from '@/lib/fx/cookies';
import { clampValue, snapToStep, stepValue } from '@/lib/fx/fields';
import { FxProvider } from '@/providers/fx-provider';
import { Label } from '@/components/ui/label';
import { MultiSelect } from '@/components/platform/multi-select';
import { FxStepper } from '@/components/fx/fields';

function renderOn(ui: ReactNode) {
  return render(
    <FxProvider initial initialTheme={FX_DEFAULT_THEME}>
      {ui}
    </FxProvider>,
  );
}

describe('FX-12 stepper: typed values are clamped, not snapped', () => {
  it('keeps 6.5 at step 1, and still clamps to the range', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxStepper aria-label="Tax" value={6} onChange={onChange} min={0} max={100} step={1} />);
    const box = screen.getByRole('spinbutton', { name: 'Tax' });
    await user.clear(box);
    await user.type(box, '6.5');
    await user.tab();
    expect(onChange).toHaveBeenLastCalledWith(6.5);

    await user.clear(box);
    await user.type(box, '140');
    await user.tab();
    expect(onChange).toHaveBeenLastCalledWith(100);
  });

  it('snaps a typed value when the page asks for it', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    renderOn(<FxStepper aria-label="Seats" value={2} onChange={onChange} min={0} max={10} step={1} snap />);
    const box = screen.getByRole('spinbutton', { name: 'Seats' });
    await user.clear(box);
    await user.type(box, '6.5');
    await user.tab();
    expect(onChange).toHaveBeenLastCalledWith(7);
  });

  it('− and + from between two steps go to the next step that way (pure)', () => {
    expect(stepValue(6.5, 1, 0, 100, 1)).toBe(7);
    expect(stepValue(6.5, -1, 0, 100, 1)).toBe(6);
    expect(stepValue(6, 1, 0, 100, 1)).toBe(7);
    expect(stepValue(0.25, 1, 0, 2, 0.1)).toBe(0.3);
    expect(clampValue(-3, 0, 10)).toBe(0);
    // No min: the grid starts at 0 rather than giving no number at all.
    expect(snapToStep(3.4, -Infinity, Infinity, 1)).toBe(3);
    expect(stepValue(2, 1, -Infinity, Infinity, 1)).toBe(3);
  });
});

describe('FX-19 the many-choice dropdown has a name', () => {
  const options = [
    { label: 'VIP', value: 'vip' },
    { label: 'Lead', value: 'lead' },
  ];

  it('from ariaLabel', () => {
    renderOn(<MultiSelect ariaLabel="Tags" options={options} value={['vip']} onChange={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: 'Tags' })).toBeInTheDocument();
  });

  it('from its label', () => {
    renderOn(
      <>
        <Label htmlFor="tags-field">Tags</Label>
        <MultiSelect id="tags-field" options={options} value={[]} onChange={vi.fn()} />
      </>,
    );
    expect(screen.getByRole('combobox', { name: 'Tags' })).toBeInTheDocument();
  });

  it('from what it asks for when nothing names it', () => {
    renderOn(<MultiSelect placeholder="Pick tags" options={options} value={['vip']} onChange={vi.fn()} />);
    expect(screen.getByRole('combobox', { name: 'Pick tags' })).toBeInTheDocument();
  });
});
