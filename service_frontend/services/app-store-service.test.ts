import { beforeEach, describe, expect, it } from 'vitest';
import { moduleBadge } from '@/types/app-store';
import { __resetMockAppStore, mockAppStoreService as svc } from './app-store-service.mock';

/**
 * Mock App Store semantics = the backend lifecycle contract (plan 08 §5).
 * These specs pin the transitions Phase B must reproduce.
 */

const find = async (name: string) => (await svc.catalog()).find((m) => m.name === name)!;

describe('app-store mock service (lifecycle contract)', () => {
  beforeEach(() => __resetMockAppStore());

  it('catalog exposes every card state', async () => {
    const modules = await svc.catalog();
    const badges = Object.fromEntries(modules.map((m) => [m.name, moduleBadge(m)]));
    expect(badges).toEqual({
      omnichannel: 'ACTIVE',
      helpdesk: 'UPDATE_AVAILABLE',
      commercial: 'NOT_INSTALLED',
      forms: 'INACTIVE',
    });
  });

  it('install → ACTIVE at the current code version', async () => {
    const m = await svc.act('commercial', 'install');
    expect(m.status).toBe('ACTIVE');
    expect(m.installedVersion).toBe(m.version);
    expect(m.updateAvailable).toBe(false);
  });

  it('install rejects an already-installed module', async () => {
    await expect(svc.act('omnichannel', 'install')).rejects.toThrow(/already installed/);
  });

  it('deactivate keeps the row (data kept) and reactivate restores it', async () => {
    expect((await svc.act('omnichannel', 'deactivate')).status).toBe('INACTIVE');
    // Still listed in installed() — INACTIVE, not gone.
    expect(await svc.installed()).toContainEqual({
      module: 'omnichannel',
      status: 'INACTIVE',
      version: '0.1.0',
    });
    expect((await svc.act('omnichannel', 'reactivate')).status).toBe('ACTIVE');
  });

  it('deactivate only from ACTIVE; reactivate only from INACTIVE', async () => {
    await expect(svc.act('commercial', 'deactivate')).rejects.toThrow(/active module/);
    await expect(svc.act('omnichannel', 'reactivate')).rejects.toThrow(/inactive module/);
  });

  it('update bumps installedVersion to the code version and clears the badge', async () => {
    expect((await find('helpdesk')).updateAvailable).toBe(true);
    const m = await svc.act('helpdesk', 'update');
    expect(m.installedVersion).toBe('1.1.0');
    expect(m.updateAvailable).toBe(false);
    await expect(svc.act('helpdesk', 'update')).rejects.toThrow(/up to date/);
  });

  it('uninstall demands the typed module name', async () => {
    await expect(svc.uninstall('omnichannel', 'omni')).rejects.toThrow(/does not match/);
    await svc.uninstall('omnichannel', 'omnichannel');
    expect((await find('omnichannel')).status).toBeNull();
    expect(await svc.installed()).not.toContainEqual(
      expect.objectContaining({ module: 'omnichannel' }),
    );
  });

  it('uninstall rejects a module that is not installed', async () => {
    await expect(svc.uninstall('commercial', 'commercial')).rejects.toThrow(/not installed/);
  });

  it('per-tenant isolation: operator uninstall wipes ONLY that tenant', async () => {
    await svc.uninstallForTenant('tnt-002', 'omnichannel', 'omnichannel');
    const other = await svc.catalogForTenant('tnt-002');
    expect(other.find((m) => m.name === 'omnichannel')!.status).toBeNull();
    // Own tenant + a third tenant untouched.
    expect((await find('omnichannel')).status).toBe('ACTIVE');
    const third = await svc.catalogForTenant('tnt-003');
    expect(third.find((m) => m.name === 'omnichannel')!.status).toBe('ACTIVE');
  });

  it('operator actions mirror tenant-side transitions', async () => {
    const m = await svc.actForTenant('tnt-003', 'commercial', 'install');
    expect(m.status).toBe('ACTIVE');
    expect((await svc.actForTenant('tnt-003', 'commercial', 'deactivate')).status).toBe(
      'INACTIVE',
    );
  });
});
