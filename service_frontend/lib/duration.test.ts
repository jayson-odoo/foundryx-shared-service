import { describe, expect, it } from 'vitest';
import { formatDuration } from './duration';

describe('formatDuration', () => {
  it('renders whole seconds under a minute', () => {
    expect(formatDuration(0)).toBe('0s');
    expect(formatDuration(45)).toBe('45s');
    expect(formatDuration(59)).toBe('59s');
  });

  it('renders minutes + seconds under an hour', () => {
    expect(formatDuration(60)).toBe('1m 0s');
    expect(formatDuration(90)).toBe('1m 30s');
    expect(formatDuration(3599)).toBe('59m 59s');
  });

  it('renders hours + minutes under a day', () => {
    expect(formatDuration(3600)).toBe('1h 0m');
    expect(formatDuration(12600)).toBe('3h 30m');
    expect(formatDuration(86399)).toBe('23h 59m');
  });

  it('renders days + hours at a day or more', () => {
    expect(formatDuration(86400)).toBe('1d 0h');
    expect(formatDuration(518400)).toBe('6d 0h');
  });

  it('renders a dash for null/undefined/NaN (no sample)', () => {
    expect(formatDuration(null)).toBe('-');
    expect(formatDuration(undefined)).toBe('-');
    expect(formatDuration(Number.NaN)).toBe('-');
  });

  it('rounds fractional seconds and clamps negatives', () => {
    expect(formatDuration(29.6)).toBe('30s');
    expect(formatDuration(-5)).toBe('0s');
  });
});
