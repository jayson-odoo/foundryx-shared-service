import { StrictMode } from 'react';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import WaCallbackPage from './page';

const originalLocation = window.location;
let replaceSpy: ReturnType<typeof vi.fn>;

function setUrl(search: string) {
  window.history.replaceState(null, '', `/wa-callback${search}`);
}

beforeEach(() => {
  replaceSpy = vi.fn();
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: {
      get search() {
        return originalLocation.search;
      },
      get pathname() {
        return originalLocation.pathname;
      },
      get origin() {
        return originalLocation.origin;
      },
      replace: replaceSpy,
    },
  });
  window.sessionStorage.clear();
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Object.defineProperty(window, 'location', {
    configurable: true,
    value: originalLocation,
  });
  Object.defineProperty(window, 'opener', { configurable: true, value: null });
});

describe('wa-callback page, no state (existing behaviour)', () => {
  it('popup: relays the code to the opener and closes', () => {
    vi.useFakeTimers();
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    const closeSpy = vi.spyOn(window, 'close').mockImplementation(() => {});
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    setUrl('?code=abc123');

    render(<WaCallbackPage />);

    expect(postMessage).toHaveBeenCalledWith(
      { type: 'FX_WA_OAUTH', code: 'abc123' },
      window.location.origin,
    );
    expect(screen.getByText('Done - you can close this window.')).toBeTruthy();
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(closeSpy).toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it('popup: relays an error description to the opener', () => {
    vi.useFakeTimers();
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    vi.spyOn(window, 'close').mockImplementation(() => {});
    setUrl('?error=access_denied&error_description=User%20denied');

    render(<WaCallbackPage />);

    expect(postMessage).toHaveBeenCalledWith(
      { type: 'FX_WA_OAUTH', error: 'User denied' },
      window.location.origin,
    );
  });

  it('no opener with a code: stashes it and returns to the channels page', () => {
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: null,
    });
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    setUrl('?code=abc123');

    render(<WaCallbackPage />);

    expect(window.sessionStorage.getItem('fx_wa_code')).toBe('abc123');
    expect(replaceSpy).toHaveBeenCalledWith(
      '/omnichannel/settings/channels?wa_connected=1',
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  it('no opener without a code: shows the cancelled message', () => {
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: null,
    });
    setUrl('');

    render(<WaCallbackPage />);

    expect(
      screen.getByText('Signup cancelled. You can close this window.'),
    ).toBeTruthy();
    expect(replaceSpy).not.toHaveBeenCalled();
  });
});

describe('wa-callback page, with the OAuth popup state (launchOAuthPopup)', () => {
  // The shape `newOAuthState` mints: 32 lowercase hex characters.
  const popupState = '0123456789abcdef0123456789abcdef';

  it('popup: relays the code with its state and never calls the partner endpoint', () => {
    vi.useFakeTimers();
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    const closeSpy = vi.spyOn(window, 'close').mockImplementation(() => {});
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    setUrl(`?code=abc123&state=${popupState}`);

    render(<WaCallbackPage />);

    expect(postMessage).toHaveBeenCalledWith(
      { type: 'FX_WA_OAUTH', code: 'abc123', state: popupState },
      window.location.origin,
    );
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(closeSpy).toHaveBeenCalled();
    expect(fetchSpy).not.toHaveBeenCalled();
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it('popup: relays an error with its state', () => {
    vi.useFakeTimers();
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    vi.spyOn(window, 'close').mockImplementation(() => {});
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    setUrl(`?error=access_denied&state=${popupState}`);

    render(<WaCallbackPage />);

    expect(postMessage).toHaveBeenCalledWith(
      { type: 'FX_WA_OAUTH', error: 'access_denied', state: popupState },
      window.location.origin,
    );
    expect(fetchSpy).not.toHaveBeenCalled();
  });
});

describe('wa-callback page, with state (partner connect)', () => {
  const okResponse = (body: unknown) =>
    ({ ok: true, status: 200, json: async () => body }) as unknown as Response;

  it('strips the query, posts state and code, then follows the redirect', async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      okResponse({
        redirect: 'https://app.example/return?status=authorized',
      }),
    );
    vi.stubGlobal('fetch', fetchSpy);
    setUrl('?state=st_1&code=secret_code');

    render(<WaCallbackPage />);

    expect(`${originalLocation.pathname}${originalLocation.search}`).toBe(
      '/wa-callback',
    );
    await waitFor(() =>
      expect(replaceSpy).toHaveBeenCalledWith(
        'https://app.example/return?status=authorized',
      ),
    );
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    const [url, init] = fetchSpy.mock.calls[0];
    expect(String(url)).toMatch(
      /\/api\/v1\/omnichannel\/connect\/wa-callback$/,
    );
    expect(init.method).toBe('POST');
    expect(JSON.parse(init.body)).toEqual({
      state: 'st_1',
      code: 'secret_code',
    });
  });

  it('takes a server-issued state (43 url-safe characters) as a partner session', async () => {
    // The shape `secrets.token_urlsafe(32)` gives; never the popup's own.
    const serverState = 'Zm9vYmFyYmF6cXV4MDEyMzQ1Njc4OWFiY2RlZi1fQUI';
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(okResponse({ redirect: 'https://app.example/r' }));
    vi.stubGlobal('fetch', fetchSpy);
    setUrl(`?state=${serverState}&code=c`);

    render(<WaCallbackPage />);

    await waitFor(() =>
      expect(replaceSpy).toHaveBeenCalledWith('https://app.example/r'),
    );
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({
      state: serverState,
      code: 'c',
    });
    expect(postMessage).not.toHaveBeenCalled();
  });

  it('forwards the Meta error and sends no code', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(
        okResponse({ redirect: 'https://app.example/return?status=cancelled' }),
      );
    vi.stubGlobal('fetch', fetchSpy);
    setUrl('?state=st_2&error=access_denied&error_description=User%20denied');

    render(<WaCallbackPage />);

    await waitFor(() => expect(replaceSpy).toHaveBeenCalled());
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({
      state: 'st_2',
      error: 'User denied',
    });
  });

  it('never touches the popup flow, even with an opener', async () => {
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(okResponse({ redirect: 'https://app.example/r' })),
    );
    setUrl('?state=st_3&code=c');

    render(<WaCallbackPage />);

    await waitFor(() =>
      expect(replaceSpy).toHaveBeenCalledWith('https://app.example/r'),
    );
    expect(postMessage).not.toHaveBeenCalled();
    expect(window.sessionStorage.getItem('fx_wa_code')).toBeNull();
  });

  it.each([404, 429, 503])(
    'shows a neutral message on a %i',
    async (status) => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue({
          ok: false,
          status,
          statusText: 'x',
          headers: new Headers(),
          json: async () => ({
            error: {
              code: 'connect_session_not_found',
              message: 'Connect session not found.',
            },
          }),
        }),
      );
      setUrl('?state=st_4&code=c');

      render(<WaCallbackPage />);

      const msg = await screen.findByText(/could not complete the connection/i);
      expect(msg.textContent).not.toMatch(
        /404|429|503|connect_session|not found/i,
      );
      expect(replaceSpy).not.toHaveBeenCalled();
    },
  );

  it('shows the neutral message on a network error or a missing redirect', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network')));
    setUrl('?state=st_5&code=c');
    const first = render(<WaCallbackPage />);
    await screen.findByText(/could not complete the connection/i);
    first.unmount();

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(okResponse({})));
    setUrl('?state=st_6&code=c');
    render(<WaCallbackPage />);
    await screen.findByText(/could not complete the connection/i);
    expect(replaceSpy).not.toHaveBeenCalled();
  });

  it('runs once under StrictMode and never falls into the no-state path', async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const postMessage = vi.fn();
    Object.defineProperty(window, 'opener', {
      configurable: true,
      value: { postMessage },
    });
    const closeSpy = vi.spyOn(window, 'close').mockImplementation(() => {});
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(okResponse({ redirect: 'https://app.example/r' }));
    vi.stubGlobal('fetch', fetchSpy);
    setUrl('?state=st_7&code=c');

    render(
      <StrictMode>
        <WaCallbackPage />
      </StrictMode>,
    );

    await waitFor(() =>
      expect(replaceSpy).toHaveBeenCalledWith('https://app.example/r'),
    );
    act(() => {
      vi.advanceTimersByTime(1000);
    });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(postMessage).not.toHaveBeenCalled();
    expect(closeSpy).not.toHaveBeenCalled();
    expect(replaceSpy).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/Signup cancelled/)).toBeNull();
    expect(window.sessionStorage.getItem('fx_wa_code')).toBeNull();
  });

  it('caps a long Meta error at 512 characters', async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(
        okResponse({ redirect: 'https://app.example/return?status=cancelled' }),
      );
    vi.stubGlobal('fetch', fetchSpy);
    const longError = 'e'.repeat(600);
    setUrl(`?state=st_8&error=access_denied&error_description=${longError}`);

    render(<WaCallbackPage />);

    await waitFor(() => expect(replaceSpy).toHaveBeenCalled());
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({
      state: 'st_8',
      error: 'e'.repeat(512),
    });
  });
});
