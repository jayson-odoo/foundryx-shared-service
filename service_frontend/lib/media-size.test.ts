import { describe, expect, it } from 'vitest';
import { bytesToMb, formatMb, mbToBytes } from './media-size';

describe('media-size conversions', () => {
  it('bytesToMb converts whole megabytes', () => {
    expect(bytesToMb(5 * 1024 * 1024)).toBe(5);
    expect(bytesToMb(0)).toBe(0);
  });

  it('mbToBytes round-trips whole megabytes', () => {
    expect(mbToBytes(5)).toBe(5 * 1024 * 1024);
    expect(mbToBytes(16)).toBe(16 * 1024 * 1024);
  });

  it('mbToBytes rounds fractional megabytes to whole bytes', () => {
    expect(Number.isInteger(mbToBytes(0.49))).toBe(true);
  });

  it('formatMb strips trailing zeros', () => {
    expect(formatMb(5 * 1024 * 1024)).toBe('5');
    expect(formatMb(16 * 1024 * 1024)).toBe('16');
  });

  it('formatMb rounds sub-MB ceilings (sticker 500 KB)', () => {
    expect(formatMb(500 * 1024)).toBe('0.49');
  });
});
