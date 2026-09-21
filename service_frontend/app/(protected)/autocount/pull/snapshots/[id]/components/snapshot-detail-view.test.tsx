import { render as rtlRender, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SettingsProvider } from '@/providers/settings-provider';
import type { AutocountPullSnapshot } from '@/types/autocount';
import { stubAuthFetch } from '../../../../companies/[id]/entities/[entityType]/components/task-editor-view.test-helpers';
import { SnapshotDetailView } from './snapshot-detail-view';

stubAuthFetch();

function render(ui: React.ReactElement) {
  return rtlRender(<SettingsProvider>{ui}</SettingsProvider>);
}

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    timeZone: 'UTC',
    formatDate: (v: string) => v ?? '',
    formatDateTime: (v: string) => v ?? '',
    formatTime: (v: string) => v ?? '',
  }),
}));

const detailStateBox = vi.hoisted(() => ({ current: { status: 'loading' } as unknown }));
const rowsRunSpy = vi.hoisted(() => vi.fn());

vi.mock('@/hooks/use-autocount-pull', () => ({
  usePullSnapshotDetail: () => ({ state: detailStateBox.current, reload: vi.fn() }),
  usePullSnapshotRows: () => ({ state: { status: 'idle' }, run: rowsRunSpy }),
}));

function buildingSnapshot(over: Partial<AutocountPullSnapshot> = {}): AutocountPullSnapshot {
  return {
    id: 'snap-1',
    entityType: 'product',
    companyId: 'company-1',
    companyCode: 'SRT',
    status: 'building',
    requestedVia: 'operator',
    createdAt: '2026-09-21T00:00:00Z',
    extractedAt: null,
    expiresAt: null,
    recordCount: 0,
    complete: false,
    contentHash: null,
    sourcePageSize: null,
    progress: null,
    error: null,
    excludedCount: 0,
    excludedRows: [],
    ...over,
  };
}

describe('SnapshotDetailView building progress (AC-11-43)', () => {
  it('shows the stage and page count via the shared JobProgress component once known', () => {
    detailStateBox.current = {
      status: 'ready',
      snapshot: buildingSnapshot({ progress: { stage: 'lookup:uom', pagesDone: 2, pagesTotal: 4 } }),
    };
    render(<SnapshotDetailView id="snap-1" />);
    expect(screen.getByTestId('job-progress-label')).toHaveTextContent('Reading lookup uom · page 2 of 4');
    // No operator Cancel for a snapshot build in this plan (BL-SS-248).
    expect(screen.queryByTestId('job-progress-cancel')).not.toBeInTheDocument();
  });

  it('falls back to a bare "Building…" line when no progress hint is known yet', () => {
    detailStateBox.current = { status: 'ready', snapshot: buildingSnapshot({ progress: null }) };
    render(<SnapshotDetailView id="snap-1" />);
    expect(screen.getByTestId('snapshot-building')).toHaveTextContent('Building…');
    expect(screen.queryByTestId('job-progress')).not.toBeInTheDocument();
  });
});
