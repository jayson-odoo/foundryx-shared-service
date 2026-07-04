// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

// Hoisted spies so the vi.mock factory below can reference them.
const { getSession, signOut } = vi.hoisted(() => ({
  getSession: vi.fn(),
  signOut: vi.fn(),
}));

vi.mock('next-auth/react', () => ({ getSession, signOut }));

import { ApiError, apiFetch } from './api-client';

function jsonResponse(status: number, body: unknown, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });
}

describe('apiFetch', () => {
  beforeEach(() => {
    getSession.mockReset();
    signOut.mockReset();
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('ends the session on a 401 with a token (expired backend JWT, plan 10 D4)', async () => {
    getSession.mockResolvedValue({ accessToken: 'expired-jwt' });
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(401, { detail: 'Could not validate credentials' }),
    );

    await expect(apiFetch('/users')).rejects.toMatchObject({ status: 401 });
    expect(signOut).toHaveBeenCalledWith({ callbackUrl: '/signin' });
  });

  it('does NOT end the session on a 401 without a token (public endpoint)', async () => {
    getSession.mockResolvedValue(null);
    vi.mocked(fetch).mockResolvedValue(jsonResponse(401, { detail: 'nope' }));

    await expect(apiFetch('/auth/login')).rejects.toBeInstanceOf(ApiError);
    expect(signOut).not.toHaveBeenCalled();
  });

  it('does NOT end the session on a 403 (permission problem, not session end)', async () => {
    getSession.mockResolvedValue({ accessToken: 'valid-jwt' });
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(403, { detail: 'Missing permission: users.read' }),
    );

    await expect(apiFetch('/users')).rejects.toMatchObject({ status: 403 });
    expect(signOut).not.toHaveBeenCalled();
  });

  it('exposes Retry-After seconds on a 429 (throttle contract, plan 10 §5)', async () => {
    getSession.mockResolvedValue(null);
    vi.mocked(fetch).mockResolvedValue(
      jsonResponse(429, { detail: 'Too many attempts.' }, { 'Retry-After': '900' }),
    );

    await expect(apiFetch('/auth/forgot-password', { method: 'POST' }))
      .rejects.toMatchObject({ status: 429, retryAfterSeconds: 900 });
  });
});
