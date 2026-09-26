import { render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import { useBrForm } from './use-br-form';

/**
 * Issue #90 W3 (AC-90-313): the BR detail page labels a test BR "Test" (owner
 * ruling 26 Sep ~12:50Z) via the SAME TEST badge the Ideas list/form uses -
 * prepended to the subtitle (`subtitle` is already `ReactNode`, no shell
 * change needed).
 *
 * Review fix S6: the record pager's `includeTest` must come from the URL's
 * `includeTest` param (carried by `use-br-list-config.tsx`'s `rowHref`
 * alongside `ctx`/`i`/`from`, review fix S6) - the lane the user was ACTUALLY
 * browsing on the list they came from - not from the loaded record's own
 * `isTest` flag (a real BR opened from a test-inclusive list must keep
 * paging through that SAME mixed lane). Only when there is no `includeTest`
 * param at all (a bookmarked/direct link) does it fall back to the loaded
 * record's own flag.
 *
 * Review fix S7: the fixture is now a COMPLETE `BusinessRequirementDetail`
 * (every field `isTest` included, now an optional property of the type) -
 * no `as any` / eslint-disable needed.
 */

const get = vi.fn();
const list = vi.fn();
const statusGraph = vi.fn();

vi.mock('@/services/business-requirement-service', () => ({
  businessRequirementService: {
    get: (...a: unknown[]) => get(...a),
    list: (...a: unknown[]) => list(...a),
    update: vi.fn(),
    statusGraph: (...a: unknown[]) => statusGraph(...a),
  },
}));

const useSearchParams = vi.hoisted(() => vi.fn(() => new URLSearchParams()));
vi.mock('next/navigation', () => ({
  useSearchParams: () => useSearchParams(),
}));

const brDetail = (over: Partial<BusinessRequirementDetail> = {}): BusinessRequirementDetail => ({
  id: 'br-1',
  productId: 'prod-1',
  productName: 'Sorento CRM',
  status: 'draft',
  statusLabel: 'Draft',
  statusColor: 'gray',
  templateKey: 'business_requirement',
  templateVersion: 1,
  title: 'Order export',
  ideaCount: 1,
  createdAt: '2026-07-20T10:00:00Z',
  updatedAt: '2026-07-20T10:00:00Z',
  isTest: false,
  answers: {},
  templateDoc: { schemaVersion: 1, pages: [] },
  ...over,
});

beforeEach(() => {
  get.mockReset();
  list.mockReset();
  statusGraph.mockReset();
  useSearchParams.mockReset();
  useSearchParams.mockReturnValue(new URLSearchParams());
  statusGraph.mockResolvedValue({ entityType: 'ideation_business_requirement', source: 'platform', statuses: [], transitions: [] });
});

describe('useBrForm - AC-90-313 TEST badge on the subtitle', () => {
  it('prepends a TEST badge to the subtitle for a test BR', async () => {
    get.mockResolvedValue(brDetail({ isTest: true }));
    const { result } = renderHook(() => useBrForm('br-1', false));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    render(<>{result.current.config!.subtitle}</>);
    expect(screen.getByText('TEST')).toBeInTheDocument();
  });

  it('does not render the TEST badge for a real BR', async () => {
    get.mockResolvedValue(brDetail());
    const { result } = renderHook(() => useBrForm('br-1', false));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    render(<>{result.current.config!.subtitle}</>);
    expect(screen.queryByText('TEST')).not.toBeInTheDocument();
  });
});

describe('useBrForm - review fix S6, the record pager carries the LIST context, not the loaded record', () => {
  const query: ListQuery = { page: 0, pageSize: 25, search: '', sort: undefined, filter: null };

  it('falls back to the loaded record\'s own isTest when there is no includeTest param (bookmarked/direct link, AC-90-313)', async () => {
    useSearchParams.mockReturnValue(new URLSearchParams());
    get.mockResolvedValue(brDetail({ isTest: true }));
    list.mockResolvedValue([brDetail({ isTest: true })]);
    const { result } = renderHook(() => useBrForm('br-1', false));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    await result.current.config!.recordNav!.fetchAt(query, 0);
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ includeTest: true }));
  });

  it('uses includeTest=true from the URL even when the loaded record is a REAL BR (opened from a test-inclusive list)', async () => {
    useSearchParams.mockReturnValue(new URLSearchParams('includeTest=1'));
    get.mockResolvedValue(brDetail({ isTest: false }));
    list.mockResolvedValue([brDetail({ isTest: false })]);
    const { result } = renderHook(() => useBrForm('br-1', false));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    await result.current.config!.recordNav!.fetchAt(query, 0);
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ includeTest: true }));
  });

  it('uses includeTest=false from the URL even when the loaded record is a TEST BR (opened via a shared link into the real-only list)', async () => {
    useSearchParams.mockReturnValue(new URLSearchParams('includeTest=0'));
    get.mockResolvedValue(brDetail({ isTest: true }));
    list.mockResolvedValue([brDetail({ isTest: true })]);
    const { result } = renderHook(() => useBrForm('br-1', false));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    await result.current.config!.recordNav!.fetchAt(query, 0);
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ includeTest: false }));
  });
});
