/**
 * Fix round 1 item 2: `use-user-form.tsx`'s load `.catch` must classify the
 * failure - a real 404 (`ApiError` status 404) sets `notFound`; anything
 * else (500, network, 403) sets `loadError` instead, so `UserFormView` can
 * throw it for `app/(protected)/error.tsx` rather than funneling every
 * failure into Next's terminal `notFound()`.
 */
import { act, renderHook, waitFor } from '@testing-library/react';
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

const { ROUTER } = vi.hoisted(() => ({ ROUTER: { push: () => {}, replace: () => {} } }));
vi.mock('next/navigation', () => ({
  useRouter: () => ROUTER,
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { id: 'admin-1' } } }),
}));

// Stable, like the real hook's memoised list: a new array each render would
// rebuild the config every render and hide a stale value.
const { NO_ACTIONS } = vi.hoisted(() => ({ NO_ACTIONS: [] as never[] }));
vi.mock('./use-user-actions', () => ({ useUserActions: () => NO_ACTIONS }));

const { CAN } = vi.hoisted(() => ({ CAN: { can: () => true, ready: true } }));
vi.mock('@/hooks/use-can', () => ({
  useCan: () => CAN,
}));

const { AVATAR } = vi.hoisted(() => ({ AVATAR: { upload: () => {}, remove: () => {} } }));
vi.mock('@/hooks/use-avatar', () => ({
  useUserAvatar: () => AVATAR,
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

describe('useUserForm - the discard guard sees typed values (owner check, FX-26)', () => {
  it('a new user: config.isDirty turns true once a value is typed', async () => {
    const { result } = renderHook(() => useUserForm(undefined, true));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    expect(result.current.config?.isDirty).toBe(false);

    act(() => result.current.form.setValue('name', 'Typed Name', { shouldDirty: true }));

    // Read inside the config memo without being in its deps, it stayed false,
    // so Cancel and Back left without asking (both looks).
    await waitFor(() => expect(result.current.config?.isDirty).toBe(true));
  });
});
