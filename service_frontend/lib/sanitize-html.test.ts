/** Client-side render-time sanitizer (plan sprint-2/07 review #2). */
import { describe, expect, it } from 'vitest';
import { sanitizeHtml } from './sanitize-html';

describe('sanitizeHtml', () => {
  it('keeps email-safe formatting', () => {
    expect(sanitizeHtml('<b>hi</b> <i>there</i>')).toBe('<b>hi</b> <i>there</i>');
  });

  it('strips script/style/iframe elements', () => {
    expect(sanitizeHtml('<b>ok</b><script>evil()</script>')).toBe('<b>ok</b>');
    expect(sanitizeHtml('<iframe src="x"></iframe>ok')).toBe('ok');
  });

  it('strips on* event attributes', () => {
    const out = sanitizeHtml('<a href="https://x" onclick="evil()">l</a>');
    expect(out).not.toContain('onclick');
    expect(out).toContain('href="https://x"');
  });

  it('strips javascript: and data: URLs', () => {
    expect(sanitizeHtml('<a href="javascript:evil()">x</a>')).not.toContain('javascript:');
    expect(sanitizeHtml('<img src="data:text/html,evil">')).not.toContain('data:');
  });

  it('handles nested elements', () => {
    const out = sanitizeHtml('<ul><li onclick="x">a</li><li>b</li></ul>');
    expect(out).not.toContain('onclick');
    expect(out).toContain('<li>a</li>');
  });
});
