import { describe, expect, it } from 'vitest';
import { migrationProgressPct } from './migration-progress';

describe('migrationProgressPct (review round 2, R2)', () => {
  it('returns 0 when there is no total yet', () => {
    expect(migrationProgressPct(0, 0)).toBe(0);
  });

  it('rounds the normal in-progress case', () => {
    expect(migrationProgressPct(1, 3)).toBe(33);
    expect(migrationProgressPct(2, 3)).toBe(67);
  });

  it('reads 100 exactly at completion', () => {
    expect(migrationProgressPct(10, 10)).toBe(100);
  });

  it('clamps to 100 when progressDone transiently exceeds the running total estimate', () => {
    // The backend's `progressTotal` is a monotonic RUNNING estimate during a
    // job and can trail `progressDone` by a beat before the next checkpoint
    // catches up - the bar must never read over 100%.
    expect(migrationProgressPct(12, 10)).toBe(100);
  });
});
