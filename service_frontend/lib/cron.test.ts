import { describe, expect, it } from 'vitest';
import {
  compileCron,
  describeCron,
  parseCron,
  DEFAULT_CRON_STATE,
  type CronState,
} from './cron';

describe('compileCron', () => {
  it('compiles each frequency to a 5-field cron', () => {
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'minute', interval: 1 })).toBe('* * * * *');
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'minute', interval: 5 })).toBe('*/5 * * * *');
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'hour', minute: 15 })).toBe('15 * * * *');
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'day', minute: 0, hour: 9 })).toBe('0 9 * * *');
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'week', minute: 30, hour: 8, dayOfWeek: 1 })).toBe('30 8 * * 1');
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'month', minute: 0, hour: 6, dayOfMonth: 15 })).toBe('0 6 15 * *');
  });

  it('clamps out-of-range values', () => {
    expect(compileCron({ ...DEFAULT_CRON_STATE, frequency: 'day', minute: 99, hour: -3 })).toBe('59 0 * * *');
  });
});

describe('parseCron', () => {
  it('round-trips compiled crons', () => {
    const states: CronState[] = [
      { ...DEFAULT_CRON_STATE, frequency: 'minute', interval: 10 },
      { ...DEFAULT_CRON_STATE, frequency: 'hour', minute: 20 },
      { ...DEFAULT_CRON_STATE, frequency: 'day', minute: 45, hour: 17 },
      { ...DEFAULT_CRON_STATE, frequency: 'week', minute: 0, hour: 9, dayOfWeek: 5 },
      { ...DEFAULT_CRON_STATE, frequency: 'month', minute: 0, hour: 0, dayOfMonth: 1 },
    ];
    for (const state of states) {
      const parsed = parseCron(compileCron(state));
      expect(parsed?.frequency).toBe(state.frequency);
      expect(compileCron(parsed!)).toBe(compileCron(state));
    }
  });

  it('returns null for non-representable strings (→ raw mode)', () => {
    expect(parseCron('0 9 * 1 *')).toBeNull(); // month-of-year constraint
    expect(parseCron('0 0 1 1 1')).toBeNull(); // dom AND dow set
    expect(parseCron('not a cron')).toBeNull();
    expect(parseCron('0 9 * *')).toBeNull(); // wrong field count
  });
});

describe('describeCron', () => {
  it('renders readable summaries', () => {
    expect(describeCron('* * * * *')).toBe('Every minute');
    expect(describeCron('*/5 * * * *')).toBe('Every 5 minutes');
    expect(describeCron('0 9 * * *')).toBe('Daily at 09:00');
    expect(describeCron('30 8 * * 1')).toBe('Weekly on Monday at 08:30');
    expect(describeCron('0 6 15 * *')).toBe('Monthly on day 15 at 06:00');
  });

  it('falls back to the raw string when unrecognised', () => {
    expect(describeCron('0 9 * 1 *')).toContain('Custom schedule');
  });
});
