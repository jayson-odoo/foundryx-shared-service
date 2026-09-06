/**
 * Plan 26 review round 2, should-fix 3: an N-way-segmented list (Contacts'
 * "All / segment" `SearchSelect`) can have its currently-selected segment
 * deleted out from under it (e.g. "Manage segments"). Generic fix in the
 * shell so any config using `ResourceListConfig.segments` gets it for free -
 * not a Contacts-only patch: when `list.segment` no longer names one of
 * `config.segments`, fall back to the first configured segment rather than
 * stranding the list on a 404 for an id that no longer exists.
 */
import type { ColumnDef } from '@tanstack/react-table';
import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { useRouter, useSearchParams } from 'next/navigation';
import { encodeListQuery } from '@/lib/list-context';
import { ResourceList } from './resource-list';
import type { ResourceListConfig } from './types';

vi.mock('next/navigation', () => ({
  useRouter: vi.fn(() => ({ push: vi.fn(), prefetch: vi.fn() })),
  useSearchParams: vi.fn(() => new URLSearchParams()),
  usePathname: vi.fn(() => '/records'),
}));

vi.mock('next-auth/react', () => ({
  useSession: () => ({ data: { user: { permissions: [] } }, status: 'authenticated' }),
}));

vi.mock('@/lib/impersonation-store', () => ({
  useImpersonationSession: () => null,
}));

vi.mock('@/services/preferences-service', () => ({
  preferencesService: {
    get: vi.fn().mockResolvedValue(null),
    save: vi.fn().mockResolvedValue(undefined),
  },
}));

vi.mock('@/services/terminology-service', () => ({
  terminologyService: { getTerminology: vi.fn().mockResolvedValue({}) },
}));

vi.mock('@/providers/import-activity-provider', () => ({
  useImportActivity: () => ({ openImport: vi.fn() }),
}));

interface Row {
  id: string;
  name: string;
}

const rows: Row[] = [{ id: 'r1', name: 'Alpha' }];

function baseConfig(overrides: Partial<ResourceListConfig<Row>> = {}): ResourceListConfig<Row> {
  const columns: ColumnDef<Row>[] = [{ id: 'name', header: 'Name', cell: ({ row }) => row.original.name }];
  return {
    viewKey: 'records.list',
    columns,
    getRowId: (row) => row.id,
    rowHref: () => '#',
    fetcher: async () => ({ data: rows, total: rows.length, page: 0 }),
    exporter: async () => '',
    filterFields: [],
    exportColumns: [],
    actions: [],
    segments: [
      { id: 'all', label: 'All contacts' },
      { id: 'seg-1', label: 'VIPs' },
    ],
    defaultSegment: 'seg-1',
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(useRouter).mockReturnValue({ push: vi.fn(), prefetch: vi.fn() } as unknown as ReturnType<typeof useRouter>);
  vi.mocked(useSearchParams).mockReturnValue(new URLSearchParams() as unknown as ReturnType<typeof useSearchParams>);
});

describe('ResourceList segment fallback (plan 26 review round 2, should-fix 3)', () => {
  it('falls back to the first configured segment when the current one is deleted out from under it', async () => {
    const fetcher = vi.fn(async () => ({ data: rows, total: rows.length, page: 0 }));
    const config = baseConfig({ fetcher });
    const { rerender } = render(<ResourceList config={config} />);

    await waitFor(() => expect(screen.getByText('VIPs')).toBeInTheDocument());

    // "seg-1" (VIPs) is deleted - the config's segment list shrinks to just
    // "All contacts".
    const shrunk = baseConfig({
      fetcher,
      segments: [{ id: 'all', label: 'All contacts' }],
      defaultSegment: 'seg-1',
    });
    rerender(<ResourceList config={shrunk} />);

    await waitFor(() => expect(screen.getByText('All contacts')).toBeInTheDocument());
    expect(screen.queryByText('VIPs')).not.toBeInTheDocument();
  });

  it('leaves an unaffected selection alone (no unnecessary refetch/reset)', async () => {
    const config = baseConfig();
    render(<ResourceList config={config} />);
    await waitFor(() => expect(screen.getByText('VIPs')).toBeInTheDocument());
    // Still there after settling - the fallback effect is a no-op when the
    // selected segment still exists.
    expect(screen.getByText('VIPs')).toBeInTheDocument();
  });
});

describe('ResourceList segment fallback waits for segmentsReady (round 3 fix)', () => {
  it('keeps a ctx-restored segment across the segments load rather than stomping it to the placeholder default', async () => {
    // Simulates Contacts: `segmentOptions()` always prepends an `all`
    // sentinel before `useContactSegments` resolves, so a naive
    // `segments.length === 0` guard never trips - the mount-time state is a
    // single-entry list, indistinguishable from "no real segments configured"
    // without `segmentsReady`.
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams({ ctx: encodeListQuery({ page: 0, pageSize: 10, segment: 'seg-1' }) }) as unknown as ReturnType<
        typeof useSearchParams
      >,
    );

    const fetcher = vi.fn(async () => ({ data: rows, total: rows.length, page: 0 }));
    const loading = baseConfig({
      fetcher,
      segments: [{ id: 'all', label: 'All contacts' }],
      segmentsReady: false,
    });
    const { rerender } = render(<ResourceList config={loading} restoreFromCtx />);

    // The restored "seg-1" isn't in the not-yet-loaded single-entry list, so
    // the trigger shows the unmatched placeholder rather than "All
    // contacts" - the tell that the effect did NOT reset the value while
    // segmentsReady is false (a reset would render "All contacts" here).
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(screen.queryByText('All contacts')).not.toBeInTheDocument();
    expect(screen.queryByText('VIPs')).not.toBeInTheDocument();

    // The real segment list resolves - rerender in place (same component
    // instance, same as `loading` flipping to `false` on the real hook).
    const ready = baseConfig({
      fetcher,
      segments: [
        { id: 'all', label: 'All contacts' },
        { id: 'seg-1', label: 'VIPs' },
      ],
      segmentsReady: true,
    });
    rerender(<ResourceList config={ready} restoreFromCtx />);

    // The ctx-restored "seg-1" survives - it was never overwritten.
    await waitFor(() => expect(screen.getByText('VIPs')).toBeInTheDocument());
  });

  it('still falls back once ready if the ctx-restored segment genuinely no longer exists', async () => {
    vi.mocked(useSearchParams).mockReturnValue(
      new URLSearchParams({ ctx: encodeListQuery({ page: 0, pageSize: 10, segment: 'seg-deleted' }) }) as unknown as ReturnType<
        typeof useSearchParams
      >,
    );

    const fetcher = vi.fn(async () => ({ data: rows, total: rows.length, page: 0 }));
    const loading = baseConfig({
      fetcher,
      segments: [{ id: 'all', label: 'All contacts' }],
      segmentsReady: false,
    });
    const { rerender } = render(<ResourceList config={loading} restoreFromCtx />);
    await waitFor(() => expect(fetcher).toHaveBeenCalled());
    expect(screen.queryByText('All contacts')).not.toBeInTheDocument();

    // Real segments load; "seg-deleted" is not among them - falls back to
    // the first configured segment.
    const ready = baseConfig({
      fetcher,
      segments: [
        { id: 'all', label: 'All contacts' },
        { id: 'seg-1', label: 'VIPs' },
      ],
      segmentsReady: true,
    });
    rerender(<ResourceList config={ready} restoreFromCtx />);

    await waitFor(() => expect(screen.getByText('All contacts')).toBeInTheDocument());
    expect(screen.queryByText('seg-deleted')).not.toBeInTheDocument();
  });
});
