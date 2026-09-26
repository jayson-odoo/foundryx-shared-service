import { render, renderHook, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import type { ListQuery } from '@/types/resource';
import type { BusinessRequirementDetail } from '@/types/business-requirement';
import { useBrForm } from './use-br-form';

/**
 * Issue #90 W3 (AC-90-313): the BR detail page labels a test BR "Test" (owner
 * ruling 26 Sep ~12:50Z) via the SAME TEST badge the Ideas list/form uses -
 * prepended to the subtitle (`subtitle` is already `ReactNode`, no shell
 * change needed). The record pager (`fetchRecordAt`) must also pass
 * `includeTest` so a test BR's own pager can find itself in the list.
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
  answers: {},
  templateDoc: { schemaVersion: 1, pages: [] },
  ...over,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
} as any);

beforeEach(() => {
  get.mockReset();
  list.mockReset();
  statusGraph.mockReset();
  statusGraph.mockResolvedValue({ entityType: 'ideation_business_requirement', source: 'platform', statuses: [], transitions: [] });
});

describe('useBrForm - AC-90-313 TEST badge on the subtitle', () => {
  it('prepends a TEST badge to the subtitle for a test BR', async () => {
    get.mockResolvedValue(brDetail({ isTest: true } as Partial<BusinessRequirementDetail>));
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

describe('useBrForm - AC-90-313 the record pager passes includeTest', () => {
  it('fetchRecordAt requests includeTest:true when the loaded BR is a test BR', async () => {
    get.mockResolvedValue(brDetail({ isTest: true } as Partial<BusinessRequirementDetail>));
    list.mockResolvedValue([brDetail({ isTest: true } as Partial<BusinessRequirementDetail>)]);
    const { result } = renderHook(() => useBrForm('br-1', false));
    await waitFor(() => expect(result.current.config).not.toBeNull());
    const query: ListQuery = { page: 0, pageSize: 25, search: '', sort: undefined, filter: null };
    await result.current.config!.fetchRecordAt(query, 0);
    expect(list).toHaveBeenCalledWith(expect.objectContaining({ includeTest: true }));
  });
});
