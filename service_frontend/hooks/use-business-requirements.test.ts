import { act, renderHook, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { useBusinessRequirements } from './use-business-requirements';

/**
 * Issue #90 W3 (AC-90-312): the BR list gains a "Show test requirements"
 * toggle (mirrors `use-ideas.ts`'s `includeTest`/`setIncludeTest`) so a test
 * idea's promoted BR (owner ruling 26 Sep ~12:50Z) can be found again.
 */

const list = vi.fn();
const listProducts = vi.fn();

vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: {
    list: (...a: unknown[]) => list(...a),
    create: vi.fn(),
    setStatus: vi.fn(),
    remove: vi.fn(),
  },
}));
vi.mock('@/services/ideation-service', () => ({
  ideationService: { listProducts: (...a: unknown[]) => listProducts(...a) },
}));

beforeEach(() => {
  list.mockReset();
  listProducts.mockReset();
  list.mockResolvedValue([]);
  listProducts.mockResolvedValue([]);
});

describe('useBusinessRequirements - AC-90-312 includeTest passthrough', () => {
  it('defaults includeTest to false on the initial load', async () => {
    const { result } = renderHook(() => useBusinessRequirements());
    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ includeTest: false }));
  });

  it('setIncludeTest(true) reloads the list with includeTest true', async () => {
    const { result } = renderHook(() => useBusinessRequirements());
    await waitFor(() => expect(result.current.loading).toBe(false));
    list.mockClear();
    act(() => {
      result.current.setIncludeTest(true);
    });
    await waitFor(() =>
      expect(list).toHaveBeenCalledWith(expect.objectContaining({ includeTest: true })),
    );
  });
});
