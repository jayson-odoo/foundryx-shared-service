/**
 * Plan 63 round 1 (AC-63-34, RED): a date field can restrict its operators to the range
 * (`operators: ['between']`), and a saved `between` with only a start or only an end keeps
 * that half instead of being reset to a preset.
 */
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import type { FilterFieldDef, FilterGroup } from '@/types/resource';
import { FilterBuilder } from './filter-builder';

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { timezone: 'Asia/Kuala_Lumpur' } }, status: 'authenticated' }),
}));

const FREE_DATE: FilterFieldDef = { field: 'createdAt', label: 'Time', type: 'date' };
const RANGE_ONLY = { field: 'createdAt', label: 'Time', type: 'date', operators: ['between'] } as unknown as FilterFieldDef;

function saved(value: string[]): FilterGroup {
  return {
    kind: 'group',
    combinator: 'and',
    rules: [{ kind: 'condition', field: 'createdAt', operator: 'between', value }],
  };
}

async function openOperators() {
  await userEvent.click(screen.getByLabelText('Filter operator'));
}

describe('operator list per field (AC-63-34)', () => {
  it('control: a plain date field offers between, before and after', async () => {
    render(<FilterBuilder fields={[FREE_DATE]} onApply={vi.fn()} initialValue={saved(['2026-11-05', '2026-11-06'])} />);
    await openOperators();
    expect(await screen.findByRole('option', { name: 'before' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'after' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'between' })).toBeInTheDocument();
  });

  it('a field restricted to the range offers between only', async () => {
    render(<FilterBuilder fields={[RANGE_ONLY]} onApply={vi.fn()} initialValue={saved(['2026-11-05', '2026-11-06'])} />);
    await openOperators();
    expect(await screen.findByRole('option', { name: 'between' })).toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'before' })).not.toBeInTheDocument();
    expect(screen.queryByRole('option', { name: 'after' })).not.toBeInTheDocument();
  });

  it('a new condition on a restricted field starts on between and never shows a native date input', async () => {
    const { container } = render(<FilterBuilder fields={[RANGE_ONLY]} onApply={vi.fn()} />);
    await waitFor(() => expect(screen.getByLabelText('Filter operator')).toHaveTextContent(/between/i));
    expect(container.querySelector('input[type="date"]')).toBeNull();
  });
});

describe('a half-open saved range keeps its half (AC-63-34)', () => {
  it.each([
    ['start only', ['2026-11-05', ''], 0, '2026-11-05'],
    ['end only', ['', '2026-11-06'], 1, '2026-11-06'],
  ])('%s survives opening and applying the builder', async (_name, value, index, kept) => {
    const onApply = vi.fn();
    render(<FilterBuilder fields={[RANGE_ONLY]} onApply={onApply} initialValue={saved(value)} />);
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    expect(onApply).toHaveBeenCalledTimes(1);
    const applied = onApply.mock.calls[0][0] as FilterGroup;
    const rule = applied.rules[0];
    expect(rule.kind === 'condition' && Array.isArray(rule.value) ? rule.value[index] : null).toBe(kept);
  });

  it('control: a complete range is applied as saved', async () => {
    const onApply = vi.fn();
    render(<FilterBuilder fields={[RANGE_ONLY]} onApply={onApply} initialValue={saved(['2026-11-05', '2026-11-06'])} />);
    await userEvent.click(screen.getByRole('button', { name: 'Apply' }));
    const rule = (onApply.mock.calls[0][0] as FilterGroup).rules[0];
    expect(rule.kind === 'condition' && rule.value).toEqual(['2026-11-05', '2026-11-06']);
  });
});

describe('a half-open saved range reads as open, not as a one-day range (AC-63-34, round 2)', () => {
  function shown(value: string[]): string {
    const { container, unmount } = render(
      <FilterBuilder fields={[RANGE_ONLY]} onApply={vi.fn()} initialValue={saved(value)} />,
    );
    const text = container.textContent ?? '';
    unmount();
    return text;
  }

  it('start only differs from the one-day range of that start and still shows the start', () => {
    const oneDay = shown(['2026-11-05', '2026-11-05']);
    const startOnly = shown(['2026-11-05', '']);
    expect(oneDay).toContain('05/11/2026');
    expect(startOnly).toContain('05/11/2026');
    expect(startOnly).not.toBe(oneDay);
  });

  it('end only differs from the one-day range of that end and still shows the end', () => {
    const oneDay = shown(['2026-11-06', '2026-11-06']);
    const endOnly = shown(['', '2026-11-06']);
    expect(oneDay).toContain('06/11/2026');
    expect(endOnly).toContain('06/11/2026');
    expect(endOnly).not.toBe(oneDay);
  });

  it('control: a complete range reads as both ends', () => {
    expect(shown(['2026-11-05', '2026-11-06'])).toMatch(/05\/11\/2026.*06\/11\/2026/);
  });
});
