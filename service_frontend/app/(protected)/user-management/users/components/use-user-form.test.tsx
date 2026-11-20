/**
 * Fix round 1 item 2: `use-user-form.tsx`'s load `.catch` must classify the
 * failure - a real 404 (`ApiError` status 404) sets `notFound`; anything
 * else (500, network, 403) sets `loadError` instead, so `UserFormView` can
 * throw it for `app/(protected)/error.tsx` rather than funneling every
 * failure into Next's terminal `notFound()`.
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { useUserForm } from './use-user-form';

const userServiceGet = vi.fn();
vi.mock('@/services/user-service', () => ({
  userService: {
    get: (...args: unknown[]) => userServiceGet(...args),
    create: vi.fn(),
    update: vi.fn(),
    getAt: vi.fn(),
  },
}));

vi.mock('@/services/roles-service', () => ({
  rolesService: { list: vi.fn().mockResolvedValue([]) },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'admin-1' } } }),
}));

vi.mock('./use-user-actions', () => ({ useUserActions: () => [] }));

vi.mock('@/hooks/use-can', () => ({
  useCan: () => ({ can: () => true, ready: true }),
}));

vi.mock('@/hooks/use-avatar', () => ({
  useUserAvatar: () => ({ upload: vi.fn(), remove: vi.fn() }),
}));

describe('useUserForm - load failure classification', () => {
  it('a real 404 sets notFound, not loadError', async () => {
    userServiceGet.mockRejectedValueOnce(new ApiError('Not found', 404));
    const { result } = renderHook(() => useUserForm('user-missing', false));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.notFound).toBe(true);
    expect(result.current.loadError).toBeNull();
  });

  it('a 500 sets loadError, not notFound', async () => {
    userServiceGet.mockRejectedValueOnce(new ApiError('Internal Server Error', 500));
    const { result } = renderHook(() => useUserForm('user-broken', false));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.notFound).toBe(false);
    expect(result.current.loadError).not.toBeNull();
  });

  it('a network failure (non-ApiError) sets loadError, not notFound', async () => {
    userServiceGet.mockRejectedValueOnce(new TypeError('Failed to fetch'));
    const { result } = renderHook(() => useUserForm('user-offline', false));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.notFound).toBe(false);
    expect(result.current.loadError).not.toBeNull();
  });

  it('a successful load clears any prior notFound/loadError', async () => {
    userServiceGet.mockResolvedValueOnce({
      id: 'user-ok',
      tenantId: 't1',
      name: 'Ok User',
      email: 'ok@example.com',
      status: 'ACTIVE',
      avatar: null,
      roles: [],
      createdAt: new Date().toISOString(),
      lastSignInAt: null,
      emailVerifiedAt: null,
      isTrashed: false,
    });
    const { result } = renderHook(() => useUserForm('user-ok', false));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.notFound).toBe(false);
    expect(result.current.loadError).toBeNull();
    expect(result.current.config).not.toBeNull();
  });
});
