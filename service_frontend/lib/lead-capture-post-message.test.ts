import { describe, expect, it, vi } from 'vitest';
import { exactOrigin, postToOpener } from './lead-capture-post-message';

describe('lead capture postMessage', () => {
  it('accepts only a bare origin', () => {
    expect(exactOrigin('https://crm.example.com')).toBe('https://crm.example.com');
    expect(exactOrigin('https://crm.example.com/')).toBe('https://crm.example.com');
    expect(exactOrigin('http://localhost:3000')).toBe('http://localhost:3000');
    for (const bad of ['*', 'null', '', null, undefined, 'javascript:alert(1)', 'https://crm.example.com/path', 'not a url']) {
      expect(exactOrigin(bad as string | null | undefined)).toBeNull();
    }
  });

  it('posts to the session returnOrigin only, never *', () => {
    const opener = { postMessage: vi.fn(), closed: false };
    expect(postToOpener(opener, 'https://crm.example.com', { type: 'lead-capture:done', sourceId: 's1' })).toBe(true);
    expect(opener.postMessage).toHaveBeenCalledWith({ type: 'lead-capture:done', sourceId: 's1' }, 'https://crm.example.com');
    for (const call of opener.postMessage.mock.calls) expect(call[1]).not.toBe('*');
  });

  it('posts nothing without an origin, an opener, or to a closed opener', () => {
    const opener = { postMessage: vi.fn(), closed: false };
    expect(postToOpener(opener, null, { type: 'lead-capture:closed' })).toBe(false);
    expect(postToOpener(opener, '*', { type: 'lead-capture:closed' })).toBe(false);
    expect(postToOpener(null, 'https://crm.example.com', { type: 'lead-capture:closed' })).toBe(false);
    expect(postToOpener({ ...opener, closed: true }, 'https://crm.example.com', { type: 'lead-capture:closed' })).toBe(false);
    expect(opener.postMessage).not.toHaveBeenCalled();
  });

  it('a throwing opener is not fatal', () => {
    const opener = { postMessage: () => { throw new Error('gone'); } };
    expect(postToOpener(opener, 'https://crm.example.com', { type: 'lead-capture:closed' })).toBe(false);
  });
});
