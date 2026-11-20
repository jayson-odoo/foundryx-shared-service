/**
 * useTeamForm (plan 28, roadmap A8) - load-failure classification (Users
 * clone pattern) + the permission-gated Edit toggle (AC-TEM-42: a caller
 * without `teams.manage` never sees Save).
 */
import { renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import { useTeamForm } from './use-team-form';

const teamServiceGet = vi.fn();
const teamServiceCreate = vi.fn();
vi.mock('@/services/team-service', () => ({
  teamService: {
    get: (...args: unknown[]) => teamServiceGet(...args),
    create: (...args: unknown[]) => teamServiceCreate(...args),
    update: vi.fn(),
    getAt: vi.fn(),
  },
}));

vi.mock('@/services/user-service', () => ({
  userService: { list: vi.fn().mockResolvedValue({ data: [], total: 0, page: 0 }) },
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
}));

vi.mock('./use-team-actions', () => ({ useTeamActions: () => [] }));

describe('useTeamForm - load failure classification (plan 28)', () => {
  it('a real 404 sets notFound, not loadError', async () => {
    teamServiceGet.mockRejectedValueOnce(new ApiError('Not found', 404));
    const { result } = renderHook(() => useTeamForm('team-missing', false));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.notFound).toBe(true);
    expect(result.current.loadError).toBeNull();
  });

  it('a 500 sets loadError, not notFound', async () => {
    teamServiceGet.mockRejectedValueOnce(new ApiError('Internal Server Error', 500));
    const { result } = renderHook(() => useTeamForm('team-broken', false));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(result.current.notFound).toBe(false);
    expect(result.current.loadError).not.toBeNull();
  });

  it('gates the Edit toggle behind teams.manage (AC-TEM-42)', async () => {
    teamServiceGet.mockResolvedValueOnce({
      id: 'team-1',
      name: 'Support',
      description: null,
      isActive: true,
      sortOrder: 0,
      members: [],
      memberCount: 0,
      createdAt: '2026-06-01T00:00:00Z',
      updatedAt: '2026-06-01T00:00:00Z',
    });
    const { result } = renderHook(() => useTeamForm('team-1', false));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.config?.editPermission).toBe('teams.manage');
  });

  it('a create submits members with role derived from leadIds', async () => {
    teamServiceCreate.mockResolvedValueOnce({
      id: 'team-new',
      name: 'Ops',
      description: null,
      isActive: true,
      sortOrder: 0,
      members: [],
      memberCount: 0,
      createdAt: '',
      updatedAt: '',
    });
    const { result } = renderHook(() => useTeamForm(undefined, true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.form.setValue('name', 'Ops');
    result.current.form.setValue('memberIds', ['u1', 'u2']);
    result.current.form.setValue('leadIds', ['u1']);

    await result.current.config?.onSave();

    expect(teamServiceCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        name: 'Ops',
        members: expect.arrayContaining([
          { userId: 'u1', role: 'lead' },
          { userId: 'u2', role: 'member' },
        ]),
      }),
    );
  });
});

describe('useTeamForm - review round 1, nit 18: 422 fieldErrors map onto RHF fields', () => {
  it('a name collision 422 sets the RHF name field error', async () => {
    teamServiceCreate.mockRejectedValueOnce(
      new ApiError('Please fix the highlighted fields.', 422, null, {
        fieldErrors: { name: 'A team with this name already exists.' },
      }),
    );
    const { result } = renderHook(() => useTeamForm(undefined, true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.form.setValue('name', 'Sales');
    const ok = await result.current.config?.onSave();

    expect(ok).toBe(false);
    // `getFieldState` reads RHF's LIVE internal formState directly (unlike
    // `form.formState.errors`, whose exposed Proxy only refreshes on a
    // React re-render of a component that actually reads it - nothing in
    // this bare-hook render does) - the correct way to assert a `setError`
    // took effect outside of a mounted consumer.
    expect(result.current.form.getFieldState('name').error?.message).toBe(
      'A team with this name already exists.',
    );
  });

  it('an invalid-member 422 sets the RHF memberIds field error', async () => {
    teamServiceCreate.mockRejectedValueOnce(
      new ApiError('Please fix the highlighted fields.', 422, null, {
        fieldErrors: { members: 'One of the selected members is invalid.' },
      }),
    );
    const { result } = renderHook(() => useTeamForm(undefined, true));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    result.current.form.setValue('name', 'Support');
    const ok = await result.current.config?.onSave();

    expect(ok).toBe(false);
    expect(result.current.form.getFieldState('memberIds').error?.message).toBe(
      'One of the selected members is invalid.',
    );
  });
});
