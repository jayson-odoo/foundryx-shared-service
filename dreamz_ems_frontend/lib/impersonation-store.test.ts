import { afterEach, describe, expect, it, vi } from 'vitest';
import { impersonationStore, type ImpersonationSession } from './impersonation-store';

const SESSION: ImpersonationSession = {
  sessionId: 'imp-1',
  startedAt: '2026-06-02T00:00:00Z',
  targetUser: { id: 'usr-9', name: 'Target', email: 't@x.io', avatar: null, status: 'ACTIVE' },
  permissions: ['roles.read'],
};

afterEach(() => impersonationStore.setSession(null));

describe('impersonationStore', () => {
  it('stores + clears the session', () => {
    expect(impersonationStore.getState()).toBeNull();
    impersonationStore.setSession(SESSION);
    expect(impersonationStore.getState()?.targetUser.id).toBe('usr-9');
    impersonationStore.setSession(null);
    expect(impersonationStore.getState()).toBeNull();
  });

  it('persists to localStorage', () => {
    impersonationStore.setSession(SESSION);
    expect(window.localStorage.getItem('dreamz.impersonation.v1')).toContain('usr-9');
  });

  it('notifies subscribers on change', () => {
    const fn = vi.fn();
    const unsub = impersonationStore.subscribe(fn);
    impersonationStore.setSession(SESSION);
    expect(fn).toHaveBeenCalled();
    unsub();
    impersonationStore.setSession(null);
    expect(fn).toHaveBeenCalledTimes(1);
  });
});
