import { describe, expect, it } from 'vitest';
import {
  endOfLocalDay,
  momentDateFields,
  startOfLocalDay,
  toServerDateFilter,
} from './date-filter';
import { matchesFilterGroup } from './client-filter';
import type { FilterGroup } from '@/types/resource';

const KL = 'Asia/Kuala_Lumpur';

const group = (...rules: FilterGroup['rules']): FilterGroup => ({ kind: 'group', combinator: 'and', rules });

describe('local days as instants', () => {
  it('a Kuala Lumpur day starts at 16:00 UTC the day before and ends a millisecond before the next', () => {
    expect(startOfLocalDay('2026-11-19', KL)).toBe('2026-11-18T16:00:00.000Z');
    expect(endOfLocalDay('2026-11-19', KL)).toBe('2026-11-19T15:59:59.999Z');
  });

  it('crosses month and year ends', () => {
    expect(endOfLocalDay('2026-12-31', KL)).toBe('2026-12-31T15:59:59.999Z');
    expect(startOfLocalDay('2027-01-01', 'UTC')).toBe('2027-01-01T00:00:00.000Z');
    expect(endOfLocalDay('2026-11-30', 'America/New_York')).toBe('2026-12-01T04:59:59.999Z');
  });
});

describe('toServerDateFilter', () => {
  it('sends "Today" as the whole local day (the bug: both ends were the same UTC midnight)', () => {
    const filter = group(
      group(),
      group({ kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-19', '2026-11-19'] }),
    );
    expect(toServerDateFilter(filter, ['joined'], KL)).toEqual(
      group(
        group(),
        group({
          kind: 'condition',
          field: 'joined',
          operator: 'between',
          value: ['2026-11-18T16:00:00.000Z', '2026-11-19T15:59:59.999Z'],
        }),
      ),
    );
  });

  it('includes the last day of a longer range, and moves before/after to the local day start', () => {
    const out = toServerDateFilter(
      group(
        { kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-13', '2026-11-19'] },
        { kind: 'condition', field: 'lastSignIn', operator: 'before', value: '2026-11-01' },
        { kind: 'condition', field: 'lastSignIn', operator: 'after', value: '2026-10-01' },
      ),
      ['joined', 'lastSignIn'],
      KL,
    );
    expect(out?.rules).toEqual([
      { kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-12T16:00:00.000Z', '2026-11-19T15:59:59.999Z'] },
      { kind: 'condition', field: 'lastSignIn', operator: 'before', value: '2026-10-31T16:00:00.000Z' },
      { kind: 'condition', field: 'lastSignIn', operator: 'after', value: '2026-09-30T16:00:00.000Z' },
    ]);
  });

  it('leaves calendar-day fields, other fields, empty ends and non-day values as they are', () => {
    const filter = group(
      { kind: 'condition', field: 'customFields.birthday', operator: 'between', value: ['2026-11-19', '2026-11-19'] },
      { kind: 'condition', field: 'name', operator: 'contains', value: '2026-11-19' },
      { kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-01', ''] },
      { kind: 'condition', field: 'joined', operator: 'after', value: '2026-11-01T00:00:00Z' },
    );
    const fields = momentDateFields([
      { field: 'joined', label: 'Joined', type: 'date' },
      { field: 'customFields.birthday', label: 'Birthday', type: 'date', calendarDate: true },
      { field: 'name', label: 'Name', type: 'text' },
    ]);
    expect(fields).toEqual(['joined']);
    const out = toServerDateFilter(filter, fields, KL);
    expect(out?.rules[0]).toBe(filter.rules[0]);
    expect(out?.rules[1]).toBe(filter.rules[1]);
    expect(out?.rules[2]).toEqual({
      kind: 'condition',
      field: 'joined',
      operator: 'between',
      value: ['2026-10-31T16:00:00.000Z', ''],
    });
    expect(out?.rules[3]).toBe(filter.rules[3]);
  });

  it('passes a missing filter or no moment fields straight through', () => {
    expect(toServerDateFilter(null, ['joined'], KL)).toBeNull();
    const filter = group({ kind: 'condition', field: 'joined', operator: 'between', value: ['2026-11-19', '2026-11-19'] });
    expect(toServerDateFilter(filter, [], KL)).toBe(filter);
  });
});

describe('client-side lists read the instants', () => {
  const valueOf = (row: { at: string }) => row.at;
  const today = toServerDateFilter(
    group({ kind: 'condition', field: 'at', operator: 'between', value: ['2026-11-19', '2026-11-19'] }),
    ['at'],
    KL,
  );

  it('keeps a row just after local midnight and drops one just before it', () => {
    expect(matchesFilterGroup({ at: '2026-11-18T16:00:30Z' }, today, valueOf)).toBe(true);
    expect(matchesFilterGroup({ at: '2026-11-19T15:59:00Z' }, today, valueOf)).toBe(true);
    expect(matchesFilterGroup({ at: '2026-11-18T15:59:30Z' }, today, valueOf)).toBe(false);
    expect(matchesFilterGroup({ at: '2026-11-19T16:00:00Z' }, today, valueOf)).toBe(false);
  });

  it('still compares plain days by day', () => {
    const days = group({ kind: 'condition', field: 'at', operator: 'between', value: ['2026-11-19', '2026-11-19'] });
    expect(matchesFilterGroup({ at: '2026-11-19T10:00:00Z' }, days, valueOf)).toBe(true);
    expect(matchesFilterGroup({ at: '2026-11-20T10:00:00Z' }, days, valueOf)).toBe(false);
  });
});
