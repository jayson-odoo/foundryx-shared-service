import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { SessionIdentity } from '@/services/auth-service';
import type { SessionSnapshot } from './use-session-sync';

const svc = { identity: vi.fn() };
vi.mock('@/services/auth-service', () => ({
  get authService() {
    return svc;
  },
}));

const update = vi.fn();
let sessionUser: Record<string, unknown> | undefined;
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: sessionUser ? { user: sessionUser } : null,
    update,
  }),
}));

import { sessionDrifted, useSessionSync } from './use-session-sync';

const BASE: SessionSnapshot & SessionIdentity = {
  email: 'demo@example.com',
  name: 'Demo User',
  avatar: null,
  roles: [{ id: 'r1', name: 'Admin' }],
  permissions: ['users.read', 'users.create'],
  isPlatformTenant: false,
};

beforeEach(() => {
  vi.clearAllMocks();
  sessionUser = { ...BASE };
});

describe('sessionDrifted', () => {
  it('is false for an identical identity', () => {
    expect(sessionDrifted(BASE, { ...BASE })).toBe(false);
  });

  it('ignores roles/permissions ordering', () => {
    expect(
      sessionDrifted(BASE, {
        ...BASE,
        permissions: ['users.create', 'users.read'],
      }),
    ).toBe(false);
  });

  it.each<[string, Partial<SessionIdentity>]>([
    ['email flip', { email: 'new@example.com' }],
    ['permission granted', { permissions: [...BASE.permissions, 'roles.read'] }],
    ['permission revoked', { permissions: ['users.read'] }],
    ['role change', { roles: [{ id: 'r2', name: 'Member' }] }],
    ['avatar set', { avatar: '/users/u1/avatar?v=2' }],
    ['name change', { name: 'Renamed' }],
    ['platform flag', { isPlatformTenant: true }],
  ])('detects %s', (_label, patch) => {
    expect(sessionDrifted(BASE, { ...BASE, ...patch })).toBe(true);
  });

  it('detects avatar REMOVAL (null is meaningful, not fallback)', () => {
    expect(
      sessionDrifted({ ...BASE, avatar: '/users/u1/avatar?v=1' }, { ...BASE, avatar: null }),
    ).toBe(true);
  });
});

describe('useSessionSync', () => {
  it('does NOT call update() when nothing drifted (loop regression — plan 04)', async () => {
    svc.identity.mockResolvedValue({ ...BASE });
    renderHook(() => useSessionSync());
    await waitFor(() => expect(svc.identity).toHaveBeenCalledTimes(1));
    expect(update).not.toHaveBeenCalled();
  });

  it('calls update() once when permissions drifted', async () => {
    svc.identity.mockResolvedValue({ ...BASE, permissions: ['users.read'] });
    renderHook(() => useSessionSync());
    await waitFor(() => expect(update).toHaveBeenCalledTimes(1));
  });

  it('skips the probe entirely without a session', async () => {
    sessionUser = undefined;
    renderHook(() => useSessionSync());
    // Effect ran; no session → no probe, no update.
    await Promise.resolve();
    expect(svc.identity).not.toHaveBeenCalled();
    expect(update).not.toHaveBeenCalled();
  });

  it('swallows a failed probe (never blocks the page)', async () => {
    svc.identity.mockRejectedValue(new Error('network'));
    renderHook(() => useSessionSync());
    await waitFor(() => expect(svc.identity).toHaveBeenCalledTimes(1));
    expect(update).not.toHaveBeenCalled();
  });
});
