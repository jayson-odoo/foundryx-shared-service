import { describe, expect, it } from 'vitest';
import { validateEmbedOrigin } from './embed-origin';

describe('validateEmbedOrigin', () => {
  it('accepts a bare https origin', () => {
    expect(validateEmbedOrigin('https://crm.acme.com')).toEqual({
      ok: true,
      value: 'https://crm.acme.com',
    });
  });

  it('accepts https with a port', () => {
    expect(validateEmbedOrigin('https://crm.acme.com:8443').value).toBe('https://crm.acme.com:8443');
  });

  it('accepts http for localhost / 127.0.0.1', () => {
    expect(validateEmbedOrigin('http://localhost:3000').ok).toBe(true);
    expect(validateEmbedOrigin('http://127.0.0.1:3001').ok).toBe(true);
  });

  it('rejects non-localhost http', () => {
    expect(validateEmbedOrigin('http://crm.acme.com').ok).toBe(false);
  });

  it('rejects a path', () => {
    expect(validateEmbedOrigin('https://crm.acme.com/leads').ok).toBe(false);
  });

  it('rejects a trailing slash', () => {
    expect(validateEmbedOrigin('https://crm.acme.com/').ok).toBe(false);
  });

  it('rejects a query / fragment', () => {
    expect(validateEmbedOrigin('https://crm.acme.com?x=1').ok).toBe(false);
    expect(validateEmbedOrigin('https://crm.acme.com#a').ok).toBe(false);
  });

  it('rejects a wildcard host', () => {
    expect(validateEmbedOrigin('https://*.acme.com').ok).toBe(false);
  });

  it('strips the default port to match a browser Origin header', () => {
    expect(validateEmbedOrigin('https://crm.acme.com:443').value).toBe('https://crm.acme.com');
    expect(validateEmbedOrigin('http://localhost:80').value).toBe('http://localhost');
  });

  it('rejects blanks and garbage', () => {
    expect(validateEmbedOrigin('').ok).toBe(false);
    expect(validateEmbedOrigin('not a url').ok).toBe(false);
  });
});
