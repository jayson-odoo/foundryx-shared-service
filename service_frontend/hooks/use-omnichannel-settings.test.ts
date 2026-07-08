import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const svc = {
  get: vi.fn(),
  update: vi.fn(),
};
vi.mock('@/services/omnichannel-settings-service', () => ({
  get omnichannelSettingsService() {
    return svc;
  },
}));

import { useOmnichannelSettings } from './use-omnichannel-settings';

const MB = 1024 * 1024;

function settings(imageMaxBytes: number | null) {
  return {
    workspaceId: null,
    overrides: {
      imageMaxBytes,
      videoMaxBytes: null,
      audioMaxBytes: null,
      documentMaxBytes: null,
      stickerMaxBytes: null,
    },
    effective: {
      IMAGE: { maxBytes: imageMaxBytes ?? 5 * MB, ceilingBytes: 5 * MB, acceptedMimes: ['image/png'] },
    },
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  svc.get.mockResolvedValue(settings(null));
});

describe('useOmnichannelSettings', () => {
  it('loads settings on mount', async () => {
    const { result } = renderHook(() => useOmnichannelSettings());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(svc.get).toHaveBeenCalledWith(undefined);
    expect(result.current.settings?.overrides.imageMaxBytes).toBeNull();
    expect(result.current.error).toBeNull();
  });

  it('surfaces a load error', async () => {
    svc.get.mockRejectedValueOnce(new Error('boom'));
    const { result } = renderHook(() => useOmnichannelSettings());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.error).toBe('boom');
  });

  it('save persists overrides and refreshes state', async () => {
    svc.update.mockResolvedValue(settings(2 * MB));
    const { result } = renderHook(() => useOmnichannelSettings());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => {
      await result.current.save({ imageMaxBytes: 2 * MB });
    });
    expect(svc.update).toHaveBeenCalledWith({ imageMaxBytes: 2 * MB }, undefined);
    expect(result.current.settings?.overrides.imageMaxBytes).toBe(2 * MB);
  });

  it('passes the workspace scope through to the service', async () => {
    renderHook(() => useOmnichannelSettings('wsp-001'));
    await waitFor(() => expect(svc.get).toHaveBeenCalledWith('wsp-001'));
  });
});
