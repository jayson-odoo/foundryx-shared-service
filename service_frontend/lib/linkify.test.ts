import { describe, expect, it } from 'vitest';
import { linkifySegments } from './linkify';

describe('linkifySegments (AC-WEB-48, D-A7B-26)', () => {
  it('returns the whole string as one text segment when there is no URL', () => {
    expect(linkifySegments('Hello there')).toEqual([{ type: 'text', value: 'Hello there' }]);
  });

  it('splits a message around an http(s) URL into text + link segments', () => {
    const segments = linkifySegments('See https://example.com/x for details');
    expect(segments).toEqual([
      { type: 'text', value: 'See ' },
      { type: 'link', value: 'https://example.com/x', href: 'https://example.com/x' },
      { type: 'text', value: ' for details' },
    ]);
  });

  it('strips trailing sentence punctuation from the link, keeping it as text', () => {
    const segments = linkifySegments('Visit https://example.com/x.');
    expect(segments).toEqual([
      { type: 'text', value: 'Visit ' },
      { type: 'link', value: 'https://example.com/x', href: 'https://example.com/x' },
      { type: 'text', value: '.' },
    ]);
  });

  it('never linkifies a javascript: scheme - it stays literal text', () => {
    const segments = linkifySegments('click javascript:alert(1)');
    expect(segments.every((s) => s.type === 'text')).toBe(true);
    expect(segments.map((s) => s.value).join('')).toBe('click javascript:alert(1)');
  });

  it('renders a <script> payload as literal text, never as markup (stored-XSS guard)', () => {
    const payload = '<img src=x onerror=alert(1)>';
    const segments = linkifySegments(payload);
    expect(segments).toEqual([{ type: 'text', value: payload }]);
  });

  it('linkifies multiple URLs independently', () => {
    const segments = linkifySegments('https://a.example and https://b.example');
    const links = segments.filter((s) => s.type === 'link').map((s) => s.href);
    expect(links).toEqual(['https://a.example', 'https://b.example']);
  });
});
