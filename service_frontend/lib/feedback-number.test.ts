import { describe, expect, it } from 'vitest';
import { formatFeedbackNumber } from './feedback-number';

describe('formatFeedbackNumber', () => {
  it('shows the stored IDEA number with the FB prefix', () => {
    expect(formatFeedbackNumber('IDEA-0016')).toBe('FB-0016');
    expect(formatFeedbackNumber('IDEA-10000')).toBe('FB-10000');
  });
  it('passes empty and foreign values through', () => {
    expect(formatFeedbackNumber(null)).toBeNull();
    expect(formatFeedbackNumber(undefined)).toBeNull();
    expect(formatFeedbackNumber('XYZ-1')).toBe('XYZ-1');
  });
});
