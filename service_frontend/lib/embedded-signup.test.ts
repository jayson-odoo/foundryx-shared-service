import { afterEach, describe, expect, it, vi } from 'vitest';
import { launchMetaOAuth } from './embedded-signup';

function relay(data: unknown) {
  window.dispatchEvent(new MessageEvent('message', { data, origin: window.location.origin }));
}

describe('launchMetaOAuth', () => {
  afterEach(() => vi.restoreAllMocks());

  it('sends a random state and takes only the code relayed with it', async () => {
    let opened = '';
    vi.spyOn(window, 'open').mockImplementation((url) => {
      opened = String(url);
      return { closed: false } as Window;
    });
    const result = launchMetaOAuth({ appId: 'a', configId: 'c', graphVersion: 'v25.0' });
    const state = new URL(opened).searchParams.get('state');
    expect(state).toMatch(/^[0-9a-f]{32}$/);
    expect(new URL(opened).searchParams.get('config_id')).toBe('c');

    relay({ type: 'FX_WA_OAUTH', code: 'forged', state: 'other' });
    relay({ type: 'FX_WA_OAUTH', code: 'forged' });
    relay({ type: 'FX_WA_OAUTH', code: 'real', state });
    await expect(result).resolves.toEqual({
      code: 'real',
      redirectUri: `${window.location.origin}/wa-callback`,
    });
  });

  it('rejects when the popup is blocked', async () => {
    vi.spyOn(window, 'open').mockReturnValue(null);
    await expect(launchMetaOAuth({ appId: 'a', configId: 'c', graphVersion: 'v25.0' })).rejects.toThrow(/Popup blocked/);
  });
});
