import { describe, expect, it } from 'vitest';
import type { PageRunFieldHint } from '@/types/integration';
import { fieldHintText } from './field-hint';

const hint: PageRunFieldHint = { kind: 'pageRun', pages: 70, lastRunSeconds: 129, savedPauseSeconds: 1 };

describe('fieldHintText (pause between pages)', () => {
  it('uses the last run with the saved pause', () => {
    // 129 s run incl. 69 x 1 s pauses -> 60 s of requests; at 1 s = ~2 min.
    expect(fieldHintText(hint, '1')).toBe('About 70 pages per run → about 2 min per run');
  });

  it('recomputes live for the typed pause', () => {
    // 60 s + 69 x 60 s = 4200 s = 70 min.
    expect(fieldHintText(hint, '60')).toBe('About 70 pages per run → about 70 min per run');
  });

  it('treats a blank value as the default 0', () => {
    expect(fieldHintText(hint, '')).toBe('About 70 pages per run → about 1 min per run');
  });

  it('says under 1 min for a short run', () => {
    expect(fieldHintText({ ...hint, pages: 1, lastRunSeconds: 5 }, '0')).toBe(
      'About 1 page per run → under 1 min per run',
    );
  });

  it('shows nothing for an invalid value or without a known run', () => {
    expect(fieldHintText(hint, '601')).toBeNull();
    expect(fieldHintText(hint, '-1')).toBeNull();
    expect(fieldHintText(hint, 'abc')).toBeNull();
    expect(fieldHintText(undefined, '1')).toBeNull();
  });
});
