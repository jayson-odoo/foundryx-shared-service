import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { WorkflowRuns } from './workflow-runs';

const { listRuns } = vi.hoisted(() => ({
  listRuns: vi.fn(),
}));

vi.mock('@/services/workflow-service', () => ({
  workflowService: {
    listRuns,
    getRun: vi.fn(),
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
