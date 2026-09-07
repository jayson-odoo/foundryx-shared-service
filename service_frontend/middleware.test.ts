import { NextRequest } from 'next/server';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { middleware } from './middleware';

/**
 * Review round 2 (B4) - `fetchAllowedOrigins` must distinguish "the backend
 * answered, with no origins" (a genuinely unknown widget key - silent) from
 * "the backend call itself failed" (a 429/5xx or a network error - logged),
 * and BOTH must fail closed for only the ONE request being served, never a
 * shared state that could poison a different widget key's request.
 */
describe('middleware frame-ancestors (web chat panel)', () => {
  let warnSpy: ReturnType<typeof vi.spyOn>;

  beforeEach(() => {
    warnSpy = vi.spyOn(console, 'warn').mockImplementation(() => {});
  });

  afterEach(() => {
    warnSpy.mockRestore();
    vi.unstubAllGlobals();
  });

  function requestFor(widgetKey: string): NextRequest {
    return new NextRequest(`http://localhost:3001/public/webchat/${widgetKey}`);
  }

  it('emits frame-ancestors none, silently, for a 200 with no origins (unknown key)', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response(JSON.stringify({ allowedOrigins: [] }), { status: 200 })),
    );

    const res = await middleware(requestFor('unknown-key'));

    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'none'");
    expect(warnSpy).not.toHaveBeenCalled();
  });

  it('emits frame-ancestors none, WITH a logged warning, on a non-2xx response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('rate limited', { status: 429 })));

    const res = await middleware(requestFor('some-key'));

    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'none'");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain('status=429');
  });

  it('emits frame-ancestors none, WITH a logged warning, on a network failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('ECONNREFUSED')));

    const res = await middleware(requestFor('some-key'));

    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'none'");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain('network');
  });

  it('a failure for one key never poisons a later request for a known-good key', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response('rate limited', { status: 429 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ allowedOrigins: ['https://shop.example'] }), { status: 200 }),
      );
    vi.stubGlobal('fetch', fetchMock);

    const failed = await middleware(requestFor('unknown-probe'));
    expect(failed.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'none'");

    const known = await middleware(requestFor('known-key'));
    expect(known.headers.get('Content-Security-Policy')).toBe(
      'frame-ancestors https://shop.example',
    );
  });
});
