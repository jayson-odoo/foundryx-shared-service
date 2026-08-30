import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkflowRuns } from './workflow-runs';

const { listRuns, getRun } = vi.hoisted(() => ({
  listRuns: vi.fn(),
  getRun: vi.fn(),
}));

vi.mock('@/services/workflow-service', () => ({
  workflowService: {
    listRuns,
    getRun,
  },
}));

vi.mock('@/hooks/use-datetime', () => ({
  useDatetime: () => ({ formatDateTime: (value: string) => value }),
}));

vi.mock('./run-replay', () => ({
  RunReplay: () => null,
}));

describe('WorkflowRuns status filter', () => {
  beforeEach(() => {
    listRuns.mockResolvedValue({ data: [], total: 0 });
    getRun.mockResolvedValue(null);
  });

  it('searches and selects a status before querying runs', async () => {
    render(<WorkflowRuns workflowId="workflow-1" onDebugInEditor={vi.fn()} />);

    await waitFor(() =>
      expect(listRuns).toHaveBeenCalledWith('workflow-1', {
        page: 0,
        pageSize: 25,
        segment: 'all',
      }),
    );

    fireEvent.click(screen.getByRole('combobox', { name: 'Filter runs by status' }));
    fireEvent.change(screen.getByPlaceholderText('Search…'), {
      target: { value: 'pend' },
    });
    expect(screen.queryByText('Success')).not.toBeInTheDocument();
    fireEvent.click(screen.getByText('Pending'));

    await waitFor(() =>
      expect(listRuns).toHaveBeenLastCalledWith('workflow-1', {
        page: 0,
        pageSize: 25,
        segment: 'pending',
      }),
    );
  });
});

describe('WorkflowRuns correlation key', () => {
  it('shows the snapshotted correlation key on a serialized run', async () => {
    listRuns.mockResolvedValue({
      data: [
        {
          id: 'run-1',
          status: 'success',
          triggeredBy: 'event',
          isTest: false,
          actorName: 'System',
          startedAt: '2026-08-30T00:00:00Z',
          finishedAt: '2026-08-30T00:00:01Z',
          durationMs: 1000,
          versionNumber: 1,
          correlationKey: 'conversation-42',
          error: null,
          createdAt: '2026-08-30T00:00:00Z',
        },
      ],
      total: 1,
    });
    render(<WorkflowRuns workflowId="workflow-1" onDebugInEditor={vi.fn()} />);
    expect(await screen.findByText('conversation-42')).toBeInTheDocument();
  });
});
