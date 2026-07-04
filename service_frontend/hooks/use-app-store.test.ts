import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { StoreModule } from '@/types/app-store';

const sessionUpdate = vi.fn();
vi.mock('next-auth/react', () => ({
  useSession: () => ({ status: 'authenticated', update: sessionUpdate }),
}));

const svc = {
  catalog: vi.fn(),
  installed: vi.fn(),
  act: vi.fn(),
  uninstall: vi.fn(),
  catalogForTenant: vi.fn(),
  actForTenant: vi.fn(),
  uninstallForTenant: vi.fn(),
};
vi.mock('@/services/app-store-service', () => ({
  get appStoreService() {
    return svc;
  },
}));

import {
  __resetInstalledModules,
  useAppStore,
  useInstalledModules,
} from './use-app-store';

const MODULE: StoreModule = {
  name: 'omnichannel',
  title: 'Omnichannel',
  description: 'WhatsApp messaging.',
  icon: 'message-square',
  version: '0.1.0',
  status: 'ACTIVE',
  installedVersion: '0.1.0',
  updateAvailable: false,
  installedAt: '2026-05-01T00:00:00Z',
};

beforeEach(() => {
  vi.clearAllMocks();
  __resetInstalledModules();
  svc.catalog.mockResolvedValue([MODULE]);
  svc.catalogForTenant.mockResolvedValue([MODULE]);
  svc.installed.mockResolvedValue([
    { module: 'omnichannel', status: 'ACTIVE', version: '0.1.0' },
    { module: 'forms', status: 'INACTIVE', version: '1.0.0' },
  ]);
});

describe('useAppStore', () => {
  it('loads the catalog for the own tenant', async () => {
    const { result } = renderHook(() => useAppStore());
    expect(result.current.loading).toBe(true);
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.modules).toEqual([MODULE]);
    expect(svc.catalog).toHaveBeenCalled();
    expect(svc.catalogForTenant).not.toHaveBeenCalled();
  });

  it('uses the operator endpoints when a tenantId is given', async () => {
    const { result } = renderHook(() => useAppStore('tnt-002'));
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(svc.catalogForTenant).toHaveBeenCalledWith('tnt-002');
    expect(svc.catalog).not.toHaveBeenCalled();
  });

  it('run() on the OWN tenant refreshes catalog + session (D7)', async () => {
    svc.act.mockResolvedValue(MODULE);
    const { result } = renderHook(() => useAppStore());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let ok = false;
    await act(async () => {
      ok = await result.current.run('omnichannel', 'deactivate');
    });
    expect(ok).toBe(true);
    expect(svc.act).toHaveBeenCalledWith('omnichannel', 'deactivate');
    expect(svc.catalog).toHaveBeenCalledTimes(2); // initial + post-action refresh
    expect(sessionUpdate).toHaveBeenCalled(); // perms refresh
    expect(svc.installed).toHaveBeenCalled(); // menu refilters
  });

  it('run() on ANOTHER tenant does NOT touch the operator session', async () => {
    svc.actForTenant.mockResolvedValue(MODULE);
    const { result } = renderHook(() => useAppStore('tnt-002'));
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.run('omnichannel', 'deactivate');
    });
    expect(svc.actForTenant).toHaveBeenCalledWith('tnt-002', 'omnichannel', 'deactivate');
    expect(sessionUpdate).not.toHaveBeenCalled();
  });

  it('surfaces action errors and reports failure', async () => {
    svc.act.mockRejectedValue(new Error('Only an active module can be deactivated.'));
    const { result } = renderHook(() => useAppStore());
    await waitFor(() => expect(result.current.loading).toBe(false));

    let ok = true;
    await act(async () => {
      ok = await result.current.run('omnichannel', 'deactivate');
    });
    expect(ok).toBe(false);
    expect(result.current.error).toMatch(/active module/);
    expect(result.current.pending).toBeNull();
  });

  it('uninstall() passes the typed confirmation through', async () => {
    svc.uninstall.mockResolvedValue(undefined);
    const { result } = renderHook(() => useAppStore());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(async () => {
      await result.current.uninstall('omnichannel', 'omnichannel');
    });
    expect(svc.uninstall).toHaveBeenCalledWith('omnichannel', 'omnichannel');
  });
});

describe('useInstalledModules (menu gating)', () => {
  it('isActive() is true only for ACTIVE modules', async () => {
    const { result } = renderHook(() => useInstalledModules());
    expect(result.current.ready).toBe(false);
    await waitFor(() => expect(result.current.ready).toBe(true));
    expect(result.current.isActive('omnichannel')).toBe(true);
    expect(result.current.isActive('forms')).toBe(false); // INACTIVE = hidden
    expect(result.current.isActive('commercial')).toBe(false); // not installed
  });
});
