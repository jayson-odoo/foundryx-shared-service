import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '@/lib/api-client';
import type { AutocountMappingView } from '@/types/autocount';

const getMapping = vi.fn();
const updateMapping = vi.fn();
vi.mock('@/services/autocount-service', () => ({
  autocountService: {
    getMapping: (...a: unknown[]) => getMapping(...a),
    updateMapping: (...a: unknown[]) => updateMapping(...a),
  },
}));

const { useAutocountMapping } = await import('./use-autocount-mapping');

const VIEW: AutocountMappingView = {
  entityType: 'supplier',
  rows: [
    {
      sourcePath: 'AccNo',
      transform: 'string',
      sorentoField: 'code',
      canonicalField: 'code',
      scope: 'header',
      isRequired: true,
      isEnabled: true,
    },
  ],
  sorentoFields: [{ field: 'code', required: true }],
  acFields: ['AccNo'],
};

beforeEach(() => {
  getMapping.mockReset().mockResolvedValue(VIEW);
  updateMapping.mockReset();
});

describe('useAutocountMapping', () => {
  it('loads the mapping view for the (company, entity)', async () => {
    const { result } = renderHook(() => useAutocountMapping('c1', 'supplier'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(getMapping).toHaveBeenCalledWith('c1', 'supplier');
    expect(result.current.view).toEqual(VIEW);
    expect(result.current.notFound).toBe(false);
  });

  it('marks notFound when the entity/company is unknown', async () => {
    getMapping.mockRejectedValue(new ApiError('Not found', 404));
    const { result } = renderHook(() => useAutocountMapping('c1', 'nope'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.notFound).toBe(true);
  });

  it('saves the rows and adopts the returned view', async () => {
    updateMapping.mockResolvedValue({ ...VIEW, acFields: ['AccNo', 'CompanyName'] });
    const { result } = renderHook(() => useAutocountMapping('c1', 'supplier'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let ok = false;
    await act(async () => {
      ok = await result.current.save([
        { sourcePath: 'AccNo', transform: 'string', sorentoField: 'code' },
      ]);
    });
    expect(ok).toBe(true);
    expect(updateMapping).toHaveBeenCalledWith('c1', 'supplier', {
      rows: [{ sourcePath: 'AccNo', transform: 'string', sorentoField: 'code' }],
    });
    expect(result.current.saveError).toBeNull();
    expect(result.current.view?.acFields).toContain('CompanyName');
  });

  it('surfaces a 422 guard rejection inline and returns false (AC-15-44)', async () => {
    updateMapping.mockRejectedValue(
      new ApiError("'bogus' is not a Sorento field accepted for supplier.", 422),
    );
    const { result } = renderHook(() => useAutocountMapping('c1', 'supplier'));
    await waitFor(() => expect(result.current.isLoading).toBe(false));

    let ok = true;
    await act(async () => {
      ok = await result.current.save([
        { sourcePath: 'AccNo', transform: 'string', sorentoField: 'bogus' },
      ]);
    });
    expect(ok).toBe(false);
    expect(result.current.saveError).toContain('not a Sorento field accepted');
  });
});
