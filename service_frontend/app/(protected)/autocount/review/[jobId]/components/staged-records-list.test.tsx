import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

// The Resource list is exercised elsewhere; stub it so this suite proves the
// no-change collapse behaviour (AC-15-11), not the grid internals.
vi.mock('@/components/platform/resource-list', () => ({
  ResourceList: () => <div data-testid="resource-list" />,
}));
vi.mock('@/services/autocount-service', () => ({
  autocountService: { listStaged: vi.fn().mockResolvedValue({ job: {}, data: [], total: 0, noChangeCount: 0 }) },
}));
vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({
    formatDate: (v: string) => v,
    formatDateTime: (v: string) => v,
    formatTime: (v: string) => v,
  }),
}));

const { StagedRecordsList } = await import('./staged-records-list');

describe('staged records list - no-change collapse (AC-15-11)', () => {
  it('renders the changed list and ONE collapsed no-change line', () => {
    render(<StagedRecordsList jobId="job-1" noChangeCount={24} />);
    // Only the changed list is mounted up front - the no-change ones are not
    // shown as full cards that bury it.
    expect(screen.getAllByTestId('resource-list')).toHaveLength(1);
    expect(screen.getByTestId('no-change-toggle')).toHaveTextContent(
      '24 records with no field changes',
    );
  });

  it('expands the no-change records on demand', async () => {
    render(<StagedRecordsList jobId="job-1" noChangeCount={24} />);
    await userEvent.click(screen.getByTestId('no-change-toggle'));
    // A second list (the no-change partition) mounts only when expanded.
    expect(screen.getAllByTestId('resource-list')).toHaveLength(2);
  });

  it('omits the collapse line when nothing was a no-op', () => {
    render(<StagedRecordsList jobId="job-1" noChangeCount={0} />);
    expect(screen.queryByTestId('no-change-collapse')).not.toBeInTheDocument();
    expect(screen.getAllByTestId('resource-list')).toHaveLength(1);
  });
});
