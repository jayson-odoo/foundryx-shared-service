import { afterEach, describe, expect, it, vi } from 'vitest';
import { GOOGLE_AUTH_URL, googleDialogUrl, launchGoogleOAuth } from './google-oauth';

const opts = { clientId: 'client-1.apps.example', scopes: ['https://www.googleapis.com/auth/adwords', 'openid', 'email'] };

describe('Google sign-in dialog (plan 68)', () => {
  afterEach(() => vi.restoreAllMocks());

  it('asks for a code with offline access, consent and the given scopes', () => {
    const url = new URL(googleDialogUrl(opts, 'https://host/wa-callback', 'st4te'));
    expect(`${url.origin}${url.pathname}`).toBe(GOOGLE_AUTH_URL);
    expect(url.searchParams.get('response_type')).toBe('code');
    expect(url.searchParams.get('access_type')).toBe('offline');
    expect(url.searchParams.get('prompt')).toBe('consent');
    expect(url.searchParams.get('redirect_uri')).toBe('https://host/wa-callback');
    expect(url.searchParams.get('state')).toBe('st4te');
    expect(url.searchParams.get('scope')).toBe(opts.scopes.join(' '));
  });

  it('takes only the code relayed with its own state, from its own origin', async () => {
    let opened = '';
    vi.spyOn(window, 'open').mockImplementation((u) => {
      opened = String(u);
      return { closed: false } as Window;
    });
    const result = launchGoogleOAuth(opts);
    const state = new URL(opened).searchParams.get('state');
    expect(state).toMatch(/^[0-9a-f]{32}$/);
    window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin, data: { type: 'FX_WA_OAUTH', code: 'forged', state: 'other' } }));
    window.dispatchEvent(new MessageEvent('message', { origin: 'https://evil.example', data: { type: 'FX_WA_OAUTH', code: 'evil', state } }));
    window.dispatchEvent(new MessageEvent('message', { origin: window.location.origin, data: { type: 'FX_WA_OAUTH', code: 'good', state } }));
    await expect(result).resolves.toEqual({ code: 'good', redirectUri: `${window.location.origin}/wa-callback` });
  });
});
