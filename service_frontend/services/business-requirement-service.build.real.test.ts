import { beforeEach, describe, expect, it, vi } from 'vitest';

const { apiFetch } = vi.hoisted(() => ({ apiFetch: vi.fn() }));

vi.mock('@/lib/api-client', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api-client')>('@/lib/api-client');
  return { ...actual, apiFetch };
});

// Imported AFTER the mock is registered.
import { realBusinessRequirementService as svc } from './business-requirement-service.real';

beforeEach(() => apiFetch.mockReset());

describe('realBusinessRequirementService build endpoints (AC-STB-09/15/19)', () => {
  it('AC-STB-09 sendToBuild POSTs the send-to-build route', async () => {
    apiFetch.mockResolvedValue({ id: 'br-1' });
    await svc.sendToBuild('br-1');
    expect(apiFetch).toHaveBeenCalledWith(
      '/ideation/business-requirements/br-1/send-to-build',
      expect.objectContaining({ method: 'POST' }),
    );
  });

  it('AC-STB-19 getBuild GETs the build route', async () => {
    apiFetch.mockResolvedValue({ state: 'none' });
    const out = await svc.getBuild('br-1');
    expect(apiFetch).toHaveBeenCalledWith('/ideation/business-requirements/br-1/build');
    expect(out).toEqual({ state: 'none' });
  });

  it('AC-STB-15 listBuildKeys GETs /ideation/build-keys', async () => {
    apiFetch.mockResolvedValue([]);
    await svc.listBuildKeys();
    expect(apiFetch).toHaveBeenCalledWith('/ideation/build-keys');
  });

  it('AC-STB-15 mintBuildKey POSTs {name}', async () => {
    apiFetch.mockResolvedValue({ id: 'k1', plaintext: 'fxb_live_x' });
    await svc.mintBuildKey('Crew');
    expect(apiFetch).toHaveBeenCalledWith(
      '/ideation/build-keys',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ name: 'Crew' }) }),
    );
  });

  it('AC-STB-15 revokeBuildKey DELETEs /ideation/build-keys/{id}', async () => {
    apiFetch.mockResolvedValue(undefined);
    await svc.revokeBuildKey('k1');
    expect(apiFetch).toHaveBeenCalledWith(
      '/ideation/build-keys/k1',
      expect.objectContaining({ method: 'DELETE' }),
    );
  });
});
