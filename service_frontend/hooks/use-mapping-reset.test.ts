import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountMappingResetPreview, AutocountMappingView } from '@/types/autocount';

const resetMappingToPreset = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    resetMappingToPreset: (...a: unknown[]) => resetMappingToPreset(...a),
  },
}));

const { useMappingReset } = await import('./use-mapping-reset');

const PREVIEW: AutocountMappingResetPreview = {
  label: 'Item (open REST API)',
  rows: [
    {
      canonicalField: 'code',
      sourcePath: 'ItemCode',
      transform: 'string',
      formula: null,
      enabled: true,
      isRequired: true,
      change: 'unchanged',
    },
  ],
  removed: [],
};

const VIEW: AutocountMappingView = {
  entityType: 'product',
  rows: [],
  sorentoFields: [],
  acFields: [],
  lineSorentoFields: [],
  lineAcFields: [],
  hasPreset: true,
};

beforeEach(() => {
  resetMappingToPreset.mockReset();
});

describe('useMappingReset (AC-12-12/13/22/23)', () => {
  it('does nothing while closed - no fetch at all', () => {
    renderHook(() => useMappingReset('c1', 'product', false, () => {}));
    expect(resetMappingToPreset).not.toHaveBeenCalled();
  });

  it('fetches the dry run the moment it opens', async () => {
    resetMappingToPreset.mockResolvedValue(PREVIEW);
    const { result } = renderHook(() => useMappingReset('c1', 'product', true, () => {}));
    expect(result.current.isLoading).toBe(true);
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(resetMappingToPreset).toHaveBeenCalledWith('c1', 'product', { dryRun: true });
    expect(result.current.preview).toEqual(PREVIEW);
    expect(result.current.loadError).toBeNull();
  });

  it('surfaces the "no preset" 422 inline (AC-12-10 defensive race)', async () => {
    resetMappingToPreset.mockRejectedValue(new ApiError('No preset is registered for this entity.', 422));
    const { result } = renderHook(() => useMappingReset('c1', 'goods_received_note', true, () => {}));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.loadError).toBe('No preset is registered for this entity.');
    expect(result.current.preview).toBeNull();
  });

  it('apply() calls dryRun=false, hands the fresh view to onApplied, and resolves true', async () => {
    resetMappingToPreset.mockResolvedValueOnce(PREVIEW).mockResolvedValueOnce(VIEW);
    const onApplied = vi.fn();
    const { result } = renderHook(() => useMappingReset('c1', 'product', true, onApplied));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let ok = false;
    await act(async () => {
      ok = await result.current.apply();
    });
    expect(ok).toBe(true);
    expect(resetMappingToPreset).toHaveBeenLastCalledWith('c1', 'product', { dryRun: false });
    expect(onApplied).toHaveBeenCalledWith(VIEW);
    expect(result.current.applyError).toBeNull();
  });

  it('a failed apply keeps the dialog data intact and surfaces the server message', async () => {
    resetMappingToPreset
      .mockResolvedValueOnce(PREVIEW)
      .mockRejectedValueOnce(new ApiError('That reset could not be applied.', 500));
    const onApplied = vi.fn();
    const { result } = renderHook(() => useMappingReset('c1', 'product', true, onApplied));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let ok = true;
    await act(async () => {
      ok = await result.current.apply();
    });
    expect(ok).toBe(false);
    expect(onApplied).not.toHaveBeenCalled();
    expect(result.current.applyError).toBe('That reset could not be applied.');
    // The preview is still on hand - the dialog stays open, showing what it
    // already loaded (AC-12-23).
    expect(result.current.preview).toEqual(PREVIEW);
  });
});
