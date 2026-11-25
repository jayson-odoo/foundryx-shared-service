import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { DateRangeTypedInputs } from './date-range-typed-inputs';

function setup(props: Partial<Parameters<typeof DateRangeTypedInputs>[0]> = {}) {
  const onChange = vi.fn();
  const onJump = vi.fn();
  render(
    <DateRangeTypedInputs
      from="2020-03-01"
      to="2020-03-31"
      minDate="2000-01-01"
      maxDate="2026-11-25"
      today="2026-11-25"
      onChange={onChange}
      onJump={onJump}
      {...props}
    />,
  );
  return { onChange, onJump };
}

describe('DateRangeTypedInputs', () => {
  it('shows both ends as dd/mm/yyyy', () => {
    setup();
    expect(screen.getByTestId('date-range-typed-from')).toHaveValue('01/03/2020');
    expect(screen.getByTestId('date-range-typed-to')).toHaveValue('31/03/2020');
  });

  it('a typed From is accepted on Enter and jumps the calendar to it', async () => {
    const { onChange, onJump } = setup();
    const from = screen.getByTestId('date-range-typed-from');
    await userEvent.clear(from);
    await userEvent.type(from, '05/02/2010{Enter}');
    expect(onChange).toHaveBeenCalledWith('2010-02-05', '2020-03-31');
    expect(onJump).toHaveBeenCalledWith('2010-02-05');
  });

  it('a From after To moves To with it (never an upside-down range)', async () => {
    const { onChange } = setup();
    const from = screen.getByTestId('date-range-typed-from');
    await userEvent.clear(from);
    await userEvent.type(from, '2021-06-01');
    await userEvent.tab();
    expect(onChange).toHaveBeenCalledWith('2021-06-01', '2021-06-01');
  });

  it('a To before From moves From with it', async () => {
    const { onChange } = setup();
    const to = screen.getByTestId('date-range-typed-to');
    await userEvent.clear(to);
    await userEvent.type(to, '15/01/2019{Enter}');
    expect(onChange).toHaveBeenCalledWith('2019-01-15', '2019-01-15');
  });

  it('refuses unreadable text and days outside the bounds', async () => {
    const { onChange } = setup();
    const from = screen.getByTestId('date-range-typed-from');
    await userEvent.clear(from);
    await userEvent.type(from, 'not a date{Enter}');
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a date like 05/11/2026');
    await userEvent.clear(from);
    await userEvent.type(from, '31/12/1999{Enter}');
    expect(screen.getByRole('alert')).toHaveTextContent('Pick a day from 01/01/2000 to 25/11/2026');
    expect(onChange).not.toHaveBeenCalled();
  });

  it('a blur without a change neither jumps the calendar nor changes the range', async () => {
    const { onChange, onJump } = setup();
    await userEvent.click(screen.getByTestId('date-range-typed-to'));
    await userEvent.tab();
    expect(onJump).not.toHaveBeenCalled();
    expect(onChange).not.toHaveBeenCalled();
  });

  it('each field keeps its own message', async () => {
    setup();
    const from = screen.getByTestId('date-range-typed-from');
    await userEvent.clear(from);
    await userEvent.type(from, 'nope');
    await userEvent.click(screen.getByTestId('date-range-typed-to'));
    await userEvent.tab();
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a date like 05/11/2026');
    expect(from).toHaveValue('nope');
  });
});
