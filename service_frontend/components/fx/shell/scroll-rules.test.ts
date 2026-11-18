import { describe, expect, it } from 'vitest';
import {
  FX_MERGE_AT,
  FX_UNMERGE_BELOW,
  nextCondensed,
  nextMerged,
} from './scroll-rules';

describe('top bar merge thresholds (64 px in, 24 px out)', () => {
  it('merges at 64 px and not before', () => {
    expect(FX_MERGE_AT).toBe(64);
    expect(nextMerged(false, 0)).toBe(false);
    expect(nextMerged(false, 63)).toBe(false);
    expect(nextMerged(false, 64)).toBe(true);
    expect(nextMerged(false, 400)).toBe(true);
  });

  it('stays merged until the page is back under 24 px', () => {
    expect(FX_UNMERGE_BELOW).toBe(24);
    expect(nextMerged(true, 63)).toBe(true);
    expect(nextMerged(true, 24)).toBe(true);
    expect(nextMerged(true, 23)).toBe(false);
  });

  it('does not flicker between 24 and 64 px: the state before decides', () => {
    expect(nextMerged(false, 40)).toBe(false);
    expect(nextMerged(true, 40)).toBe(true);
  });
});

describe('phone top bar condensing', () => {
  it('condenses once the red button is under the bar, and opens back up', () => {
    expect(
      nextCondensed(false, { y: 10, actionBottom: 120, barBottom: 60 }),
    ).toBe(false);
    expect(
      nextCondensed(false, { y: 80, actionBottom: 60, barBottom: 60 }),
    ).toBe(true);
    expect(
      nextCondensed(true, { y: 30, actionBottom: 90, barBottom: 60 }),
    ).toBe(false);
  });

  it('falls back to the 64 px / 24 px rule on a page without a red button', () => {
    expect(nextCondensed(false, { y: 64, actionBottom: null, barBottom: 60 })).toBe(true);
    expect(nextCondensed(true, { y: 30, actionBottom: null, barBottom: 60 })).toBe(true);
    expect(nextCondensed(true, { y: 10, actionBottom: null, barBottom: 60 })).toBe(false);
  });
});
