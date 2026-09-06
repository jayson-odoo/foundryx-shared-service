import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { DateRangePicker, resolvePresetRange } from './date-range-picker';

const KL = 'Asia/Kuala_Lumpur';

describe('resolvePresetRange', () => {
  it('resolves last7 to a 7-day inclusive window ending today (report tz)', () => {
    const fixedNow = new Date('2026-03-10T20:00:00Z'); // 2026-03-11 04:00 KL
    vi.useFakeTimers();
    vi.setSystemTime(fixedNow);
    const { from, to } = resolvePresetRange('last7', KL);
    vi.useRealTimers();
    expect(to).toBe('2026-03-11');
    expect(from).toBe('2026-03-05');
  });

  it('resolves last30 to a 30-day inclusive window', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-10T20:00:00Z'));
    const { from, to } = resolvePresetRange('last30', KL);
    vi.useRealTimers();
    expect(to).toBe('2026-03-11');
    expect(from).toBe('2026-02-10');
  });

  it('resolves thisMonth from the 1st through today', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-10T20:00:00Z'));
    const { from, to } = resolvePresetRange('thisMonth', KL);
    vi.useRealTimers();
    expect(from).toBe('2026-03-01');
    expect(to).toBe('2026-03-11');
  });

  it('resolves lastMonth to the previous full calendar month', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-03-10T20:00:00Z'));
    const { from, to } = resolvePresetRange('lastMonth', KL);
    vi.useRealTimers();
    expect(from).toBe('2026-02-01');
    expect(to).toBe('2026-02-28');
  });

  it('resolves lastMonth across a year boundary', () => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date('2026-01-10T20:00:00Z'));
    const { from, to } = resolvePresetRange('lastMonth', KL);
    vi.useRealTimers();
    expect(from).toBe('2025-12-01');
    expect(to).toBe('2025-12-31');
  });
});

describe('DateRangePicker', () => {
  it('renders the resolved range and switches presets via the SearchSelect', () => {
    const onChange = vi.fn();
    render(
      <DateRangePicker
        value={{ preset: 'last7', from: '2026-03-01', to: '2026-03-07' }}
        onChange={onChange}
        timeZone={KL}
      />,
    );
    expect(screen.getByText('1 Mar - 7 Mar')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('combobox', { name: 'Date range preset' }));
    fireEvent.click(screen.getByText('Last 30 days'));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ preset: 'last30' }),
    );
  });

  it('a two-click custom pick does not close after the FIRST click, even when it lands before the previous range (react-day-picker range-merge gotcha)', () => {
    const onChange = vi.fn();
    render(
      <DateRangePicker
        value={{ preset: 'last7', from: '2026-03-10', to: '2026-03-16' }}
        onChange={onChange}
        timeZone={KL}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: /10 Mar - 16 Mar/ }));

    // Click a day BEFORE the existing range's start - react-day-picker's own
    // range-merge can hand back {from: newDay, to: oldTo} on this very first
    // click (a "complete-looking" range); the picker must still treat it as
    // step one of a fresh two-click pick and keep the popover open.
    fireEvent.click(screen.getByRole('button', { name: /March 1st, 2026/ }));
    expect(onChange).toHaveBeenLastCalledWith({ preset: 'custom', from: '2026-03-01', to: '2026-03-01' });
    expect(screen.getByRole('button', { name: /March 7th, 2026/ })).toBeInTheDocument();

    // Second click completes the range (order-independent: clicking an
    // earlier day than the anchor still yields from <= to).
    fireEvent.click(screen.getByRole('button', { name: /March 7th, 2026/ }));
    expect(onChange).toHaveBeenLastCalledWith({ preset: 'custom', from: '2026-03-01', to: '2026-03-07' });
  });

  it('shows a single day label when from equals to', () => {
    render(
      <DateRangePicker
        value={{ preset: 'custom', from: '2026-03-05', to: '2026-03-05' }}
        onChange={vi.fn()}
        timeZone={KL}
      />,
    );
    expect(screen.getByText('5 Mar')).toBeInTheDocument();
  });
});
