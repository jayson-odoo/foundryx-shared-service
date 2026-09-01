import { renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { AiModelList } from '@/types/ai';

const svc = {
  listModels: vi.fn(),
};
vi.mock('@/services/ai-service', () => ({
  get aiService() {
    return svc;
  },
}));

import { useAiModels } from './use-ai-models';

const LIVE: AiModelList = {
  data: [
    { id: 'gemini-2.5-flash', label: 'Gemini 2.5 Flash' },
    { id: 'gemini-2.5-pro', label: 'Gemini 2.5 Pro' },
  ],
  isLive: true,
  message: null,
};

const STATIC_FALLBACK: AiModelList = {
  data: [{ id: 'claude-sonnet-4-5', label: 'Claude Sonnet 4.5' }],
  isLive: false,
  message: 'The API key was rejected by the provider.',
};

beforeEach(() => {
  vi.clearAllMocks();
  svc.listModels.mockResolvedValue(LIVE);
});

describe('useAiModels (AC-BI-05)', () => {
  it('loads the live model list for the selected connection', async () => {
    const { result } = renderHook(() => useAiModels('conn-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(svc.listModels).toHaveBeenCalledWith('conn-1');
    expect(result.current.models).toHaveLength(2);
    expect(result.current.isLive).toBe(true);
  });

  it('serves the curated static fallback when the live call failed', async () => {
    // The backend already did the fallback and reported isLive:false - the form
    // must still render a usable picker.
    svc.listModels.mockResolvedValue(STATIC_FALLBACK);
    const { result } = renderHook(() => useAiModels('conn-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.models).toHaveLength(1);
    expect(result.current.isLive).toBe(false);
    expect(result.current.message).toContain('rejected');
  });

  it('never throws when the endpoint itself fails - the form stays usable', async () => {
    svc.listModels.mockRejectedValue(new Error('network down'));
    const { result } = renderHook(() => useAiModels('conn-1'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.models).toEqual([]);
    expect(result.current.isLive).toBe(false);
    expect(result.current.message).toBeTruthy();
  });

  it('fetches nothing until a connection is chosen', async () => {
    const { result } = renderHook(() => useAiModels(null));
    await waitFor(() => expect(result.current.models).toEqual([]));
    expect(svc.listModels).not.toHaveBeenCalled();
  });

  it('refetches when the connection changes (a new provider = a new catalog)', async () => {
    const { result, rerender } = renderHook(({ id }) => useAiModels(id), {
      initialProps: { id: 'conn-1' as string | null },
    });
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    rerender({ id: 'conn-2' });
    await waitFor(() => expect(svc.listModels).toHaveBeenCalledWith('conn-2'));
    expect(svc.listModels).toHaveBeenCalledTimes(2);
  });
});
