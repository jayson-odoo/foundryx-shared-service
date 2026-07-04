/**
 * SimulateDateDialog (sprint-4/03 Slice 6) — Preview dry-runs the sweep as-of a
 * date and lists the would-advance rows; Apply commits. Service is mocked.
 */
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const simulate = vi.fn();
vi.mock('@/services/status-engine-service', () => ({
  statusEngineService: { simulate: (...a: unknown[]) => simulate(...a) },
}));
vi.mock('sonner', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import type { StatusNodeData } from '@/types/status-engine';
import { SimulateDateDialog } from './simulate-date-dialog';

const STATUSES = [
  { id: 's-draft', label: 'Draft' },
  { id: 's-active', label: 'Active' },
] as unknown as StatusNodeData[];

function renderDialog() {
  return render(
    <SimulateDateDialog
      entityType="project"
      entityLabel="Event"
      statuses={STATUSES}
      onClose={vi.fn()}
    />,
  );
}

describe('SimulateDateDialog', () => {
  beforeEach(() => simulate.mockReset());

  it('Preview dry-runs and lists would-advance rows with from→to labels', async () => {
    simulate.mockResolvedValue({
      data: [{ id: 'p1', label: 'Annual conf', fromId: 's-draft', toId: 's-active' }],
      applied: false,
    });
    renderDialog();
    fireEvent.change(screen.getByLabelText('As-of date'), { target: { value: '2026-09-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));

    await waitFor(() => expect(simulate).toHaveBeenCalledWith('project', '2026-09-01', false));
    expect(await screen.findByText('Annual conf')).toBeInTheDocument();
    expect(screen.getByText('Draft → Active')).toBeInTheDocument();
    expect(screen.getByText(/1 record\(s\) would advance/)).toBeInTheDocument();
  });

  it('Apply commits with apply=true after a preview', async () => {
    simulate.mockResolvedValue({
      data: [{ id: 'p1', label: 'Annual conf', fromId: 's-draft', toId: 's-active' }],
      applied: false,
    });
    renderDialog();
    fireEvent.change(screen.getByLabelText('As-of date'), { target: { value: '2026-09-01' } });
    fireEvent.click(screen.getByRole('button', { name: 'Preview' }));
    await screen.findByText('Annual conf');

    simulate.mockResolvedValue({ data: [], applied: true });
    fireEvent.click(screen.getByRole('button', { name: 'Apply' }));
    await waitFor(() => expect(simulate).toHaveBeenLastCalledWith('project', '2026-09-01', true));
  });

  it('Preview is disabled until a date is picked', () => {
    renderDialog();
    expect(screen.getByRole('button', { name: 'Preview' })).toBeDisabled();
  });
});
