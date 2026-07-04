import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  usePortalDecisions,
  usePortalReviewQueue,
  usePortalSubmissions,
  usePortalSubmitOptions,
} from './use-portal-review';

/**
 * The list hooks thread the global event-filter context (AC-06-25) into the
 * service: when a project filter is active, the active scope id is passed as the
 * service `contextId`; unfiltered (or tenant scope) passes null. The mock store
 * lets each test set the active filter key.
 */

const sessionStore = vi.hoisted(() => ({ token: 'portal-token' }));
vi.mock('next-auth/react', () => ({
  useSession: () => ({
    data: { accessToken: sessionStore.token },
    status: 'authenticated',
  }),
}));

const filterStore = vi.hoisted(() => ({ activeContextKey: null as string | null }));
vi.mock('@/providers/portal-filter-provider', () => ({
  usePortalFilter: () => ({
    activeContextKey: filterStore.activeContextKey,
    setActiveContextKey: vi.fn(),
  }),
}));

const svc = vi.hoisted(() => ({
  mySubmissions: vi.fn(async () => []),
  submitOptions: vi.fn(async () => []),
  myReviews: vi.fn(async () => []),
  decisions: vi.fn(async () => []),
}));
vi.mock('@/services/portal-review-service', () => ({
  portalReviewService: svc,
}));

describe('use-portal-review list hooks — contextId threading (AC-06-25)', () => {
  beforeEach(() => {
    filterStore.activeContextKey = null;
    Object.values(svc).forEach((fn) => fn.mockClear());
  });

  it('passes the active project scope id as contextId when a filter is active', async () => {
    filterStore.activeContextKey = 'project:evt-summit';
    renderHook(() => usePortalSubmissions());
    await waitFor(() =>
      expect(svc.mySubmissions).toHaveBeenCalledWith('portal-token', 'evt-summit'),
    );
  });

  it('passes null contextId when unfiltered', async () => {
    filterStore.activeContextKey = null;
    renderHook(() => usePortalReviewQueue());
    await waitFor(() =>
      expect(svc.myReviews).toHaveBeenCalledWith('portal-token', null),
    );
  });

  it('passes null contextId for a tenant-wide scope (not an event)', async () => {
    filterStore.activeContextKey = 'tenant:';
    renderHook(() => usePortalDecisions());
    await waitFor(() =>
      expect(svc.decisions).toHaveBeenCalledWith('portal-token', null),
    );
  });

  it('threads the filter into submit-options too', async () => {
    filterStore.activeContextKey = 'project:evt-workshop';
    renderHook(() => usePortalSubmitOptions());
    await waitFor(() =>
      expect(svc.submitOptions).toHaveBeenCalledWith('portal-token', 'evt-workshop'),
    );
  });
});
