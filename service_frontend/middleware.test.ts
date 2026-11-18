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

  it('emits frame-ancestors none, WITH a logged warning, on a 200 with a non-JSON body', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(new Response('<html>not json</html>', { status: 200 })),
    );

    const res = await middleware(requestFor('some-key'));

    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'none'");
    expect(warnSpy).toHaveBeenCalledTimes(1);
    expect(warnSpy.mock.calls[0][0]).toContain('bad body');
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

/**
 * SS-FEEDBACK-BOARD-LINK - the personal feedback board is framed by the
 * Sorento CRM public page (`/feedback/board/{token}`), so its pages allow
 * exactly 'self' + the configured CRM origins, and send no X-Frame-Options
 * (which would override the CSP in some browsers). No backend call: the
 * list is deployment config, never a per-request lookup.
 */
describe('middleware frame-ancestors (feedback board)', () => {
  const TOKEN = 'a'.repeat(43);
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  function boardRequest(path = `/public/feedback/board/${TOKEN}`): NextRequest {
    return new NextRequest(`http://localhost:3001${path}`);
  }

  it('allows self + the prod CRM origin by default', async () => {
    vi.stubEnv('FEEDBACK_BOARD_FRAME_ANCESTORS', undefined as unknown as string);
    const res = await middleware(boardRequest());
    expect(res.headers.get('Content-Security-Policy')).toBe(
      "frame-ancestors 'self' https://fe-sorento.foundryx.my",
    );
    expect(res.headers.get('X-Frame-Options')).toBeNull();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('covers nested board pages (item by number, roadmap, changelog)', async () => {
    vi.stubEnv('FEEDBACK_BOARD_FRAME_ANCESTORS', 'https://crm.example.test');
    for (const sub of ['/FB-0042', '/roadmap', '/changelog']) {
      const res = await middleware(boardRequest(`/public/feedback/board/${TOKEN}${sub}`));
      expect(res.headers.get('Content-Security-Policy')).toBe(
        "frame-ancestors 'self' https://crm.example.test",
      );
    }
  });

  it('reads a configurable list (comma or space separated)', async () => {
    vi.stubEnv(
      'FEEDBACK_BOARD_FRAME_ANCESTORS',
      'https://crm.example.test, https://crm2.example.test  http://localhost:3000',
    );
    const res = await middleware(boardRequest());
    expect(res.headers.get('Content-Security-Policy')).toBe(
      "frame-ancestors 'self' https://crm.example.test https://crm2.example.test http://localhost:3000",
    );
  });

  it('drops invalid entries so config can never widen or inject the policy', async () => {
    vi.stubEnv(
      'FEEDBACK_BOARD_FRAME_ANCESTORS',
      "https://*.example.test * 'unsafe-inline' https://ok.example.test;script-src http://evil.test https://crm.example.test/path",
    );
    const res = await middleware(boardRequest());
    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'self'");
  });

  it('an empty list means same-origin only', async () => {
    vi.stubEnv('FEEDBACK_BOARD_FRAME_ANCESTORS', '');
    const res = await middleware(boardRequest());
    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'self'");
  });

  it('leaves the webchat policy untouched', async () => {
    vi.stubEnv('FEEDBACK_BOARD_FRAME_ANCESTORS', 'https://crm.example.test');
    fetchMock.mockResolvedValue(
      new Response(JSON.stringify({ allowedOrigins: ['https://shop.example'] }), { status: 200 }),
    );
    const res = await middleware(new NextRequest('http://localhost:3001/public/webchat/key-1'));
    expect(res.headers.get('Content-Security-Policy')).toBe('frame-ancestors https://shop.example');
  });

  it('matches only the board routes, not other public pages', async () => {
    const { config } = await import('./middleware');
    expect(config.matcher).toContain('/public/feedback/board/:path*');
    expect(config.matcher).not.toContain('/public/feedback/:path*');
  });
});

describe('middleware: hosted Lead Capture wizard (plan 64 L-C)', () => {
  it('can never be framed and sends no referrer', async () => {
    const fetchSpy = vi.fn();
    vi.stubGlobal('fetch', fetchSpy);
    const res = await middleware(new NextRequest('http://localhost:3001/public/lead-capture/connect'));
    expect(res.headers.get('Content-Security-Policy')).toBe("frame-ancestors 'none'");
    expect(res.headers.get('X-Frame-Options')).toBe('DENY');
    expect(res.headers.get('Referrer-Policy')).toBe('no-referrer');
    expect(fetchSpy).not.toHaveBeenCalled();
    vi.unstubAllGlobals();
  });
});
