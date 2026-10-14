import { describe, expect, it } from 'vitest';
import { safeCallbackPath } from './safe-callback';

describe('safeCallbackPath', () => {
  it('keeps a same-origin path', () => {
    expect(safeCallbackPath('/portal/ideas')).toBe('/portal/ideas');
    expect(safeCallbackPath('/documents?shared=abc')).toBe('/documents?shared=abc');
  });
  it.each([
    'https://evil.example',
    '//evil.example',
    '/\\evil.example',
    'javascript:alert(1)',
    '/a\\b',
    '/x\nSet-Cookie:',
    '/..//evil.example',
    '/.//evil.example',
    '/%2e%2e//evil.example',
    '',
    null,
    undefined,
  ])(
    'falls back for %s',
    (raw) => {
      expect(safeCallbackPath(raw as string | null | undefined)).toBe('/');
    },
  );
});
