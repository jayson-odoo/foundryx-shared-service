import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { RequestInternal, User } from 'next-auth';
import authOptions from './auth-options';

type AuthorizeFn = (
  credentials: Record<string, string> | undefined,
  req: Pick<RequestInternal, 'body' | 'query' | 'headers' | 'method'>,
) => Promise<User | null>;

// CredentialsProvider keeps the user config (incl. authorize) under .options.
const provider = authOptions.providers[0] as unknown as {
  options: { authorize: AuthorizeFn };
};
const authorize = provider.options.authorize;

const req = { headers: { host: 'localhost:3001' }, body: {}, query: {}, method: 'POST' };
const credentials = {
  email: 'demo@example.com',
  password: 'demo1234',
  rememberMe: 'false',
};

function thrownPayload(err: unknown): { code: number; message: string } {
  return JSON.parse((err as Error).message);
}

describe('authorize() error classes (BL-005)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('maps an unreachable backend to the distinct infra message (not credentials)', async () => {
    vi.mocked(fetch).mockRejectedValue(new TypeError('fetch failed'));
    const err = await authorize(credentials, req).catch((e) => e);
    expect(thrownPayload(err)).toEqual({
      code: 503,
      message: 'Service temporarily unavailable — please try again.',
    });
  });

  it('maps a 5xx backend response to the infra message', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response('Internal Server Error', { status: 500 }),
    );
    const err = await authorize(credentials, req).catch((e) => e);
    expect(thrownPayload(err)).toEqual({
      code: 500,
      message: 'Service temporarily unavailable — please try again.',
    });
  });

  it('keeps the uniform credentials message on 401 (no enumeration regression)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Invalid email or password.' }), {
        status: 401,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const err = await authorize(credentials, req).catch((e) => e);
    expect(thrownPayload(err)).toEqual({
      code: 401,
      message: 'Invalid email or password.',
    });
  });

  it('passes specific 4xx detail through (e.g. suspended tenant 403)', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(JSON.stringify({ detail: 'This tenant is suspended.' }), {
        status: 403,
        headers: { 'Content-Type': 'application/json' },
      }),
    );
    const err = await authorize(credentials, req).catch((e) => e);
    expect(thrownPayload(err)).toEqual({
      code: 403,
      message: 'This tenant is suspended.',
    });
  });

  it('returns the session user on success', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          access_token: 'jwt-abc',
          user: {
            id: 7,
            tenantId: 't1',
            isPlatformTenant: false,
            email: 'demo@example.com',
            name: 'Demo',
            roles: [{ id: 'r1', name: 'Admin' }],
            permissions: ['users.read'],
            status: 'ACTIVE',
          },
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const user = await authorize(credentials, req);
    expect(user).toMatchObject({
      id: '7',
      email: 'demo@example.com',
      accessToken: 'jwt-abc',
    });
  });
});

describe('jwt callback update trigger (plan 04 session refresh)', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn());
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('re-pulls identity fields (email/name) alongside roles/permissions', async () => {
    vi.mocked(fetch).mockResolvedValue(
      new Response(
        JSON.stringify({
          email: 'fresh@example.com',
          name: 'Fresh Name',
          avatar: null,
          roles: [{ id: 'r1', name: 'Admin' }],
          permissions: ['users.read'],
          status: 'ACTIVE',
        }),
        { status: 200, headers: { 'Content-Type': 'application/json' } },
      ),
    );
    const jwt = authOptions.callbacks!.jwt!;
    const token = await jwt({
      token: {
        id: '1',
        email: 'stale@example.com',
        name: 'Stale Name',
        accessToken: 'jwt-abc',
      },
      trigger: 'update',
      // The callback only reads token/trigger — the rest of the NextAuth
      // params object is irrelevant here.
    } as Parameters<typeof jwt>[0]);
    expect(token.email).toBe('fresh@example.com');
    expect(token.name).toBe('Fresh Name');
    expect(token.permissions).toEqual(['users.read']);
  });
});
